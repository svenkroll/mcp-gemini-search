"""Reproduction tests for issue #31: capped HTTP client loggers, tokens on tool errors.

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order of
the issue. Everything runs against a scripted provider, an ``httpx.MockTransport``
and the in-memory FastMCP client; no network access and no Gemini key.

ACs with evidence ``test`` covered here: AC1 to AC4. AC5 is a review item.

Issue edge cases covered here:

- EC1: ``LOG_LEVEL=debug`` keeps the HTTP client loggers capped, other loggers log
- EC2: ``LOG_LEVEL=warning`` or ``error``: the cap is not stricter than the root level
- EC3: an HTTP client logger emitting ``WARNING`` is written as a JSON line
- EC4: ``analyze_url`` with ``url_unsafe`` after a response carries token figures
- EC5: provider errors log ``null`` token figures
- EC6: input rejected before any Gemini call logs ``null`` token figures
"""

import asyncio
import io
import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from functools import partial
from typing import Any

import httpx
import pytest
from fastmcp import Client, FastMCP

from gemini_search_mcp.config import Settings
from gemini_search_mcp.provider import (
    Citation,
    FakeProvider,
    ProviderError,
    Retrieval,
    RetrievalStatus,
    SearchResult,
    UrlAnalysisResult,
    Usage,
)
from gemini_search_mcp.server import TOOL_CALL_LOGGER_NAME, build_server, configure_logging
from gemini_search_mcp.urlpolicy import resolve_redirects

FAKE_KEY = "fake-gemini-key-AIzaSyFAKE0123456789"
FAKE_MODEL = "fake-model-config"

CONFIG_VARIABLES = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_MAX_CONCURRENCY",
    "GEMINI_MAX_RETRIES",
    "ANALYZE_URL_ENABLED",
    "LOG_QUERIES",
    "LOG_LEVEL",
    "MCP_TRANSPORT",
    "MCP_HOST",
    "MCP_PORT",
    "MCP_BEARER_TOKEN",
)

HTTP_CLIENT_LOGGERS = ("httpx", "httpx2", "httpcore", "httpcore.connection")
WATCHED_LOGGERS = (*HTTP_CLIENT_LOGGERS, "gemini_search_mcp.other", TOOL_CALL_LOGGER_NAME)

QUERY = "capital of France"
TARGET_URL = "https://example.com/page"
QUESTION = "What is the price?"
REDIRECT_URL = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc123"
REDIRECT_TARGET = "https://example.com/paris"

USAGE = Usage(input_tokens=33, output_tokens=44)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test without any ADR 0010 variable in the environment."""
    for name in CONFIG_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """Route the process JSON logging into a buffer and restore all logger state."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_root_level = root.level
    saved_levels = {name: logging.getLogger(name).level for name in WATCHED_LOGGERS}
    stream = io.StringIO()
    try:
        yield stream
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_root_level)
        for name, level in saved_levels.items():
            logging.getLogger(name).setLevel(level)


def _log_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _tool_call_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [line for line in _log_lines(stream) if line.get("event") == "tool_call"]


def _settings() -> Settings:
    return Settings(
        gemini_api_key=FAKE_KEY,
        gemini_model=FAKE_MODEL,
        analyze_url_enabled=True,
    )


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


def _server(provider: FakeProvider, resolver: Any = _identity_resolver) -> FastMCP:
    return build_server(_settings(), provider, resolver=resolver)


async def _call(server: FastMCP, name: str, arguments: dict[str, Any]) -> Any:
    async with Client(server) as client:
        return await client.call_tool(name, arguments, raise_on_error=False)


def _analysis(status: RetrievalStatus) -> UrlAnalysisResult:
    return UrlAnalysisResult(
        answer="",
        retrievals=[Retrieval(url=TARGET_URL, status=status)],
        usage=USAGE,
        model="fake-model-analyze",
    )


# AC1: INFO and DEBUG records of the capped loggers are silent, WARNING is one JSON line


@pytest.mark.parametrize("logger_name", HTTP_CLIENT_LOGGERS)
@pytest.mark.parametrize("level", ["info", "debug"])
def test_ac1_http_client_loggers_drop_info_and_debug_but_write_warning(
    log_stream: io.StringIO, level: Any, logger_name: str
) -> None:
    configure_logging(level, log_stream)
    logger = logging.getLogger(logger_name)

    logger.debug("debug record for %s", logger_name)
    logger.info("HTTP Request: GET https://example.com/secret-path")
    assert log_stream.getvalue() == ""

    logger.warning("warning record for %s", logger_name)
    (line,) = _log_lines(log_stream)
    assert line["level"] == "warning"
    assert line["logger"] == logger_name
    assert line["message"] == f"warning record for {logger_name}"


# AC2: a search with real redirect resolution writes exactly one line


def test_ac2_search_with_redirect_resolution_writes_only_the_tool_call_line(
    log_stream: io.StringIO,
) -> None:
    configure_logging("info", log_stream)

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == REDIRECT_URL:
            return httpx.Response(302, headers={"location": REDIRECT_TARGET})
        return httpx.Response(200)

    resolver = partial(resolve_redirects, transport=httpx.MockTransport(handler))
    result = SearchResult(
        answer="Paris is the capital of France.",
        citations=[Citation(url=REDIRECT_URL, title="Paris", start_index=0, end_index=5)],
        search_queries=["capital of france"],
        usage=Usage(input_tokens=11, output_tokens=22),
        model="fake-model-search",
    )
    server = _server(FakeProvider(search_outcomes=[result]), resolver)

    response = asyncio.run(_call(server, "search", {"query": QUERY}))

    assert response.is_error is False
    assert [source["url"] for source in response.structured_content["sources"]] == [REDIRECT_TARGET]
    (line,) = _log_lines(log_stream)
    assert line["event"] == "tool_call"
    assert line["status"] == "ok"
    assert "vertexaisearch" not in log_stream.getvalue()


