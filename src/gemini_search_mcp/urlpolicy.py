"""URL policy of ADR 0008: input check and grounding redirect resolution.

Framework-free module. It may import only the standard library, pydantic and
httpx (ADR 0009). It has two stages:

* **Input check** (:func:`check_url`): a pure function without network access
  and without DNS resolution. URL syntax is parsed by pydantic's ``HttpUrl``
  and IP literals are classified by the standard library ``ipaddress`` module
  (``is_global``, including IPv4-mapped IPv6 addresses). There are no custom
  URL or IP parsers.
* **Fetch check** (:func:`resolve_redirect`, :func:`resolve_redirects`): the
  only network requests this module makes. They go exclusively to hosts in
  :data:`REDIRECT_ALLOWLIST`, over HTTPS, never follow redirects
  automatically and never read response content.

The module-level limit constants are read at call time, so tests may override
them (e.g. with ``monkeypatch``) to keep time-based tests short.
"""

import asyncio
import ipaddress
from collections.abc import Sequence

import httpx
from pydantic import HttpUrl, TypeAdapter, ValidationError

MAX_URL_LENGTH = 2048
"""Maximum length of a URL in characters, measured on the unmodified input."""

ALLOWED_PORTS = frozenset({80, 443})
"""Explicit ports the input check accepts (an absent port is always accepted)."""

FORBIDDEN_HOST_SUFFIXES = ("localhost", ".local", ".internal", ".localhost")
"""Host name suffixes rejected by the input check (compared case-insensitively
and after removing one trailing dot)."""

REDIRECT_ALLOWLIST = frozenset({"vertexaisearch.cloud.google.com"})
"""Hosts that may be contacted for redirect resolution (ADR 0008)."""

MAX_REDIRECTS = 5
"""Maximum number of redirects followed within the allowlist per URL."""

MAX_CONCURRENCY = 5
"""Maximum number of redirect resolutions running in parallel."""

CONNECT_TIMEOUT_SECONDS = 3.0
"""Connect timeout per request."""

URL_TIMEOUT_SECONDS = 5.0
"""Total time per URL, all hops included, measured from the start of its
resolution (not from when it queued for a free concurrency slot)."""

OVERALL_BUDGET_SECONDS = 8.0
"""Overall time budget of one :func:`resolve_redirects` call, queueing included."""

_HTTP_URL_ADAPTER: TypeAdapter[HttpUrl] = TypeAdapter(HttpUrl)
"""Shared parser for the URL syntax check; it performs no network access."""

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
"""HTTP status codes treated as redirects."""


