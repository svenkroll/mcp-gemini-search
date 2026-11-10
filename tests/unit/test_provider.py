"""Unit tests for the provider boundary from ADR 0009."""

import dataclasses
import typing

import pytest

from gemini_search_mcp.provider import (
    Citation,
    ProviderError,
    ProviderErrorKind,
    Retrieval,
    SearchProvider,
    SearchResult,
    UrlAnalysisResult,
    Usage,
)

USAGE = Usage(input_tokens=10, output_tokens=20)
CITATION = Citation(url="https://example.com/a", title="A", start_index=0, end_index=5)
SEARCH_RESULT = SearchResult(
    answer="answer",
    citations=[CITATION],
    search_queries=["query"],
    usage=USAGE,
    model="gemini-3.8-flash",
)


def test_data_objects_are_immutable() -> None:
    mutable: Citation = CITATION
    with pytest.raises(dataclasses.FrozenInstanceError):
        mutable.title = "B"  # ty: ignore[invalid-assignment]


def test_usage_allows_missing_token_figures() -> None:
    usage = Usage(input_tokens=None, output_tokens=None)
    assert usage.input_tokens is None
    assert usage.output_tokens is None


def test_data_objects_compare_by_value() -> None:
    assert dataclasses.replace(SEARCH_RESULT) == SEARCH_RESULT
    assert Retrieval(url="https://example.com", status="retrieved") == Retrieval(
        url="https://example.com", status="retrieved"
    )


@pytest.mark.parametrize("kind", ["unavailable", "rejected", "internal"])
def test_provider_error_carries_kind(kind: ProviderErrorKind) -> None:
    error = ProviderError(kind)
    assert isinstance(error, Exception)
    assert error.kind == kind
    assert kind in str(error)


def test_provider_error_keeps_message_without_secrets_in_repr() -> None:
    error = ProviderError("unavailable", "backend is temporarily unavailable")
    assert str(error) == "backend is temporarily unavailable"
    assert error.kind == "unavailable"


def test_search_provider_protocol_shape() -> None:
    hints = typing.get_type_hints(SearchProvider.search)
    assert hints == {"query": str, "return": SearchResult}
    hints = typing.get_type_hints(SearchProvider.analyze_url)
    assert hints == {"url": str, "question": str, "return": UrlAnalysisResult}
