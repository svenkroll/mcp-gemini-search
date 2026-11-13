"""Tests for citation validation in the Gemini adapter (issue #20).

The adapter must deliver only citations whose URL and UTF-8 byte offsets are
valid for the answer exactly as ``search`` returns it. The tests exercise the
public ``search`` method through a fake ``InteractionsClient`` that returns
hand-written interactions; no network, no Gemini key. The measurement result
of issue #29 is ``undecidable``: indices are never corrected by a block offset.

Acceptance criteria (AC) and known edge cases (EC) use the numbering of the
issue. A test that proves the same rule for an AC and an EC carries both IDs.
"""

import asyncio
import logging
import re
from typing import Any

import pytest
from google.genai import interactions

from gemini_search_mcp.config import Settings
from gemini_search_mcp.gemini_client import GeminiProvider
from gemini_search_mcp.provider import Citation, SearchResult
from gemini_search_mcp.tools.search import SearchInput, run_search

ADAPTER_LOGGER = "gemini_search_mcp.gemini_client"

# "Köln" is 5 bytes (ö has 2), the emoji has 4 bytes: the answer has 13 bytes.
ANSWER = "Köln 🌍 ok"
ANSWER_BYTES = len(ANSWER.encode("utf-8"))
O_UMLAUT_START = 1  # ö occupies bytes 1 and 2
EMOJI_START = 6  # the emoji occupies bytes 6 to 9

OK_URL = "https://example.com/valid"


def _annotation(
    url: Any = OK_URL,
    start: Any = 0,
    end: Any = 5,
    title: Any = "Title",
) -> dict[str, Any]:
    """Build one hand-written ``url_citation`` annotation; ``None`` omits the field."""
    annotation: dict[str, Any] = {"type": "url_citation"}
    for key, value in (("url", url), ("start_index", start), ("end_index", end), ("title", title)):
        if value is not None:
            annotation[key] = value
    return annotation


def _interaction(blocks: list[tuple[str, list[dict[str, Any]]]]) -> interactions.Interaction:
    """Build an interaction with one ``model_output`` step holding the text blocks."""
    payload = {
        "id": "int_citation_validation",
        "status": "completed",
        "model": "gemini-3.8-flash",
        "steps": [
            {
                "type": "model_output",
                "content": [
                    {"type": "text", "text": text, "annotations": annotations}
                    for text, annotations in blocks
                ],
            }
        ],
    }
    return interactions.Interaction.model_validate(payload)


class _FakeInteractions:
    """Return one scripted interaction."""

    def __init__(self, response: interactions.Interaction) -> None:
        self._response = response

    async def create(self, **_: Any) -> interactions.Interaction:
        return self._response


def _provider(response: interactions.Interaction) -> GeminiProvider:
    settings = Settings(
        gemini_api_key="test-api-key-not-real",
        gemini_model="gemini-3.8-flash",
        gemini_timeout_seconds=60,
        gemini_max_concurrency=2,
        gemini_max_retries=0,
    )
    return GeminiProvider(settings, _FakeInteractions(response))


def _search(
    annotations: list[dict[str, Any]], text: str = ANSWER, query: str = "query"
) -> SearchResult:
    provider = _provider(_interaction([(text, annotations)]))
    return asyncio.run(provider.search(query))


def _spans(result: SearchResult) -> list[tuple[str, int, int]]:
    return [(c.url, c.start_index, c.end_index) for c in result.citations]


def _adapter_debug_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == ADAPTER_LOGGER and record.levelno == logging.DEBUG
    ]


# --- AC1: one test per drop rule -----------------------------------------------


def test_ac1_ec1_citation_without_url_is_dropped() -> None:
    result = _search([_annotation(url=None), _annotation(url="https://example.com/kept")])

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


def test_ac1_ec1_citation_with_empty_url_is_dropped() -> None:
    result = _search([_annotation(url=""), _annotation(url="https://example.com/kept")])

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


def test_ac1_ec2_citation_without_start_index_is_dropped() -> None:
    result = _search([_annotation(start=None), _annotation(url="https://example.com/kept")])

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


