"""Tool errors shared by ``search`` and ``analyze_url`` (ADR 0007).

A tool error carries exactly one code from the ADR 0007 table and the fixed
client message of that code. It never carries input values, provider messages,
Pydantic texts or exception texts. Technical details stay available to the
server only through exception chaining (``raise ToolError(...) from exc``):
``__cause__`` may be logged as ``error_detail`` together with the request ID
(ADR 0007), but it is never part of :attr:`ToolError.message` or of
:meth:`ToolError.to_payload`.

Mapping of failures to codes, used by both tools:

========================================  ========================
Failure                                   Code
========================================  ========================
``ProviderError(kind="unavailable")``     ``upstream_unavailable``
``ProviderError(kind="rejected")``        ``upstream_error``
``ProviderError(kind="internal")``        ``internal_error``
a :class:`ToolError`                      its own code, unchanged
any other ``Exception``                   ``internal_error``
========================================  ========================

``BaseException`` subclasses that are not ``Exception`` (in particular
``asyncio.CancelledError`` on client cancellation) are never mapped; they
propagate, because on cancellation no result is produced (ADR 0007).

The table is :data:`PROVIDER_ERROR_CODES` plus :func:`tool_error_from_exception`.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from gemini_search_mcp.provider import ProviderError, ProviderErrorKind

ErrorCode = Literal[
    "invalid_input",
    "url_not_allowed",
    "url_unreachable",
    "url_unsafe",
    "upstream_unavailable",
    "upstream_error",
    "internal_error",
]
"""All tool error codes of ADR 0007."""

FixedMessageCode = Literal[
    "url_not_allowed",
    "url_unreachable",
    "url_unsafe",
    "upstream_unavailable",
    "upstream_error",
    "internal_error",
]
"""Codes whose message is a constant; ``invalid_input`` is built from field and rule."""

ERROR_MESSAGES: Mapping[FixedMessageCode, str] = MappingProxyType(
    {
        "url_not_allowed": "URL is not allowed.",
        "url_unreachable": "URL could not be retrieved.",
        "url_unsafe": "URL was rejected as unsafe.",
        "upstream_unavailable": "Search backend is temporarily unavailable.",
        "upstream_error": "Search backend returned an error.",
        "internal_error": "Internal error.",
    }
)
"""Fixed client message per code, verbatim from the ADR 0007 table."""

INVALID_INPUT_MESSAGE_TEMPLATE = "Invalid input: {field} {rule}."
"""Message of ``invalid_input`` per ADR 0007: ``Invalid input: <field> <rule>.``"""

InputField = Literal["query", "max_sources", "url", "question"]
"""Input field names of the tool contracts (ADR 0003, ADR 0004).

``query`` and ``max_sources`` belong to ``search``, ``url`` and ``question``
to ``analyze_url``. Only these names may appear in an ``invalid_input``
message, so a client-supplied key or value can never be echoed.
"""

InputRule = Literal[
    "is required",
    "must be a string",
    "must not be empty",
    "must have at most 4000 characters",
    "must be an integer",
    "must be between 1 and 10",
]
"""Contract rule texts that may follow the field name in ``invalid_input``.

Each text names a rule of ADR 0003 or ADR 0004, never an input value. Example message:
``Invalid input: max_sources must be between 1 and 10.``
"""

PROVIDER_ERROR_CODES: Mapping[ProviderErrorKind, FixedMessageCode] = MappingProxyType(
    {
        "unavailable": "upstream_unavailable",
        "rejected": "upstream_error",
        "internal": "internal_error",
    }
)
"""Mapping of every ``ProviderError.kind`` (ADR 0009) to its ADR 0007 code."""


class ToolError(Exception):
    """A tool call failed with one ADR 0007 code and its fixed message.

    Attributes:
        code: the ADR 0007 error code.
        message: the client message; for every code except ``invalid_input``
            exactly ``ERROR_MESSAGES[code]``.

    ``str(exc)`` equals :attr:`message`. Instances never hold input values or
    upstream details; chain the original exception with ``from`` instead.

    Args:
        code: any code except ``invalid_input``; use
            :class:`InvalidInputError` for that one.
    """

    code: ErrorCode
    message: str

    def __init__(self, code: FixedMessageCode) -> None:
        message = ERROR_MESSAGES[code]
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message

    def to_payload(self, request_id: str) -> dict[str, dict[str, str]]:
        """Return the ADR 0007 error object for the tool result text content.

        Precondition: ``request_id`` is the UUID4 the server generated for this
        call.

        Returns:
            ``{"error": {"code": code, "message": message, "request_id":
            request_id}}`` with exactly these three keys, nothing else.
        """
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "request_id": request_id,
            }
        }


class InvalidInputError(ToolError):
    """``invalid_input``: the input violates a tool contract rule (ADR 0007).

    Attributes:
        code: always ``invalid_input``.
        field: the violated field, one of :data:`InputField`.
        rule: the violated rule, one of :data:`InputRule`.
        message: ``INVALID_INPUT_MESSAGE_TEMPLATE`` filled with field and
            rule, e.g. ``Invalid input: query must not be empty.``

    Field and rule are typed literals, so the message can never contain an
    input value, a Pydantic text or an exception text.
    """

    field: InputField
    rule: InputRule

    def __init__(self, field: InputField, rule: InputRule) -> None:
        message = INVALID_INPUT_MESSAGE_TEMPLATE.format(field=field, rule=rule)
        Exception.__init__(self, message)
        self.code = "invalid_input"
        self.message = message
        self.field = field
        self.rule = rule


def tool_error_from_exception(error: Exception) -> ToolError:
    """Map any exception raised during a tool call to a :class:`ToolError`.

    Mapping (see the module docstring):

    - a :class:`ToolError` (including :class:`InvalidInputError`) is returned
      unchanged;
    - a ``ProviderError`` becomes ``ToolError(PROVIDER_ERROR_CODES[kind])``;
      a ``kind`` missing from that table becomes ``internal_error``;
    - every other exception becomes ``ToolError("internal_error")``.

    Postcondition: the returned error's message is the fixed message of its
    code; no text of ``error`` reaches it. A newly created error has
    ``__cause__`` set to ``error`` so the server can log the details.

    Only ``Exception`` is accepted: cancellation (``asyncio.CancelledError``)
    and other ``BaseException`` subclasses must propagate and are never mapped.
    """
    if isinstance(error, ToolError):
        return error
    if isinstance(error, ProviderError):
        mapped = ToolError(PROVIDER_ERROR_CODES.get(error.kind, "internal_error"))
    else:
        mapped = ToolError("internal_error")
    mapped.__cause__ = error
    return mapped
