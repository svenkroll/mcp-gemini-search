"""Acceptance tests for the URL policy of ADR 0008 (issue #5).

The input check is tested as a pure function. Redirect resolution always runs
against ``httpx.MockTransport``: the transport rejects every request whose host
is not on the redirect allowlist, so no test can reach the network and no test
can silently contact a target URL. Time-based tests shorten the module limits
with ``monkeypatch``; the module reads its constants at call time.
"""

import asyncio
import socket
import time
from collections.abc import Callable, Coroutine, Mapping

import httpx
import pytest

from gemini_search_mcp import urlpolicy
from gemini_search_mcp.urlpolicy import UrlRejectedError, check_url

ALLOWLIST_HOST = "vertexaisearch.cloud.google.com"
TARGET_URL = "https://example.com/target"

_URL_PREFIX = "https://example.com/"
_LENGTH_2048_URL = _URL_PREFIX + "a" * (2048 - len(_URL_PREFIX))
_LENGTH_2049_URL = _URL_PREFIX + "a" * (2049 - len(_URL_PREFIX))

AC1_CASES = [
    pytest.param("https://example.com/a", "https://example.com/a", id="scheme-https-allowed"),
    pytest.param("http://example.com/a", "http://example.com/a", id="scheme-http-allowed"),
    pytest.param("ftp://example.com/a", None, id="scheme-ftp-rejected"),
    pytest.param("not a url", None, id="syntax-invalid-rejected"),
    pytest.param("https://example.com/a", "https://example.com/a", id="no-credentials-allowed"),
    pytest.param("https://user:secret@example.com/a", None, id="credentials-rejected"),
    pytest.param("https://example.com:443/a", "https://example.com/a", id="port-443-allowed"),
    pytest.param("https://example.com:8080/a", None, id="port-8080-rejected"),
    pytest.param("https://8.8.8.8/", "https://8.8.8.8/", id="global-ip-allowed"),
    pytest.param("https://127.0.0.1/", None, id="loopback-ip-rejected"),
    pytest.param("https://example.com/a", "https://example.com/a", id="host-suffix-ok-allowed"),
    pytest.param("https://printer.local/", None, id="host-suffix-local-rejected"),
    pytest.param(_LENGTH_2048_URL, _LENGTH_2048_URL, id="length-2048-allowed"),
    pytest.param(_LENGTH_2049_URL, None, id="length-2049-rejected"),
]


