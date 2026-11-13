"""Acceptance tests for the asynchronous Gemini adapter (issue #4).

The tests exercise the adapter only through the public ``search`` and
``analyze_url`` methods. The Gemini SDK is present, but no network connection is
opened: a fake ``InteractionsClient`` returns hand-written fixtures from
``tests/fixtures/gemini/``, and fake ``sleep``/clock boundaries replace all real
waiting. Fixtures contain no real responses, API keys or user data.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import pytest
from google.genai import interactions
from google.genai._interactions_continuation import ContinuationTimeoutError
from google.genai.errors import (
    APIError,
    ClientError,
    ContinuationInterruptedError,
    ServerError,
)

from gemini_search_mcp.config import Settings
from gemini_search_mcp.gemini_client import URL_CONTEXT_INSTRUCTION, GeminiProvider
from gemini_search_mcp.provider import ProviderError, Usage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gemini"


def _load_fixture(name: str) -> interactions.Interaction:
    """Load one hand-written interaction fixture and validate it with the SDK."""
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return interactions.Interaction.model_validate(payload)


def _settings(**overrides: Any) -> Settings:
    """Build valid settings for the adapter with test-safe defaults."""
    values: dict[str, Any] = {
        "gemini_api_key": "test-api-key-not-real",
        "gemini_model": "gemini-3.8-flash",
        "gemini_timeout_seconds": 60,
        "gemini_max_concurrency": 4,
        "gemini_max_retries": 2,
    }
    values.update(overrides)
    return Settings(**values)


class _Headers:
    """Case-insensitive header view of a hand-written HTTP response."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = {key.lower(): value for key, value in values.items()}

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._values.get(key.lower(), default)

    def __getitem__(self, key: str) -> str:
        return self._values[key.lower()]

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._values


