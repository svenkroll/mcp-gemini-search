"""Acceptance tests for the URL policy from ADR 0008 (issue #5).

The input check is exercised through ``check_url`` only. The redirect
resolution runs against an ``httpx.MockTransport``; no test opens a network
connection. Every mocked transport records the requests it sees so the tests can
prove that only allowlist hosts are contacted.
"""

import asyncio
import time

import httpx
import pytest

from gemini_search_mcp.urlpolicy import (
    REDIRECT_ALLOWLIST,
    UrlRejected,
    check_url,
    resolve_redirect,
    resolve_redirects,
)

ALLOWLIST_HOST = "vertexaisearch.cloud.google.com"
TARGET = "https://example.com/target"
URL_BASE = "https://example.com/"
URL_AT_LIMIT = URL_BASE + "a" * (2048 - len(URL_BASE))


def _allowlist(path: str) -> str:
    """Return an allowlist URL for ``path``."""
    return f"https://{ALLOWLIST_HOST}{path}"


def _redirect(location: str) -> httpx.Response:
    """Build a redirect response carrying ``location``."""
    return httpx.Response(302, headers={"Location": location})


def _run_redirect(url: str, transport: httpx.AsyncBaseTransport) -> str | None:
    """Resolve one URL against a mocked transport."""

    async def scenario() -> str | None:
        async with httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
        ) as client:
            return await resolve_redirect(url, client)

    return asyncio.run(scenario())


def _run_resolution(
    urls: list[str],
    transport: httpx.AsyncBaseTransport,
) -> dict[str, str | None]:
    """Resolve a batch against a mocked transport."""
    return asyncio.run(resolve_redirects(urls, transport=transport))


def test_ac1_input_check_accepts_and_rejects_each_rule() -> None:
    """AC1: every ADR 0008 input rule has an allowed and a rejected case."""
    cases: list[tuple[str, str, bool]] = [
        ("scheme", "https://example.com/", True),
        ("scheme", "ftp://example.com/", False),
        ("length", URL_AT_LIMIT, True),
        ("length", URL_AT_LIMIT + "a", False),
        ("credentials", "https://example.com/", True),
        ("credentials", "https://user:pass@example.com/", False),
        ("port", "https://example.com:443/", True),
        ("port", "https://example.com:8080/", False),
        ("ip_literal", "https://8.8.8.8/", True),
        ("ip_literal", "https://127.0.0.1/", False),
        ("host_suffix", "https://example.com/", True),
        ("host_suffix", "https://svc.internal/", False),
        ("syntax", "https://example.com/path?q=1", True),
        ("syntax", "https://exa mple.com/", False),
    ]

    for _rule, url, allowed in cases:
        if allowed:
            assert isinstance(check_url(url), str)
        else:
            with pytest.raises(UrlRejected) as rejected:
                check_url(url)
            assert isinstance(rejected.value.reason, str)
            assert rejected.value.reason


def test_ac2_input_check_performs_no_network_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2: the input check works with every socket entry point disabled."""

    def _forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("the input check must not touch the network")

    monkeypatch.setattr("socket.getaddrinfo", _forbidden)
    monkeypatch.setattr("socket.gethostbyname", _forbidden)
    monkeypatch.setattr("socket.gethostbyname_ex", _forbidden)
    monkeypatch.setattr("socket.gethostbyaddr", _forbidden)
    monkeypatch.setattr("socket.socket", _forbidden)
    monkeypatch.setattr("socket.create_connection", _forbidden)

    for url in [
        "https://example.com/",
        "HTTPS://Example.COM/a",
        "https://bücher.example",
        "https://8.8.8.8/",
    ]:
        assert isinstance(check_url(url), str)

    for url in ["ftp://example.com/", "https://127.0.0.1/", "https://localhost/"]:
        with pytest.raises(UrlRejected):
            check_url(url)


def test_ec1_url_length_boundary_is_2048() -> None:
    """EC1: exactly 2,048 characters are allowed, 2,049 are rejected."""
    assert len(URL_AT_LIMIT) == 2048
    assert isinstance(check_url(URL_AT_LIMIT), str)

    too_long = URL_AT_LIMIT + "a"
    assert len(too_long) == 2049
    with pytest.raises(UrlRejected):
        check_url(too_long)


def test_ec2_upper_case_scheme_and_host_are_normalized() -> None:
    """EC2: ``HTTPS://Example.COM/a`` is allowed and returned normalized."""
    assert check_url("HTTPS://Example.COM/a") == "https://example.com/a"


