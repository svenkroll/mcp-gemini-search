"""Acceptance tests for the FastMCP server over the in-memory transport (issue #8).

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order of
the issue. Everything runs against a scripted provider and a scripted redirect
resolver through the in-memory FastMCP client; no network access, no port and no
Gemini key. Keys and tokens in fixtures are obviously fake.

ACs with evidence ``test`` covered here: AC1 to AC4, AC9 and AC10. HTTP
behavior (AC5 to AC8) lives in ``tests/integration/test_server_http.py``.

Issue edge cases covered here:

- EC2: ``is_origin_allowed`` decision table (HTTP part in the integration tests)
- EC3: ``LOG_QUERIES=true`` with ``analyze_url`` logs the question, never the URL
- EC4: client cancellation gives no result and one ``cancelled`` log line
- EC5: two identical calls give two log lines with different request IDs
- EC6: ``MCP_TRANSPORT=stdio`` opens no port and has no health endpoints
- EC7: ``ANALYZE_URL_ENABLED=false`` lists only ``search``; ``analyze_url`` is unknown
- EC8: ``ANALYZE_URL_ENABLED=true`` lists both tools in a stable order
"""

import asyncio
import io
import json
import logging
import re
import uuid
from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastmcp import Client, FastMCP

from gemini_search_mcp import server as server_module
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
from gemini_search_mcp.server import (
    TOOL_CALL_LOGGER_NAME,
    build_server,
    configure_logging,
    is_origin_allowed,
    main,
)
from gemini_search_mcp.tools.analyze_url import ANALYZE_URL_INPUT_SCHEMA, ANALYZE_URL_OUTPUT_SCHEMA
from gemini_search_mcp.tools.search import SEARCH_INPUT_SCHEMA, SEARCH_OUTPUT_SCHEMA

# Obviously fake values; they never leave this test process.
FAKE_KEY = "fake-gemini-key-AIzaSyFAKE0123456789"
FAKE_BEARER = "fake-bearer-token-" + "x" * 20
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

QUERY = "capital of France"
TARGET_URL = "https://example.com/page"
QUESTION = "What is the price?"

SEARCH_RESULT = SearchResult(
    answer="Paris is the capital of France.",
    citations=[
        Citation(url="https://example.com/paris", title="Paris", start_index=0, end_index=5)
    ],
    search_queries=["capital of france"],
    usage=Usage(input_tokens=11, output_tokens=22),
    model="fake-model-search",
)
ANALYZE_RESULT = UrlAnalysisResult(
    answer="It costs 5 euros.",
    retrievals=[Retrieval(url=TARGET_URL, status="retrieved")],
    usage=Usage(input_tokens=33, output_tokens=44),
    model="fake-model-analyze",
)

