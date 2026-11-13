"""Acceptance tests for the URL policy module (issue #5, ADR 0008).

``check_input_url`` is exercised entirely offline. ``resolve_redirects`` only
ever runs against ``httpx.MockTransport``: the guarded transport in this module
records every request and refuses any host outside the redirect allowlist, so
no test can reach the network and AC4 is checked on every single request.
"""

import asyncio
import socket
from collections.abc import Awaitable, Callable

import httpx
import pytest

from gemini_search_mcp.urlpolicy import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_PARALLEL_RESOLUTIONS,
    MAX_REDIRECTS,
    MAX_URL_LENGTH,
    OVERALL_BUDGET_SECONDS,
    REDIRECT_ALLOWLIST,
    TOTAL_TIMEOUT_SECONDS,
    RedirectResolution,
    UrlPolicyError,
    check_input_url,
    resolve_redirects,
)

ALLOWLIST_HOST = "vertexaisearch.cloud.google.com"
Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]

# 2,048 characters: the longest URL the input check still accepts (EC1).
_MAX_LENGTH_URL = "https://example.com/" + "a" * (MAX_URL_LENGTH - len("https://example.com/"))


class _GuardedTransport(httpx.MockTransport):
    """Mock transport that records requests and refuses hosts off the allowlist."""

    requests: list[httpx.Request]

    def __init__(self, handler: Handler) -> None:
        self.requests = []

        async def guarded(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if request.url.host not in REDIRECT_ALLOWLIST:
                raise AssertionError(f"contacted a host outside the allowlist: {request.url}")
            return await handler(request)

        super().__init__(guarded)


def _allowlist_url(path: str) -> str:
    return f"https://{ALLOWLIST_HOST}{path}"


def _redirect(location: str) -> httpx.Response:
    return httpx.Response(302, headers={"Location": location})


def _routes(routes: dict[str, httpx.Response]) -> Handler:
    """Serve one scripted response per request path; unexpected paths fail."""

    async def handler(request: httpx.Request) -> httpx.Response:
        try:
            return routes[request.url.path]
        except KeyError:
            raise AssertionError(f"unexpected request: {request.url}") from None

    return handler


def _chain_routes(hops: int, target: str) -> dict[str, httpx.Response]:
    """Build ``hops`` allowlist redirects from ``/hop0`` followed by ``target``."""
    routes = {f"/hop{index}": _redirect(f"/hop{index + 1}") for index in range(hops)}
    routes[f"/hop{hops}"] = _redirect(target)
    return routes


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (_MAX_LENGTH_URL, _MAX_LENGTH_URL),
        (_MAX_LENGTH_URL + "a", None),
        ("https://example.com/path", "https://example.com/path"),
        ("http://example.com/path", "http://example.com/path"),
        ("ftp://example.com/path", None),
        ("example.com/path", None),
        ("https://user:secret@example.com/path", None),
        ("https://example.com:443/path", "https://example.com/path"),
        ("https://example.com:8080/path", None),
        ("https://8.8.8.8/path", "https://8.8.8.8/path"),
        ("https://192.168.1.1/path", None),
        ("https://svc.internal/path", None),
    ],
    ids=[
        "length-2048",
        "length-2049",
        "scheme-https",
        "scheme-http",
        "scheme-ftp",
        "syntax-missing-scheme",
        "credentials-password",
        "port-443",
        "port-8080",
        "ip-global",
        "ip-private",
        "host-suffix-internal",
    ],
)
def test_ac1_every_input_rule_has_an_allowed_and_a_rejected_case(
    url: str, expected: str | None
) -> None:
    """AC1: each of the six rules is proven with an allowed and a rejected case."""
    if expected is None:
        with pytest.raises(UrlPolicyError) as rejected:
            check_input_url(url)
        assert rejected.value.reason.strip()
    else:
        assert check_input_url(url) == expected