class _Recorder:
    """Records requests and enforces the allowlist on every single request."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def check(self, request: httpx.Request) -> None:
        assert request.url.host in urlpolicy.REDIRECT_ALLOWLIST, f"contacted {request.url}"
        assert request.url.scheme == "https", f"contacted {request.url}"
        self.urls.append(str(request.url))


def _allowlist_url(path: str) -> str:
    return f"https://{ALLOWLIST_HOST}{path}"


def _redirect(location: str, status: int = 302) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location})


def _scripted_handler(
    recorder: _Recorder, routes: Mapping[str, httpx.Response | BaseException]
) -> Callable[[httpx.Request], Coroutine[None, None, httpx.Response]]:
    async def handler(request: httpx.Request) -> httpx.Response:
        recorder.check(request)
        outcome = routes.get(request.url.path)
        assert outcome is not None, f"unexpected request to {request.url}"
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return handler


def _mock_client(
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.mark.parametrize(("url", "expected"), AC1_CASES)
def test_ac1_every_input_rule_has_allowed_and_rejected_case(url: str, expected: str | None) -> None:
    """AC1: each input rule rejects one case and accepts one case."""
    if expected is None:
        with pytest.raises(UrlRejectedError) as excinfo:
            check_url(url)
        assert isinstance(excinfo.value.reason, str)
        assert excinfo.value.reason
    else:
        assert check_url(url) == expected


def test_ac2_input_check_performs_no_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: the input check works with sockets and DNS resolution disabled."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the input check must not access the network")

    monkeypatch.setattr(socket, "socket", _forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", _forbidden)

    assert check_url("https://example.com/a") == "https://example.com/a"
    with pytest.raises(UrlRejectedError):
        check_url("https://127.0.0.1/a")


def test_ac3_redirect_chain_within_allowlist_resolves_to_target() -> None:
    """AC3: a chain of allowlist redirects ends at the first external target."""
    recorder = _Recorder()
    hops = [_allowlist_url(f"/hop/{index}") for index in range(5)]
    routes = {
        f"/hop/{index}": _redirect(hops[index + 1] if index + 1 < len(hops) else TARGET_URL)
        for index in range(len(hops))
    }
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(hops[0], client)

    assert asyncio.run(scenario()) == TARGET_URL
    assert recorder.urls == hops
    assert TARGET_URL not in recorder.urls


def test_ac3_more_than_five_redirects_is_unresolved() -> None:
    """AC3: a sixth redirect into the allowlist makes the URL unresolved."""
    recorder = _Recorder()
    hops = [_allowlist_url(f"/too-many/{index}") for index in range(7)]
    routes = {
        f"/too-many/{index}": _redirect(hops[index + 1] if index + 1 < len(hops) else TARGET_URL)
        for index in range(len(hops))
    }
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(hops[0], client)

    assert asyncio.run(scenario()) is None
    assert TARGET_URL not in recorder.urls


def test_ac4_no_host_outside_the_allowlist_is_contacted() -> None:
    """AC4: the mocked transport asserts the allowlist on every request."""
    recorder = _Recorder()
    start = _allowlist_url("/start")
    routes = {"/start": _redirect(TARGET_URL)}
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(start, client)

    assert asyncio.run(scenario()) == TARGET_URL
    assert recorder.urls == [start]
    assert all(httpx.URL(url).host in urlpolicy.REDIRECT_ALLOWLIST for url in recorder.urls)


def test_ac5_invalid_location_target_is_unresolved() -> None:
    """AC5: a Location that fails the input check makes the URL unresolved."""
    recorder = _Recorder()
    start = _allowlist_url("/start")
    routes = {"/start": _redirect("https://example.com:8080/blocked")}
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(start, client)

    assert asyncio.run(scenario()) is None
    assert recorder.urls == [start]


def test_ac5_timeout_is_unresolved() -> None:
    """AC5: a transport timeout makes the URL unresolved instead of raising."""
    recorder = _Recorder()
    start = _allowlist_url("/start")
    routes: dict[str, httpx.Response | BaseException] = {
        "/start": httpx.ConnectTimeout("simulated timeout")
    }
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(start, client)

    assert asyncio.run(scenario()) is None


def test_ac5_response_without_redirect_is_unresolved() -> None:
    """AC5: a 200 response without Location makes the URL unresolved."""
    recorder = _Recorder()
    start = _allowlist_url("/start")
    routes = {"/start": httpx.Response(200)}
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(start, client)

    assert asyncio.run(scenario()) is None
    assert recorder.urls == [start]


def test_ac6_respects_the_concurrency_limit() -> None:
    """AC6: at most MAX_CONCURRENCY resolutions run in parallel."""
    urls = [_allowlist_url(f"/parallel/{index}") for index in range(6)]
    release = asyncio.Event()
    limit_reached = asyncio.Event()
    state = {"started": 0, "active": 0, "max_active": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host in urlpolicy.REDIRECT_ALLOWLIST, f"contacted {request.url}"
        state["started"] += 1
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        if state["started"] == urlpolicy.MAX_CONCURRENCY:
            limit_reached.set()
        try:
            await release.wait()
        finally:
            state["active"] -= 1
        return httpx.Response(200)

    async def scenario() -> tuple[dict[str, str | None], int, int, int]:
        async with _mock_client(handler) as client:
            task = asyncio.create_task(urlpolicy.resolve_redirects(urls, client))
            await asyncio.sleep(0)
            if task.done():
                result = await task
                return result, state["started"], state["max_active"], state["max_active"]
            await asyncio.wait_for(limit_reached.wait(), timeout=2.0)
            await asyncio.sleep(0.05)
            started_while_blocked = state["started"]
            max_while_blocked = state["max_active"]
            release.set()
            result = await asyncio.wait_for(task, timeout=3.0)
            return result, started_while_blocked, max_while_blocked, state["max_active"]

    result, started_while_blocked, max_while_blocked, max_active = asyncio.run(scenario())

    assert started_while_blocked == urlpolicy.MAX_CONCURRENCY
    assert max_while_blocked == urlpolicy.MAX_CONCURRENCY
    assert max_active <= urlpolicy.MAX_CONCURRENCY
    assert result == dict.fromkeys(urls)


def test_ac6_overall_budget_marks_open_urls_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: when the overall budget ends, open URLs count as unresolved."""
    monkeypatch.setattr(urlpolicy, "OVERALL_BUDGET_SECONDS", 0.2)
    urls = [_allowlist_url(f"/budget/{index}") for index in range(2)]

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host in urlpolicy.REDIRECT_ALLOWLIST, f"contacted {request.url}"
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def scenario() -> tuple[dict[str, str | None], float]:
        async with _mock_client(handler) as client:
            started = time.monotonic()
            result = await asyncio.wait_for(urlpolicy.resolve_redirects(urls, client), timeout=3.0)
            return result, time.monotonic() - started

    result, elapsed = asyncio.run(scenario())

    assert result == dict.fromkeys(urls)
    assert elapsed < 2.0


