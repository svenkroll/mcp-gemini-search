"""URL policy: input check and grounding redirect resolution (ADR 0008).

Framework-free module with the two stages of the URL policy from ADR 0008:

- **Input check** (:func:`check_input_url`): validates one URL entirely
  offline -- no network access, no DNS resolution -- and returns it
  normalized, or rejects it with :class:`UrlPolicyError` (issue #5).
- **Redirect resolution** (:func:`resolve_redirects`): resolves grounding
  redirect URLs of the host ``vertexaisearch.cloud.google.com`` to their
  target URL by following redirects manually, HTTPS only, never reading
  content (ADR 0003, ADR 0008).

This module may import only the standard library, pydantic and httpx
(ADR 0009); in particular it must never import ``fastmcp`` or
``google.genai``. Per ADR 0008 it builds on the existing building blocks
pydantic ``HttpUrl`` for URL syntax and :mod:`ipaddress` for IP literals
(``is_global``); it contains no custom URL or IP parsers.

The module itself never logs. A rejection reason is meant for the log of the
calling layer only and never reaches a client (ADR 0007); the module also
never reads or returns page content.
"""

import asyncio
import ipaddress
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx
from pydantic import HttpUrl, TypeAdapter, ValidationError

REDIRECT_ALLOWLIST: frozenset[str] = frozenset({"vertexaisearch.cloud.google.com"})
"""The only hosts the server itself ever connects to (ADR 0008).

Connections for redirect resolution go only to these hosts and only via
HTTPS. Hosts are compared case-insensitively on the normalized host.
"""

MAX_URL_LENGTH = 2048
"""Maximum number of characters of an input URL (ADR 0008).

A URL with exactly 2,048 characters is allowed, one with 2,049 characters is
rejected (EC1). Characters, not bytes, are counted.
"""

MAX_REDIRECTS = 5
"""Maximum number of redirects followed within the allowlist (ADR 0008).

A chain that would need a sixth hop within the allowlist counts as
unresolved (AC3).
"""

MAX_PARALLEL_RESOLUTIONS = 5
"""Maximum number of URLs whose redirects are resolved in parallel (ADR 0008)."""

CONNECT_TIMEOUT_SECONDS = 3.0
"""Connect timeout in seconds for every single request of a resolution (ADR 0008)."""

TOTAL_TIMEOUT_SECONDS = 5.0
"""Total timeout in seconds per URL being resolved (ADR 0008)."""

OVERALL_BUDGET_SECONDS = 8.0
"""Overall time budget in seconds for one batch of resolutions (ADR 0008)."""

Clock = Callable[[], float]
"""Monotonic clock like ``time.monotonic``; injectable so tests own the budget."""


