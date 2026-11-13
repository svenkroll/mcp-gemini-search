"""Domain logic and contract of the ``analyze_url`` tool (ADR 0004).

Framework-free (ADR 0009): imports only the standard library, ``provider``,
``urlpolicy`` and the sibling module :mod:`gemini_search_mcp.tools.errors`.
The server (issue #8) wraps :func:`run_analyze_url` and advertises
:data:`ANALYZE_URL_INPUT_SCHEMA` and :data:`ANALYZE_URL_OUTPUT_SCHEMA`.

Input rules are enforced at two boundaries:

1. the advertised JSON schema (:data:`ANALYZE_URL_INPUT_SCHEMA`), checked by
   the MCP layer;
2. :class:`AnalyzeUrlInput` itself: an instance can only exist with a URL
   that passed the ADR 0008 input check (stored normalized) and a valid,
   trimmed question; construction from raw tool arguments goes through
   :meth:`AnalyzeUrlInput.from_arguments`. Every input error is therefore
   raised before the provider can be called.

Retrieval mapping (ADR 0004), applied by :func:`select_retrieved_url` to the
retrievals whose URL matches the requested URL:

=================================================  ===================
Retrievals for the requested URL                   Result
=================================================  ===================
at least one with status ``retrieved``             success
none ``retrieved``, at least one ``unsafe``        ``url_unsafe``
only other (also unknown) statuses, or none        ``url_unreachable``
=================================================  ===================

Retrievals for other URLs never influence the result. On every error no part
of the provider answer reaches the client: the error is a
:class:`~gemini_search_mcp.tools.errors.ToolError` with its fixed message.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Self, cast

from gemini_search_mcp.provider import Retrieval, SearchProvider, UrlAnalysisResult, Usage
from gemini_search_mcp.tools.errors import InvalidInputError, ToolError, tool_error_from_exception
from gemini_search_mcp.urlpolicy import UrlRejectedError, check_url

QUESTION_MAX_LENGTH = 4000
"""Maximum length of the trimmed question in Unicode code points (``len(str)``)."""

QUESTION_MIN_LENGTH = 1
"""Minimum length of the trimmed question in Unicode code points."""

ANALYZE_URL_INPUT_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": (
                    "Public http or https URL to analyze. Credentials, ports other "
                    "than 80 and 443, local host names and private or reserved IP "
                    "addresses are rejected."
                ),
            },
            "question": {
                "type": "string",
                "minLength": QUESTION_MIN_LENGTH,
                "description": (
                    "Question about the content of the URL. Leading and trailing "
                    "whitespace is removed; the rest must have "
                    f"{QUESTION_MIN_LENGTH} to {QUESTION_MAX_LENGTH} characters."
                ),
            },
        },
        "required": ["url", "question"],
    }
)
"""JSON schema of the ``analyze_url`` arguments (ADR 0004).

