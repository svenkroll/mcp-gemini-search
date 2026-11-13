"""Domain logic and contract of the ``search`` tool (ADR 0003).

Framework-free (ADR 0009): imports only the standard library, ``provider``,
``urlpolicy`` and the sibling module :mod:`gemini_search_mcp.tools.errors`.
The server (issue #8) wraps :func:`run_search` and advertises
:data:`SEARCH_INPUT_SCHEMA` and :data:`SEARCH_OUTPUT_SCHEMA`.

Input rules are enforced at two boundaries:

1. the advertised JSON schema (:data:`SEARCH_INPUT_SCHEMA`), checked by the
   MCP layer;
2. :class:`SearchInput` itself: an instance can only exist with a valid,
   trimmed query and a valid ``max_sources``; construction from raw tool
   arguments goes through :meth:`SearchInput.from_arguments`.

Index unit: ``Citation.start_index`` and ``Citation.end_index`` are UTF-8 byte
offsets into ``answer`` (ADR 0003, adapter from issue #4; start inclusive, end
exclusive). They are copied unchanged into :class:`Evidence`; the server never
computes or corrects positions. ``Evidence.text`` is taken from
``answer.encode("utf-8")`` and decoded again, never from the ``str`` directly.
The Gemini adapter validates every citation against the UTF-8 bytes of the
answer and drops malformed ones (issue #20), so valid indices reach this
module; the tolerance of :func:`evidence_text` is only a second line of defense.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, Self, cast
from urllib.parse import urlsplit

from gemini_search_mcp.provider import Citation, SearchProvider, Usage
from gemini_search_mcp.tools.errors import InvalidInputError, tool_error_from_exception
from gemini_search_mcp.urlpolicy import (
    REDIRECT_ALLOWLIST,
    UrlRejectedError,
    check_url,
    resolve_redirects,
)

QUERY_MAX_LENGTH = 4000
"""Maximum length of the trimmed query in Unicode code points (``len(str)``)."""

QUERY_MIN_LENGTH = 1
"""Minimum length of the trimmed query in Unicode code points."""

MAX_SOURCES_MIN = 1
"""Smallest allowed ``max_sources`` (ADR 0003)."""

MAX_SOURCES_MAX = 10
"""Largest allowed ``max_sources`` (ADR 0003)."""

MAX_SOURCES_DEFAULT = 5
"""``max_sources`` when the argument is absent (ADR 0003)."""

SEARCH_INPUT_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": QUERY_MIN_LENGTH,
                "description": (
                    "Search query. Leading and trailing whitespace is removed; "
                    f"the rest must have {QUERY_MIN_LENGTH} to {QUERY_MAX_LENGTH} characters."
                ),
            },
            "max_sources": {
                "type": "integer",
                "minimum": MAX_SOURCES_MIN,
                "maximum": MAX_SOURCES_MAX,
                "default": MAX_SOURCES_DEFAULT,
                "description": "Maximum number of returned sources.",
            },
        },
        "required": ["query"],
    }
)
"""JSON schema of the ``search`` arguments (ADR 0003).