class UrlPolicyError(Exception):
    """A URL violates one of the input rules of ADR 0008 (issue #5).

    Attributes:
        reason: short English text of the violated rule, e.g.
            ``url must not contain credentials``. It is used only for
            logging by the calling layer and never reaches a client
            (ADR 0007).

    ``str(exc)`` is always ``reason``. The reason never contains parts of
    the rejected URL beyond rule-neutral facts such as a scheme or a suffix
    name.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class RedirectResolution:
    """Outcome of resolving one input URL (issue #5).

    Attributes:
        url: the input URL, exactly as passed to :func:`resolve_redirects`.
        target_url: the normalized target URL when the URL was resolved;
            ``None`` when the URL counts as unresolved.
    """

    url: str
    target_url: str | None


_HTTP_URL = TypeAdapter(HttpUrl)

_NAT64_NETWORK = ipaddress.IPv6Network("64:ff9b::/96")
"""Well-known NAT64 prefix carrying an IPv4 address in its last 32 bits."""


def _has_non_global_embedded_ipv4(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Whether an IPv6 literal embeds a non-global IPv4 address.

    Covers IPv4-mapped IPv6 (``::ffff:0:0/96``) via ``ipv4_mapped`` and the
    well-known NAT64 prefix ``64:ff9b::/96``. Only the last 32 bits are
    extracted; no address text is parsed here.
    """
    if not isinstance(address, ipaddress.IPv6Address):
        return False
    embedded = address.ipv4_mapped
    if embedded is None and address in _NAT64_NETWORK:
        embedded = ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return embedded is not None and not embedded.is_global


def _parse_input_url(url: str) -> HttpUrl:
    """Apply the input rules of ADR 0008 and return the parsed, normalized URL.

    Shared by :func:`check_input_url` and :func:`resolve_redirects` so every
    rule is evaluated exactly once and in one place. Raises
    :class:`UrlPolicyError` for the first violated rule.
    """
    if len(url) > MAX_URL_LENGTH:
        raise UrlPolicyError(f"url must be at most {MAX_URL_LENGTH} characters")
    try:
        parsed = _HTTP_URL.validate_python(url)
    except ValidationError as exc:
        raise UrlPolicyError("url must be a valid absolute http or https URL") from exc
    if parsed.host is None:
        raise UrlPolicyError("url must contain a host")
    if parsed.scheme not in ("http", "https"):
        raise UrlPolicyError("url scheme must be http or https")
    if parsed.username is not None or parsed.password is not None:
        raise UrlPolicyError("url must not contain credentials")
    if parsed.port not in (None, 80, 443):
        raise UrlPolicyError("url port must be empty, 80 or 443")

    host = parsed.host
    literal = host[1:-1] if host.startswith("[") and host.endswith("]") else host
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        pass
    else:
        if (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
            or _has_non_global_embedded_ipv4(address)
        ):
            raise UrlPolicyError("url host must not be a non-public IP address")

    normalized_host = host.rstrip(".").lower()
    if normalized_host == "localhost" or normalized_host.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise UrlPolicyError("url host must not be a local host name")
    return parsed


def check_input_url(url: str) -> str:
    """Check one URL against the input rules of ADR 0008, entirely offline.

    The check performs no network access and no DNS resolution (AC2): only
    the URL string itself is examined. URL syntax is validated with pydantic
    ``HttpUrl``, IP literals with :func:`ipaddress.ip_address`; there are no
    custom URL or IP parsers (ADR 0008).

    Rules, in evaluation order; the first violated rule wins:

    1. **Length**: at most :data:`MAX_URL_LENGTH` (2,048) characters. A URL
       with exactly 2,048 characters is allowed, one with 2,049 characters
       is rejected (EC1).
    2. **Syntax, scheme and host**: the URL must parse as pydantic
       ``HttpUrl`` with a host present and the scheme ``http`` or ``https``,
       in any letter case (``HTTPS://Example.COM/a`` is allowed, EC2).
    3. **Credentials**: the URL must contain neither a user name nor a
       password; a user name without a password is rejected as well, so
       ``https://user@example.com`` is rejected (EC7).
    4. **Port**: the port must be empty, 80 or 443, regardless of the
       scheme: ``:443`` and ``:80`` are allowed, ``:8080`` is rejected
       (EC3).
    5. **IP literal**: if the host is an IPv4 or IPv6 literal (pydantic
       keeps the surrounding brackets of an IPv6 literal; they are removed
       before the check), its address must satisfy ``is_global`` and must be
       neither multicast nor reserved (``ipaddress`` ``is_multicast`` and
       ``is_reserved``); additionally, an IPv4 address embedded in an
       IPv4-mapped IPv6 literal or in the NAT64 prefix ``64:ff9b::/96`` must
       itself be global. This rejects loopback, private, link-local,
       multicast, CGNAT, reserved and IPv4-mapped IPv6 addresses:
       ``[::1]``, ``[::ffff:127.0.0.1]``, ``224.0.0.1``, ``[ff00::1]``,
       ``[::7f00:1]``, ``[64:ff9b::127.0.0.1]`` and ``100.64.0.1`` are
       rejected, ``[2606:4700:4700::1111]`` and ``8.8.8.8`` are allowed
       (EC4, EC5).
    6. **Host name suffixes**: the host, after removing trailing dots and
       lower-casing, must neither be ``localhost`` nor end with
       ``.localhost``, ``.local`` or ``.internal``: ``LOCALHOST``,
       ``localhost.``, ``foo.localhost``, ``printer.local`` and
       ``svc.internal`` are rejected (EC6).

    Args:
        url: the URL to check, exactly as received; it is not trimmed.

    Returns:
        The normalized URL string, the normalization of pydantic
        ``HttpUrl``: scheme and host lower-cased, an internationalized
        domain name encoded as ASCII (punycode), the scheme's default port
        omitted, and a trailing slash added when the path is empty.
        ``HTTPS://Example.COM/a`` becomes ``https://example.com/a`` (EC2),
        ``https://bücher.example`` becomes ``https://xn--bcher-kva.example/``
        (EC8).

    Raises:
        UrlPolicyError: the URL violates one of the rules above; ``reason``
            names the violated rule and is used only for logging.
    """
    return str(_parse_input_url(url))


async def resolve_redirects(
    urls: Sequence[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    now: Clock | None = None,
) -> list[RedirectResolution]:
    """Resolve grounding redirect URLs to their target URLs (ADR 0003, ADR 0008).

    Batch resolution for the redirect URLs of one ``search`` call.
    Duplicates are resolved once: ``urls`` entries that are equal as strings
    produce exactly one result entry, in order of first occurrence, and are
    fetched at most once (EC13). An empty ``urls`` returns an empty list
    without any request (EC12).

    Batch limits (ADR 0008, AC6):

    - at most :data:`MAX_PARALLEL_RESOLUTIONS` (5) URLs are resolved at the
      same time; further URLs wait for a free slot;
    - the whole batch has :data:`OVERALL_BUDGET_SECONDS` (8) seconds,
      measured with ``now()``; every single request is additionally capped
      by the remaining budget, and URLs still open when the budget ends
      count as unresolved -- the function returns without waiting for their
      pending requests.

    Per URL, the fetch check of ADR 0008 applies:

    - only ``https`` URLs whose host is on :data:`REDIRECT_ALLOWLIST` are
      fetched, and only after passing :func:`check_input_url`. Any other
      input URL -- wrong scheme (e.g. ``http://``), a host outside the
      allowlist, or a URL rejected by the input check -- counts as
      unresolved without any request (AC4).
    - each hop is one ``GET`` request with redirects disabled (never
      followed automatically), sent through an ``httpx.AsyncClient`` created
      for the batch and closed before returning; the connect timeout is
      :data:`CONNECT_TIMEOUT_SECONDS` (3 s) and the total timeout
      :data:`TOTAL_TIMEOUT_SECONDS` (5 s). The response body is never read;
      only the status code and the ``Location`` header are used.
    - a response with a 3xx status and a ``Location`` header is one redirect
      hop. The ``Location`` value is resolved against the current URL, so a
      relative target on the allowlist host becomes absolute and is followed
      as the next hop (EC9).
    - a ``Location`` target whose normalized host is on the allowlist and
      whose scheme is ``https`` passes :func:`check_input_url` (so it carries
      no credentials and no non-default port) and is followed as the next
      hop. At most :data:`MAX_REDIRECTS` (5) redirects are followed within the
      allowlist; a chain that would need a sixth hop within the allowlist
      counts as unresolved (AC3).
    - the first ``Location`` target outside the allowlist is never fetched.
      It is checked with :func:`check_input_url`; on success the normalized
      target URL is the result, on failure the URL counts as unresolved
      (AC5). Both ``https`` and ``http`` targets outside the allowlist are
      treated this way, because the input check allows both schemes.
    - a ``Location`` target on an allowlist host that is not an ``https``
      URL, e.g. ``http://vertexaisearch.cloud.google.com/...``, is neither
      followed nor returned: the URL counts as unresolved (EC10).
    - any response without a redirect status and a ``Location`` header (for
      example status 200, EC11), a missing or invalid ``Location`` value, a
      timeout, a connection or transport error, and any other error end the
      resolution of that URL as unresolved (AC5).

    The function never raises for an unresolvable URL: every failure is an
    unresolved result entry. Only programmer errors (e.g. a non-string
    entry) propagate.

    Args:
        urls: input URLs, typically grounding redirect URLs from the
            citations of one search. Non-allowlist URLs are never fetched
            and count as unresolved (see above).
        transport: httpx transport used for every request; ``None`` means
            the httpx default transport. Tests inject ``httpx.MockTransport``
            so no request ever reaches the network (AC4).
        now: monotonic clock measuring the overall budget; defaults to
            ``time.monotonic``. Injectable so tests own the budget without
            real waiting (AC6).

    Returns:
        One :class:`RedirectResolution` per distinct input URL, in order of
        first occurrence. ``target_url`` is the normalized target URL as
        returned by :func:`check_input_url`, or ``None`` when the URL counts
        as unresolved.

    Postcondition:
        No host outside :data:`REDIRECT_ALLOWLIST` was contacted, no request
        followed a redirect automatically, and no response body was read.
    """
    clock = now if now is not None else time.monotonic
    distinct_urls = list(dict.fromkeys(urls))
    if not distinct_urls:
        return []

    deadline = clock() + OVERALL_BUDGET_SECONDS
    semaphore = asyncio.Semaphore(MAX_PARALLEL_RESOLUTIONS)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        tasks = {
            url: asyncio.create_task(_resolve_with_slot(client, url, deadline, clock, semaphore))
            for url in distinct_urls
        }
        _, pending = await asyncio.wait(tasks.values(), timeout=max(0.0, deadline - clock()))
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    results: list[RedirectResolution] = []
    for url, task in tasks.items():
        if task in pending:
            results.append(RedirectResolution(url=url, target_url=None))
        else:
            results.append(task.result())
    return results


def _request_timeout(remaining_seconds: float) -> httpx.Timeout:
    """Per-request timeout capped by the remaining batch budget (ADR 0008)."""
    total = min(TOTAL_TIMEOUT_SECONDS, remaining_seconds)
    connect = min(CONNECT_TIMEOUT_SECONDS, total)
    return httpx.Timeout(connect=connect, read=total, write=total, pool=connect)


async def _resolve_with_slot(
    client: httpx.AsyncClient,
    url: str,
    deadline: float,
    clock: Clock,
    semaphore: asyncio.Semaphore,
) -> RedirectResolution:
    """Resolve one URL once a parallel slot is free, capped by the budget."""
    async with semaphore:
        remaining = deadline - clock()
        if remaining <= 0:
            return RedirectResolution(url=url, target_url=None)
        try:
            async with asyncio.timeout(min(TOTAL_TIMEOUT_SECONDS, remaining)):
                target_url = await _resolve_one(client, url, deadline, clock)
        except TimeoutError:
            target_url = None
        return RedirectResolution(url=url, target_url=target_url)


async def _resolve_one(
    client: httpx.AsyncClient,
    url: str,
    deadline: float,
    clock: Clock,
) -> str | None:
    """Follow the redirect chain of one URL; return its target or ``None``."""
    try:
        parsed = _parse_input_url(url)
    except UrlPolicyError:
        return None
    if parsed.scheme != "https" or parsed.host not in REDIRECT_ALLOWLIST:
        return None

    current = str(parsed)
    followed = 0
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            return None
        try:
            request = client.build_request("GET", current, timeout=_request_timeout(remaining))
            response = await client.send(request, stream=True, follow_redirects=False)
        except Exception:
            return None
        try:
            status_code = response.status_code
            location = response.headers.get("Location")
        finally:
            await response.aclose()

        if not 300 <= status_code < 400 or location is None:
            return None
        try:
            target = httpx.URL(current).join(location)
        except Exception:
            return None

        target_host = (target.host or "").lower()
        if target_host in REDIRECT_ALLOWLIST:
            if target.scheme.lower() != "https" or followed >= MAX_REDIRECTS:
                return None
            try:
                current = check_input_url(str(target))
            except UrlPolicyError:
                return None
            followed += 1
            continue

        try:
            return check_input_url(str(target))
        except UrlPolicyError:
            return None
