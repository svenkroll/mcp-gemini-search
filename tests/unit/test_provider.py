"""Acceptance tests for the provider boundary and its fake (ADR 0009, issue #2)."""

import asyncio

import pytest

from gemini_search_mcp.provider import (
    Citation,
    FakeProvider,
    ProviderError,
    Retrieval,
    SearchResult,
    UrlAnalysisResult,
    Usage,
)


def _search_result(answer: str) -> SearchResult:
    return SearchResult(
        answer=answer,
        citations=[
            Citation(
                url="https://example.com/article",
                title="Example article",
                start_index=0,
                end_index=7,
            )
        ],
        search_queries=["example query"],
        usage=Usage(input_tokens=10, output_tokens=20),
        model="gemini-3.8-flash",
    )


def _analysis_result(answer: str) -> UrlAnalysisResult:
    return UrlAnalysisResult(
        answer=answer,
        retrievals=[Retrieval(url="https://example.com/article", status="retrieved")],
        usage=Usage(input_tokens=10, output_tokens=20),
        model="gemini-3.8-flash",
    )


def test_ac6_fake_provider_returns_and_raises_preset_outcomes_in_order() -> None:
    first_search = _search_result("first")
    second_search = _search_result("second")
    first_analysis = _analysis_result("analysis")
    provider = FakeProvider(
        search_outcomes=[first_search, ProviderError("unavailable"), second_search],
        analyze_url_outcomes=[first_analysis, ProviderError("rejected")],
    )

    assert asyncio.run(provider.search("first query")) is first_search
    assert (
        asyncio.run(provider.analyze_url("https://example.com/article", "why?")) is first_analysis
    )

    with pytest.raises(ProviderError) as unavailable:
        asyncio.run(provider.search("second query"))
    assert unavailable.value.kind == "unavailable"

    with pytest.raises(ProviderError) as rejected:
        asyncio.run(provider.analyze_url("https://example.com/article", "why?"))
    assert rejected.value.kind == "rejected"

    assert asyncio.run(provider.search("third query")) is second_search


def test_ec8_fake_provider_raises_internal_when_its_script_is_exhausted() -> None:
    provider = FakeProvider(
        search_outcomes=[_search_result("only")],
        analyze_url_outcomes=[],
    )

    assert asyncio.run(provider.search("first query")) is not None

    with pytest.raises(ProviderError) as exhausted_search:
        asyncio.run(provider.search("second query"))
    assert exhausted_search.value.kind == "internal"

    with pytest.raises(ProviderError) as exhausted_analysis:
        asyncio.run(provider.analyze_url("https://example.com/article", "why?"))
    assert exhausted_analysis.value.kind == "internal"