REQUIRED_LOG_FIELDS = {
    "ts",
    "level",
    "event",
    "request_id",
    "tool",
    "status",
    "error_code",
    "duration_ms",
    "model",
    "input_tokens",
    "output_tokens",
}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test without any ADR 0010 variable in the environment."""
    for name in CONFIG_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """Route the process JSON logging into a buffer and restore it afterwards."""
    root = logging.getLogger()
    tool_logger = logging.getLogger(TOOL_CALL_LOGGER_NAME)
    saved_handlers = list(root.handlers)
    saved_levels = (root.level, tool_logger.level)
    stream = io.StringIO()
    configure_logging("info", stream)
    try:
        yield stream
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_levels[0])
        tool_logger.setLevel(saved_levels[1])


def _settings(
    *,
    analyze_url_enabled: bool = False,
    log_queries: bool = False,
    bearer: str | None = None,
) -> Settings:
    return Settings(
        gemini_api_key=FAKE_KEY,
        gemini_model=FAKE_MODEL,
        analyze_url_enabled=analyze_url_enabled,
        log_queries=log_queries,
        mcp_bearer_token=bearer,
    )


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


def _server(
    provider: FakeProvider | None = None,
    *,
    analyze_url_enabled: bool = False,
    log_queries: bool = False,
    bearer: str | None = None,
) -> FastMCP:
    return build_server(
        _settings(analyze_url_enabled=analyze_url_enabled, log_queries=log_queries, bearer=bearer),
        provider or FakeProvider(),
        resolver=_identity_resolver,
    )


async def _call(
    server: FastMCP, name: str, arguments: dict[str, Any], *, mode: str = "auto"
) -> Any:
    async with Client(server, mode=mode) as client:
        return await client.call_tool(name, arguments, raise_on_error=False)


async def _list(server: FastMCP, *, mode: str = "auto") -> list[Any]:
    async with Client(server, mode=mode) as client:
        return await client.list_tools()


def _text(result: Any) -> str:
    assert len(result.content) == 1
    return result.content[0].text


def _log_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def _tool_call_lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [line for line in _log_lines(stream) if line.get("event") == "tool_call"]


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4 and str(uuid.UUID(value)) == value
    except ValueError:
        return False


# AC1 / EC7 / EC8: registered tools and their schemas


def test_ac1_enabled_lists_both_tools_with_schemas_of_the_models() -> None:
    tools = {tool.name: tool for tool in asyncio.run(_list(_server(analyze_url_enabled=True)))}

    assert set(tools) == {"search", "analyze_url"}
    assert tools["search"].input_schema == dict(SEARCH_INPUT_SCHEMA)
    assert tools["search"].output_schema == dict(SEARCH_OUTPUT_SCHEMA)
    assert tools["analyze_url"].input_schema == dict(ANALYZE_URL_INPUT_SCHEMA)
    assert tools["analyze_url"].output_schema == dict(ANALYZE_URL_OUTPUT_SCHEMA)


def test_ac1_default_lists_only_search_with_its_schemas() -> None:
    tools = asyncio.run(_list(_server()))

    assert [tool.name for tool in tools] == ["search"]
    assert tools[0].input_schema == dict(SEARCH_INPUT_SCHEMA)
    assert tools[0].output_schema == dict(SEARCH_OUTPUT_SCHEMA)


def test_ec7_disabled_analyze_url_is_answered_as_unknown_tool() -> None:
    provider = FakeProvider(analyze_url_outcomes=[ANALYZE_RESULT])
    server = _server(provider)

    result = asyncio.run(_call(server, "analyze_url", {"url": TARGET_URL, "question": QUESTION}))

    assert result.is_error is True
    assert "unknown tool" in _text(result).lower()
    assert result.structured_content is None
    # The scripted outcome was never consumed: the provider was not called.
    assert asyncio.run(provider.analyze_url(TARGET_URL, QUESTION)) is ANALYZE_RESULT


def test_ec8_enabled_lists_search_then_analyze_url_in_a_stable_order() -> None:
    async def scenario() -> list[list[str]]:
        orders = []
        async with Client(_server(analyze_url_enabled=True)) as client:
            for _ in range(3):
                orders.append([tool.name for tool in await client.list_tools()])
        orders.append([tool.name for tool in await _list(_server(analyze_url_enabled=True))])
        return orders

    assert asyncio.run(scenario()) == [["search", "analyze_url"]] * 4


# AC2: analyze_url description (ADR 0004, "Role and tool description")


def _analyze_url_description() -> str:
    tools = asyncio.run(_list(_server(analyze_url_enabled=True)))
    description = next(tool for tool in tools if tool.name == "analyze_url").description
    assert isinstance(description, str)
    return description.lower()


@pytest.mark.parametrize(
    ("fact", "patterns"),
    [
        ("one question about one public URL", [r"one question", r"one public url"]),
        ("Google performs the retrieval", [r"google", r"retriev"]),
        ("PDF included", [r"pdf"]),
        ("summary only when asked for", [r"summary", r"only when the question asks"]),
        ("no original text, no verbatim quotes", [r"original text", r"verbatim"]),
        ("page content not in the caller's context", [r"context"]),
        ("own costs", [r"cost"]),
        ("not necessarily cheaper than own fetch", [r"not necessarily cheaper"]),
        ("may retrieve pages the caller's fetch cannot load", [r"cannot load"]),
        ("fails for paywalled content", [r"paywall"]),
        ("fails for private or local addresses", [r"private", r"local"]),
        ("fails for video and audio", [r"video", r"audio"]),
        ("retrieved content is untrusted", [r"untrusted", r"instructions"]),
    ],
)
def test_ac2_description_states_required_fact(fact: str, patterns: list[str]) -> None:
    description = _analyze_url_description()

    for pattern in patterns:
        assert re.search(pattern, description), f"missing fact: {fact} ({pattern})"


def test_ac2_description_has_no_cost_claim_and_no_default_recommendation() -> None:
    description = _analyze_url_description()

    # "cheaper" may appear only in the required "not necessarily cheaper" fact.
    assert description.count("cheaper") == description.count("not necessarily cheaper")
    for forbidden in (
        "cheap ",
        "cost-effective",
        "saves",
        "reduces cost",
        "by default",
        "prefer",
        "recommend",
        "instead of your own",
        "always use",
        "should use",
    ):
        assert forbidden not in description, forbidden


# AC3: success result


def test_ac3_search_text_content_is_the_json_of_structured_content() -> None:
    server = _server(FakeProvider(search_outcomes=[SEARCH_RESULT]))

    result = asyncio.run(_call(server, "search", {"query": QUERY}))

    assert result.is_error is False
    assert result.structured_content["answer"] == SEARCH_RESULT.answer
    assert result.structured_content["sources"][0]["url"] == "https://example.com/paris"
    assert json.loads(_text(result)) == result.structured_content


def test_ac3_analyze_url_text_content_is_the_json_of_structured_content() -> None:
    server = _server(FakeProvider(analyze_url_outcomes=[ANALYZE_RESULT]), analyze_url_enabled=True)

    result = asyncio.run(_call(server, "analyze_url", {"url": TARGET_URL, "question": QUESTION}))

    assert result.is_error is False
    assert result.structured_content == {
        "answer": ANALYZE_RESULT.answer,
        "url": TARGET_URL,
        "retrieval_status": "retrieved",
    }
    assert json.loads(_text(result)) == result.structured_content


# AC4: every ADR 0007 error code as isError with the fixed message


class _RaisingProvider(FakeProvider):
    """Provider whose every operation raises the given exception."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    async def search(self, query: str) -> SearchResult:
        raise self._error

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult:
        raise self._error


