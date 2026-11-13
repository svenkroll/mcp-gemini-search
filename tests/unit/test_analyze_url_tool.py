"""Acceptance tests for the ``analyze_url`` tool logic (ADR 0004, ADR 0007, issue #7).

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order of
the issue. Everything runs against a scripted provider; no network access and
no Gemini key. Fixtures contain only hand-written URLs.

Issue edge cases:

- EC1: whitespace-only ``question``
- EC2: ``url`` that is a string but not a URL
- EC3: ``url`` missing or not a string
- EC4: reported URL differs only by normalization
- EC5: success for the requested URL and ``unsafe`` for another URL
- EC6: answer says the content does not answer the question
"""

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from gemini_search_mcp.provider import (
    FakeProvider,
    ProviderError,
    Retrieval,
    UrlAnalysisResult,
    Usage,
)
from gemini_search_mcp.tools.analyze_url import (
    ANALYZE_URL_OUTPUT_SCHEMA,
    AnalyzeUrlInput,
    AnalyzeUrlOutput,
    AnalyzeUrlToolResult,
    run_analyze_url,
)
from gemini_search_mcp.tools.errors import InvalidInputError, ToolError

URL = "https://example.com/page"
QUESTION = "What is the price?"
LEAKY_ANSWER = "GEMINI-ANSWER-TEXT-MUST-NOT-LEAK"


class _RecordingProvider(FakeProvider):
    """Scripted provider that also records the arguments it received."""

    def __init__(self, outcomes: Sequence[UrlAnalysisResult | ProviderError]) -> None:
        super().__init__(analyze_url_outcomes=outcomes)
        self.calls: list[tuple[str, str]] = []

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult:
        self.calls.append((url, question))
        return await super().analyze_url(url, question)


def _result(
    retrievals: Sequence[Retrieval] = (Retrieval(url=URL, status="retrieved"),),
    answer: str = "the answer",
    usage: Usage | None = None,
    model: str = "test-model",
) -> UrlAnalysisResult:
    return UrlAnalysisResult(
        answer=answer,
        retrievals=list(retrievals),
        usage=usage or Usage(input_tokens=11, output_tokens=22),
        model=model,
    )


def _run(
    outcome: UrlAnalysisResult | ProviderError,
    *,
    url: str = URL,
    question: str = QUESTION,
) -> tuple[AnalyzeUrlToolResult, _RecordingProvider]:
    provider = _RecordingProvider([outcome])
    result = asyncio.run(
        run_analyze_url(AnalyzeUrlInput(url=url, question=question), provider=provider)
    )
    return result, provider


def _run_error(outcome: UrlAnalysisResult | ProviderError, *, url: str = URL) -> ToolError:
    provider = _RecordingProvider([outcome])
    with pytest.raises(ToolError) as excinfo:
        asyncio.run(run_analyze_url(AnalyzeUrlInput(url=url, question=QUESTION), provider=provider))
    return excinfo.value


def _rejected_input(arguments: dict[str, Any]) -> tuple[ToolError, _RecordingProvider]:
    """Run the full path from raw arguments; the provider must stay untouched."""
    provider = _RecordingProvider([_result()])

    async def go() -> None:
        tool_input = AnalyzeUrlInput.from_arguments(arguments)
        await run_analyze_url(tool_input, provider=provider)

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(go())
    return excinfo.value, provider


# --- AC1: successful retrieval ---------------------------------------------------


def test_ac1_successful_retrieval_returns_answer_url_and_status() -> None:
    result, _ = _run(_result(answer="It costs 5 euros."))

    assert result.output.answer == "It costs 5 euros."
    assert result.output.url == URL
    assert result.output.retrieval_status == "retrieved"


def test_ac1_structured_content_has_exactly_the_adr_keys() -> None:
    result, _ = _run(_result(answer="It costs 5 euros."))

    assert result.output.to_structured_content() == {
        "answer": "It costs 5 euros.",
        "url": URL,
        "retrieval_status": "retrieved",
    }
    assert set(ANALYZE_URL_OUTPUT_SCHEMA["properties"]) == {"answer", "url", "retrieval_status"}


def test_ac1_provider_receives_normalized_url_and_trimmed_question() -> None:
    _, provider = _run(
        _result(retrievals=[Retrieval(url="https://example.com/", status="retrieved")]),
        url="HTTPS://Example.COM",
        question="  \t What is it? \n ",
    )

    assert provider.calls == [("https://example.com/", "What is it?")]


def test_ac1_usage_and_model_are_passed_on() -> None:
    result, _ = _run(_result(usage=Usage(input_tokens=3, output_tokens=4), model="m-1"))

    assert result.usage == Usage(input_tokens=3, output_tokens=4)
    assert result.model == "m-1"