class _Response:
    """Minimal HTTP response carrying only the headers the adapter may read."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = _Headers(headers or {})


def _api_error(status: int, headers: dict[str, str] | None = None) -> APIError:
    """Build a realistic SDK error for one HTTP status and optional headers."""
    body = {
        "error": {
            "code": status,
            "status": "ERROR",
            "message": "hand-written fixture error",
        }
    }
    response = _Response(headers)
    if 400 <= status < 500:
        return ClientError(status, body, response)
    if 500 <= status < 600:
        return ServerError(status, body, response)
    return APIError(status, body, response)


class _Sleeper:
    """Record requested sleeps instead of waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class _FakeInteractions:
    """Scripted ``InteractionsClient`` double that records every call."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.started = 0
        self.active = 0
        self.max_active = 0
        self.gate: asyncio.Event | None = None

    async def create(
        self,
        *,
        model: str,
        input: str,
        tools: list[dict[str, Any]],
        system_instruction: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        self.calls.append(
            {
                "model": model,
                "input": input,
                "tools": tools,
                "system_instruction": system_instruction,
                "timeout": timeout,
            }
        )
        self.started += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.gate is not None:
                await self.gate.wait()
            outcome = self._outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        finally:
            self.active -= 1


def _provider(
    outcomes: list[Any],
    *,
    sleeper: _Sleeper | None = None,
    **settings_overrides: Any,
) -> tuple[GeminiProvider, _FakeInteractions]:
    """Build the adapter with a fake client and a recording sleeper."""
    fake = _FakeInteractions(outcomes)
    provider = GeminiProvider(
        _settings(**settings_overrides),
        fake,
        sleep=sleeper or _Sleeper(),
    )
    return provider, fake


def test_ac1_search_maps_answer_citations_and_search_queries() -> None:
    """AC1: several citations and search queries are fully mapped."""
    response = _load_fixture("search_full.json")
    provider, fake = _provider([response])

    result = asyncio.run(provider.search("distinctive query"))

    assert result.answer == "First part with a citation. Second part with another citation."
    assert [
        (citation.url, citation.title, citation.start_index, citation.end_index)
        for citation in result.citations
    ] == [
        ("https://example.com/one", "One", 0, 10),
        ("https://example.com/two", "Two", 0, 10),
    ]
    assert result.search_queries == ["first query", "second query", "third query"]
    assert result.usage == Usage(input_tokens=11, output_tokens=22)
    assert result.model == "gemini-3.8-flash"
    assert fake.calls[0]["model"] == "gemini-3.8-flash"
    assert fake.calls[0]["input"] == "distinctive query"
    assert {"type": "google_search"} in fake.calls[0]["tools"]


def test_ec1_search_without_grounding_metadata_keeps_answer_and_empty_lists() -> None:
    """EC1: no grounding metadata keeps the answer, citations and queries empty."""
    response = _load_fixture("search_no_grounding.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.search("query"))

    assert result.answer == "Only an answer."
    assert result.citations == []
    assert result.search_queries == []


def test_ac2_citation_indices_are_utf8_byte_offsets() -> None:
    """AC2: non-ASCII text proves the documented UTF-8 byte index unit."""
    response = _load_fixture("search_non_ascii.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.search("query"))

    citation = result.citations[0]
    encoded = result.answer.encode("utf-8")
    assert encoded[citation.start_index : citation.end_index].decode("utf-8") == "🌍"


def test_ec3_umlauts_and_emoji_before_a_citation_keep_byte_indices() -> None:
    """EC3: umlauts and an emoji before the cited text do not shift indices."""
    response = _load_fixture("search_non_ascii.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.search("query"))

    citation = result.citations[1]
    encoded = result.answer.encode("utf-8")
    assert encoded[citation.start_index : citation.end_index].decode("utf-8") == "Köln"


def test_ec2_citation_without_title_maps_to_empty_string() -> None:
    """EC2: a citation without a title gets an empty title."""
    response = _load_fixture("search_citation_without_title.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.search("query"))

    assert result.citations[0].title == ""


def test_ac3_url_context_statuses_map_to_retrieval_statuses() -> None:
    """AC3: success, unsafe, error and unknown statuses are mapped."""
    response = _load_fixture("url_context_statuses.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.analyze_url("https://example.com/success", "What?"))

    assert [(retrieval.url, retrieval.status) for retrieval in result.retrievals] == [
        ("https://example.com/success", "retrieved"),
        ("https://example.com/unsafe", "unsafe"),
        ("https://example.com/error", "failed"),
        ("https://example.com/unknown", "failed"),
    ]


def test_ec7_url_context_maps_further_urls_besides_the_requested_one() -> None:
    """EC7: every reported URL becomes a retrieval, not only the requested one."""
    response = _load_fixture("url_context_multiple_urls.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.analyze_url("https://example.com/requested", "What?"))

    assert [(retrieval.url, retrieval.status) for retrieval in result.retrievals] == [
        ("https://example.com/requested", "retrieved"),
        ("https://example.com/other", "failed"),
    ]


def test_ac4_429_and_503_are_retried_with_retry_after_and_400_is_not() -> None:
    """AC4: retryable statuses respect Retry-After, 400 is rejected at once."""
    response = _load_fixture("search_no_grounding.json")

    sleeper = _Sleeper()
    provider, fake = _provider(
        [_api_error(429, {"Retry-After": "2"}), response],
        sleeper=sleeper,
    )
    assert asyncio.run(provider.search("query")).answer == "Only an answer."
    assert len(fake.calls) == 2
    assert sleeper.delays == [pytest.approx(2.0)]

    sleeper = _Sleeper()
    provider, fake = _provider(
        [_api_error(503, {"Retry-After": "1.5"}), response],
        sleeper=sleeper,
    )
    assert asyncio.run(provider.search("query")).answer == "Only an answer."
    assert len(fake.calls) == 2
    assert sleeper.delays == [pytest.approx(1.5)]

    sleeper = _Sleeper()
    provider, fake = _provider([_api_error(400)], sleeper=sleeper)
    with pytest.raises(ProviderError) as rejected:
        asyncio.run(provider.search("query"))
    assert rejected.value.kind == "rejected"
    assert len(fake.calls) == 1
    assert sleeper.delays == []

    sleeper = _Sleeper()
    provider, fake = _provider(
        [_api_error(429), _api_error(429), _api_error(429), response],
        sleeper=sleeper,
    )
    with pytest.raises(ProviderError) as exhausted:
        asyncio.run(provider.search("query"))
    assert exhausted.value.kind == "unavailable"
    assert len(fake.calls) == 3
    assert len(sleeper.delays) == 2


def test_ac5_timeout_and_exhausted_retries_raise_unavailable() -> None:
    """AC5: a timeout and exhausted retries both map to unavailable."""
    provider, fake = _provider([TimeoutError("transport timeout")])
    with pytest.raises(ProviderError) as timed_out:
        asyncio.run(provider.search("query"))
    assert timed_out.value.kind == "unavailable"
    assert len(fake.calls) == 1

    sleeper = _Sleeper()
    provider, fake = _provider(
        [_api_error(503), _api_error(503), _api_error(503)],
        sleeper=sleeper,
    )
    with pytest.raises(ProviderError) as exhausted:
        asyncio.run(provider.search("query"))
    assert exhausted.value.kind == "unavailable"
    assert len(fake.calls) == 3


def test_f1_continuation_interrupted_by_timeout_maps_to_unavailable() -> None:
    """F1: the SDK's continuation wrapper around a timeout maps to unavailable.

    The SDK reports a per-call timeout after progress as
    ``ContinuationInterruptedError`` with a ``TimeoutError`` subclass as its
    ``__cause__`` (see ``google.genai._gaos.google_genai`` in the pinned SDK).
    The adapter must treat that timeout like a plain ``TimeoutError`` and raise
    ``ProviderError("unavailable")`` instead of falling through to "internal".
    """
    interrupted = ContinuationInterruptedError(
        "Automatic continuation was interrupted after 1 completed hop(s)."
    )
    interrupted.__cause__ = ContinuationTimeoutError(
        "interactions.create() timed out before automatic continuation finished"
    )
    provider, fake = _provider([interrupted])

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.search("query"))

    assert error.value.kind == "unavailable"
    assert len(fake.calls) == 1


def test_ac6_more_calls_than_max_concurrency_wait() -> None:
    """AC6: calls above GEMINI_MAX_CONCURRENCY wait for a free permit."""

    async def scenario() -> None:
        response = _load_fixture("search_no_grounding.json")
        fake = _FakeInteractions([response, response, response])
        fake.gate = asyncio.Event()
        provider = GeminiProvider(
            _settings(gemini_max_concurrency=2),
            fake,
            sleep=_Sleeper(),
        )
        tasks = [asyncio.create_task(provider.search(f"query {index}")) for index in range(3)]
        try:
            for _ in range(100):
                if fake.started >= 2:
                    break
                await asyncio.sleep(0)
            assert fake.started == 2
            assert fake.max_active == 2
            fake.gate.set()
            results = await asyncio.gather(*tasks)
        finally:
            fake.gate.set()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        assert len(results) == 3
        assert fake.max_active == 2

    asyncio.run(scenario())


def test_ac7_cancellation_is_propagated_without_a_retry() -> None:
    """AC7: caller cancellation ends the call without a retry."""
    sleeper = _Sleeper()
    provider, fake = _provider([asyncio.CancelledError()], sleeper=sleeper)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.search("query"))

    assert len(fake.calls) == 1
    assert sleeper.delays == []


def test_ac8_missing_usage_metadata_yields_none_tokens() -> None:
    """AC8: without usage metadata both token values are None."""
    response = _load_fixture("search_no_grounding.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.search("query"))

    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None


def test_ec8_usage_with_input_tokens_only_keeps_output_none() -> None:
    """EC8: usage metadata with input tokens only sets output_tokens to None."""
    response = _load_fixture("usage_input_only.json")
    provider, _ = _provider([response])

    result = asyncio.run(provider.search("query"))

    assert result.usage.input_tokens == 7
    assert result.usage.output_tokens is None


def test_ac9_logs_contain_neither_key_nor_query(caplog: pytest.LogCaptureFixture) -> None:
    """AC9: captured logs contain neither the API key, query, URL nor question."""
    key = "sk-hand-written-secret-key-123"
    query = "private-query-987"
    url = "https://example.com/private-page-987"
    question = "private-question-987"
    sleeper = _Sleeper()
    provider, _ = _provider(
        [
            _api_error(429),
            _load_fixture("search_no_grounding.json"),
            _load_fixture("url_context_statuses.json"),
        ],
        sleeper=sleeper,
        gemini_api_key=key,
    )

    with caplog.at_level(logging.DEBUG):
        asyncio.run(provider.search(query))
        asyncio.run(provider.analyze_url(url, question))

    for secret in (key, query, url, question):
        assert secret not in caplog.text


def test_ac10_every_analyze_url_call_carries_the_injection_instruction() -> None:
    """AC10: every analyze_url call, including a retry, sends the instruction."""
    response = _load_fixture("url_context_statuses.json")
    sleeper = _Sleeper()
    provider, fake = _provider([_api_error(429), response, response], sleeper=sleeper)

    asyncio.run(provider.analyze_url("https://example.com/page", "What does it say?"))
    asyncio.run(provider.analyze_url("https://example.com/page", "What does it say?"))

    assert len(fake.calls) == 3
    for call in fake.calls:
        assert URL_CONTEXT_INSTRUCTION in (call["system_instruction"] or "")
        assert {"type": "url_context"} in call["tools"]
        assert "https://example.com/page" in call["input"]
        assert "What does it say?" in call["input"]


def test_ec4_zero_retries_makes_exactly_one_attempt() -> None:
    """EC4: GEMINI_MAX_RETRIES=0 attempts once and raises unavailable on 429."""
    sleeper = _Sleeper()
    provider, fake = _provider(
        [_api_error(429)],
        sleeper=sleeper,
        gemini_max_retries=0,
    )

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.search("query"))

    assert error.value.kind == "unavailable"
    assert len(fake.calls) == 1
    assert sleeper.delays == []


def test_ec5_retry_after_beyond_the_budget_stops_without_waiting() -> None:
    """EC5: a Retry-After longer than the budget stops the call immediately."""
    sleeper = _Sleeper()
    provider, fake = _provider(
        [_api_error(429, {"Retry-After": "3600"})],
        sleeper=sleeper,
        gemini_timeout_seconds=5,
    )

    with pytest.raises(ProviderError) as error:
        asyncio.run(provider.search("query"))

    assert error.value.kind == "unavailable"
    assert len(fake.calls) == 1
    assert sleeper.delays == []


def test_ec6_missing_or_unparseable_retry_after_uses_backoff_with_jitter() -> None:
    """EC6: without a usable Retry-After the exponential backoff with jitter runs."""
    response = _load_fixture("search_no_grounding.json")

    for headers in (None, {"Retry-After": "not-a-number"}):
        sleeper = _Sleeper()
        provider, fake = _provider([_api_error(429, headers), response], sleeper=sleeper)

        result = asyncio.run(provider.search("query"))

        assert result.answer == "Only an answer."
        assert len(fake.calls) == 2
        assert len(sleeper.delays) == 1
        assert 1.0 <= sleeper.delays[0] < 2.0


def test_default_client_stays_open_after_construction() -> None:
    """The lazily built SDK client must not be closed by garbage collection."""

    async def scenario() -> bool:
        provider = GeminiProvider(_settings())
        interactions_client: Any = provider._default_interactions()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return interactions_client.sdk_configuration.async_client.is_closed

    assert asyncio.run(scenario()) is False