``maxLength`` is deliberately absent: the 4,000-character limit applies after
trimming, which JSON Schema cannot express; :class:`SearchInput` enforces it.
JSON Schema ``integer`` rejects ``"5"`` and ``true``.
"""

SEARCH_OUTPUT_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "evidence": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "start_index": {"type": "integer"},
                                    "end_index": {"type": "integer"},
                                },
                                "required": ["text", "start_index", "end_index"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["title", "url", "evidence"],
                    "additionalProperties": False,
                },
            },
            "search_queries": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["answer", "sources", "search_queries"],
        "additionalProperties": False,
    }
)
"""JSON schema of the ``search`` ``structuredContent`` (ADR 0003)."""


@dataclass(frozen=True, slots=True)
class SearchInput:
    """Validated ``search`` arguments (ADR 0003).

    Attributes:
        query: the query with leading and trailing whitespace removed
            (``str.strip()``); 1 to :data:`QUERY_MAX_LENGTH` code points.
        max_sources: an ``int`` (never a ``bool``) from :data:`MAX_SOURCES_MIN`
            to :data:`MAX_SOURCES_MAX`.

    ``__post_init__`` enforces the rules strictly, without coercion, and
    stores the trimmed query. Checks run in this order; the first violation
    raises ``InvalidInputError`` with:

    1. ``query`` not a ``str``: ``("query", "must be a string")``
    2. trimmed ``query`` empty: ``("query", "must not be empty")``
    3. trimmed ``query`` longer than :data:`QUERY_MAX_LENGTH` code points:
       ``("query", "must have at most 4000 characters")``
    4. ``type(max_sources) is not int`` (rejects ``"5"``, ``5.0``, ``True``,
       ``None``): ``("max_sources", "must be an integer")``
    5. ``max_sources`` outside the range:
       ``("max_sources", "must be between 1 and 10")``

    Raises:
        InvalidInputError: on the first violated rule.
    """

    query: str
    max_sources: int = MAX_SOURCES_DEFAULT

    def __post_init__(self) -> None:
        query: object = self.query
        if not isinstance(query, str):
            raise InvalidInputError("query", "must be a string")
        trimmed = query.strip()
        if len(trimmed) < QUERY_MIN_LENGTH:
            raise InvalidInputError("query", "must not be empty")
        if len(trimmed) > QUERY_MAX_LENGTH:
            raise InvalidInputError("query", "must have at most 4000 characters")
        if type(self.max_sources) is not int:
            raise InvalidInputError("max_sources", "must be an integer")
        if not MAX_SOURCES_MIN <= self.max_sources <= MAX_SOURCES_MAX:
            raise InvalidInputError("max_sources", "must be between 1 and 10")
        object.__setattr__(self, "query", trimmed)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> Self:
        """Build a :class:`SearchInput` from raw MCP tool arguments.

        Precondition: ``arguments`` is the decoded JSON object of the call.

        - A missing ``query`` key raises
          ``InvalidInputError("query", "is required")``.
        - A missing ``max_sources`` key uses :data:`MAX_SOURCES_DEFAULT`; an
          explicit ``null`` is not absent and fails as ``must be an integer``.
        - Unknown keys are ignored.
        - All other rules are those of the constructor.

        Raises:
            InvalidInputError: on the first violated rule.
        """
        if "query" not in arguments:
            raise InvalidInputError("query", "is required")
        max_sources = arguments.get("max_sources", MAX_SOURCES_DEFAULT)
        return cls(query=cast(str, arguments["query"]), max_sources=cast(int, max_sources))


@dataclass(frozen=True, slots=True)
class Evidence:
    """One citation of a source inside ``answer`` (ADR 0003).

    Attributes:
        text: ``answer.encode("utf-8")[start_index:end_index]`` decoded as
            UTF-8; see :func:`evidence_text`.
        start_index: ``Citation.start_index``, unchanged (UTF-8 bytes,
            inclusive).
        end_index: ``Citation.end_index``, unchanged (UTF-8 bytes, exclusive).
    """

    text: str
    start_index: int
    end_index: int


@dataclass(frozen=True, slots=True)
class Source:
    """One source per target URL (ADR 0003).

    Attributes:
        title: title of the source's first citation, ``""`` when it has none.
        url: the target URL as normalized by ``urlpolicy.check_url``.
        evidence: one entry per kept citation of this target URL, in citation
            order; never empty.
    """

    title: str
    url: str
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SearchOutput:
    """``structuredContent`` of a successful ``search`` call (ADR 0003).

    Attributes:
        answer: the provider answer, unchanged.
        sources: at most ``max_sources`` merged sources, ordered by first
            citation.
        search_queries: the executed search queries, unchanged and in provider
            order.
    """

    answer: str
    sources: list[Source] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)

    def to_structured_content(self) -> dict[str, Any]:
        """Return the JSON object of ADR 0003 that matches :data:`SEARCH_OUTPUT_SCHEMA`.

        Keys and nesting exactly as in the ADR; the tool text content is the
        same object serialized as JSON.
        """
        return {
            "answer": self.answer,
            "sources": [
                {
                    "title": source.title,
                    "url": source.url,
                    "evidence": [
                        {
                            "text": item.text,
                            "start_index": item.start_index,
                            "end_index": item.end_index,
                        }
                        for item in source.evidence
                    ],
                }
                for source in self.sources
            ],
            "search_queries": list(self.search_queries),
        }


@dataclass(frozen=True, slots=True)
class SearchToolResult:
    """Outcome of :func:`run_search` for the server (issue #8).

    Attributes:
        output: the client-visible result.
        usage: token usage reported by the provider, for the log line.
        model: the model reported by the provider, for the log line.
    """

    output: SearchOutput
    usage: Usage
    model: str


class RedirectResolver(Protocol):
    """Resolves grounding redirect URLs to target URLs (ADR 0003, ADR 0008).

    Contract of ``urlpolicy.resolve_redirects``: one entry per distinct input
    URL, mapped to the normalized target URL or ``None`` when unresolved.
    Must enforce the fetch check and limits of ADR 0008 itself. Production
    uses :data:`DEFAULT_REDIRECT_RESOLVER`; tests inject a fake without
    network access.
    """

    async def __call__(self, urls: Iterable[str], /) -> Mapping[str, str | None]:
        """Resolve every URL in ``urls``; never raise for a failed resolution."""
        ...


DEFAULT_REDIRECT_RESOLVER: RedirectResolver = resolve_redirects
"""Production resolver: ``urlpolicy.resolve_redirects`` with the ADR 0008 limits."""


async def run_search(
    tool_input: SearchInput,
    *,
    provider: SearchProvider,
    resolver: RedirectResolver,
) -> SearchToolResult:
    """Execute one ``search`` call (ADR 0003, ADR 0007).

    Precondition: ``tool_input`` is valid by construction (see
    :class:`SearchInput`); input errors are raised before this function runs.

    Steps:

    1. Call ``provider.search(tool_input.query)`` exactly once.
    2. Build the sources with :func:`build_sources`.
    3. Return ``answer`` and ``search_queries`` unchanged together with the
       sources, the usage and the model.

    A result without citations, or with all sources dropped, is a success
    with an empty ``sources`` list; missing search queries give an empty
    ``search_queries`` list.

    Raises:
        ToolError: every ``Exception`` raised by the provider, the resolver or
            this function is mapped with ``tool_error_from_exception``:
            ``ProviderError`` ``unavailable`` -> ``upstream_unavailable``,
            ``rejected`` -> ``upstream_error``, ``internal`` ->
            ``internal_error``; anything else -> ``internal_error``. The
            original exception is only available as ``__cause__``.

    Cancellation (``asyncio.CancelledError``) propagates unmapped.
    """
    try:
        result = await provider.search(tool_input.query)
        sources = await build_sources(
            result.citations,
            result.answer,
            tool_input.max_sources,
            resolver=resolver,
        )
    except Exception as error:
        raise tool_error_from_exception(error) from error
    return SearchToolResult(
        output=SearchOutput(
            answer=result.answer,
            sources=sources,
            search_queries=list(result.search_queries),
        ),
        usage=result.usage,
        model=result.model,
    )


async def build_sources(
    citations: Sequence[Citation],
    answer: str,
    max_sources: int,
    *,
    resolver: RedirectResolver,
) -> list[Source]:
    """Turn provider citations into the ADR 0003 sources.

    Algorithm:

    1. Input check: each ``citation.url`` passes ``urlpolicy.check_url``;
       a rejected citation is dropped.
    2. Redirects: a checked URL whose host is in
       ``urlpolicy.REDIRECT_ALLOWLIST`` is a grounding redirect. All distinct
       redirect URLs are resolved in one ``resolver`` call (never called when
       there is none). An unresolved redirect drops its citations. A resolved
       target passes ``check_url`` again (defense in depth for injected
       resolvers); on rejection its citations are dropped.
    3. All other checked URLs are their own target URL.
    4. Merge: kept citations are grouped by normalized target URL, so a
       redirect and a direct URL with the same target form one source.
    5. Order: "first citation" is the position in ``citations`` (the adapter
       delivers them in order of appearance in the answer). Sources are
       ordered by the position of their first kept citation; a source's
       ``title`` is that citation's title (``""`` if it has none); its
       evidence lists all its kept citations in citation order, one
       :class:`Evidence` per citation via :func:`evidence_text`.
    6. Truncate to the first ``max_sources`` sources.

    Postconditions: every evidence entry corresponds to exactly one input
    citation; a dropped citation contributes no evidence; target URLs are
    unique; ``len(result) <= max_sources``.
    """
    checked: list[tuple[Citation, str]] = []
    for citation in citations:
        try:
            checked.append((citation, check_url(citation.url)))
        except UrlRejectedError:
            continue

    redirect_urls = [url for _, url in checked if _is_grounding_redirect(url)]
    resolved: Mapping[str, str | None] = {}
    if redirect_urls:
        resolved = await resolver(list(dict.fromkeys(redirect_urls)))

    sources: dict[str, Source] = {}
    for citation, url in checked:
        target: str | None = url
        if _is_grounding_redirect(url):
            target = resolved.get(url)
            if target is None:
                continue
            try:
                target = check_url(target)
            except UrlRejectedError:
                continue
        evidence = Evidence(
            text=evidence_text(answer, citation.start_index, citation.end_index),
            start_index=citation.start_index,
            end_index=citation.end_index,
        )
        source = sources.get(target)
        if source is None:
            sources[target] = Source(title=citation.title, url=target, evidence=[evidence])
        else:
            source.evidence.append(evidence)

    return list(sources.values())[:max_sources]


def _is_grounding_redirect(url: str) -> bool:
    """Return whether the normalized ``url`` points to a redirect allowlist host."""
    return urlsplit(url).hostname in REDIRECT_ALLOWLIST


def evidence_text(answer: str, start_index: int, end_index: int) -> str:
    """Return the slice of ``answer`` between two UTF-8 byte offsets.

    Computes ``answer.encode("utf-8", errors="surrogatepass")[start:end]``
    with negative offsets treated as 0, and decodes it with
    ``errors="replace"``, so an offset inside a multi-byte character yields
    U+FFFD instead of an exception. ``surrogatepass`` encodes a lone surrogate
    in ``answer`` as its three bytes, so later offsets stay aligned and the
    surrogate itself becomes U+FFFD in the slice. Offsets beyond the answer
    are truncated by slicing; ``end_index <= start_index`` yields ``""``.
    Never raises for any answer and any integer offsets.

    The Gemini adapter already validates citations and drops those with
    missing, out-of-range or multi-byte-cutting offsets, so it delivers only
    valid offsets. This tolerance is a second line of defense that protects
    against providers that do not validate.
    """
    data = answer.encode("utf-8", errors="surrogatepass")
    return data[max(start_index, 0) : max(end_index, 0)].decode("utf-8", errors="replace")