def _failed_analysis(status: RetrievalStatus) -> UrlAnalysisResult:
    return UrlAnalysisResult(
        answer="",
        retrievals=[Retrieval(url=TARGET_URL, status=status)],
        usage=Usage(),
        model="fake-model-analyze",
    )


ERROR_CASES = [
    pytest.param(
        "invalid_input",
        "search",
        {},
        FakeProvider(),
        "Invalid input: query is required.",
        id="invalid_input",
    ),
    pytest.param(
        "url_not_allowed",
        "analyze_url",
        {"url": "http://localhost/", "question": QUESTION},
        FakeProvider(),
        "URL is not allowed.",
        id="url_not_allowed",
    ),
    pytest.param(
        "url_unreachable",
        "analyze_url",
        {"url": TARGET_URL, "question": QUESTION},
        FakeProvider(analyze_url_outcomes=[_failed_analysis("failed")]),
        "URL could not be retrieved.",
        id="url_unreachable",
    ),
    pytest.param(
        "url_unsafe",
        "analyze_url",
        {"url": TARGET_URL, "question": QUESTION},
        FakeProvider(analyze_url_outcomes=[_failed_analysis("unsafe")]),
        "URL was rejected as unsafe.",
        id="url_unsafe",
    ),
    pytest.param(
        "upstream_unavailable",
        "search",
        {"query": QUERY},
        FakeProvider(search_outcomes=[ProviderError("unavailable", "429 from backend")]),
        "Search backend is temporarily unavailable.",
        id="upstream_unavailable",
    ),
    pytest.param(
        "upstream_error",
        "search",
        {"query": QUERY},
        FakeProvider(search_outcomes=[ProviderError("rejected", "400 from backend")]),
        "Search backend returned an error.",
        id="upstream_error",
    ),
    pytest.param(
        "internal_error",
        "search",
        {"query": QUERY},
        FakeProvider(search_outcomes=[ProviderError("internal", "boom")]),
        "Internal error.",
        id="internal_error",
    ),
    pytest.param(
        "internal_error",
        "search",
        {"query": QUERY},
        _RaisingProvider(RuntimeError("secret internal detail")),
        "Internal error.",
        id="internal_error_unexpected_exception",
    ),
]


@pytest.mark.parametrize(("code", "tool", "arguments", "provider", "message"), ERROR_CASES)
def test_ac4_error_code_is_an_is_error_result_with_fixed_message_and_request_id(
    code: str, tool: str, arguments: dict[str, Any], provider: FakeProvider, message: str
) -> None:
    server = _server(provider, analyze_url_enabled=True)

    result = asyncio.run(_call(server, tool, arguments))

    assert result.is_error is True
    assert result.structured_content is None
    payload = json.loads(_text(result))
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message", "request_id"}
    assert payload["error"]["code"] == code
    assert payload["error"]["message"] == message
    assert _is_uuid4(payload["error"]["request_id"])
    assert "secret internal detail" not in _text(result)
    assert "from backend" not in _text(result)


# AC9: annotations, title and stable order


