"""Acceptance tests for the ``search`` tool logic (ADR 0003, ADR 0007, issue #6).

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order of
the issue. Everything runs against fakes at the system boundaries: a scripted
provider and a scripted redirect resolver; no network access and no Gemini key.
Fixtures contain only hand-written URLs.

Issue edge cases:

- EC1: whitespace-only ``query``
- EC2: ``query`` with surrounding whitespace is trimmed
- EC3: 4,000 characters including emoji are allowed (characters, not bytes)
- EC4: ``max_sources`` absent, 0, 11, ``"5"`` and ``true``
- EC5: same target via redirect and directly gives one source
- EC6: several titles for one target use the first citation's title
- EC7: citation without title gives an empty title
- EC8: all sources dropped is a success with empty ``sources``
- EC9: more sources than ``max_sources`` keeps the earliest first citations
"""

import asyncio
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import pytest

from gemini_search_mcp.provider import (
    Citation,
    FakeProvider,
    ProviderError,
    SearchResult,
    Usage,
)
from gemini_search_mcp.tools.errors import InvalidInputError, ToolError
from gemini_search_mcp.tools.search import (
    SEARCH_INPUT_SCHEMA,
    SEARCH_OUTPUT_SCHEMA,
    Evidence,
    SearchInput,
    SearchOutput,
    Source,
    build_sources,
    evidence_text,
    run_search,
)

REDIRECT_HOST = "vertexaisearch.cloud.google.com"
LEAKY_DETAIL = "api-key-AIza-SECRET at https://internal.example/stack"


def _redirect(name: str) -> str:
    """Build a grounding redirect URL on the ADR 0008 allowlist host."""
    return f"https://{REDIRECT_HOST}/grounding-api-redirect/{name}"


def _cite(url: str, title: str = "", start: int = 0, end: int = 1) -> Citation:
    return Citation(url=url, title=title, start_index=start, end_index=end)


class _RecordingProvider(FakeProvider):
    """Scripted provider that also records the queries it received."""

    def __init__(self, outcomes: Sequence[SearchResult | ProviderError]) -> None:
        super().__init__(search_outcomes=outcomes)
        self.queries: list[str] = []

    async def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return await super().search(query)


class _FakeResolver:
    """Scripted redirect resolver; unlisted URLs resolve to ``None``."""

    def __init__(self, mapping: Mapping[str, str | None] | None = None) -> None:
        self.mapping = dict(mapping or {})
        self.calls: list[list[str]] = []

    async def __call__(self, urls: Iterable[str], /) -> Mapping[str, str | None]:
        requested = list(dict.fromkeys(urls))
        self.calls.append(requested)
        return {url: self.mapping.get(url) for url in requested}


class _RaisingResolver:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def __call__(self, urls: Iterable[str], /) -> Mapping[str, str | None]:
        raise self.error


def _result(
    answer: str = "answer",
    citations: Sequence[Citation] = (),
    search_queries: Sequence[str] = (),
    usage: Usage | None = None,
    model: str = "test-model",
) -> SearchResult:
    return SearchResult(
        answer=answer,
        citations=list(citations),
        search_queries=list(search_queries),
        usage=usage or Usage(input_tokens=11, output_tokens=22),
        model=model,
    )


def _search(
    result: SearchResult | ProviderError,
    *,
    query: str = "query",
    max_sources: int = 5,
    resolver: Any = None,
) -> tuple[Any, _RecordingProvider]:
    """Run ``run_search`` against a one-shot provider; return result and provider."""
    provider = _RecordingProvider([result])
    outcome = asyncio.run(
        run_search(
            SearchInput(query=query, max_sources=max_sources),
            provider=provider,
            resolver=resolver or _FakeResolver(),
        )
    )
    return outcome, provider


def _sources(
    citations: Sequence[Citation],
    *,
    max_sources: int = 5,
    answer: str = "answer",
    resolver: Any = None,
) -> list[Source]:
    outcome, _ = _search(_result(answer, citations), max_sources=max_sources, resolver=resolver)
    return outcome.output.sources


# --- AC1: input rules at both boundaries ---------------------------------------