def test_ac1_from_arguments_builds_normalized_trimmed_input() -> None:
    tool_input = AnalyzeUrlInput.from_arguments({"url": "HTTPS://Example.COM", "question": " q "})

    assert tool_input == AnalyzeUrlInput(url="https://example.com/", question="q")
    assert tool_input.url == "https://example.com/"
    assert tool_input.question == "q"


def test_ac1_output_model_serializes_to_the_three_fields() -> None:
    output = AnalyzeUrlOutput(answer="a", url=URL)

    assert output.to_structured_content() == {
        "answer": "a",
        "url": URL,
        "retrieval_status": "retrieved",
    }


# --- AC2: question rules ---------------------------------------------------------


@pytest.mark.parametrize("question", ["", " ", "   \t\n\r  "])
def test_ac2_empty_question_after_trimming_is_invalid_input(question: str) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        AnalyzeUrlInput(url=URL, question=question)

    assert excinfo.value.code == "invalid_input"
    assert excinfo.value.field == "question"
    assert excinfo.value.message == "Invalid input: question must not be empty."


def test_ac2_question_with_4001_characters_is_invalid_input() -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        AnalyzeUrlInput(url=URL, question="a" * 4001)

    assert excinfo.value.code == "invalid_input"
    assert excinfo.value.field == "question"
    assert excinfo.value.message == "Invalid input: question must have at most 4000 characters."


def test_ac2_question_with_4000_characters_is_accepted() -> None:
    assert AnalyzeUrlInput(url=URL, question="\U0001f600" * 4000).question == "\U0001f600" * 4000


def test_ac2_length_limit_applies_after_trimming() -> None:
    assert AnalyzeUrlInput(url=URL, question="  " + "a" * 4000 + " \n").question == "a" * 4000
    with pytest.raises(InvalidInputError):
        AnalyzeUrlInput(url=URL, question="  " + "a" * 4001 + "  ")


def test_ac2_invalid_question_does_not_reach_the_provider() -> None:
    error, provider = _rejected_input({"url": URL, "question": "a" * 4001})

    assert error.code == "invalid_input"
    assert provider.calls == []


# --- AC3: URL input check --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.1/",
        "https://192.168.1.1/page",
        "http://[::1]/",
        "https://example.com:8080/",
        "https://user:pass@example.com/",
        "http://localhost/",
        "http://LOCALHOST/admin",
    ],
)
def test_ac3_disallowed_url_is_url_not_allowed_without_provider_call(url: str) -> None:
    error, provider = _rejected_input({"url": url, "question": QUESTION})

    assert error.code == "url_not_allowed"
    assert error.message == "URL is not allowed."
    assert provider.calls == []


def test_ac3_constructor_raises_url_not_allowed() -> None:
    with pytest.raises(ToolError) as excinfo:
        AnalyzeUrlInput(url="http://10.0.0.1/", question=QUESTION)

    assert excinfo.value.code == "url_not_allowed"


# --- AC4: retrieval status mapping -----------------------------------------------


def test_ac4_unsafe_status_is_url_unsafe() -> None:
    error = _run_error(_result(retrievals=[Retrieval(url=URL, status="unsafe")]))

    assert error.code == "url_unsafe"
    assert error.message == "URL was rejected as unsafe."


def test_ac4_failed_status_is_url_unreachable() -> None:
    error = _run_error(_result(retrievals=[Retrieval(url=URL, status="failed")]))

    assert error.code == "url_unreachable"
    assert error.message == "URL could not be retrieved."


def test_ac4_unknown_status_is_url_unreachable() -> None:
    unknown: Any = "some_future_status"
    error = _run_error(_result(retrievals=[Retrieval(url=URL, status=unknown)]))

    assert error.code == "url_unreachable"


def test_ac4_missing_result_for_the_url_is_url_unreachable() -> None:
    error = _run_error(_result(retrievals=[]))

    assert error.code == "url_unreachable"


def test_ac4_only_retrieval_for_another_url_is_url_unreachable() -> None:
    other = Retrieval(url="https://other.example/", status="retrieved")

    assert _run_error(_result(retrievals=[other])).code == "url_unreachable"


# --- AC5: no provider answer text in errors --------------------------------------


@pytest.mark.parametrize(
    ("retrievals", "code"),
    [
        ([Retrieval(url=URL, status="unsafe")], "url_unsafe"),
        ([Retrieval(url=URL, status="failed")], "url_unreachable"),
        ([], "url_unreachable"),
    ],
)
def test_ac5_error_result_contains_no_answer_text(retrievals: list[Retrieval], code: str) -> None:
    error = _run_error(_result(retrievals=retrievals, answer=LEAKY_ANSWER))

    assert error.code == code
    assert LEAKY_ANSWER not in error.message
    assert LEAKY_ANSWER not in str(error)
    assert LEAKY_ANSWER not in str(error.to_payload("req-1"))


