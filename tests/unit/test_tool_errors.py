"""Tests for the shared tool error type (ADR 0007, issue #6).

Every error code of ADR 0007 gets a test for its fixed message; the mapping
from provider failures and unexpected exceptions to codes is checked through
``tool_error_from_exception``. The mapping inside ``run_search`` is covered in
``test_search_tool.py``.
"""

from typing import Any

import pytest

from gemini_search_mcp.provider import ProviderError
from gemini_search_mcp.tools.errors import (
    InvalidInputError,
    ToolError,
    tool_error_from_exception,
)

LEAKY_DETAIL = "api-key-AIza-SECRET at https://internal.example/stack"

FIXED_MESSAGES = [
    pytest.param("url_not_allowed", "URL is not allowed.", id="url_not_allowed"),
    pytest.param("url_unreachable", "URL could not be retrieved.", id="url_unreachable"),
    pytest.param("url_unsafe", "URL was rejected as unsafe.", id="url_unsafe"),
    pytest.param(
        "upstream_unavailable",
        "Search backend is temporarily unavailable.",
        id="upstream_unavailable",
    ),
    pytest.param("upstream_error", "Search backend returned an error.", id="upstream_error"),
    pytest.param("internal_error", "Internal error.", id="internal_error"),
]


@pytest.mark.parametrize(("code", "message"), FIXED_MESSAGES)
def test_tool_error_carries_code_and_fixed_message(code: Any, message: str) -> None:
    error = ToolError(code)

    assert error.code == code
    assert error.message == message
    assert str(error) == message


@pytest.mark.parametrize(("code", "message"), FIXED_MESSAGES)
def test_tool_error_payload_has_exactly_the_adr0007_shape(code: Any, message: str) -> None:
    payload = ToolError(code).to_payload("3f2b8c1e-0000-4000-8000-000000000000")

    assert payload == {
        "error": {
            "code": code,
            "message": message,
            "request_id": "3f2b8c1e-0000-4000-8000-000000000000",
        }
    }


def test_invalid_input_error_message_names_field_and_rule() -> None:
    error = InvalidInputError("max_sources", "must be between 1 and 10")

    assert isinstance(error, ToolError)
    assert error.code == "invalid_input"
    assert error.field == "max_sources"
    assert error.rule == "must be between 1 and 10"
    assert error.message == "Invalid input: max_sources must be between 1 and 10."
    assert str(error) == "Invalid input: max_sources must be between 1 and 10."


def test_invalid_input_error_payload_has_exactly_the_adr0007_shape() -> None:
    payload = InvalidInputError("query", "must not be empty").to_payload("req-1")

    assert payload == {
        "error": {
            "code": "invalid_input",
            "message": "Invalid input: query must not be empty.",
            "request_id": "req-1",
        }
    }


@pytest.mark.parametrize(
    ("kind", "code", "message"),
    [
        pytest.param(
            "unavailable",
            "upstream_unavailable",
            "Search backend is temporarily unavailable.",
            id="unavailable",
        ),
        pytest.param(
            "rejected", "upstream_error", "Search backend returned an error.", id="rejected"
        ),
        pytest.param("internal", "internal_error", "Internal error.", id="internal"),
    ],
)
def test_ac7_provider_error_kind_maps_to_code_without_details(
    kind: Any, code: str, message: str
) -> None:
    original = ProviderError(kind, LEAKY_DETAIL)

    mapped = tool_error_from_exception(original)

    assert mapped.code == code
    assert mapped.message == message
    assert LEAKY_DETAIL not in str(mapped)
    assert LEAKY_DETAIL not in str(mapped.to_payload("req-1"))
    assert mapped.__cause__ is original


@pytest.mark.parametrize(
    "original",
    [
        pytest.param(RuntimeError(LEAKY_DETAIL), id="runtime_error"),
        pytest.param(KeyError(LEAKY_DETAIL), id="key_error"),
        pytest.param(ValueError(LEAKY_DETAIL), id="value_error"),
    ],
)
def test_ac7_unexpected_exception_maps_to_internal_error_without_details(
    original: Exception,
) -> None:
    mapped = tool_error_from_exception(original)

    assert mapped.code == "internal_error"
    assert mapped.message == "Internal error."
    assert "SECRET" not in str(mapped)
    assert "SECRET" not in str(mapped.to_payload("req-1"))
    assert mapped.__cause__ is original


def test_tool_error_is_returned_unchanged() -> None:
    original = InvalidInputError("query", "must not be empty")

    assert tool_error_from_exception(original) is original