def test_ac1_valid_input_is_accepted_with_defaults() -> None:
    tool_input = SearchInput(query="what is new")

    assert tool_input.query == "what is new"
    assert tool_input.max_sources == 5


def test_ac1_ec2_query_is_trimmed_in_search_input() -> None:
    assert SearchInput(query="  \t padded query \n ").query == "padded query"


@pytest.mark.parametrize(
    "query", ["", " ", "   \t\n\r  ", chr(0xA0), chr(0x3000) + " " + chr(0x2003)]
)
def test_ac1_ec1_blank_query_is_rejected(query: str) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput(query=query)

    assert excinfo.value.code == "invalid_input"
    assert excinfo.value.field == "query"
    assert excinfo.value.rule == "must not be empty"
    assert excinfo.value.message == "Invalid input: query must not be empty."


@pytest.mark.parametrize("query", [123, None, ["a"], {"q": "a"}, True, b"bytes"])
def test_ac1_non_string_query_is_rejected(query: Any) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput(query=query)

    assert excinfo.value.message == "Invalid input: query must be a string."


def test_ac1_ec3_query_of_4000_emoji_characters_is_allowed() -> None:
    query = "\U0001f600" * 4000  # 16,000 bytes in UTF-8, 4,000 characters

    assert SearchInput(query=query).query == query


def test_ac1_ec3_query_of_4001_characters_is_rejected() -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput(query="\U0001f600" * 4001)

    assert excinfo.value.field == "query"
    assert excinfo.value.message == "Invalid input: query must have at most 4000 characters."


def test_ac1_ec2_length_limit_applies_after_trimming() -> None:
    padded = "  " + "a" * 4000 + "  \n"

    assert SearchInput(query=padded).query == "a" * 4000
    with pytest.raises(InvalidInputError):
        SearchInput(query="  " + "a" * 4001 + "  ")


@pytest.mark.parametrize("value", [1, 5, 10])
def test_ac1_max_sources_inside_range_is_accepted(value: int) -> None:
    assert SearchInput(query="q", max_sources=value).max_sources == value


@pytest.mark.parametrize("value", [0, 11, -1, 100])
def test_ac1_ec4_max_sources_outside_range_is_rejected(value: int) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput(query="q", max_sources=value)

    assert excinfo.value.field == "max_sources"
    assert excinfo.value.rule == "must be between 1 and 10"
    assert excinfo.value.message == "Invalid input: max_sources must be between 1 and 10."


@pytest.mark.parametrize("value", ["5", True, False, 5.0, 5.5, None, [5]])
def test_ac1_ec4_max_sources_of_wrong_type_is_rejected(value: Any) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput(query="q", max_sources=value)

    assert excinfo.value.field == "max_sources"
    assert excinfo.value.message == "Invalid input: max_sources must be an integer."


def test_ac1_query_violation_is_reported_before_max_sources_violation() -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput(query=" ", max_sources=0)

    assert excinfo.value.field == "query"


def test_ac1_error_message_never_echoes_the_input_value() -> None:
    value: Any = "SECRET-VALUE"
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput(query="q", max_sources=value)

    assert "SECRET-VALUE" not in excinfo.value.message
    assert "SECRET-VALUE" not in str(excinfo.value)
    assert excinfo.value.to_payload("req-1")["error"]["message"] == excinfo.value.message


def test_ac1_from_arguments_builds_input_and_applies_default() -> None:
    tool_input = SearchInput.from_arguments({"query": "  hello  "})

    assert tool_input == SearchInput(query="hello", max_sources=5)


def test_ac1_ec4_from_arguments_absent_max_sources_is_five() -> None:
    assert SearchInput.from_arguments({"query": "q"}).max_sources == 5


def test_ac1_from_arguments_uses_given_max_sources() -> None:
    assert SearchInput.from_arguments({"query": "q", "max_sources": 10}).max_sources == 10


def test_ac1_from_arguments_missing_query_is_required() -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput.from_arguments({"max_sources": 3})

    assert excinfo.value.field == "query"
    assert excinfo.value.rule == "is required"
    assert excinfo.value.message == "Invalid input: query is required."


