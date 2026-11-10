"""Unit tests for the FakeProvider from ADR 0009."""

import asyncio

import pytest

from gemini_search_mcp.fakes import FakeProvider
from gemini_search_mcp.provider import (
    ProviderError,
    ProviderErrorKind,
    Retrieval,
    SearchResult,
    UrlAnalysisResult,
    Usage,
)

USAGE = Usage(input_tokens=1, output_tokens=2)
SEARCH_RESULTS = [
    SearchResult(
        answer=f"answer-{index}", citations=[], search_queries=[], usage=USAGE, model="model"
    )
    for index in range(2)
]
URL_RESULT = UrlAnalysisResult(
    answer="url answer",
    retrievals=[Retrieval(url="https://example.com", status="retrieved")],
    usage=USAGE,
    model="model",
)


def test_search_returns_preset_results_in_order() -> None:
    provider = FakeProvider(search=SEARCH_RESULTS)
    assert asyncio.run(provider.search("first")) is SEARCH_RESULTS[0]
    assert asyncio.run(provider.search("second")) is SEARCH_RESULTS[1]
    assert asyncio.run(provider.search("third")) is SEARCH_RESULTS[-1]
    assert provider.calls["search"] == [("first",), ("second",), ("third",)]


def test_analyze_url_returns_preset_result() -> None:
    provider = FakeProvider(analyze_url=[URL_RESULT])
    result = asyncio.run(provider.analyze_url("https://example.com", "why?"))
    assert result is URL_RESULT
    assert provider.calls["analyze_url"] == [("https://example.com", "why?")]


@pytest.mark.parametrize("kind", ["unavailable", "rejected", "internal"])
def test_search_raises_preset_error_kind(kind: ProviderErrorKind) -> None:
    provider = FakeProvider(search=[SEARCH_RESULTS[0], kind])
    assert asyncio.run(provider.search("ok")) is SEARCH_RESULTS[0]
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.search("fails"))
    assert excinfo.value.kind == kind


def test_analyze_url_raises_preset_error_instance() -> None:
    error = ProviderError("rejected", "unsafe url")
    provider = FakeProvider(analyze_url=[error])
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.analyze_url("https://example.com", "why?"))
    assert excinfo.value is error


def test_error_preset_repeats_after_exhaustion() -> None:
    provider = FakeProvider(search=["unavailable"])
    for _ in range(3):
        with pytest.raises(ProviderError):
            asyncio.run(provider.search("query"))
    assert len(provider.calls["search"]) == 3


def test_missing_preset_for_called_operation_is_rejected() -> None:
    provider = FakeProvider(analyze_url=[URL_RESULT])
    with pytest.raises(TypeError, match="search"):
        asyncio.run(provider.search("query"))


# --- Additional coverage: both preset results and all error kinds per operation ---

URL_RESULTS = [
    UrlAnalysisResult(answer=f"url answer {index}", retrievals=[], usage=USAGE, model="model")
    for index in range(2)
]


def test_analyze_url_returns_preset_results_in_order() -> None:
    provider = FakeProvider(analyze_url=URL_RESULTS)
    assert asyncio.run(provider.analyze_url("https://a.example", "one")) is URL_RESULTS[0]
    assert asyncio.run(provider.analyze_url("https://b.example", "two")) is URL_RESULTS[1]
    assert asyncio.run(provider.analyze_url("https://c.example", "three")) is URL_RESULTS[-1]
    assert provider.calls["analyze_url"] == [
        ("https://a.example", "one"),
        ("https://b.example", "two"),
        ("https://c.example", "three"),
    ]


@pytest.mark.parametrize("kind", ["unavailable", "rejected", "internal"])
def test_analyze_url_raises_preset_error_kind(kind: ProviderErrorKind) -> None:
    provider = FakeProvider(analyze_url=[URL_RESULT, kind])
    assert asyncio.run(provider.analyze_url("https://example.com", "why?")) is URL_RESULT
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.analyze_url("https://example.com", "again"))
    assert excinfo.value.kind == kind


def test_search_raises_preset_error_instance_passed_in() -> None:
    error = ProviderError("internal", "boom")
    provider = FakeProvider(search=[error])
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.search("query"))
    assert excinfo.value is error
    assert excinfo.value.kind == "internal"


def test_search_and_analyze_url_presets_are_independent() -> None:
    provider = FakeProvider(search=["unavailable"], analyze_url=[URL_RESULT])
    with pytest.raises(ProviderError):
        asyncio.run(provider.search("query"))
    assert asyncio.run(provider.analyze_url("https://example.com", "why?")) is URL_RESULT
    assert provider.calls["search"] == [("query",)]
    assert provider.calls["analyze_url"] == [("https://example.com", "why?")]


def test_missing_preset_for_analyze_url_is_rejected() -> None:
    provider = FakeProvider(search=SEARCH_RESULTS)
    with pytest.raises(TypeError, match="analyze_url"):
        asyncio.run(provider.analyze_url("https://example.com", "why?"))


def test_default_fake_provider_has_no_presets() -> None:
    provider = FakeProvider()
    with pytest.raises(TypeError):
        asyncio.run(provider.search("query"))
    with pytest.raises(TypeError):
        asyncio.run(provider.analyze_url("https://example.com", "why?"))