def test_ec3_explicit_ports_80_and_443_are_allowed() -> None:
    """EC3: ports 443 and 80 are allowed, 8080 is rejected."""
    assert isinstance(check_url("https://example.com:443/"), str)
    assert isinstance(check_url("https://example.com:80/"), str)
    with pytest.raises(UrlRejected):
        check_url("https://example.com:8080/")


def test_ec4_ip_literals_are_judged_by_is_global() -> None:
    """EC4: loopback and IPv4-mapped loopback are rejected, global IPv6 is allowed."""
    with pytest.raises(UrlRejected):
        check_url("https://[::1]/")
    with pytest.raises(UrlRejected):
        check_url("https://[::ffff:127.0.0.1]/")
    assert isinstance(check_url("https://[2606:4700:4700::1111]/"), str)


def test_ec5_cgnat_is_rejected_and_public_ipv4_is_allowed() -> None:
    """EC5: 100.64.0.1 is rejected, 8.8.8.8 is allowed."""
    with pytest.raises(UrlRejected):
        check_url("https://100.64.0.1/")
    assert isinstance(check_url("https://8.8.8.8/"), str)


def test_ec6_blocked_host_suffixes_are_rejected() -> None:
    """EC6: localhost, local and internal hosts are rejected, with a trailing dot too."""
    for url in [
        "https://LOCALHOST/",
        "https://localhost./",
        "https://foo.localhost/",
        "https://printer.local/",
        "https://svc.internal/",
    ]:
        with pytest.raises(UrlRejected):
            check_url(url)


def test_ec7_user_name_without_password_is_rejected() -> None:
    """EC7: credentials without a password are still credentials."""
    with pytest.raises(UrlRejected):
        check_url("https://user@example.com/")


def test_ec8_internationalized_domain_is_allowed() -> None:
    """EC8: an IDN host is allowed and returned with its IDNA form."""
    assert check_url("https://bücher.example") == "https://xn--bcher-kva.example/"


def test_ac3_redirect_chain_within_allowlist_resolves_to_target() -> None:
    """AC3: a chain of allowlist redirects resolves to the first outside target."""
    routes = {
        "/r0": _redirect(_allowlist("/r1")),
        "/r1": _redirect(_allowlist("/r2")),
        "/r2": _redirect(_allowlist("/r3")),
        "/r3": _redirect(_allowlist("/r4")),
        "/r4": _redirect(TARGET),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return routes[request.url.path]

    result = _run_redirect(_allowlist("/r0"), httpx.MockTransport(handler))

    assert result == TARGET
    assert requested == ["/r0", "/r1", "/r2", "/r3", "/r4"]


def test_ac3_sixth_redirect_within_allowlist_is_unresolved() -> None:
    """AC3: more than five redirects count as unresolved."""
    routes = {f"/r{index}": _redirect(_allowlist(f"/r{index + 1}")) for index in range(6)}
    routes["/r6"] = _redirect(TARGET)
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return routes[request.url.path]

    result = _run_redirect(_allowlist("/r0"), httpx.MockTransport(handler))

    assert result is None
    assert "/r6" not in requested


def test_ac4_only_allowlist_hosts_are_contacted() -> None:
    """AC4: the mocked transport sees no request to a host outside the allowlist."""
    routes = {
        "/external": _redirect(TARGET),
        "/invalid": _redirect("https://127.0.0.1/internal"),
        "/http": _redirect(f"http://{ALLOWLIST_HOST}/next"),
        "/chain": _redirect(_allowlist("/external")),
    }
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return routes[request.url.path]

    async def scenario() -> list[str | None]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
        ) as client:
            return [
                await resolve_redirect(_allowlist("/external"), client),
                await resolve_redirect(_allowlist("/invalid"), client),
                await resolve_redirect(_allowlist("/http"), client),
                await resolve_redirect(_allowlist("/chain"), client),
            ]

    results = asyncio.run(scenario())

    assert results == [TARGET, None, None, TARGET]
    assert requests
    for request in requests:
        assert request.url.scheme == "https"
        assert request.url.host in REDIRECT_ALLOWLIST