def test_ac2_input_check_performs_no_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: socket and HTTP client use fail loudly during the input check."""

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("the input check performed network access")

    for name in ("getaddrinfo", "create_connection", "socket"):
        monkeypatch.setattr(socket, name, forbidden)
    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)

    assert check_input_url("https://example.com/path") == "https://example.com/path"
    with pytest.raises(UrlPolicyError):
        check_input_url("https://localhost/")


def test_ec1_url_length_boundary_is_2048_characters() -> None:
    """EC1: 2,048 characters are allowed, 2,049 are rejected."""
    assert MAX_URL_LENGTH == 2048
    assert len(_MAX_LENGTH_URL) == MAX_URL_LENGTH
    assert check_input_url(_MAX_LENGTH_URL) == _MAX_LENGTH_URL
    with pytest.raises(UrlPolicyError):
        check_input_url(_MAX_LENGTH_URL + "a")


def test_ec2_upper_case_scheme_and_host_are_normalized() -> None:
    """EC2: an upper-case scheme and host are returned normalized."""
    assert check_input_url("HTTPS://Example.COM/a") == "https://example.com/a"


def test_ec3_explicit_ports_443_and_80_are_allowed_and_8080_is_rejected() -> None:
    """EC3: the explicit default ports are allowed, another port is rejected."""
    assert check_input_url("https://example.com:443/path") == "https://example.com/path"
    assert check_input_url("http://example.com:80/path") == "http://example.com/path"
    with pytest.raises(UrlPolicyError):
        check_input_url("https://example.com:8080/path")


def test_ec4_ipv6_literals_are_checked_with_is_global() -> None:
    """EC4: loopback and IPv4-mapped literals are rejected, a global one allowed."""
    for url in ("https://[::1]/", "https://[::ffff:127.0.0.1]/"):
        with pytest.raises(UrlPolicyError):
            check_input_url(url)
    assert (
        check_input_url("https://[2606:4700:4700::1111]/path")
        == "https://[2606:4700:4700::1111]/path"
    )


def test_ec5_cgnat_is_rejected_and_a_global_ipv4_is_allowed() -> None:
    """EC5: 100.64.0.1 is CGNAT and rejected; 8.8.8.8 is global and allowed."""
    with pytest.raises(UrlPolicyError):
        check_input_url("https://100.64.0.1/path")
    assert check_input_url("https://8.8.8.8/path") == "https://8.8.8.8/path"


def test_f1_multicast_and_reserved_ip_literals_are_rejected() -> None:
    """F1: multicast and reserved literals are rejected, not only non-global ones.

    On Python 3.14 ``ipaddress`` reports ``is_global=True`` for multicast
    addresses, the IETF-reserved ``::7f00:1`` and NAT64-embedded non-global
    IPv4, so the literal rule may not rely on ``is_global`` alone (ADR 0008
    requires rejecting multicast and reserved IPv4/IPv6 ranges).
    """
    for url in (
        "https://224.0.0.1/",
        "https://[ff00::1]/",
        "https://[::7f00:1]/",
        "https://[64:ff9b::127.0.0.1]/",
    ):
        with pytest.raises(UrlPolicyError):
            check_input_url(url)


def test_ec6_local_host_names_are_rejected() -> None:
    """EC6: localhost, its suffixes, .local and .internal are rejected."""
    for url in (
        "https://LOCALHOST/",
        "https://localhost./",
        "https://foo.localhost/",
        "https://printer.local/",
        "https://svc.internal/",
    ):
        with pytest.raises(UrlPolicyError):
            check_input_url(url)


def test_ec7_username_without_password_is_rejected() -> None:
    """EC7: a user name without a password still counts as credentials."""
    with pytest.raises(UrlPolicyError):
        check_input_url("https://user@example.com")


def test_ec8_internationalized_domain_name_is_allowed_as_punycode() -> None:
    """EC8: an internationalized host is accepted and returned as punycode."""
    assert check_input_url("https://bücher.example") == "https://xn--bcher-kva.example/"


def test_ac3_redirect_chain_within_the_allowlist_resolves_to_the_target() -> None:
    """AC3: five allowlist redirects are followed, then the target is returned."""
    assert MAX_REDIRECTS == 5
    transport = _GuardedTransport(_routes(_chain_routes(5, "https://example.com/final")))

    results = asyncio.run(resolve_redirects([_allowlist_url("/hop0")], transport=transport))

    assert results[0].target_url == "https://example.com/final"
    assert [request.url.path for request in transport.requests] == [
        f"/hop{index}" for index in range(6)
    ]
    assert {request.method for request in transport.requests} == {"GET"}


def test_ac3_more_than_five_redirects_within_the_allowlist_is_unresolved() -> None:
    """AC3: a sixth allowlist hop is not followed and the URL is unresolved."""
    transport = _GuardedTransport(_routes(_chain_routes(6, "https://example.com/final")))

    results = asyncio.run(resolve_redirects([_allowlist_url("/hop0")], transport=transport))

    assert results[0].target_url is None
    assert [request.url.path for request in transport.requests] == [
        f"/hop{index}" for index in range(6)
    ]


def test_ec9_relative_location_is_resolved_against_the_current_url() -> None:
    """EC9: a relative Location on the allowlist host becomes the next hop."""
    transport = _GuardedTransport(
        _routes(
            {
                "/a/b": _redirect("next"),
                "/a/next": _redirect("https://example.com/final"),
            }
        )
    )

    results = asyncio.run(resolve_redirects([_allowlist_url("/a/b")], transport=transport))

    assert results[0].target_url == "https://example.com/final"
    assert [request.url.path for request in transport.requests] == ["/a/b", "/a/next"]


def test_ec10_http_location_on_an_allowlist_host_is_unresolved() -> None:
    """EC10: an http Location on the allowlist host is neither followed nor returned."""
    transport = _GuardedTransport(_routes({"/start": _redirect(f"http://{ALLOWLIST_HOST}/next")}))

    results = asyncio.run(resolve_redirects([_allowlist_url("/start")], transport=transport))

    assert results[0].target_url is None
    assert len(transport.requests) == 1


def test_ec11_response_without_redirect_is_unresolved() -> None:
    """EC11: a 200 from the allowlist host without Location is unresolved."""
    transport = _GuardedTransport(_routes({"/start": httpx.Response(200)}))

    results = asyncio.run(resolve_redirects([_allowlist_url("/start")], transport=transport))

    assert results[0].target_url is None


def test_ec12_empty_batch_returns_empty_without_a_request() -> None:
    """EC12: an empty URL list yields an empty result and no request."""
    transport = _GuardedTransport(_routes({}))

    results = asyncio.run(resolve_redirects([], transport=transport))

    assert results == []
    assert transport.requests == []


def test_ec13_duplicate_urls_yield_one_result_and_one_fetch() -> None:
    """EC13: the same URL twice produces one entry and is fetched at most once."""
    url = _allowlist_url("/start")
    transport = _GuardedTransport(_routes({"/start": _redirect("https://example.com/final")}))

    results = asyncio.run(resolve_redirects([url, url], transport=transport))

    assert [result.url for result in results] == [url]
    assert results[0].target_url == "https://example.com/final"
    assert len(transport.requests) == 1


def test_ac4_no_host_outside_the_allowlist_is_contacted() -> None:
    """AC4: the guarded transport sees only allowlist hosts; external URLs are not fetched."""
    transport = _GuardedTransport(_routes({"/start": _redirect("https://example.com/final")}))

    results = asyncio.run(
        resolve_redirects(
            ["https://example.com/direct", _allowlist_url("/start")],
            transport=transport,
        )
    )

    assert [result.target_url for result in results] == [None, "https://example.com/final"]
    assert {request.url.host for request in transport.requests} == {ALLOWLIST_HOST}


def test_ac5_invalid_location_target_is_unresolved() -> None:
    """AC5: a Location target that fails the input check is unresolved and not fetched."""
    transport = _GuardedTransport(_routes({"/start": _redirect("https://localhost/secret")}))

    results = asyncio.run(resolve_redirects([_allowlist_url("/start")], transport=transport))

    assert results[0].target_url is None
    assert len(transport.requests) == 1


@pytest.mark.parametrize(
    "error",
    [httpx.ReadTimeout("timed out"), httpx.ConnectError("connection failed")],
    ids=["timeout", "error"],
)
def test_ac5_timeout_and_transport_error_are_unresolved(error: Exception) -> None:
    """AC5: a timeout and a transport error end the resolution as unresolved."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise error

    transport = _GuardedTransport(handler)

    results = asyncio.run(resolve_redirects([_allowlist_url("/start")], transport=transport))

    assert results[0].target_url is None