def test_ac1_ec1_from_arguments_blank_query_is_rejected() -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput.from_arguments({"query": "  \t\n "})

    assert excinfo.value.message == "Invalid input: query must not be empty."


def test_ac1_ec3_from_arguments_allows_4000_emoji() -> None:
    query = "\U0001f600" * 4000

    assert SearchInput.from_arguments({"query": query}).query == query


@pytest.mark.parametrize("value", [0, 11])
def test_ac1_ec4_from_arguments_rejects_max_sources_out_of_range(value: int) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput.from_arguments({"query": "q", "max_sources": value})

    assert excinfo.value.message == "Invalid input: max_sources must be between 1 and 10."


@pytest.mark.parametrize("value", ["5", True, 5.0, None])
def test_ac1_ec4_from_arguments_rejects_max_sources_of_wrong_type(value: object) -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput.from_arguments({"query": "q", "max_sources": value})

    assert excinfo.value.message == "Invalid input: max_sources must be an integer."


def test_ac1_from_arguments_rejects_non_string_query() -> None:
    with pytest.raises(InvalidInputError) as excinfo:
        SearchInput.from_arguments({"query": 42})

    assert excinfo.value.message == "Invalid input: query must be a string."


def test_ac1_from_arguments_ignores_unknown_keys() -> None:
    tool_input = SearchInput.from_arguments({"query": "q", "unexpected": "value"})

    assert tool_input == SearchInput(query="q", max_sources=5)


def test_ac1_ec1_invalid_input_never_reaches_the_provider() -> None:
    provider = _RecordingProvider([_result()])

    with pytest.raises(InvalidInputError):
        tool_input = SearchInput.from_arguments({"query": "   "})
        asyncio.run(run_search(tool_input, provider=provider, resolver=_FakeResolver()))

    assert provider.queries == []


def test_ac1_input_schema_advertises_the_adr0003_rules() -> None:
    properties = SEARCH_INPUT_SCHEMA["properties"]

    assert SEARCH_INPUT_SCHEMA["type"] == "object"
    assert list(SEARCH_INPUT_SCHEMA["required"]) == ["query"]
    assert properties["query"]["type"] == "string"
    assert properties["query"]["minLength"] == 1
    # JSON Schema "integer" rejects the string "5" and the boolean true (EC4).
    assert properties["max_sources"]["type"] == "integer"
    assert properties["max_sources"]["minimum"] == 1
    assert properties["max_sources"]["maximum"] == 10
    assert properties["max_sources"]["default"] == 5


# --- Provider call and pass-through ---------------------------------------------


def test_ec2_provider_is_called_once_with_the_trimmed_query() -> None:
    outcome, provider = _search(_result(), query="  trimmed query \n")

    assert outcome is not None
    assert provider.queries == ["trimmed query"]


def test_run_search_passes_answer_queries_usage_and_model_through() -> None:
    result = _result(
        answer="Unchanged answer.\n",
        search_queries=["first query", "second query"],
        usage=Usage(input_tokens=7, output_tokens=None),
        model="model-x",
    )

    outcome, _ = _search(result)

    assert outcome.output.answer == "Unchanged answer.\n"
    assert outcome.output.search_queries == ["first query", "second query"]
    assert outcome.usage == Usage(input_tokens=7, output_tokens=None)
    assert outcome.model == "model-x"


# --- AC2: merging by target URL --------------------------------------------------


def test_ac2_several_citations_of_one_url_form_one_source_with_all_evidence() -> None:
    answer = "alpha beta gamma"
    citations = [
        _cite("https://example.com/a", "Page A", 0, 5),
        _cite("https://example.com/a", "Page A", 6, 10),
        _cite("https://example.com/a", "Page A", 11, 16),
    ]

    sources = _sources(citations, answer=answer)

    assert sources == [
        Source(
            title="Page A",
            url="https://example.com/a",
            evidence=[
                Evidence("alpha", 0, 5),
                Evidence("beta", 6, 10),
                Evidence("gamma", 11, 16),
            ],
        )
    ]