def test_ac1_ec2_citation_without_end_index_is_dropped() -> None:
    result = _search([_annotation(end=None), _annotation(url="https://example.com/kept")])

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


def test_ac1_ec3_citation_with_negative_start_is_dropped() -> None:
    result = _search([_annotation(start=-1, end=5), _annotation(url="https://example.com/kept")])

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


def test_ac1_ec4_citation_with_empty_segment_is_dropped() -> None:
    result = _search([_annotation(start=5, end=5), _annotation(url="https://example.com/kept")])

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


def test_ac1_ec6_citation_ending_one_byte_beyond_the_answer_is_dropped() -> None:
    result = _search(
        [
            _annotation(start=0, end=ANSWER_BYTES + 1),
            _annotation(url="https://example.com/kept"),
        ]
    )

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (O_UMLAUT_START + 1, EMOJI_START),  # starts inside the umlaut
        (0, O_UMLAUT_START + 1),  # ends inside the umlaut
        (EMOJI_START + 1, ANSWER_BYTES),  # starts inside the emoji
        (0, EMOJI_START + 2),  # ends inside the emoji
    ],
)
def test_ac1_ec7_citation_cutting_a_multi_byte_character_is_dropped(start: int, end: int) -> None:
    result = _search(
        [
            _annotation(start=start, end=end),
            _annotation(url="https://example.com/kept"),
        ]
    )

    assert _spans(result) == [("https://example.com/kept", 0, 5)]


def test_ac1_kept_citations_keep_their_order_around_dropped_ones() -> None:
    result = _search(
        [
            _annotation(url="https://example.com/first", start=0, end=5),
            _annotation(url="", start=0, end=5),
            _annotation(url="https://example.com/second", start=EMOJI_START, end=EMOJI_START + 4),
            _annotation(start=3, end=3),
            _annotation(url="https://example.com/third", start=0, end=ANSWER_BYTES),
        ]
    )

    assert _spans(result) == [
        ("https://example.com/first", 0, 5),
        ("https://example.com/second", EMOJI_START, EMOJI_START + 4),
        ("https://example.com/third", 0, ANSWER_BYTES),
    ]


# --- AC2 / EC5 and EC10: boundaries that stay ----------------------------------


def test_ac2_ec5_citation_ending_at_the_answer_length_is_kept() -> None:
    result = _search([_annotation(start=EMOJI_START, end=ANSWER_BYTES)])

    assert _spans(result) == [(OK_URL, EMOJI_START, ANSWER_BYTES)]


def test_ec10_citation_without_title_is_kept_with_empty_title() -> None:
    result = _search([_annotation(title=None)])

    assert result.citations == [Citation(url=OK_URL, title="", start_index=0, end_index=5)]


# --- AC3 / EC8: several annotated text blocks (measurement result: undecidable) -


def _two_block_interaction() -> interactions.Interaction:
    first = "ö" * 10 + "x" * 17  # 37 bytes, 27 characters
    second = "y" * 53
    return _interaction(
        [
            (first, []),
            (
                second,
                [
                    _annotation(url="https://example.com/b1", start=14, end=30),
                    _annotation(url="https://example.com/b2", start=20, end=41),
                ],
            ),
        ]
    )


def test_ac3_ec8_indices_of_a_later_block_are_not_shifted_by_the_block_offset() -> None:
    result = asyncio.run(_provider(_two_block_interaction()).search("query"))

    assert len(result.answer.encode("utf-8")) == 90
    assert _spans(result) == [
        ("https://example.com/b1", 14, 30),
        ("https://example.com/b2", 20, 41),
    ]


def test_ac3_ec8_block_beyond_offset_zero_with_annotations_writes_numbers_to_debug_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        asyncio.run(_provider(_two_block_interaction()).search("query"))

    records = _adapter_debug_records(caplog)
    text = " ".join(record.getMessage() for record in records)
    # block count 2; the second block has offset 37, length 53, smallest start 14, largest end 41
    for number in ("2", "37", "53", "14", "41"):
        assert re.search(rf"(?<!\d){number}(?!\d)", text), number


