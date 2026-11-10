"""Unit tests for the provider boundary and ``FakeProvider`` from ADR 0009.

Covers the immutable data objects and ``ProviderError`` semantics, that
``FakeProvider`` satisfies the ``SearchProvider`` protocol, returns preset
results without network access and raises preset ``ProviderError`` kinds in
order, repeating the last preset outcome (AK6).
"""

import asyncio
import dataclasses
from collections.abc import Coroutine
from typing import Any, get_args

import pytest

from gemini_search_mcp.fakes import FakeProvider
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


def _run[T](coroutine: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coroutine)


SEARCH_RESULT = SearchResult(
    answer="preset answer",
    citations=[Citation(url="https://example.test/a", title="A", start_index=0, end_index=5)],
    search_queries=["preset query"],
    usage=Usage(input_tokens=11, output_tokens=22),
    model="gemini-test",
)

URL_RESULT = UrlAnalysisResult(
    answer="preset analysis",
    retrievals=[Retrieval(url="https://example.test/a", status="retrieved")],
    usage=Usage(input_tokens=3, output_tokens=4),
    model="gemini-test",
)


# AK6: preset results are returned.


def test_fake_provider_returns_preset_search_result() -> None:
    provider = FakeProvider(search_outcomes=[SEARCH_RESULT])
    assert _run(provider.search("hello")) == SEARCH_RESULT


def test_fake_provider_returns_preset_url_analysis_result() -> None:
    provider = FakeProvider(analyze_outcomes=[URL_RESULT])
    assert _run(provider.analyze_url("https://example.test/a", "why?")) == URL_RESULT


def test_fake_provider_satisfies_search_provider_protocol() -> None:
    assert isinstance(FakeProvider(search_outcomes=[SEARCH_RESULT]), SearchProvider)


def test_fake_provider_records_requests_for_assertions() -> None:
    provider = FakeProvider(search_outcomes=[SEARCH_RESULT], analyze_outcomes=[URL_RESULT])
    _run(provider.search("first"))
    _run(provider.search("second"))
    _run(provider.analyze_url("https://example.test/b", "question"))
    assert provider.search_queries == ["first", "second"]
    assert provider.analyze_requests == [("https://example.test/b", "question")]


# AK6: preset ProviderError kinds are raised.


@pytest.mark.parametrize("kind", get_args(ProviderErrorKind))
def test_fake_provider_raises_preset_search_error_kind(kind: ProviderErrorKind) -> None:
    error = ProviderError(kind)
    provider = FakeProvider(search_outcomes=[error])
    with pytest.raises(ProviderError) as caught:
        _run(provider.search("q"))
    assert caught.value.kind == kind


@pytest.mark.parametrize("kind", get_args(ProviderErrorKind))
def test_fake_provider_raises_preset_analyze_error_kind(kind: ProviderErrorKind) -> None:
    provider = FakeProvider(analyze_outcomes=[ProviderError(kind)])
    with pytest.raises(ProviderError) as caught:
        _run(provider.analyze_url("https://example.test/a", "q"))
    assert caught.value.kind == kind


def test_fake_provider_serves_outcomes_in_order() -> None:
    provider = FakeProvider(search_outcomes=[SEARCH_RESULT, ProviderError("unavailable")])
    assert _run(provider.search("one")) == SEARCH_RESULT
    with pytest.raises(ProviderError) as caught:
        _run(provider.search("two"))
    assert caught.value.kind == "unavailable"


def test_fake_provider_repeats_last_outcome() -> None:
    provider = FakeProvider(analyze_outcomes=[URL_RESULT])
    for _ in range(3):
        assert _run(provider.analyze_url("https://example.test/a", "q")) == URL_RESULT


def test_fake_provider_set_outcomes_replaces_sequence() -> None:
    provider = FakeProvider(search_outcomes=[ProviderError("internal")])
    with pytest.raises(ProviderError):
        _run(provider.search("q"))
    provider.set_search_outcomes(SEARCH_RESULT)
    assert _run(provider.search("q")) == SEARCH_RESULT
    provider.set_analyze_outcomes(URL_RESULT)
    assert _run(provider.analyze_url("https://example.test/a", "q")) == URL_RESULT


def test_fake_provider_without_preset_outcome_fails_loudly() -> None:
    provider = FakeProvider()
    with pytest.raises(AssertionError):
        _run(provider.search("q"))
    with pytest.raises(AssertionError):
        _run(provider.analyze_url("https://example.test/a", "q"))


def test_fake_provider_rejects_mismatched_outcome_type() -> None:
    provider = FakeProvider(search_outcomes=[URL_RESULT])
    with pytest.raises(TypeError):
        _run(provider.search("q"))


def test_fake_provider_rejects_mismatched_analyze_outcome_type() -> None:
    provider = FakeProvider(analyze_outcomes=[SEARCH_RESULT])
    with pytest.raises(TypeError, match="URL analysis outcome must be"):
        _run(provider.analyze_url("https://example.test/a", "q"))


def test_fake_provider_does_not_mix_search_and_analyze_outcomes() -> None:
    provider = FakeProvider(search_outcomes=[SEARCH_RESULT], analyze_outcomes=[URL_RESULT])
    assert _run(provider.analyze_url("https://example.test/a", "q")) == URL_RESULT
    assert _run(provider.search("q")) == SEARCH_RESULT


# ProviderError carries a stable kind and a generic message.


@pytest.mark.parametrize("kind", get_args(ProviderErrorKind))
def test_provider_error_exposes_kind_and_generic_message(kind: ProviderErrorKind) -> None:
    error = ProviderError(kind)
    assert error.kind == kind
    assert kind in str(error)


def test_provider_error_keeps_explicit_message() -> None:
    error = ProviderError("rejected", "request refused")
    assert str(error) == "request refused"
    assert error.kind == "rejected"


def test_provider_error_is_an_exception() -> None:
    assert issubclass(ProviderError, Exception)


# Data objects are immutable and carry the ADR 0009 fields and defaults.


@pytest.mark.parametrize(
    ("instance", "expected"),
    [
        (SearchResult(answer="a"), {"answer": "a", "citations": [], "search_queries": []}),
        (UrlAnalysisResult(answer="a"), {"answer": "a", "retrievals": []}),
        (Usage(), {"input_tokens": None, "output_tokens": None}),
    ],
    ids=["search-result", "url-analysis-result", "usage"],
)
def test_data_objects_expose_documented_defaults(
    instance: object, expected: dict[str, object]
) -> None:
    for name, value in expected.items():
        assert getattr(instance, name) == value


@pytest.mark.parametrize(
    "instance",
    [
        SearchResult(answer="a"),
        UrlAnalysisResult(answer="a"),
        Usage(input_tokens=1, output_tokens=2),
        Citation(url="https://example.test/a", title="t", start_index=0, end_index=1),
        Retrieval(url="https://example.test/a", status="failed"),
    ],
    ids=["search-result", "url-analysis-result", "usage", "citation", "retrieval"],
)
def test_data_objects_are_frozen(instance: object) -> None:
    assert dataclasses.is_dataclass(instance)
    first_field = dataclasses.fields(instance)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, first_field, "changed")


def test_mutable_defaults_are_not_shared_between_instances() -> None:
    first = SearchResult(answer="a")
    second = SearchResult(answer="b")
    first.citations.append(
        Citation(url="https://example.test/a", title="t", start_index=0, end_index=1)
    )
    assert second.citations == []