def test_ac2_urls_with_the_same_normalized_form_are_merged() -> None:
    citations = [
        _cite("HTTPS://Example.COM/a", "One", 0, 1),
        _cite("https://example.com:443/a", "Two", 2, 3),
    ]

    sources = _sources(citations)

    assert len(sources) == 1
    assert sources[0].url == "https://example.com/a"
    assert [item.start_index for item in sources[0].evidence] == [0, 2]


def test_ac2_ec5_redirect_and_direct_url_with_the_same_target_form_one_source() -> None:
    redirect = _redirect("abc")
    resolver = _FakeResolver({redirect: "https://example.com/target"})
    citations = [
        _cite(redirect, "Via redirect", 0, 5),
        _cite("https://example.com/target", "Direct", 6, 10),
    ]

    sources = _sources(citations, answer="alpha beta", resolver=resolver)

    assert len(sources) == 1
    assert sources[0].url == "https://example.com/target"
    assert sources[0].evidence == [Evidence("alpha", 0, 5), Evidence("beta", 6, 10)]


def test_ac2_several_redirects_to_one_target_form_one_source() -> None:
    first, second = _redirect("one"), _redirect("two")
    resolver = _FakeResolver(
        {first: "https://example.com/target", second: "https://example.com/target"}
    )

    sources = _sources([_cite(first, "A", 0, 1), _cite(second, "B", 2, 3)], resolver=resolver)

    assert len(sources) == 1
    assert len(sources[0].evidence) == 2


def test_ac2_ec6_title_of_the_first_citation_is_used() -> None:
    citations = [
        _cite("https://example.com/a", "First title", 0, 1),
        _cite("https://example.com/a", "Second title", 2, 3),
        _cite("https://example.com/a", "", 4, 5),
    ]

    assert _sources(citations)[0].title == "First title"


def test_ac2_ec6_title_of_the_first_citation_wins_across_redirect_and_direct() -> None:
    redirect = _redirect("abc")
    resolver = _FakeResolver({redirect: "https://example.com/target"})
    citations = [
        _cite(redirect, "Redirect title", 0, 1),
        _cite("https://example.com/target", "Direct title", 2, 3),
    ]

    assert _sources(citations, resolver=resolver)[0].title == "Redirect title"


def test_ac2_ec7_citation_without_title_gives_an_empty_title() -> None:
    sources = _sources([_cite("https://example.com/a", "", 0, 1)])

    assert sources[0].title == ""


def test_ac2_redirects_are_resolved_in_one_call_for_all_distinct_redirect_urls() -> None:
    first, second = _redirect("one"), _redirect("two")
    resolver = _FakeResolver({first: "https://example.com/one", second: "https://example.com/two"})
    citations = [
        _cite(first, "One", 0, 1),
        _cite("https://example.com/direct", "Direct", 2, 3),
        _cite(second, "Two", 4, 5),
        _cite(first, "One", 6, 7),
    ]

    sources = _sources(citations, resolver=resolver)

    assert len(resolver.calls) == 1
    assert sorted(resolver.calls[0]) == sorted([first, second])
    assert [source.url for source in sources] == [
        "https://example.com/one",
        "https://example.com/direct",
        "https://example.com/two",
    ]


def test_ac2_without_redirect_urls_the_resolver_is_not_called() -> None:
    resolver = _FakeResolver()

    _sources([_cite("https://example.com/a", "A", 0, 1)], resolver=resolver)

    assert resolver.calls == []


# --- AC3: ordering and truncation ------------------------------------------------


def test_ac3_sources_are_ordered_by_first_citation() -> None:
    citations = [
        _cite("https://example.com/b", "B", 0, 1),
        _cite("https://example.com/a", "A", 2, 3),
        _cite("https://example.com/b", "B", 4, 5),
        _cite("https://example.com/c", "C", 6, 7),
    ]

    sources = _sources(citations)

    assert [source.url for source in sources] == [
        "https://example.com/b",
        "https://example.com/a",
        "https://example.com/c",
    ]
    assert [len(source.evidence) for source in sources] == [2, 1, 1]