def test_ac9_every_registered_tool_has_annotations_and_title() -> None:
    tools = asyncio.run(_list(_server(analyze_url_enabled=True)))

    assert [tool.name for tool in tools] == ["search", "analyze_url"]
    for tool in tools:
        assert isinstance(tool.title, str)
        assert tool.title.strip() != ""
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is True
        assert tool.annotations.idempotent_hint is True
    assert tools[0].title != tools[1].title


def test_ac9_default_registered_tool_has_annotations_and_title() -> None:
    (tool,) = asyncio.run(_list(_server()))

    assert tool.name == "search"
    assert isinstance(tool.title, str)
    assert tool.title.strip() != ""
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is True
    assert tool.annotations.idempotent_hint is True


# AC10: log line


def test_ac10_successful_call_writes_one_line_with_all_required_fields(
    log_stream: io.StringIO,
) -> None:
    server = _server(FakeProvider(search_outcomes=[SEARCH_RESULT]))

    asyncio.run(_call(server, "search", {"query": QUERY}))

    (line,) = _tool_call_lines(log_stream)
    assert set(line) == REQUIRED_LOG_FIELDS
    assert line["event"] == "tool_call"
    assert line["level"] == "info"
    assert line["tool"] == "search"
    assert line["status"] == "ok"
    assert line["error_code"] is None
    assert line["model"] == SEARCH_RESULT.model
    assert line["input_tokens"] == 11
    assert line["output_tokens"] == 22
    assert _is_uuid4(line["request_id"])
    assert isinstance(line["duration_ms"], int)
    assert line["duration_ms"] >= 0
    timestamp = datetime.fromisoformat(line["ts"])
    assert timestamp.utcoffset() == timedelta(0)


def test_ac10_failed_call_writes_one_error_line_with_the_request_id_of_the_result(
    log_stream: io.StringIO,
) -> None:
    server = _server(FakeProvider(search_outcomes=[ProviderError("unavailable")]))

    result = asyncio.run(_call(server, "search", {"query": QUERY}))

    (line,) = _tool_call_lines(log_stream)
    assert set(line) == REQUIRED_LOG_FIELDS
    assert line["level"] == "error"
    assert line["status"] == "error"
    assert line["error_code"] == "upstream_unavailable"
    assert line["tool"] == "search"
    assert line["model"] == FAKE_MODEL
    assert line["input_tokens"] is None
    assert line["output_tokens"] is None
    assert line["request_id"] == json.loads(_text(result))["error"]["request_id"]


@pytest.mark.parametrize("log_queries", [True, False])
def test_ac10_query_is_logged_only_with_query_logging_enabled(
    log_stream: io.StringIO, log_queries: bool
) -> None:
    server = _server(FakeProvider(search_outcomes=[SEARCH_RESULT]), log_queries=log_queries)

    asyncio.run(_call(server, "search", {"query": QUERY}))

    (line,) = _tool_call_lines(log_stream)
    if log_queries:
        assert line["query"] == QUERY
    else:
        assert "query" not in line
        assert QUERY not in log_stream.getvalue()


def test_ac10_logs_never_contain_key_token_or_provider_message(log_stream: io.StringIO) -> None:
    leaky = ProviderError("rejected", f"request with {FAKE_KEY} and Bearer {FAKE_BEARER} failed")
    provider = FakeProvider(search_outcomes=[SEARCH_RESULT, leaky])
    server = _server(provider, bearer=FAKE_BEARER)

    asyncio.run(_call(server, "search", {"query": QUERY}))
    failed = asyncio.run(_call(server, "search", {"query": QUERY}))

    output = log_stream.getvalue()
    for secret in (FAKE_KEY, FAKE_BEARER, "request with"):
        assert secret not in output
        assert secret not in _text(failed)
    error_id = json.loads(_text(failed))["error"]["request_id"]
    details = [line for line in _log_lines(log_stream) if line.get("event") == "error_detail"]
    assert len(details) == 1
    assert details[0]["request_id"] == error_id
    assert details[0]["error_code"] == "upstream_error"


@pytest.mark.parametrize("level", ["debug", "warning", "error"])
def test_ac10_tool_call_line_is_written_at_every_log_level(
    log_stream: io.StringIO, level: Any
) -> None:
    configure_logging(level, log_stream)
    server = _server(FakeProvider(search_outcomes=[SEARCH_RESULT]))

    asyncio.run(_call(server, "search", {"query": QUERY}))

    assert len(_tool_call_lines(log_stream)) == 1


