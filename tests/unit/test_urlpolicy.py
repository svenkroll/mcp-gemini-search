"""Acceptance tests for the URL policy from ADR 0008 (issue #5).

The input check is exercised through ``check_url``; the fetch check through
``resolve_redirect`` and ``resolve_redirects``. Every network request runs
against an ``httpx.MockTransport``, never against the real network. Fixtures
contain only hand-written URLs.
"""

import asyncio
import socket
import time

import httpx
import pytest

from gemini_search_mcp.urlpolicy import (
    ResolutionLimits,
    UrlRejectedError,
    check_url,
    resolve_redirect,
    resolve_redirects,
)

ALLOWLIST_HOST = "vertexaisearch.cloud.google.com"
EXTERNAL_TARGET = "https://example.com/target"


def _allowlist_url(path: str) -> str:
    """Build an HTTPS URL on the ADR 0008 redirect allowlist host."""
    return f"https://{ALLOWLIST_HOST}{path}"


def _assert_rejected(url: str, reason: str) -> None:
    """Assert that the input check rejects ``url`` with ``reason``."""
    with pytest.raises(UrlRejectedError) as excinfo:
        check_url(url)
    assert excinfo.value.reason == reason
    assert str(excinfo.value) == reason


class _Recorder:
    """MockTransport handler that records requests and serves canned responses."""

    def __init__(self, responses: dict[str, httpx.Response] | None = None) -> None:
        self.responses = responses or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.get(str(request.url), httpx.Response(200))

    @property
    def urls(self) -> list[str]:
        return [str(request.url) for request in self.requests]

    @property
    def hosts(self) -> list[str]:
        return [request.url.host for request in self.requests]


def _redirect_chain(allowlist_hops: int) -> tuple[dict[str, httpx.Response], str]:
    """Build a chain of ``allowlist_hops`` allowlist redirects ending in the target."""
    responses: dict[str, httpx.Response] = {}
    for index in range(allowlist_hops):
        responses[_allowlist_url(f"/r{index}")] = httpx.Response(
            302, headers={"Location": _allowlist_url(f"/r{index + 1}")}
        )
    responses[_allowlist_url(f"/r{allowlist_hops}")] = httpx.Response(
        302, headers={"Location": EXTERNAL_TARGET}
    )
    return responses, _allowlist_url("/r0")


# --- AC1: every input rule has a rejected and an allowed case -----------------


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        pytest.param("ftp://example.com/", "scheme", id="scheme"),
        pytest.param("https://", "syntax", id="missing-host"),
        pytest.param("https://example.com/" + "a" * 2029, "length", id="length"),
        pytest.param("https://user@example.com/", "credentials", id="credentials"),
        pytest.param("https://example.com:8080/", "port", id="port"),
        pytest.param("https://127.0.0.1/", "ip_literal", id="ip-literal"),
        pytest.param("https://printer.local/", "host_suffix", id="host-suffix"),
    ],
)
def test_ac1_rejects_each_input_rule(url: str, reason: str) -> None:
    """AC1: each ADR 0008 rule has a rejected case with its own reason."""
    _assert_rejected(url, reason)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param("http://example.com/", "http://example.com/", id="scheme"),
        pytest.param("https://example.com/", "https://example.com/", id="host-present"),
        pytest.param("https://example.com/short", "https://example.com/short", id="length"),
        pytest.param("https://example.com/page", "https://example.com/page", id="credentials"),
        pytest.param("https://example.com:443/", "https://example.com/", id="port"),
        pytest.param("https://8.8.8.8/", "https://8.8.8.8/", id="ip-literal"),
        pytest.param("https://example.com/", "https://example.com/", id="host-suffix"),
    ],
)
def test_ac1_allows_each_input_rule(url: str, expected: str) -> None:
    """AC1: each ADR 0008 rule has an allowed case."""
    assert check_url(url) == expected


# --- AC2: the input check never touches the network ---------------------------