def test_ac3_ordering_follows_the_first_citation_not_the_number_of_citations() -> None:
    citations = [
        _cite("https://example.com/first", "First", 0, 1),
        _cite("https://example.com/many", "Many", 2, 3),
        _cite("https://example.com/many", "Many", 4, 5),
        _cite("https://example.com/many", "Many", 6, 7),
    ]

    assert [source.url for source in _sources(citations)] == [
        "https://example.com/first",
        "https://example.com/many",
    ]


def test_ac3_ec9_truncation_keeps_the_sources_with_the_earliest_first_citation() -> None:
    citations = [
        _cite(f"https://example.com/{name}", name, i, i + 1) for i, name in enumerate("abcd")
    ]

    sources = _sources(citations, max_sources=2)

    assert [source.url for source in sources] == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_ac3_truncation_applies_after_merging() -> None:
    citations = [
        _cite("https://example.com/a", "A", 0, 1),
        _cite("https://example.com/b", "B", 2, 3),
        _cite("https://example.com/a", "A", 4, 5),
        _cite("https://example.com/c", "C", 6, 7),
    ]

    sources = _sources(citations, max_sources=2)

    assert [source.url for source in sources] == ["https://example.com/a", "https://example.com/b"]
    assert [len(source.evidence) for source in sources] == [2, 1]


def test_ac3_truncated_sources_leave_no_evidence_behind() -> None:
    citations = [
        _cite("https://example.com/a", "A", 0, 1),
        _cite("https://example.com/b", "B", 2, 3),
    ]

    sources = _sources(citations, max_sources=1)

    assert [(item.start_index, item.end_index) for s in sources for item in s.evidence] == [(0, 1)]


def test_ac3_truncation_counts_only_sources_that_were_kept() -> None:
    citations = [
        _cite("ftp://example.com/dropped", "Dropped", 0, 1),
        _cite("https://example.com/a", "A", 2, 3),
        _cite("https://example.com/b", "B", 4, 5),
        _cite("https://example.com/c", "C", 6, 7),
    ]

    sources = _sources(citations, max_sources=2)

    assert [source.url for source in sources] == ["https://example.com/a", "https://example.com/b"]


@pytest.mark.parametrize(("max_sources", "expected"), [(1, 1), (5, 5), (10, 10)])
def test_ac3_result_never_exceeds_max_sources(max_sources: int, expected: int) -> None:
    citations = [_cite(f"https://example.com/{i}", "", i, i + 1) for i in range(12)]

    assert len(_sources(citations, max_sources=max_sources)) == expected


def test_ac3_default_input_truncates_to_five_sources() -> None:
    citations = [_cite(f"https://example.com/{i}", "", i, i + 1) for i in range(8)]
    provider = _RecordingProvider([_result(citations=citations)])

    outcome = asyncio.run(
        run_search(
            SearchInput.from_arguments({"query": "q"}),
            provider=provider,
            resolver=_FakeResolver(),
        )
    )

    assert len(outcome.output.sources) == 5


def test_ac3_build_sources_orders_and_truncates_directly() -> None:
    citations = [
        _cite("https://example.com/b", "B", 0, 1),
        _cite("https://example.com/a", "A", 2, 3),
    ]

    sources = asyncio.run(build_sources(citations, "ab", 1, resolver=_FakeResolver()))

    assert [source.url for source in sources] == ["https://example.com/b"]


# --- AC4: dropped sources with their evidence -----------------------------------


def test_ac4_unresolvable_redirect_is_dropped_with_its_evidence() -> None:
    bad = _redirect("unresolvable")
    citations = [
        _cite(bad, "Lost", 0, 5),
        _cite("https://example.com/kept", "Kept", 6, 10),
        _cite(bad, "Lost", 11, 16),
    ]
    resolver = _FakeResolver({bad: None})

    sources = _sources(citations, answer="alpha beta gamma", resolver=resolver)

    assert sources == [
        Source(title="Kept", url="https://example.com/kept", evidence=[Evidence("beta", 6, 10)])
    ]


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("ftp://example.com/file", id="scheme"),
        pytest.param("not a url", id="syntax"),
        pytest.param("https://user:pass@example.com/", id="credentials"),
        pytest.param("https://example.com:8080/", id="port"),
        pytest.param("https://127.0.0.1/", id="ip_literal"),
        pytest.param("http://localhost/", id="host_suffix"),
        pytest.param("https://example.com/" + "a" * 2100, id="length"),
        pytest.param("", id="empty"),
    ],
)
def test_ac4_citation_rejected_by_the_input_check_is_dropped_with_its_evidence(url: str) -> None:
    citations = [_cite(url, "Rejected", 0, 5), _cite("https://example.com/ok", "Ok", 6, 10)]

    sources = _sources(citations, answer="alpha beta")

    assert sources == [
        Source(title="Ok", url="https://example.com/ok", evidence=[Evidence("beta", 6, 10)])
    ]