# EC1: debug keeps the HTTP client loggers capped, other loggers log at DEBUG


def test_ec1_debug_level_caps_http_clients_but_other_loggers_log_debug(
    log_stream: io.StringIO,
) -> None:
    configure_logging("debug", log_stream)

    for name in HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).debug("connection detail")
        logging.getLogger(name).info("HTTP Request: GET https://example.com/x")
    assert log_stream.getvalue() == ""

    logging.getLogger("gemini_search_mcp.other").debug("other debug record")
    (line,) = _log_lines(log_stream)
    assert line["level"] == "debug"
    assert line["logger"] == "gemini_search_mcp.other"
    assert line["message"] == "other debug record"


# EC2: warning and error keep their behavior, the cap is not stricter than the root level


def test_ec2_warning_level_still_writes_http_client_warnings(log_stream: io.StringIO) -> None:
    configure_logging("warning", log_stream)

    logging.getLogger("httpx").info("dropped")
    logging.getLogger("httpx").warning("kept")

    (line,) = _log_lines(log_stream)
    assert line["level"] == "warning"
    assert line["message"] == "kept"


@pytest.mark.parametrize("logger_name", HTTP_CLIENT_LOGGERS)
def test_ec2_error_level_is_not_lowered_by_the_cap(
    log_stream: io.StringIO, logger_name: str
) -> None:
    configure_logging("error", log_stream)
    logger = logging.getLogger(logger_name)

    logger.warning("dropped warning")
    assert log_stream.getvalue() == ""

    logger.error("kept error")
    (line,) = _log_lines(log_stream)
    assert line["level"] == "error"
    assert line["message"] == "kept error"


# EC3: an HTTP client WARNING is a JSON line


def test_ec3_http_client_warning_is_written_as_one_json_line(log_stream: io.StringIO) -> None:
    configure_logging("info", log_stream)

    logging.getLogger("httpx").warning("connection pool exhausted")

    raw = log_stream.getvalue()
    assert raw.count("\n") == 1
    line = json.loads(raw)
    assert line["event"] == "log"
    assert line["level"] == "warning"
    assert line["logger"] == "httpx"
    assert line["message"] == "connection pool exhausted"


# AC3 / EC4: tool error after a successful provider result keeps the token figures


def test_ac3_url_unreachable_logs_the_token_figures_of_the_provider_result(
    log_stream: io.StringIO,
) -> None:
    configure_logging("info", log_stream)
    server = _server(FakeProvider(analyze_url_outcomes=[_analysis("failed")]))

    response = asyncio.run(_call(server, "analyze_url", {"url": TARGET_URL, "question": QUESTION}))

    assert response.is_error is True
    (line,) = _tool_call_lines(log_stream)
    assert line["status"] == "error"
    assert line["error_code"] == "url_unreachable"
    assert line["input_tokens"] == 33
    assert line["output_tokens"] == 44


def test_ac3_ec4_url_unsafe_logs_the_token_figures_of_the_provider_result(
    log_stream: io.StringIO,
) -> None:
    configure_logging("info", log_stream)
    server = _server(FakeProvider(analyze_url_outcomes=[_analysis("unsafe")]))

    response = asyncio.run(_call(server, "analyze_url", {"url": TARGET_URL, "question": QUESTION}))

    assert response.is_error is True
    (line,) = _tool_call_lines(log_stream)
    assert line["status"] == "error"
    assert line["error_code"] == "url_unsafe"
    assert line["input_tokens"] == 33
    assert line["output_tokens"] == 44


# AC4 / EC5: provider errors log null token figures


@pytest.mark.parametrize(
    ("tool", "arguments", "kind", "code"),
    [
        ("search", {"query": QUERY}, "unavailable", "upstream_unavailable"),
        ("search", {"query": QUERY}, "rejected", "upstream_error"),
        (
            "analyze_url",
            {"url": TARGET_URL, "question": QUESTION},
            "unavailable",
            "upstream_unavailable",
        ),
        (
            "analyze_url",
            {"url": TARGET_URL, "question": QUESTION},
            "rejected",
            "upstream_error",
        ),
    ],
)
def test_ac4_ec5_provider_error_logs_null_token_figures(
    log_stream: io.StringIO, tool: str, arguments: dict[str, Any], kind: Any, code: str
) -> None:
    configure_logging("info", log_stream)
    provider = FakeProvider(
        search_outcomes=[ProviderError(kind)],
        analyze_url_outcomes=[ProviderError(kind)],
    )

    asyncio.run(_call(_server(provider), tool, arguments))

    (line,) = _tool_call_lines(log_stream)
    assert line["error_code"] == code
    assert line["input_tokens"] is None
    assert line["output_tokens"] is None


# AC4 / EC6: input rejection logs null token figures


@pytest.mark.parametrize(
    ("tool", "arguments", "code"),
    [
        ("search", {}, "invalid_input"),
        ("analyze_url", {"url": TARGET_URL}, "invalid_input"),
        ("analyze_url", {"url": "http://localhost/", "question": QUESTION}, "url_not_allowed"),
    ],
)
def test_ac4_ec6_input_rejection_logs_null_token_figures(
    log_stream: io.StringIO, tool: str, arguments: dict[str, Any], code: str
) -> None:
    configure_logging("info", log_stream)
    server = _server(FakeProvider())

    asyncio.run(_call(server, tool, arguments))

    (line,) = _tool_call_lines(log_stream)
    assert line["error_code"] == code
    assert line["input_tokens"] is None
    assert line["output_tokens"] is None
