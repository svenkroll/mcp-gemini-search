"""URL policy from ADR 0008: input check and grounding redirect resolution.

Framework-free layer (ADR 0009): it may import only the standard library,
pydantic and httpx. It has two stages:

- :func:`check_url`, the **input check** for every URL the server accepts or
  returns. It never touches the network and never resolves DNS. URL syntax is
  parsed by Pydantic ``HttpUrl``, IP literals by the standard library
  ``ipaddress``; there is no custom URL or IP parser.
- :func:`resolve_redirect` and :func:`resolve_redirects`, the **fetch check**
  for the only network requests the server makes itself: resolving grounding
  redirect URLs (ADR 0003) against the hosts in :data:`REDIRECT_ALLOWLIST`.
  Redirects are followed manually, content is never read, only the
  ``Location`` header counts.

Rejection reasons and unresolved outcomes are meant for logging only; they
never reach a client (ADR 0007). Nothing in this module logs a URL.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

import httpx

MAX_URL_LENGTH = 2048
"""Maximum number of characters of an accepted or returned URL (ADR 0008)."""

ALLOWED_PORTS: frozenset[int] = frozenset({80, 443})
"""Ports a URL may carry, explicitly or implicitly (ADR 0008)."""

BLOCKED_HOST_SUFFIXES: tuple[str, ...] = ("localhost", ".local", ".internal", ".localhost")
"""Host name endings that are rejected, exactly as listed in ADR 0008.

Compared against the lower-cased host with one trailing dot removed, using
plain ``str.endswith``; ``localhost`` therefore also matches ``LOCALHOST``,
``localhost.`` and ``foo.localhost``.
"""

REDIRECT_ALLOWLIST: frozenset[str] = frozenset({"vertexaisearch.cloud.google.com"})
"""Lower-case host names the server may contact to resolve redirects (ADR 0008)."""

REDIRECT_STATUS_CODES: frozenset[int] = frozenset({301, 302, 303, 307, 308})
"""HTTP statuses whose ``Location`` header is evaluated as a redirect."""

RejectionReason = Literal[
    "syntax",
    "scheme",
    "length",
    "credentials",
    "port",
    "ip_literal",
    "host_suffix",
]
"""Reason of a failed input check, one per ADR 0008 rule plus ``syntax``.

- ``syntax``: not a string Pydantic ``HttpUrl`` accepts for a reason other
  than the scheme, including a missing or empty host.