def test_ac2_check_url_performs_no_network_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: the input check neither opens sockets nor resolves DNS."""

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("check_url must not access the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)

    assert check_url("https://example.com/page") == "https://example.com/page"
    assert check_url("https://bücher.example") == "https://xn--bcher-kva.example/"
    _assert_rejected("https://127.0.0.1/", "ip_literal")
    _assert_rejected("https://printer.local/", "host_suffix")


# --- AC3: redirect chains within the allowlist --------------------------------


def test_ac3_chain_within_allowlist_resolves_to_target() -> None:
    """AC3: five allowlist hops are followed and resolve to the external target."""
    responses, start = _redirect_chain(5)
    recorder = _Recorder(responses)

    result = asyncio.run(resolve_redirect(start, transport=httpx.MockTransport(recorder)))

    assert result == EXTERNAL_TARGET
    assert recorder.urls == [
        _allowlist_url("/r0"),
        _allowlist_url("/r1"),
        _allowlist_url("/r2"),
        _allowlist_url("/r3"),
        _allowlist_url("/r4"),
        _allowlist_url("/r5"),
    ]


def test_ac3_more_than_five_hops_is_unresolved() -> None:
    """AC3: a sixth allowlist hop is not followed and counts as unresolved."""
    responses, start = _redirect_chain(6)
    recorder = _Recorder(responses)

    result = asyncio.run(resolve_redirect(start, transport=httpx.MockTransport(recorder)))

    assert result is None
    assert _allowlist_url("/r6") not in recorder.urls


# --- AC4: no host outside the allowlist is ever contacted ---------------------


def test_ac4_only_allowlist_hosts_are_contacted() -> None:
    """AC4: every request goes to an allowlist host; other hosts are never contacted."""
    recorder = _Recorder(
        {_allowlist_url("/start"): httpx.Response(302, headers={"Location": EXTERNAL_TARGET})}
    )
    result = asyncio.run(
        resolve_redirect(_allowlist_url("/start"), transport=httpx.MockTransport(recorder))
    )
    assert result == EXTERNAL_TARGET
    assert recorder.hosts == [ALLOWLIST_HOST]

    outside = _Recorder()
    assert (
        asyncio.run(
            resolve_redirect("https://example.com/start", transport=httpx.MockTransport(outside))
        )
        is None
    )
    assert outside.requests == []


# --- AC5: invalid Location, timeout and non-redirect responses ----------------


def test_ac5_invalid_location_target_is_unresolved() -> None:
    """AC5: a Location target that fails the input check is unresolved."""
    recorder = _Recorder(
        {_allowlist_url("/start"): httpx.Response(302, headers={"Location": "https://[::1]/"})}
    )

    result = asyncio.run(
        resolve_redirect(_allowlist_url("/start"), transport=httpx.MockTransport(recorder))
    )

    assert result is None
    assert recorder.hosts == [ALLOWLIST_HOST]


def test_ac5_timeout_is_unresolved() -> None:
    """AC5: a transport timeout counts as unresolved instead of raising."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timeout", request=request)

    result = asyncio.run(
        resolve_redirect(_allowlist_url("/start"), transport=httpx.MockTransport(handler))
    )

    assert result is None