@pytest.mark.parametrize("kind", ["unavailable", "rejected", "internal"])
def test_ac5_provider_error_text_does_not_reach_the_result(kind: Any) -> None:
    error = _run_error(ProviderError(kind, LEAKY_ANSWER))

    assert LEAKY_ANSWER not in error.message
    assert LEAKY_ANSWER not in str(error.to_payload("req-1"))


# --- AC6: provider error kinds ---------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("unavailable", "upstream_unavailable"),
        ("rejected", "upstream_error"),
        ("internal", "internal_error"),
    ],
)
def test_ac6_provider_error_kind_maps_to_code(kind: Any, code: str) -> None:
    error = _run_error(ProviderError(kind, "detail"))

    assert error.code == code


def test_ac6_unknown_provider_error_kind_is_internal_error() -> None:
    kind: Any = "something_new"

    assert _run_error(ProviderError(kind, "detail")).code == "internal_error"


# --- EC1 to EC3: input edge cases ------------------------------------------------


def test_ec1_whitespace_only_question_is_invalid_input_without_provider_call() -> None:
    error, provider = _rejected_input({"url": URL, "question": " \t\n "})

    assert isinstance(error, InvalidInputError)
    assert error.code == "invalid_input"
    assert error.field == "question"
    assert provider.calls == []


def test_ec2_string_that_is_not_a_url_is_url_not_allowed_without_provider_call() -> None:
    error, provider = _rejected_input({"url": "not a url", "question": QUESTION})

    assert error.code == "url_not_allowed"
    assert provider.calls == []


def test_ec3_missing_url_is_invalid_input_for_url() -> None:
    error, provider = _rejected_input({"question": QUESTION})

    assert isinstance(error, InvalidInputError)
    assert error.field == "url"
    assert error.message == "Invalid input: url is required."
    assert provider.calls == []


@pytest.mark.parametrize("url", [None, 123, ["https://example.com/"], True, b"https://a.example"])
def test_ec3_non_string_url_is_invalid_input_for_url(url: Any) -> None:
    error, provider = _rejected_input({"url": url, "question": QUESTION})

    assert isinstance(error, InvalidInputError)
    assert error.field == "url"
    assert error.message == "Invalid input: url must be a string."
    assert provider.calls == []


# --- EC4 to EC6: retrieval edge cases --------------------------------------------


@pytest.mark.parametrize(
    ("requested", "reported"),
    [
        ("https://example.com/", "HTTPS://EXAMPLE.COM/"),
        ("https://example.com/", "https://example.com"),
        ("https://example.com/a", "https://Example.com/a"),
        ("https://example.com/", "https://example.com:443/"),
    ],
)
def test_ec4_reported_url_differing_only_by_normalization_counts_as_requested(
    requested: str, reported: str
) -> None:
    result, _ = _run(
        _result(retrievals=[Retrieval(url=reported, status="retrieved")]), url=requested
    )

    assert result.output.url == requested
    assert result.output.retrieval_status == "retrieved"


def test_ec4_unsafe_reported_with_differing_normalization_is_url_unsafe() -> None:
    error = _run_error(
        _result(retrievals=[Retrieval(url="HTTPS://Example.COM", status="unsafe")]),
        url="https://example.com/",
    )

    assert error.code == "url_unsafe"


def test_ec5_unsafe_for_another_url_does_not_affect_success() -> None:
    result, _ = _run(
        _result(
            retrievals=[
                Retrieval(url="https://other.example/", status="unsafe"),
                Retrieval(url=URL, status="retrieved"),
            ],
            answer="fine",
        )
    )

    assert result.output.answer == "fine"
    assert result.output.url == URL
    assert result.output.retrieval_status == "retrieved"


def test_ec5_unsafe_for_another_url_listed_after_success_is_still_success() -> None:
    result, _ = _run(
        _result(
            retrievals=[
                Retrieval(url=URL, status="retrieved"),
                Retrieval(url="https://other.example/", status="unsafe"),
            ]
        )
    )

    assert result.output.retrieval_status == "retrieved"


def test_ec6_answer_saying_content_does_not_answer_is_success_and_unchanged() -> None:
    answer = "  The page does not contain this information.\n\nSorry.  "
    result, _ = _run(_result(answer=answer))

    assert result.output.answer == answer
    assert result.output.retrieval_status == "retrieved"