class UrlRejectedError(Exception):
    """The input check rejected a URL.

    Attributes:
        reason: short English description of the violated rule, e.g.
            ``"port not allowed"``. It is meant for logging only and must never
            be returned to a client. It never contains credentials of the URL.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def check_url(url: str) -> str:
    """Apply the input check of ADR 0008 to one URL and return it normalized.

    Pure function: no network access, no DNS resolution. The URL is accepted
    only if all of these hold:

    * at most :data:`MAX_URL_LENGTH` characters (exactly 2,048 is allowed,
      2,049 is rejected); the length is measured on ``url`` as given
    * it parses as a pydantic ``HttpUrl``, which implies scheme ``http`` or
      ``https`` (case-insensitive) and a present host
    * it contains neither a user name nor a password
    * its explicit port is absent, 80 or 443 (``:8080`` is rejected)
    * if the host is an IP literal, the address is global according to
      ``ipaddress`` (``is_global``); loopback, private, link-local, multicast,
      CGNAT (``100.64.0.0/10``) and reserved ranges are rejected, and an
      IPv4-mapped IPv6 literal such as ``[::ffff:127.0.0.1]`` is judged by its
      embedded IPv4 address
    * the host, lower-cased and with one trailing dot removed, does not end in
      ``localhost``, ``.local``, ``.internal`` or ``.localhost``
      (see :data:`FORBIDDEN_HOST_SUFFIXES`)

    Internationalized domain names are allowed. The returned string is the
    normalization of ``HttpUrl`` (lower-case scheme and host, IDN in punycode,
    default port removed, empty path becomes ``/``), e.g.
    ``HTTPS://Example.COM/a`` becomes ``https://example.com/a``.

    Args:
        url: the URL to check, as received.

    Returns:
        The normalized URL.

    Raises:
        UrlRejectedError: if any rule above is violated; ``reason`` names the
            rule. Syntactically invalid input is rejected the same way, never
            with another exception type.
    """
    if len(url) > MAX_URL_LENGTH:
        raise UrlRejectedError("url too long")

    try:
        parsed = _HTTP_URL_ADAPTER.validate_python(url)
    except ValidationError as exc:
        raise UrlRejectedError("invalid url") from exc

    if parsed.username is not None or parsed.password is not None:
        raise UrlRejectedError("credentials not allowed")

    if parsed.port not in ALLOWED_PORTS:
        raise UrlRejectedError("port not allowed")

    host = parsed.host
    if host is None:
        raise UrlRejectedError("host missing")

    literal = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global:
            raise UrlRejectedError("ip literal not global")
        return str(parsed)

    normalized_host = host.lower().removesuffix(".")
    if any(normalized_host.endswith(suffix) for suffix in FORBIDDEN_HOST_SUFFIXES):
        raise UrlRejectedError("forbidden host suffix")

    return str(parsed)


def _is_allowlist_https(url: str) -> bool:
    """Return whether ``url`` may be requested by the fetch check."""
    parsed = httpx.URL(url)
    return (
        parsed.scheme == "https"
        and parsed.host in REDIRECT_ALLOWLIST
        and parsed.port in (None, 443)
    )


async def _request_headers(client: httpx.AsyncClient, url: str) -> tuple[int, str | None] | None:
    """Request ``url`` and return status and ``Location`` without reading the body."""
    timeout = httpx.Timeout(URL_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
    request = client.build_request("GET", url, timeout=timeout)
    try:
        response = await client.send(request, stream=True, follow_redirects=False)
    except httpx.HTTPError, httpx.InvalidURL:
        return None
    try:
        return response.status_code, response.headers.get("Location")
    finally:
        await response.aclose()


async def _follow_redirects(client: httpx.AsyncClient, start: str) -> str | None:
    """Follow allowlist redirects from ``start`` and return the first external target."""
    current = start
    hops = 0
    while True:
        fetched = await _request_headers(client, current)
        if fetched is None:
            return None
        status, location = fetched
        if status not in _REDIRECT_STATUSES or location is None or not location.strip():
            return None

        try:
            target = check_url(str(httpx.URL(current).join(location)))
        except UrlRejectedError, httpx.InvalidURL, ValueError:
            return None

        if not _is_allowlist_https(target):
            if httpx.URL(target).host in REDIRECT_ALLOWLIST:
                return None
            return target

        if hops >= MAX_REDIRECTS:
            return None
        hops += 1
        current = target


async def resolve_redirect(url: str, client: httpx.AsyncClient) -> str | None:
    """Resolve one grounding redirect URL to its target URL (fetch check).

    Algorithm:

    1. ``url`` must pass :func:`check_url`, use ``https``, have a host in
       :data:`REDIRECT_ALLOWLIST` and an absent or ``443`` port. Otherwise the
       result is ``None`` and nothing is requested.
    2. Request the current URL with ``GET`` through ``client`` with
       ``follow_redirects=False``, a connect timeout of
       :data:`CONNECT_TIMEOUT_SECONDS`, and in streaming mode so that the
       response body is never read; the response is closed after the headers
       arrived. Only status and ``Location`` header are used.
    3. A redirect status (301, 302, 303, 307, 308) with a ``Location`` header
       is resolved against the current URL (a relative ``Location`` therefore
       stays on the current host). The result is passed through
       :func:`check_url`.
    4. If the target is an ``https`` URL on an allowlist host (port absent or
       443), it is the next hop and is requested as in step 2. At most
       :data:`MAX_REDIRECTS` such hops are followed; a further redirect into
       the allowlist makes the URL unresolved.
    5. The first target whose host is outside the allowlist is returned as the
       normalized target URL and is never requested.

    The URL is unresolved and ``None`` is returned when: the target of a hop
    fails :func:`check_url`; an allowlist host is addressed via ``http://`` or
    a port other than 443 (it is not requested);
    the response is not a redirect (e.g. ``200``) or lacks ``Location``; more
    than :data:`MAX_REDIRECTS` hops are needed; a transport error occurs; or
    :data:`URL_TIMEOUT_SECONDS` elapse for the whole resolution.

    No host outside :data:`REDIRECT_ALLOWLIST` is ever contacted, and no
    exception for network failures, timeouts or invalid targets is raised.
    Task cancellation is not swallowed.

    Args:
        url: the redirect URL to resolve.
        client: HTTP client used for all requests; tests pass one with a
            mocked transport. The caller owns its lifecycle.

    Returns:
        The normalized target URL, or ``None`` if the URL is unresolved.
    """
    try:
        start = check_url(url)
    except UrlRejectedError:
        return None

    if not _is_allowlist_https(start):
        return None

    try:
        async with asyncio.timeout(URL_TIMEOUT_SECONDS):
            return await _follow_redirects(client, start)
    except TimeoutError:
        return None


async def resolve_redirects(
    urls: Sequence[str], client: httpx.AsyncClient
) -> dict[str, str | None]:
    """Resolve several grounding redirect URLs concurrently.

    Each distinct URL (compared as the exact input string) is resolved at most
    once with :func:`resolve_redirect`, even if it occurs several times in
    ``urls``. At most :data:`MAX_CONCURRENCY` resolutions run in parallel, each
    limited by :data:`URL_TIMEOUT_SECONDS`. The whole call is limited by
    :data:`OVERALL_BUDGET_SECONDS`; when the budget ends, resolutions that are
    still running or have not started are cancelled and count as unresolved.
    Results already obtained are kept.

    Args:
        urls: the redirect URLs to resolve; may be empty.
        client: HTTP client, see :func:`resolve_redirect`.

    Returns:
        A dict with exactly one entry per distinct input URL, in order of first
        occurrence. The value is the normalized target URL, or ``None`` if the
        URL is unresolved. An empty ``urls`` yields ``{}`` without any request.
        Never raises for network failures or timeouts.
    """
    distinct = list(dict.fromkeys(urls))
    if not distinct:
        return {}

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    results: dict[str, str | None] = {}

    async def resolve_one(url: str) -> None:
        async with semaphore:
            results[url] = await resolve_redirect(url, client)

    tasks = [asyncio.create_task(resolve_one(url)) for url in distinct]
    try:
        async with asyncio.timeout(OVERALL_BUDGET_SECONDS):
            await asyncio.gather(*tasks)
    except TimeoutError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    return {url: results.get(url) for url in distinct}