def test_ac5_per_url_timeout_is_unresolved() -> None:
    """AC5: a resolution exceeding the per-URL limit counts as unresolved."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2.0)
        return httpx.Response(200)

    limits = ResolutionLimits(per_url_timeout_seconds=0.05)
    started = time.monotonic()
    result = asyncio.run(
        resolve_redirect(
            _allowlist_url("/slow"), transport=httpx.MockTransport(handler), limits=limits
        )
    )
    elapsed = time.monotonic() - started

    assert result is None
    assert elapsed < 1.0


def test_ac5_response_without_redirect_is_unresolved() -> None:
    """AC5: a 200 response from an allowlist host is not a redirect."""
    recorder = _Recorder({_allowlist_url("/start"): httpx.Response(200)})

    result = asyncio.run(
        resolve_redirect(_allowlist_url("/start"), transport=httpx.MockTransport(recorder))
    )

    assert result is None
    assert recorder.hosts == [ALLOWLIST_HOST]


# --- AC6: concurrency limit and overall budget --------------------------------


def test_ac6_respects_max_parallel() -> None:
    """AC6: at most five URLs are resolved at the same time."""
    state = {"active": 0, "max_active": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["active"] += 1
        state["max_active"] = max(state["max_active"], state["active"])
        try:
            await asyncio.sleep(0.01)
        finally:
            state["active"] -= 1
        return httpx.Response(200)

    urls = [_allowlist_url(f"/parallel/{index}") for index in range(10)]
    results = asyncio.run(resolve_redirects(urls, transport=httpx.MockTransport(handler)))

    assert results == dict.fromkeys(urls)
    assert 1 <= state["max_active"] <= 5


def test_ac6_stops_at_overall_budget() -> None:
    """AC6: URLs still open when the budget ends count as unresolved."""

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2.0)
        return httpx.Response(200)

    urls = [_allowlist_url(f"/budget/{index}") for index in range(3)]
    limits = ResolutionLimits(budget_seconds=0.05, per_url_timeout_seconds=10.0)

    started = time.monotonic()
    results = asyncio.run(
        resolve_redirects(urls, transport=httpx.MockTransport(handler), limits=limits)
    )
    elapsed = time.monotonic() - started

    assert results == dict.fromkeys(urls)
    assert elapsed < 1.0


# --- F1: malformed Location header -------------------------------------------


@pytest.mark.parametrize(
    "location",
    [
        pytest.param("https:evil.com", id="scheme-without-slashes"),
        pytest.param("https://[bad", id="unparsable-ipv6-literal"),
    ],
)
def test_f1_malformed_location_header_is_unresolved(location: str) -> None:
    """F1: a malformed Location on an allowlist redirect counts as unresolved."""
    recorder = _Recorder(
        {_allowlist_url("/start"): httpx.Response(302, headers={"Location": location})}
    )

    result = asyncio.run(
        resolve_redirect(_allowlist_url("/start"), transport=httpx.MockTransport(recorder))
    )

    assert result is None
    assert recorder.hosts == [ALLOWLIST_HOST]


# --- EC1: URL length boundary -------------------------------------------------


def test_ec1_url_with_2048_characters_is_allowed() -> None:
    """EC1: exactly 2,048 characters are allowed."""
    url = "https://example.com/" + "a" * (2048 - len("https://example.com/"))
    assert len(url) == 2048

    assert check_url(url) == url


def test_ec1_url_with_2049_characters_is_rejected() -> None:
    """EC1: 2,049 characters are rejected with the length reason."""
    url = "https://example.com/" + "a" * (2049 - len("https://example.com/"))
    assert len(url) == 2049

    _assert_rejected(url, "length")


# --- EC2: upper-case scheme and host ------------------------------------------


def test_ec2_upper_case_scheme_and_host_are_normalized() -> None:
    """EC2: an upper-case scheme and host are accepted and returned lower-cased."""
    assert check_url("HTTPS://Example.COM/a") == "https://example.com/a"


# --- EC3: explicit ports ------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        pytest.param("https://example.com:443/a", "https://example.com/a", id="https-443"),
        pytest.param("http://example.com:80/a", "http://example.com/a", id="http-80"),
        pytest.param("https://example.com:80/a", "https://example.com:80/a", id="https-80"),
    ],
)
def test_ec3_allowed_ports_are_accepted(url: str, expected: str) -> None:
    """EC3: explicit ports 443 and 80 are allowed."""
    assert check_url(url) == expected


def test_ec3_other_port_is_rejected() -> None:
    """EC3: port 8080 is rejected with the port reason."""
    _assert_rejected("https://example.com:8080/", "port")


# --- EC4: IPv6 literals -------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://[::1]/", id="loopback"),
        pytest.param("https://[::ffff:127.0.0.1]/", id="ipv4-mapped-loopback"),
    ],
)
def test_ec4_non_global_ipv6_literal_is_rejected(url: str) -> None:
    """EC4: loopback and IPv4-mapped loopback IPv6 literals are rejected."""
    _assert_rejected(url, "ip_literal")


def test_ec4_global_ipv6_literal_is_allowed() -> None:
    """EC4: a global IPv6 literal is allowed."""
    assert check_url("https://[2606:4700:4700::1111]") == "https://[2606:4700:4700::1111]/"


# --- EC5: IPv4 literals -------------------------------------------------------


def test_ec5_cgnat_ipv4_literal_is_rejected() -> None:
    """EC5: a CGNAT IPv4 literal is rejected."""
    _assert_rejected("https://100.64.0.1/", "ip_literal")


def test_ec5_global_ipv4_literal_is_allowed() -> None:
    """EC5: a global IPv4 literal is allowed."""
    assert check_url("https://8.8.8.8/") == "https://8.8.8.8/"


# --- EC6: blocked host suffixes ----------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("https://LOCALHOST/", id="upper-case-localhost"),
        pytest.param("https://localhost./", id="trailing-dot"),
        pytest.param("https://foo.localhost/", id="subdomain-localhost"),
        pytest.param("https://printer.local/", id="local"),
        pytest.param("https://svc.internal/", id="internal"),
    ],
)
def test_ec6_blocked_host_suffix_is_rejected(url: str) -> None:
    """EC6: localhost, .local, .internal and .localhost hosts are rejected."""
    _assert_rejected(url, "host_suffix")


# --- EC7: credentials --------------------------------------------------------


def test_ec7_user_name_without_password_is_rejected() -> None:
    """EC7: a user name without a password still counts as credentials."""
    _assert_rejected("https://user@example.com", "credentials")


# --- EC8: internationalized domain name --------------------------------------


def test_ec8_internationalized_domain_is_allowed() -> None:
    """EC8: an IDN host is accepted and returned in Punycode."""
    assert check_url("https://bücher.example") == "https://xn--bcher-kva.example/"


# --- EC9/EC10: relative and insecure allowlist Locations ----------------------


def test_ec9_relative_location_is_resolved_and_followed() -> None:
    """EC9: a relative Location is resolved against the current URL."""
    start = _allowlist_url("/redirect")
    hop = _allowlist_url("/hop")
    recorder = _Recorder(
        {
            start: httpx.Response(302, headers={"Location": "/hop"}),
            hop: httpx.Response(302, headers={"Location": EXTERNAL_TARGET}),
        }
    )

    result = asyncio.run(resolve_redirect(start, transport=httpx.MockTransport(recorder)))

    assert result == EXTERNAL_TARGET
    assert recorder.urls == [start, hop]


def test_ec10_http_location_on_allowlist_host_is_unresolved() -> None:
    """EC10: an http Location on an allowlist host is never fetched."""
    start = _allowlist_url("/start")
    recorder = _Recorder(
        {start: httpx.Response(302, headers={"Location": f"http://{ALLOWLIST_HOST}/hop"})}
    )

    result = asyncio.run(resolve_redirect(start, transport=httpx.MockTransport(recorder)))

    assert result is None
    assert recorder.urls == [start]


# --- EC11: 200 response without redirect -------------------------------------


def test_ec11_200_response_is_unresolved() -> None:
    """EC11: a 200 response from an allowlist host is unresolved."""
    recorder = _Recorder({_allowlist_url("/start"): httpx.Response(200)})

    result = asyncio.run(
        resolve_redirect(_allowlist_url("/start"), transport=httpx.MockTransport(recorder))
    )

    assert result is None


# --- EC12/EC13: batch behavior ------------------------------------------------


def test_ec12_empty_url_list_returns_empty_mapping() -> None:
    """EC12: an empty input returns an empty result without any request."""
    recorder = _Recorder()

    assert asyncio.run(resolve_redirects([], transport=httpx.MockTransport(recorder))) == {}
    assert recorder.requests == []


def test_ec13_duplicate_url_is_resolved_once() -> None:
    """EC13: the same URL twice yields one entry and is resolved at most once."""
    start = _allowlist_url("/duplicate")
    recorder = _Recorder({start: httpx.Response(302, headers={"Location": EXTERNAL_TARGET})})

    results = asyncio.run(
        resolve_redirects([start, start], transport=httpx.MockTransport(recorder))
    )

    assert results == {start: EXTERNAL_TARGET}
    assert recorder.urls == [start]