- ``scheme``: the scheme is neither ``http`` nor ``https``.
- ``length``: more than :data:`MAX_URL_LENGTH` characters.
- ``credentials``: a user name and/or password is present.
- ``port``: the port is not in :data:`ALLOWED_PORTS`.
- ``ip_literal``: the host is a non-global or multicast IP literal.
- ``host_suffix``: the host ends in one of :data:`BLOCKED_HOST_SUFFIXES`.
"""


class UrlRejectedError(ValueError):
    """A URL failed the input check of ADR 0008.

    Attributes:
        reason: the violated rule as a :data:`RejectionReason`.

    ``str(exc)`` is exactly ``reason``. The exception never carries the URL
    itself or a Pydantic error text, so it is safe to log; it is for logging
    only and never reaches a client.
    """

    def __init__(self, reason: RejectionReason) -> None:
        self.reason: RejectionReason = reason
        super().__init__(reason)

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class ResolutionLimits:
    """Limits of redirect resolution; the defaults are the ADR 0008 values.

    Attributes:
        max_redirects: maximum number of ``Location`` targets on an allowlist
            host that are followed after the initial request for one URL;
            at most ``1 + max_redirects`` requests are sent per URL.
        max_parallel: maximum number of URLs resolved at the same time in one
            :func:`resolve_redirects` call.
        connect_timeout_seconds: connect timeout of every single request.
        per_url_timeout_seconds: wall-clock limit for the whole resolution of
            one URL, all hops included.
        budget_seconds: wall-clock limit for one :func:`resolve_redirects`
            call, all URLs included.
    """

    max_redirects: int = 5
    max_parallel: int = 5
    connect_timeout_seconds: float = 3.0
    per_url_timeout_seconds: float = 5.0
    budget_seconds: float = 8.0


DEFAULT_LIMITS = ResolutionLimits()
"""The ADR 0008 limits: 5 redirects, 5 parallel, 3 s connect, 5 s per URL, 8 s budget."""


def check_url(url: str) -> str:
    """Apply the ADR 0008 input check to ``url`` and return it normalized.

    Performs no network access and no DNS resolution. The rules are checked
    in this order; the first violated rule determines the reason:

    1. ``length``: ``url`` has more than :data:`MAX_URL_LENGTH` characters
       (2,048 is allowed, 2,049 is rejected).
    2. ``scheme`` / ``syntax``: ``url`` is parsed with Pydantic ``HttpUrl``.
       A non-``http``/``https`` scheme is ``scheme``; any other parse failure,
       including a missing host, is ``syntax``.
    3. ``credentials``: the parsed URL has a user name or a password, also a
       user name without password (``https://user@example.com``).
    4. ``port``: the effective port (explicit or the scheme default) is not
       in :data:`ALLOWED_PORTS`; ``:80`` and ``:443`` are allowed for both
       schemes, ``:8080`` is rejected.
    5. ``ip_literal``: the host is an IPv4 literal or a bracketed IPv6 literal
       whose ``ipaddress`` object is not ``is_global`` or is ``is_multicast``.
       For an IPv4-mapped IPv6 address the mapped IPv4 address is checked
       (``[::ffff:127.0.0.1]`` is rejected). Examples: ``100.64.0.1``
       (CGNAT) and ``[::1]`` are rejected, ``8.8.8.8`` and
       ``[2606:4700:4700::1111]`` are allowed. IPv4 forms that ``HttpUrl``
       normalizes (e.g. ``2130706433``) are checked in normalized form.
    6. ``host_suffix``: the lower-cased host with one trailing dot removed
       ends in one of :data:`BLOCKED_HOST_SUFFIXES` (``LOCALHOST``,
       ``localhost.``, ``foo.localhost``, ``printer.local``,
       ``svc.internal`` are rejected).
    7. ``length``: the normalized result has more than
       :data:`MAX_URL_LENGTH` characters.

    Args:
        url: the URL as received, not stripped or otherwise pre-processed.

    Returns:
        ``str(HttpUrl(url))``: scheme and host lower-cased, an internationalized
        host in Punycode (``https://bücher.example`` becomes
        ``https://xn--bcher-kva.example/``), the default port of the scheme
        dropped and an empty path written as ``/``. Example:
        ``HTTPS://Example.COM/a`` returns ``https://example.com/a``.

    Raises:
        UrlRejectedError: with the reason of the first violated rule.
    """
    raise NotImplementedError


async def resolve_redirect(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    limits: ResolutionLimits = DEFAULT_LIMITS,
) -> str | None:
    """Resolve one grounding redirect URL to its target URL (ADR 0008 fetch check).

    Algorithm:

    - The start URL must pass :func:`check_url`, use ``https`` and have a host
      in :data:`REDIRECT_ALLOWLIST`; otherwise ``None`` is returned without
      any request.
    - Each hop sends one ``GET`` to the current URL with redirects never
      followed automatically and the response body never read.
    - A response whose status is not in :data:`REDIRECT_STATUS_CODES` (e.g.
      200), or a redirect without ``Location`` header, makes the URL
      unresolved.
    - The ``Location`` value is resolved against the current URL (a relative
      ``Location`` stays on the current host) and then input-checked with
      :func:`check_url`; a failed check makes the URL unresolved.
    - If the checked target's host is in :data:`REDIRECT_ALLOWLIST`, it is the
      next hop only if its scheme is ``https``; an ``http`` target on an
      allowlist host is never fetched and makes the URL unresolved. After the
      initial request at most ``limits.max_redirects`` such hops are followed;
      a further redirect to an allowlist host makes the URL unresolved.
    - The first checked target whose host is not in
      :data:`REDIRECT_ALLOWLIST` is returned as the result; it is never
      contacted.

    Only hosts in :data:`REDIRECT_ALLOWLIST` are ever contacted, only via
    ``https``. Every request uses ``limits.connect_timeout_seconds`` as
    connect timeout; the whole resolution is limited to
    ``limits.per_url_timeout_seconds``.

    Args:
        url: the grounding redirect URL as received from the provider.
        transport: httpx transport for all requests; ``None`` uses the default
            network transport. Tests pass an ``httpx.MockTransport``.
        limits: resolution limits, by default the ADR 0008 values.

    Returns:
        The normalized target URL as returned by :func:`check_url`, or
        ``None`` when the URL is unresolved: failed start check, timeout,
        transport or HTTP error, non-redirect response, missing or invalid
        ``Location``, ``http`` hop on an allowlist host, too many redirects.

    Never raises for these cases; only cancellation of the calling task
    propagates.
    """
    raise NotImplementedError


async def resolve_redirects(
    urls: Iterable[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    limits: ResolutionLimits = DEFAULT_LIMITS,
) -> dict[str, str | None]:
    """Resolve several grounding redirect URLs within the ADR 0008 limits.

    Each distinct URL is resolved at most once, exactly as by
    :func:`resolve_redirect` with the same ``transport`` and ``limits``. At
    most ``limits.max_parallel`` resolutions run at the same time. The whole
    call returns after at most ``limits.budget_seconds``; resolutions still
    open at that moment are cancelled and count as unresolved.

    Args:
        urls: the URLs to resolve; duplicates are allowed.
        transport: httpx transport for all requests; ``None`` uses the default
            network transport. Tests pass an ``httpx.MockTransport``.
        limits: resolution limits, by default the ADR 0008 values.

    Returns:
        A dict with exactly one entry per distinct input string, in order of
        first occurrence, mapping it to its normalized target URL or to
        ``None`` when unresolved. An empty input returns ``{}`` without any
        request.

    Never raises for a failed resolution; only cancellation of the calling
    task propagates.
    """
    raise NotImplementedError
