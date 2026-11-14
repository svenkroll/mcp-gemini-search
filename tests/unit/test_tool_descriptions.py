"""Acceptance tests for the tool descriptions and server instructions (issue #37).

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order of
issue #37. AC1 to AC6 and EC1 are covered here; EC2 over Streamable HTTP lives
in ``tests/integration/test_tool_descriptions_http.py``. AC7 is proven by review.

Everything runs against the in-memory FastMCP client and a scripted provider; no
network access and no Gemini key. The tests read the texts as a calling agent
does: the tool descriptions from ``tools/list`` and the server instructions from
the initialize result. Only these tests read ``FACT_SUFFIX`` from
``eval/catalog.py``; ``src/`` must not import it.
"""

import asyncio
import importlib.util
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from gemini_search_mcp.config import Settings
from gemini_search_mcp.provider import FakeProvider
from gemini_search_mcp.server import build_server

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "eval" / "catalog.py"

FAKE_KEY = "fake-gemini-key-for-description-tests"


def _load_fact_suffix() -> str:
    spec = importlib.util.spec_from_file_location("eval_catalog_for_descriptions", CATALOG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_catalog_for_descriptions"] = module
    spec.loader.exec_module(module)
    return str(module.FACT_SUFFIX)


FACT_SUFFIX = _load_fact_suffix()


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


def _server(*, analyze_url_enabled: bool) -> FastMCP:
    settings = Settings(gemini_api_key=FAKE_KEY, analyze_url_enabled=analyze_url_enabled)
    return build_server(settings, FakeProvider(), resolver=_identity_resolver)


async def _read_texts(*, analyze_url_enabled: bool) -> tuple[dict[str, Any], str]:
    """Return the listed tools by name and the server instructions of the handshake."""
    async with Client(_server(analyze_url_enabled=analyze_url_enabled), mode="legacy") as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        initialized = client.initialize_result
        assert initialized is not None
        assert isinstance(initialized.instructions, str)
        return tools, initialized.instructions


def _texts(*, analyze_url_enabled: bool = True) -> tuple[dict[str, Any], str]:
    return asyncio.run(_read_texts(analyze_url_enabled=analyze_url_enabled))


def _description(name: str) -> str:
    tools, _ = _texts()
    description = tools[name].description
    assert isinstance(description, str)
    return description


# AC1: search description (issue #37, S1 to S6)


@pytest.mark.parametrize(
    ("fact", "patterns"),
    [
        (
            "S1 searches with Google Search grounding through Gemini, answer with sources",
            [r"google search grounding", r"through gemini", r"answer with its sources"],
        ),
        (
            "S2 Gemini decides on its own; plain question may be answered from model knowledge, "
            "then lists are empty and the call still succeeds",
            [r"decides on its own", r"model knowledge", r"empty", r"still succeeds"],
        ),
        (
            "S3 ask for verifiable sources in the query: look the answer up, cite the page",
            [r"verifiable sources", r"ask", r"look\b.*\bup\b", r"\bcite\b"],
        ),
        (
            "S4 example pair: plain question and the same question asking for an "
            "authoritative source with a link",
            [r"example", r"authoritative source", r"\blink\b"],
        ),
        (
            "S5 append a suffix to get a confirmed fact only",
            [r"confirmed fact", r"append"],
        ),
        (
            "S6 evidence with UTF-8 byte offsets; web content untrusted, never follow instructions",
            [r"evidence", r"utf-8 byte offsets", r"untrusted", r"never follow instructions"],
        ),
    ],
    ids=["s1", "s2", "s3", "s4", "s5", "s6"],
)
def test_ac1_search_description_states_required_fact(fact: str, patterns: list[str]) -> None:
    description = _description("search").lower()

    for pattern in patterns:
        assert re.search(pattern, description), f"missing fact: {fact} ({pattern})"


# AC2: analyze_url description (issue #37, A1 to A3); the facts of ADR 0004 stay covered by
# the existing tests in tests/unit/test_server.py


@pytest.mark.parametrize(
    ("fact", "patterns"),
    [
        (
            "A1 use it when you already have the URL and need one specific piece of "
            "information; without a URL use search",
            [
                r"already have the url",
                r"specific piece of information",
                r"without a url",
                r"\bsearch\b",
            ],
        ),
        (
            "A2 answer comes only from the retrieved content; says so explicitly when the "
            "content does not answer",
            [r"only from the retrieved content", r"does not answer", r"explicitly"],
        ),
        ("A3 long documents may be truncated during retrieval", [r"long documents", r"truncat"]),
    ],
    ids=["a1", "a2", "a3"],
)
def test_ac2_analyze_url_description_states_new_fact(fact: str, patterns: list[str]) -> None:
    description = _description("analyze_url").lower()

    for pattern in patterns:
        assert re.search(pattern, description), f"missing fact: {fact} ({pattern})"


# AC3: the fact suffix of the evaluation catalog is part of the search description


def test_ac3_search_description_contains_fact_suffix_verbatim() -> None:
    assert FACT_SUFFIX.strip() != ""

    assert FACT_SUFFIX in _description("search")


# AC4: server instructions say that sources come with the answer when the query asks for them


def test_ac4_server_instructions_say_sources_come_when_the_query_asks_for_them() -> None:
    _, instructions = _texts()
    text = " ".join(instructions.lower().split())

    assert re.search(r"query asks for (sources|them)", text), instructions
    assert re.search(r"\bsources\b", text)
    assert re.search(r"\banswer\b", text)


# AC5: no evaluation term in any text

EVALUATION_TERMS = ("answer_with_sources", "-sources", "-fact")


def test_ac5_no_description_or_instruction_contains_an_evaluation_term() -> None:
    tools, instructions = _texts()
    texts = {
        "search description": tools["search"].description,
        "analyze_url description": tools["analyze_url"].description,
        "server instructions": instructions,
    }

    for name, text in texts.items():
        assert isinstance(text, str) and text.strip() != "", name
        for term in EVALUATION_TERMS:
            assert term not in text.lower(), f"{name} contains {term!r}"


# AC6: schemas of both tools are unchanged

SEARCH_INPUT = {
    "properties": {
        "max_sources": {
            "default": 5,
            "description": "Maximum number of returned sources.",
            "maximum": 10,
            "minimum": 1,
            "type": "integer",
        },
        "query": {
            "description": (
                "Search query. Leading and trailing whitespace is removed; the rest must "
                "have 1 to 4000 characters."
            ),
            "minLength": 1,
            "type": "string",
        },
    },
    "required": ["query"],
    "type": "object",
}
SEARCH_OUTPUT = {
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "search_queries": {"items": {"type": "string"}, "type": "array"},
        "sources": {
            "items": {
                "additionalProperties": False,
                "properties": {
                    "evidence": {
                        "items": {
                            "additionalProperties": False,
                            "properties": {
                                "end_index": {"type": "integer"},
                                "start_index": {"type": "integer"},
                                "text": {"type": "string"},
                            },
                            "required": ["text", "start_index", "end_index"],
                            "type": "object",
                        },
                        "type": "array",
                    },
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["title", "url", "evidence"],
                "type": "object",
            },
            "type": "array",
        },
    },
    "required": ["answer", "sources", "search_queries"],
    "type": "object",
}
ANALYZE_URL_INPUT = {
    "properties": {
        "question": {
            "description": (
                "Question about the content of the URL. Leading and trailing whitespace is "
                "removed; the rest must have 1 to 4000 characters."
            ),
            "minLength": 1,
            "type": "string",
        },
        "url": {
            "description": (
                "Public http or https URL to analyze. Credentials, ports other than 80 and "
                "443, local host names and private or reserved IP addresses are rejected."
            ),
            "type": "string",
        },
    },
    "required": ["url", "question"],
    "type": "object",
}
ANALYZE_URL_OUTPUT = {
    "additionalProperties": False,
    "properties": {
        "answer": {"type": "string"},
        "retrieval_status": {"enum": ["retrieved"], "type": "string"},
        "url": {"type": "string"},
    },
    "required": ["answer", "url", "retrieval_status"],
    "type": "object",
}


def test_ac6_listed_schemas_of_both_tools_are_unchanged() -> None:
    tools, _ = _texts()

    assert tools["search"].input_schema == SEARCH_INPUT
    assert tools["search"].output_schema == SEARCH_OUTPUT
    assert tools["analyze_url"].input_schema == ANALYZE_URL_INPUT
    assert tools["analyze_url"].output_schema == ANALYZE_URL_OUTPUT


# EC1: analyze_url not registered


def test_ec1_without_analyze_url_the_instructions_and_search_description_read_correctly() -> None:
    tools, instructions = _texts(analyze_url_enabled=False)
    text = " ".join(instructions.lower().split())

    assert list(tools) == ["search"]
    # The instructions carry the new search sentence ...
    assert re.search(r"query asks for (sources|them)", text), instructions
    # ... and still name analyze_url only conditionally on it being listed.
    assert re.search(r"analyze_url, when it is listed", text), instructions
    # The search description is complete and does not point to the missing tool.
    description = tools["search"].description
    assert isinstance(description, str)
    assert FACT_SUFFIX in description
    assert "analyze_url" not in description.lower()