def test_ac3_ec8_log_for_later_block_contains_no_content(caplog: pytest.LogCaptureFixture) -> None:
    first = "FIRST-BLOCK-SENTINEL " + "x" * 16  # 37 bytes
    second = "SECOND-BLOCK-SENTINEL " + "y" * 20
    response = _interaction(
        [
            (first, []),
            (
                second,
                [
                    _annotation(
                        url="https://example.com/url-sentinel-8841",
                        title="title-sentinel-8841",
                        start=40,
                        end=50,
                    )
                ],
            ),
        ]
    )

    with caplog.at_level(logging.DEBUG):
        asyncio.run(_provider(response).search("query-sentinel-8841"))

    assert _adapter_debug_records(caplog) != []
    for sentinel in (
        "BLOCK-SENTINEL",
        "url-sentinel-8841",
        "title-sentinel-8841",
        "query-sentinel-8841",
    ):
        assert sentinel not in caplog.text


def test_ac3_ec8_no_offset_log_when_only_the_first_block_has_annotations(
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = _interaction(
        [
            ("First block. ", [_annotation(start=0, end=5)]),
            ("Second block without annotations.", []),
        ]
    )

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(_provider(response).search("query"))

    assert _spans(result) == [(OK_URL, 0, 5)]
    assert _adapter_debug_records(caplog) == []


# --- AC4: one debug record per interaction with counts per drop reason ---------


def test_ac4_debug_record_counts_dropped_citations_without_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    answer = "ANSWER-SENTINEL-4711 ö 🌍 end"
    encoded = answer.encode("utf-8")
    total = len(encoded)
    umlaut = encoded.index("ö".encode())
    emoji = encoded.index("🌍".encode())
    url = "https://example.com/url-sentinel-4711"
    title = "title-sentinel-4711"
    query = "query-sentinel-4711"

    def ann(**kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("url", url)
        return _annotation(title=title, **kwargs)

    annotations = [
        ann(start=0, end=5),  # kept
        ann(url=None, start=0, end=5),  # 1 x missing URL
        ann(start=None, end=5),  # 2 x missing index
        ann(start=0, end=None),
        ann(start=0, end=total + 1),  # 3 x beyond the answer
        ann(start=1, end=total + 2),
        ann(start=2, end=total + 3),
        ann(start=umlaut + 1, end=emoji),  # 4 x inside a multi-byte character
        ann(start=0, end=umlaut + 1),
        ann(start=emoji + 1, end=total),
        ann(start=0, end=emoji + 2),
    ]

    with caplog.at_level(logging.DEBUG):
        result = _search(annotations, text=answer, query=query)

    assert len(result.citations) == 1
    records = _adapter_debug_records(caplog)
    assert len(records) == 1
    message = records[0].getMessage()
    for count in ("1", "2", "3", "4"):
        assert re.search(rf"(?<!\d){count}(?!\d)", message), count
    for sentinel in ("ANSWER-SENTINEL-4711", "url-sentinel-4711", "title-sentinel-4711", query):
        assert sentinel not in caplog.text


# --- AC5 / EC9: only malformed citations -----------------------------------------


def test_ac5_ec9_search_with_only_malformed_citations_succeeds_with_empty_sources() -> None:
    answer = "Plain answer with text."
    total = len(answer.encode("utf-8"))
    annotations = [
        _annotation(url="https://example.com/a", start=4, end=4),
        _annotation(url="https://example.com/b", start=0, end=total + 1),
        _annotation(url="https://example.com/c", start=-3, end=5),
        _annotation(url="https://example.com/d", start=None, end=5),
    ]
    provider = _provider(_interaction([(answer, annotations)]))

    async def no_redirects(urls: Any, /) -> dict[str, str | None]:
        return dict.fromkeys(urls)

    outcome = asyncio.run(
        run_search(SearchInput(query="query"), provider=provider, resolver=no_redirects)
    )

    assert outcome.output.sources == []
    assert outcome.output.answer == answer