def test_ec1_length_boundary() -> None:
    """EC1: exactly 2,048 characters are allowed, 2,049 are rejected."""
    assert len(_LENGTH_2048_URL) == 2048
    assert check_url(_LENGTH_2048_URL) == _LENGTH_2048_URL

    assert len(_LENGTH_2049_URL) == 2049
    with pytest.raises(UrlRejectedError):
        check_url(_LENGTH_2049_URL)


def test_ec2_upper_case_scheme_and_host_are_normalized() -> None:
    """EC2: an upper-case scheme and host are accepted and returned normalized."""
    assert check_url("HTTPS://Example.COM/a") == "https://example.com/a"


def test_ec3_explicit_ports() -> None:
    """EC3: ports 443 and 80 are allowed, 8080 is rejected."""
    assert check_url("https://example.com:443/a") == "https://example.com/a"
    assert check_url("http://example.com:80/a") == "http://example.com/a"

    with pytest.raises(UrlRejectedError):
        check_url("https://example.com:8080/a")


def test_ec4_ip_literals() -> None:
    """EC4: loopback and IPv4-mapped literals are rejected, global IPv6 allowed."""
    for rejected in ("https://[::1]/", "https://[::ffff:127.0.0.1]/"):
        with pytest.raises(UrlRejectedError):
            check_url(rejected)

    assert check_url("https://[2606:4700:4700::1111]/") == "https://[2606:4700:4700::1111]/"


def test_ec5_cgnat_and_public_ipv4() -> None:
    """EC5: a CGNAT address is rejected, a public IPv4 literal is allowed."""
    with pytest.raises(UrlRejectedError):
        check_url("https://100.64.0.1/")

    assert check_url("https://8.8.8.8/") == "https://8.8.8.8/"


def test_ec6_forbidden_host_suffixes() -> None:
    """EC6: localhost, .localhost, .local and .internal hosts are rejected."""
    for host in ("LOCALHOST", "localhost.", "foo.localhost", "printer.local", "svc.internal"):
        with pytest.raises(UrlRejectedError):
            check_url(f"https://{host}/")


def test_ec7_user_name_without_password_is_rejected() -> None:
    """EC7: a user name without a password still counts as credentials."""
    with pytest.raises(UrlRejectedError) as excinfo:
        check_url("https://alice@example.com")

    assert "alice" not in excinfo.value.reason


def test_ec8_internationalized_domain_name_is_allowed() -> None:
    """EC8: an IDN is accepted and normalized to punycode."""
    assert check_url("https://bücher.example") == "https://xn--bcher-kva.example/"


def test_ec9_relative_location_is_resolved_and_followed() -> None:
    """EC9: a relative Location stays on the allowlist host and is followed."""
    recorder = _Recorder()
    start = _allowlist_url("/grounding/abc")
    next_hop = _allowlist_url("/next")
    routes = {
        "/grounding/abc": _redirect("/next"),
        "/next": _redirect(TARGET_URL),
    }
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(start, client)

    assert asyncio.run(scenario()) == TARGET_URL
    assert recorder.urls == [start, next_hop]


def test_ec10_http_location_on_allowlist_is_not_fetched() -> None:
    """EC10: an allowlist host addressed via http is never fetched."""
    recorder = _Recorder()
    start = _allowlist_url("/start")
    routes = {"/start": _redirect(f"http://{ALLOWLIST_HOST}/next")}
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(start, client)

    assert asyncio.run(scenario()) is None
    assert recorder.urls == [start]


def test_ec11_200_response_without_redirect_is_unresolved() -> None:
    """EC11: a 200 response from the allowlist host is unresolved."""
    recorder = _Recorder()
    start = _allowlist_url("/start")
    routes = {"/start": httpx.Response(200)}
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> str | None:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirect(start, client)

    assert asyncio.run(scenario()) is None


def test_ec12_empty_url_list_makes_no_request() -> None:
    """EC12: an empty batch returns an empty mapping without any request."""
    recorder = _Recorder()

    async def handler(request: httpx.Request) -> httpx.Response:
        recorder.check(request)
        raise AssertionError(f"unexpected request to {request.url}")

    async def scenario() -> dict[str, str | None]:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirects([], client)

    assert asyncio.run(scenario()) == {}
    assert recorder.urls == []


def test_ec13_duplicate_url_is_resolved_once() -> None:
    """EC13: the same URL twice yields one entry and one resolution."""
    recorder = _Recorder()
    start = _allowlist_url("/start")
    routes = {"/start": _redirect(TARGET_URL)}
    handler = _scripted_handler(recorder, routes)

    async def scenario() -> dict[str, str | None]:
        async with _mock_client(handler) as client:
            return await urlpolicy.resolve_redirects([start, start], client)

    assert asyncio.run(scenario()) == {start: TARGET_URL}
    assert recorder.urls == [start]