``maxLength`` is deliberately absent for both fields: the question limit
applies after trimming, which JSON Schema cannot express, and the URL limits
are those of the ADR 0008 input check (``url_not_allowed``), both enforced by
:class:`AnalyzeUrlInput`.
"""

ANALYZE_URL_OUTPUT_SCHEMA: Mapping[str, Any] = MappingProxyType(
    {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "url": {"type": "string"},
            "retrieval_status": {"type": "string", "enum": ["retrieved"]},
        },
        "required": ["answer", "url", "retrieval_status"],
        "additionalProperties": False,
    }
)
"""JSON schema of the ``analyze_url`` ``structuredContent`` (ADR 0004)."""


@dataclass(frozen=True, slots=True)
class AnalyzeUrlInput:
    """Validated ``analyze_url`` arguments (ADR 0004, ADR 0008).

    Attributes:
        url: the URL as normalized by ``urlpolicy.check_url`` (e.g.
            ``HTTPS://Example.COM`` is stored as ``https://example.com/``).
        question: the question with leading and trailing whitespace removed
            (``str.strip()``); 1 to :data:`QUESTION_MAX_LENGTH` code points.

    ``__post_init__`` enforces the rules strictly, without coercion, and
    stores the normalized URL and the trimmed question. Checks run in this
    order; the first violation raises:

    1. ``url`` not a ``str``: ``InvalidInputError("url", "must be a string")``
    2. ``url`` rejected by ``urlpolicy.check_url`` (any
       ``UrlRejectedError``, including a string that is not a URL such as
       ``"not a url"`` or ``""``): ``ToolError("url_not_allowed")``, chained
       ``from`` the ``UrlRejectedError``
    3. ``question`` not a ``str``:
       ``InvalidInputError("question", "must be a string")``
    4. trimmed ``question`` empty (also whitespace only):
       ``InvalidInputError("question", "must not be empty")``
    5. trimmed ``question`` longer than :data:`QUESTION_MAX_LENGTH` code
       points: ``InvalidInputError("question", "must have at most 4000
       characters")``

    The URL is passed to ``check_url`` exactly as received, not stripped.

    Raises:
        InvalidInputError: on a violated contract rule (``invalid_input``).
        ToolError: ``url_not_allowed`` when the URL fails the input check.
    """

    url: str
    question: str

    def __post_init__(self) -> None:
        url: object = self.url
        if not isinstance(url, str):
            raise InvalidInputError("url", "must be a string")
        try:
            normalized_url = check_url(url)
        except UrlRejectedError as error:
            raise ToolError("url_not_allowed") from error
        question: object = self.question
        if not isinstance(question, str):
            raise InvalidInputError("question", "must be a string")
        trimmed = question.strip()
        if len(trimmed) < QUESTION_MIN_LENGTH:
            raise InvalidInputError("question", "must not be empty")
        if len(trimmed) > QUESTION_MAX_LENGTH:
            raise InvalidInputError("question", "must have at most 4000 characters")
        object.__setattr__(self, "url", normalized_url)
        object.__setattr__(self, "question", trimmed)

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, object]) -> Self:
        """Build an :class:`AnalyzeUrlInput` from raw MCP tool arguments.

        Precondition: ``arguments`` is the decoded JSON object of the call.

        - A missing ``url`` key raises ``InvalidInputError("url", "is
          required")``; this check runs first.
        - A missing ``question`` key raises ``InvalidInputError("question",
          "is required")``; this check runs second, before any constructor
          rule.
        - An explicit ``null`` is not absent and fails as ``must be a
          string``.
        - Unknown keys are ignored.
        - All other rules and their order are those of the constructor.

        Raises:
            InvalidInputError: on a violated contract rule.
            ToolError: ``url_not_allowed`` when the URL fails the input check.
        """
        if "url" not in arguments:
            raise InvalidInputError("url", "is required")
        if "question" not in arguments:
            raise InvalidInputError("question", "is required")
        return cls(
            url=cast(str, arguments["url"]),
            question=cast(str, arguments["question"]),
        )


@dataclass(frozen=True, slots=True)
class AnalyzeUrlOutput:
    """``structuredContent`` of a successful ``analyze_url`` call (ADR 0004).

    Attributes:
        answer: the provider answer, unchanged (also when it states that the
            content does not answer the question).
        url: the URL Gemini reports as retrieved, normalized by
            ``urlpolicy.check_url``; equal to ``AnalyzeUrlInput.url``.
        retrieval_status: always ``"retrieved"``.
    """

    answer: str
    url: str
    retrieval_status: Literal["retrieved"] = "retrieved"

    def to_structured_content(self) -> dict[str, Any]:
        """Return the JSON object of ADR 0004 that matches :data:`ANALYZE_URL_OUTPUT_SCHEMA`.

        Exactly the keys ``answer``, ``url`` and ``retrieval_status``; the
        tool text content is the same object serialized as JSON.
        """
        return {
            "answer": self.answer,
            "url": self.url,
            "retrieval_status": self.retrieval_status,
        }


@dataclass(frozen=True, slots=True)
class AnalyzeUrlToolResult:
    """Outcome of :func:`run_analyze_url` for the server (issue #8).

    Attributes:
        output: the client-visible result.
        usage: token usage reported by the provider, for the log line.
        model: the model reported by the provider, for the log line.
    """

    output: AnalyzeUrlOutput
    usage: Usage
    model: str


async def run_analyze_url(
    tool_input: AnalyzeUrlInput,
    *,
    provider: SearchProvider,
) -> AnalyzeUrlToolResult:
    """Execute one ``analyze_url`` call (ADR 0004, ADR 0007).

    Precondition: ``tool_input`` is valid by construction (see
    :class:`AnalyzeUrlInput`); input errors, including ``url_not_allowed``,
    are raised before this function runs, so the provider is never called
    for invalid input.

    Steps:

    1. Call ``provider.analyze_url(tool_input.url, tool_input.question)``
       exactly once, with the normalized URL and the trimmed question.
    2. Determine the reported URL with :func:`select_retrieved_url` from the
       result's retrievals and ``tool_input.url``.
    3. Return the answer unchanged, the reported URL and
       ``retrieval_status="retrieved"`` together with usage and model.

    Raises:
        ToolError: every ``Exception`` raised by the provider or this function
            is mapped with ``tool_error_from_exception``: ``url_unsafe`` and
            ``url_unreachable`` from :func:`select_retrieved_url` unchanged;
            ``ProviderError`` ``unavailable`` -> ``upstream_unavailable``,
            ``rejected`` -> ``upstream_error``, ``internal`` (or an unknown
            kind) -> ``internal_error``; anything else -> ``internal_error``.
            The error carries only its fixed message, never provider answer
            text; the original exception is only available as ``__cause__``.

    A failure after the provider returned a result (``url_unsafe``,
    ``url_unreachable``) carries that result's usage and model on the error
    (:meth:`ToolError.with_response`); a failure of the provider call carries
    none.

    Cancellation (``asyncio.CancelledError``) propagates unmapped.
    """
    result: UrlAnalysisResult | None = None
    try:
        result = await provider.analyze_url(tool_input.url, tool_input.question)
        url = select_retrieved_url(result.retrievals, tool_input.url)
    except Exception as error:
        mapped = tool_error_from_exception(error)
        if result is not None:
            mapped.with_response(result.usage, result.model)
        if mapped is error:
            raise
        raise mapped from error
    return AnalyzeUrlToolResult(
        output=AnalyzeUrlOutput(answer=result.answer, url=url),
        usage=result.usage,
        model=result.model,
    )


def select_retrieved_url(retrievals: Sequence[Retrieval], requested_url: str) -> str:
    """Apply the ADR 0004 retrieval mapping for the requested URL.

    Precondition: ``requested_url`` is already normalized by
    ``urlpolicy.check_url``.

    A retrieval matches when ``urlpolicy.check_url(retrieval.url)`` equals
    ``requested_url``; differences removed by that normalization (case of
    scheme or host, ``/`` for an empty path, default port) therefore still
    match. A retrieval whose URL ``check_url`` rejects never matches and is
    ignored, as are all retrievals for other URLs, whatever their status.

    Among the matching retrievals, in this priority:

    1. any with status ``"retrieved"``: return its normalized URL;
    2. otherwise any with status ``"unsafe"``: ``ToolError("url_unsafe")``;
    3. otherwise (only ``"failed"`` or unknown status values, or no matching
       retrieval at all): ``ToolError("url_unreachable")``.

    Returns:
        The normalized URL of the matching retrieved entry (equal to
        ``requested_url``).

    Raises:
        ToolError: ``url_unsafe`` or ``url_unreachable`` as above.
    """
    unsafe = False
    for retrieval in retrievals:
        try:
            normalized = check_url(retrieval.url)
        except UrlRejectedError:
            continue
        if normalized != requested_url:
            continue
        if retrieval.status == "retrieved":
            return normalized
        if retrieval.status == "unsafe":
            unsafe = True
    raise ToolError("url_unsafe" if unsafe else "url_unreachable")