def test_ac5_missing_location_and_response_without_redirect_are_unresolved() -> None:
    """AC5: a redirect without Location and a non-redirect response are unresolved."""
    for response in (httpx.Response(302), httpx.Response(204)):
        transport = _GuardedTransport(_routes({"/start": response}))

        results = asyncio.run(resolve_redirects([_allowlist_url("/start")], transport=transport))

        assert results[0].target_url is None


def test_ac6_at_most_five_urls_are_resolved_in_parallel() -> None:
    """AC6: six or more URLs never run more than five resolutions at the same time."""
    assert MAX_PARALLEL_RESOLUTIONS == 5

    async def scenario() -> tuple[list[RedirectResolution], int]:
        gate = asyncio.Event()
        started = 0
        active = 0
        max_active = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal started, active, max_active
            started += 1
            active += 1
            max_active = max(max_active, active)
            try:
                await gate.wait()
            finally:
                active -= 1
            return _redirect("https://example.com/final")

        transport = _GuardedTransport(handler)
        urls = [_allowlist_url(f"/r{index}") for index in range(7)]
        task = asyncio.create_task(resolve_redirects(urls, transport=transport))
        try:
            for _ in range(200):
                if started >= MAX_PARALLEL_RESOLUTIONS or task.done():
                    break
                await asyncio.sleep(0)
            if task.done():
                # Surface a failure of the resolution itself instead of asserting
                # on counters that never moved.
                await task
            assert started == MAX_PARALLEL_RESOLUTIONS
            assert max_active == MAX_PARALLEL_RESOLUTIONS
            gate.set()
            results = await asyncio.wait_for(task, timeout=5)
        finally:
            gate.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return list(results), max_active

    results, max_active = asyncio.run(scenario())

    assert max_active <= MAX_PARALLEL_RESOLUTIONS
    assert len(results) == 7
    assert all(result.target_url == "https://example.com/final" for result in results)


def test_ac6_urls_open_when_the_budget_ends_are_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC6: a request still open when the overall budget ends is unresolved."""
    assert CONNECT_TIMEOUT_SECONDS == 3.0
    assert TOTAL_TIMEOUT_SECONDS == 5.0
    assert OVERALL_BUDGET_SECONDS == 8.0
    monkeypatch.setattr("gemini_search_mcp.urlpolicy.OVERALL_BUDGET_SECONDS", 0.1)

    async def scenario() -> tuple[list[RedirectResolution], list[httpx.Request]]:
        never = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            await never.wait()
            return httpx.Response(200)

        transport = _GuardedTransport(handler)
        results = await asyncio.wait_for(
            resolve_redirects([_allowlist_url("/open")], transport=transport),
            timeout=2,
        )
        return list(results), transport.requests

    results, requests = asyncio.run(scenario())

    assert len(requests) == 1
    assert results[0].target_url is None