# EC3 / EC4 / EC5: logging edge cases


def test_ec3_analyze_url_query_log_holds_the_question_never_the_url(
    log_stream: io.StringIO,
) -> None:
    server = _server(
        FakeProvider(analyze_url_outcomes=[ANALYZE_RESULT]),
        analyze_url_enabled=True,
        log_queries=True,
    )

    asyncio.run(_call(server, "analyze_url", {"url": TARGET_URL, "question": QUESTION}))

    (line,) = _tool_call_lines(log_stream)
    assert line["tool"] == "analyze_url"
    assert line["query"] == QUESTION
    assert TARGET_URL not in log_stream.getvalue()


def test_ec4_cancelled_call_produces_no_result_and_one_cancelled_line(
    log_stream: io.StringIO,
) -> None:
    class BlockingProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.started = asyncio.Event()

        async def search(self, query: str) -> SearchResult:
            self.started.set()
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async def scenario() -> None:
        provider = BlockingProvider()
        server = _server(provider)
        task = asyncio.ensure_future(server.call_tool("search", {"query": QUERY}))
        await asyncio.wait_for(provider.started.wait(), timeout=5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    (line,) = _tool_call_lines(log_stream)
    assert line["status"] == "cancelled"
    assert line["error_code"] is None
    assert line["level"] == "info"
    assert [entry for entry in _log_lines(log_stream) if entry.get("event") == "error_detail"] == []


def test_ec5_two_identical_calls_write_two_lines_with_different_request_ids(
    log_stream: io.StringIO,
) -> None:
    server = _server(FakeProvider(search_outcomes=[SEARCH_RESULT, SEARCH_RESULT]))

    asyncio.run(_call(server, "search", {"query": QUERY}))
    asyncio.run(_call(server, "search", {"query": QUERY}))

    first, second = _tool_call_lines(log_stream)
    assert first["request_id"] != second["request_id"]
    assert _is_uuid4(first["request_id"])
    assert _is_uuid4(second["request_id"])


# EC2: Origin decision table (the HTTP behavior is in the integration tests)


@pytest.mark.parametrize(
    ("origin", "scheme", "host", "allowed"),
    [
        (None, "http", "127.0.0.1:8000", True),
        ("http://127.0.0.1:8000", "http", "127.0.0.1:8000", True),
        ("http://127.0.0.1:8001", "http", "127.0.0.1:8000", False),
        ("https://127.0.0.1:8000", "http", "127.0.0.1:8000", False),
        ("http://localhost:8000", "http", "127.0.0.1:8000", False),
        ("http://example.com", "http", "example.com", True),
        ("http://example.com:80", "http", "example.com", True),
        ("HTTP://EXAMPLE.COM", "http", "example.com", True),
        ("http://example.com", "http", "EXAMPLE.com", True),
        ("https://example.com", "https", "example.com", True),
        ("https://example.com:443", "https", "example.com", True),
        ("http://example.com:443", "http", "example.com", False),
        ("https://example.com", "http", "example.com", False),
        ("http://example.com", "https", "example.com", False),
        ("http://evil.example", "http", "example.com", False),
        ("http://example.com.evil.example", "http", "example.com", False),
        ("http://example.com/path", "http", "example.com", False),
        ("null", "http", "example.com", False),
        ("", "http", "example.com", False),
        ("not a url", "http", "example.com", False),
        ("http://[", "http", "example.com", False),
    ],
)
def test_ec2_origin_decision(origin: str | None, scheme: str, host: str, allowed: bool) -> None:
    assert is_origin_allowed(origin, scheme=scheme, host=host) is allowed


# EC6: stdio opens no port and has no health endpoints


def test_ec6_stdio_main_runs_stdio_transport_and_never_builds_http_or_serves(
    monkeypatch: pytest.MonkeyPatch, log_stream: io.StringIO
) -> None:
    import uvicorn

    run_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def fake_run(self: FastMCP, *args: Any, **kwargs: Any) -> None:
        run_calls.append((args, kwargs))

    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("stdio mode must not build or serve an HTTP app")

    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    monkeypatch.setattr(FastMCP, "run", fake_run)
    monkeypatch.setattr(server_module, "build_http_app", forbidden)
    monkeypatch.setattr(uvicorn, "run", forbidden)
    monkeypatch.setattr(uvicorn.Server, "serve", forbidden)

    main()

    ((args, kwargs),) = run_calls
    assert kwargs.get("transport", args[0] if args else None) == "stdio"
