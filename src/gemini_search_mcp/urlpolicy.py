"""URL policy from ADR 0008: input check and grounding redirect resolution.

Framework-free module. It imports only the standard library, ``pydantic`` and
``httpx`` (ADR 0009). It has two stages:

* **Input check** (:func:`check_url`): pure, no network access, no DNS.
* **Fetch check** (:func:`resolve_redirect`, :func:`resolve_redirects`): the only
  network requests the server makes itself. They go exclusively to hosts in
  :data:`REDIRECT_ALLOWLIST` over HTTPS, never follow redirects automatically
  and never read response content.

Reasons carried by :class:`UrlRejected` are for logging only and must not be
shown to clients.
"""

import httpx

REDIRECT_ALLOWLIST: frozenset[str] = frozenset({"vertexaisearch.cloud.google.com"})
"""Lower-case hosts that may be contacted for redirect resolution."""

MAX_URL_LENGTH = 2048
"""Maximum accepted URL length in characters (2,048 allowed, 2,049 rejected)."""

ALLOWED_PORTS: frozenset[int] = frozenset({80, 443})
"""Explicit ports accepted by the input check (absent port is also accepted)."""

BLOCKED_HOST_SUFFIXES: tuple[str, ...] = ("localhost", ".local", ".internal", ".localhost")
"""Host name suffixes rejected after lower-casing and trailing-dot removal."""

MAX_REDIRECTS = 5
"""Maximum number of redirects followed within the allowlist per URL."""

MAX_CONCURRENCY = 5
"""Maximum number of parallel resolutions in :func:`resolve_redirects`."""

CONNECT_TIMEOUT_SECONDS = 3.0
"""Connect timeout per URL."""

PER_URL_TIMEOUT_SECONDS = 5.0
"""Total time limit per URL across all its hops."""

TOTAL_BUDGET_SECONDS = 8.0
"""Overall budget for one :func:`resolve_redirects` call."""


class UrlRejected(ValueError):
    """The input check rejected a URL.

    Attributes:
        reason: short machine-friendly text of the violated rule (for example
            ``"scheme"``, ``"length"``, ``"credentials"``, ``"port"``,
            ``"ip_literal"``, ``"host_suffix"``, ``"syntax"``, ``"missing_host"``).
            Used only for logging, never returned to clients.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def check_url(url: str) -> str:
    """Apply the ADR 0008 input check to ``url`` without any network access.

    Rules, all of them required:

    * at most :data:`MAX_URL_LENGTH` characters (measured on the input string);
    * syntax valid per Pydantic ``HttpUrl``; scheme ``http`` or ``https`` only
      (case-insensitive); host present;
    * no credentials (neither user name nor password);
    * port absent, ``80`` or ``443`` (:data:`ALLOWED_PORTS`);
    * if the host is an IP literal (IPv4 or bracketed IPv6) it must satisfy
      ``ipaddress`` ``is_global``; IPv4-mapped IPv6 is judged by its IPv4 part
      (``[::ffff:127.0.0.1]`` is rejected);
    * the host, lower-cased and without a trailing dot, does not end in one of
      :data:`BLOCKED_HOST_SUFFIXES` (``LOCALHOST``, ``localhost.``,
      ``foo.localhost``, ``printer.local``, ``svc.internal`` are rejected).

    Internationalized domain names are allowed. No DNS resolution happens.

    Args:
        url: the URL as received.

    Returns:
        The normalized URL as produced by Pydantic ``HttpUrl`` (lower-case
        scheme and host, IDNA host); e.g. ``HTTPS://Example.COM/a`` becomes
        ``https://example.com/a``.

    Raises:
        UrlRejected: if any rule is violated; ``reason`` names the rule.
    """
    raise NotImplementedError


async def resolve_redirect(url: str, client: httpx.AsyncClient) -> str | None:
    """Resolve one grounding redirect to its target URL.

    Preconditions: ``client`` was created with ``follow_redirects=False``.

    Behavior:

    * ``url`` must be ``https`` and its host must be in
      :data:`REDIRECT_ALLOWLIST`; otherwise nothing is requested and the result
      is ``None``.
    * Each hop is a request whose content is never read (streamed, closed after
      the headers); only the ``Location`` header counts. Redirects are never
      followed automatically.
    * A relative ``Location`` is resolved against the current URL.
    * If the ``Location`` target is an ``https`` URL on the allowlist it becomes
      the next hop, at most :data:`MAX_REDIRECTS` hops. A sixth redirect means
      unresolved.
    * The first target outside the allowlist is not fetched. It is passed
      through :func:`check_url` and its normalized form is returned.
    * An ``http://`` target on an allowlist host is not fetched: unresolved.
    * Every request goes to an allowlist host, never anywhere else.

    Returns:
        The normalized target URL, or ``None`` (unresolved) on timeout,
        transport error, a response without redirect status or without
        ``Location``, too many redirects, or a target rejected by
        :func:`check_url`. Never raises for these cases.
    """
    raise NotImplementedError


async def resolve_redirects(
    urls: list[str],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    max_concurrency: int = MAX_CONCURRENCY,
    per_url_timeout: float = PER_URL_TIMEOUT_SECONDS,
    connect_timeout: float = CONNECT_TIMEOUT_SECONDS,
    total_budget: float = TOTAL_BUDGET_SECONDS,
) -> dict[str, str | None]:
    """Resolve several grounding redirects concurrently.

    Creates one ``httpx.AsyncClient`` (``follow_redirects=False``, the given
    ``transport``, connect timeout ``connect_timeout``) and resolves each
    distinct URL with :func:`resolve_redirect`.

    * At most ``max_concurrency`` resolutions run in parallel.
    * Each URL has at most ``per_url_timeout`` seconds in total.
    * The whole call takes at most ``total_budget`` seconds; URLs still open
      then are cancelled and count as unresolved (``None``).
    * Duplicate URLs (exact string equality) appear once in the result and are
      resolved at most once.
    * An empty ``urls`` returns ``{}`` without creating a client or any request.

    The keyword parameters default to the ADR 0008 limits; they exist so tests
    can shorten them and inject a mocked transport.

    Returns:
        A mapping from each distinct input URL (in first-occurrence order) to
        its normalized target URL, or ``None`` if unresolved. Never raises
        for resolution failures.
    """
    raise NotImplementedError