def test_ac4_resolved_target_rejected_by_the_input_check_is_dropped_with_its_evidence() -> None:
    redirect = _redirect("to-internal")
    resolver = _FakeResolver({redirect: "http://127.0.0.1/admin"})
    citations = [_cite(redirect, "Internal", 0, 5), _cite("https://example.com/ok", "Ok", 6, 10)]

    sources = _sources(citations, answer="alpha beta", resolver=resolver)

    assert [source.url for source in sources] == ["https://example.com/ok"]
    assert [item.start_index for s in sources for item in s.evidence] == [6]


def test_ac4_redirect_url_rejected_by_the_input_check_is_never_resolved() -> None:
    # Port 8080 on the allowlist host fails the input check before any resolution.
    bad = f"https://{REDIRECT_HOST}:8080/grounding-api-redirect/abc"
    resolver = _FakeResolver({bad: "https://example.com/target"})

    sources = _sources([_cite(bad, "Bad", 0, 1)], resolver=resolver)

    assert sources == []
    assert all(bad not in call for call in resolver.calls)


def test_ac4_dropped_redirect_does_not_remove_evidence_of_a_direct_source_with_same_target() -> (
    None
):
    redirect = _redirect("lost")
    resolver = _FakeResolver({redirect: None})
    citations = [
        _cite(redirect, "Lost", 0, 5),
        _cite("https://example.com/target", "Direct", 6, 10),
    ]

    sources = _sources(citations, answer="alpha beta", resolver=resolver)

    assert sources == [Source("Direct", "https://example.com/target", [Evidence("beta", 6, 10)])]


def test_ac4_ec8_all_sources_dropped_is_a_success_with_empty_sources() -> None:
    bad_redirect = _redirect("lost")
    citations = [
        _cite(bad_redirect, "Lost", 0, 5),
        _cite("ftp://example.com/x", "Rejected", 6, 10),
    ]
    result = _result(
        answer="alpha beta",
        citations=citations,
        search_queries=["executed query"],
    )

    outcome, _ = _search(result, resolver=_FakeResolver({bad_redirect: None}))

    assert outcome.output.sources == []
    assert outcome.output.answer == "alpha beta"
    assert outcome.output.search_queries == ["executed query"]


# --- AC5: no citations and no search queries -------------------------------------


def test_ac5_answer_without_citations_and_queries_is_a_success_with_empty_lists() -> None:
    outcome, _ = _search(_result(answer="Plain answer.", citations=[], search_queries=[]))

    assert outcome.output.answer == "Plain answer."
    assert outcome.output.sources == []
    assert outcome.output.search_queries == []


def test_ac5_missing_citations_keep_the_search_queries() -> None:
    outcome, _ = _search(_result(search_queries=["only query"]))

    assert outcome.output.sources == []
    assert outcome.output.search_queries == ["only query"]


def test_ac5_missing_search_queries_keep_the_sources() -> None:
    outcome, _ = _search(_result(citations=[_cite("https://example.com/a", "A", 0, 1)]))

    assert len(outcome.output.sources) == 1
    assert outcome.output.search_queries == []


def test_ac5_resolver_is_not_called_without_citations() -> None:
    resolver = _FakeResolver()

    _search(_result(), resolver=resolver)

    assert resolver.calls == []


# --- AC6: evidence corresponds 1:1 to delivered citations ------------------------