def test_ac5_invalid_location_target_is_unresolved() -> None:
    """AC5: a Location target rejected by the input check is unresolved."""
    transport = httpx.MockTransport(
        lambda request: _redirect("https://127.0.0.1/internal"),
    )

    assert _run_redirect(_allowlist("/start"), transport) is None


def test_ac5_timeout_is_unresolved() -> None:
    """AC5: a transport timeout is unresolved instead of raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timeout", request=request)

    assert _run_redirect(_allowlist("/start"), httpx.MockTransport(handler)) is None


def test_ac5_response_without_redirect_is_unresolved() -> None:
    """AC5: a response without redirect status is unresolved."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200))

    assert _run_redirect(_allowlist("/start"), transport) is None


def test_ac6_resolution_respects_the_concurrency_limit() -> None:
    """AC6: at most ``max_concurrency`` resolutions run at the same time."""
    urls = [_allowlist(f"/start/{index}") for index in range(4)]
    state = {"started": 0, "active": 0, "max_active": 0}

    async def scenario() -> dict[str, str | None]:
        gate = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            state["started"] += 1
            state["active"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
            try:
                await gate.wait()
            finally:
                state["active"] -= 1
            return _redirect(TARGET)

        task = asyncio.create_task(
            resolve_redirects(
                urls,
                transport=httpx.MockTransport(handler),
                max_concurrency=2,
                per_url_timeout=5.0,
                total_budget=5.0,
            )
        )
        try:
            for _ in range(200):
                if state["started"] >= 2:
                    break
                await asyncio.sleep(0)
            assert state["started"] == 2
            assert state["max_active"] == 2
            gate.set()
            return await asyncio.wait_for(task, timeout=5.0)
        finally:
            gate.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    result = asyncio.run(scenario())

    assert result == dict.fromkeys(urls, TARGET)
    assert state["max_active"] == 2


def test_ac6_overall_budget_marks_open_resolutions_unresolved() -> None:
    """AC6: URLs still open when the overall budget ends count as unresolved."""
    urls = [_allowlist(f"/start/{index}") for index in range(3)]

    async def scenario() -> tuple[dict[str, str | None], float]:
        async def handler(request: httpx.Request) -> httpx.Response:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        started = time.monotonic()
        result = await asyncio.wait_for(
            resolve_redirects(
                urls,
                transport=httpx.MockTransport(handler),
                per_url_timeout=30.0,
                total_budget=0.05,
            ),
            timeout=3.0,
        )
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(scenario())

    assert result == dict.fromkeys(urls)
    assert elapsed < 1.0


def test_ec9_relative_location_is_resolved_and_followed() -> None:
    """EC9: a relative Location on an allowlist host becomes the next hop."""
    routes = {
        "/start": _redirect("/next"),
        "/next": _redirect(TARGET),
    }
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return routes[request.url.path]

    result = _run_redirect(_allowlist("/start"), httpx.MockTransport(handler))

    assert result == TARGET
    assert requested == ["/start", "/next"]


def test_ec10_http_location_on_allowlist_host_is_unresolved() -> None:
    """EC10: an http:// Location on an allowlist host is not fetched."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return _redirect(f"http://{ALLOWLIST_HOST}/next")

    result = _run_redirect(_allowlist("/start"), httpx.MockTransport(handler))

    assert result is None
    assert requested == ["/start"]


def test_ec11_response_without_redirect_from_allowlist_host_is_unresolved() -> None:
    """EC11: a 200 response from the allowlist host is unresolved."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="ok"))

    assert _run_redirect(_allowlist("/start"), transport) is None


def test_ec12_empty_url_list_returns_empty_result_without_requests() -> None:
    """EC12: an empty batch returns ``{}`` and makes no request."""
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200)

    result = _run_resolution([], httpx.MockTransport(handler))

    assert result == {}
    assert requested == []


def test_ec13_duplicate_url_is_resolved_once() -> None:
    """EC13: the same URL twice yields one entry and at most one resolution."""
    url = _allowlist("/start")
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return _redirect(TARGET)

    result = _run_resolution([url, url], httpx.MockTransport(handler))

    assert result == {url: TARGET}
    assert len(requested) == 1