def test_ac6_every_evidence_corresponds_to_exactly_one_kept_citation() -> None:
    lost = _redirect("lost")
    redirect = _redirect("ok")
    resolver = _FakeResolver({lost: None, redirect: "https://example.com/r"})
    citations = [
        _cite("https://example.com/a", "A", 0, 1),
        _cite(lost, "Lost", 2, 3),
        _cite(redirect, "R", 4, 5),
        _cite("ftp://example.com/x", "Rejected", 6, 7),
        _cite("https://example.com/a", "A", 8, 9),
        _cite("https://example.com/r", "R", 10, 11),
        _cite("https://example.com/b", "B", 12, 13),
    ]
    kept = [(0, 1), (4, 5), (8, 9), (10, 11), (12, 13)]

    sources = _sources(citations, answer="x" * 20, resolver=resolver)

    delivered = [(item.start_index, item.end_index) for s in sources for item in s.evidence]
    assert sorted(delivered) == kept
    assert len(delivered) == len(set(delivered))


def test_ac6_evidence_of_a_dropped_citation_is_never_delivered() -> None:
    citations = [
        _cite("https://example.com/a", "A", 0, 1),
        _cite("ftp://example.com/x", "Rejected", 2, 3),
    ]

    delivered = [
        (item.start_index, item.end_index) for s in _sources(citations) for item in s.evidence
    ]

    assert delivered == [(0, 1)]


def test_ac6_every_source_has_at_least_one_evidence() -> None:
    citations = [_cite(f"https://example.com/{i}", "", i, i + 1) for i in range(4)]

    assert all(source.evidence for source in _sources(citations))


def test_ac6_evidence_indices_are_copied_unchanged_from_the_citation() -> None:
    sources = _sources([_cite("https://example.com/a", "A", 3, 9)], answer="0123456789")

    assert sources[0].evidence == [Evidence("345678", 3, 9)]


# --- Evidence text: UTF-8 byte indices -------------------------------------------


def test_ec3_evidence_text_is_sliced_by_utf8_bytes_not_characters() -> None:
    # "é" is two bytes: "abc" spans bytes 3..6 but characters 2..5.
    answer = "é abc"
    sources = _sources([_cite("https://example.com/a", "A", 3, 6)], answer=answer)

    assert sources[0].evidence == [Evidence("abc", 3, 6)]


def test_ec3_evidence_text_with_emoji_and_german_umlauts() -> None:
    answer = "Grüße \U0001f600 aus Köln: sonnig."
    start = answer.encode("utf-8").index(b"sonnig")
    end = start + len(b"sonnig")

    sources = _sources([_cite("https://example.com/a", "A", start, end)], answer=answer)

    assert sources[0].evidence == [Evidence("sonnig", start, end)]


def test_ec3_evidence_text_covering_multibyte_characters_is_decoded() -> None:
    answer = "x Köln y"
    needle = "Köln".encode()
    start = answer.encode("utf-8").index(needle)
    end = start + len(needle)  # end index is exclusive
    sources = _sources([_cite("https://example.com/a", "A", start, end)], answer=answer)

    assert sources[0].evidence[0].text == "Köln"


def test_ec3_evidence_text_function_slices_utf8_bytes() -> None:
    assert evidence_text("\U0001f600 ok", 5, 7) == "ok"
    assert evidence_text("plain ascii", 6, 11) == "ascii"
    assert evidence_text("abc", 1, 1) == ""


def test_ec3_evidence_text_function_never_raises_for_odd_offsets() -> None:
    answer = "éa"

    assert "�" in evidence_text(answer, 1, 3)  # inside a multi-byte character
    assert evidence_text(answer, -5, 2) == "é"
    assert evidence_text(answer, 0, 999) == "éa"
    assert evidence_text(answer, 5, 2) == ""


def test_ac6_evidence_text_tolerates_lone_surrogate_in_answer() -> None:
    answer = "a\ud800b"  # a lone surrogate takes 3 bytes, so "b" is bytes 4 to 5

    assert evidence_text(answer, 4, 5) == "b"
    assert "\ud800" not in evidence_text(answer, 0, 5)


def test_ac6_lone_surrogate_in_answer_keeps_the_search_successful() -> None:
    answer = "a\ud800b"
    outcome, _ = _search(_result(answer, [_cite("https://example.com/a", "A", 4, 5)]))

    assert outcome.output.answer == answer
    assert outcome.output.sources[0].evidence[0].text == "b"


# --- AC7: error mapping in run_search -------------------------------------------


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
def test_ac7_provider_error_kind_gives_the_right_code_without_details(
    kind: Any, code: str, message: str
) -> None:
    original = ProviderError(kind, LEAKY_DETAIL)

    with pytest.raises(ToolError) as excinfo:
        _search(original)

    assert excinfo.value.code == code
    assert excinfo.value.message == message
    assert LEAKY_DETAIL not in str(excinfo.value)
    assert LEAKY_DETAIL not in str(excinfo.value.to_payload("req-1"))
    assert excinfo.value.__cause__ is original


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(RuntimeError(LEAKY_DETAIL), id="runtime_error"),
        pytest.param(KeyError(LEAKY_DETAIL), id="key_error"),
        pytest.param(TimeoutError(LEAKY_DETAIL), id="timeout_error"),
    ],
)
def test_ac7_unexpected_provider_exception_gives_internal_error_without_details(
    error: Exception,
) -> None:
    class _Failing(FakeProvider):
        async def search(self, query: str) -> SearchResult:
            raise error

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(
            run_search(SearchInput(query="q"), provider=_Failing(), resolver=_FakeResolver())
        )

    assert excinfo.value.code == "internal_error"
    assert excinfo.value.message == "Internal error."
    assert "SECRET" not in str(excinfo.value)
    assert "SECRET" not in str(excinfo.value.to_payload("req-1"))
    assert excinfo.value.__cause__ is error


def test_ac7_unexpected_resolver_exception_gives_internal_error_without_details() -> None:
    error = RuntimeError(LEAKY_DETAIL)
    provider = _RecordingProvider([_result(citations=[_cite(_redirect("abc"), "A", 0, 1)])])

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(
            run_search(SearchInput(query="q"), provider=provider, resolver=_RaisingResolver(error))
        )

    assert excinfo.value.code == "internal_error"
    assert excinfo.value.message == "Internal error."
    assert "SECRET" not in str(excinfo.value)
    assert excinfo.value.__cause__ is error


def test_ac7_exhausted_fake_provider_script_is_an_internal_error() -> None:
    provider = FakeProvider()

    with pytest.raises(ToolError) as excinfo:
        asyncio.run(run_search(SearchInput(query="q"), provider=provider, resolver=_FakeResolver()))

    assert excinfo.value.code == "internal_error"


def test_ac7_cancellation_is_not_mapped_to_a_tool_error() -> None:
    class _Cancelled(FakeProvider):
        async def search(self, query: str) -> SearchResult:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_search(SearchInput(query="q"), provider=_Cancelled(), resolver=_FakeResolver())
        )


def test_ac7_cancellation_during_resolution_is_not_mapped_to_a_tool_error() -> None:
    provider = _RecordingProvider([_result(citations=[_cite(_redirect("abc"), "A", 0, 1)])])

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            run_search(
                SearchInput(query="q"),
                provider=provider,
                resolver=_RaisingResolver(asyncio.CancelledError()),
            )
        )


# --- Output contract -------------------------------------------------------------


def test_output_structured_content_has_exactly_the_adr0003_shape() -> None:
    output = SearchOutput(
        answer="alpha",
        sources=[Source("A", "https://example.com/a", [Evidence("alpha", 0, 5)])],
        search_queries=["q1"],
    )

    content = output.to_structured_content()

    assert content == {
        "answer": "alpha",
        "sources": [
            {
                "title": "A",
                "url": "https://example.com/a",
                "evidence": [{"text": "alpha", "start_index": 0, "end_index": 5}],
            }
        ],
        "search_queries": ["q1"],
    }
    assert set(content) == set(SEARCH_OUTPUT_SCHEMA["properties"])
    assert json.loads(json.dumps(content)) == content


def test_output_structured_content_of_an_empty_result_keeps_empty_lists() -> None:
    content = SearchOutput(answer="only text").to_structured_content()

    assert content == {"answer": "only text", "sources": [], "search_queries": []}
