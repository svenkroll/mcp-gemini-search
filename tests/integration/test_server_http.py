"""Acceptance tests for the stateless Streamable HTTP app (issue #8, ADR 0002).

The app from ``build_http_app`` is driven in-process through an ASGI transport,
so no port is opened and there is no network access. The scripted provider and
the scripted redirect resolver replace Gemini; fixtures contain no real keys.

Issue edge cases covered here:

- EC1: a request without ``Origin`` is processed
- EC2: an ``Origin`` equal to the address the server is reached at is processed;
  every other ``Origin``, including ``null``, gets 403
"""

import asyncio
import json
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS

from gemini_search_mcp.config import Settings
from gemini_search_mcp.provider import (
    Citation,
    FakeProvider,
    ProviderError,
    Retrieval,
    SearchResult,
    UrlAnalysisResult,
    Usage,
)
from gemini_search_mcp.server import build_http_app, build_server

# Obviously fake value; it never leaves this test process.
FAKE_KEY = "fake-gemini-key-for-http-tests"

BASE_URL = "http://testserver"
MCP_URL = f"{BASE_URL}/mcp"
MODERN_REVISION = "2026-07-28"
RPC_HEADERS = {"Accept": "application/json, text/event-stream"}

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


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANALYZE_URL_ENABLED", "LOG_QUERIES", "MCP_TRANSPORT", "MCP_BEARER_TOKEN"):
        monkeypatch.delenv(name, raising=False)


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


class _CountingProvider(FakeProvider):
    """Scripted provider that counts how often Gemini would have been called."""

    def __init__(
        self,
        search_outcomes: list[SearchResult | ProviderError] | None = None,
        analyze_url_outcomes: list[UrlAnalysisResult | ProviderError] | None = None,
    ) -> None:
        super().__init__(search_outcomes or [], analyze_url_outcomes or [])
        self.calls = 0

    async def search(self, query: str) -> SearchResult:
        self.calls += 1
        return await super().search(query)

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult:
        self.calls += 1
        return await super().analyze_url(url, question)


def _server(provider: FakeProvider) -> FastMCP:
    settings = Settings(
        gemini_api_key=FAKE_KEY,
        analyze_url_enabled=True,
    )
    return build_server(settings, provider, resolver=_identity_resolver)


@dataclass
class _Http:
    """An in-process HTTP app and helpers to talk to it."""

    app: Any

    def raw(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app),
            base_url=BASE_URL,
        )

    def client(self, mode: str) -> Client:
        def factory(
            headers: dict[str, str] | None = None,
            timeout: httpx2.Timeout | None = None,
            auth: httpx2.Auth | None = None,
            **_: Any,
        ) -> httpx2.AsyncClient:
            return httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=self.app),
                base_url=BASE_URL,
                headers=headers,
                timeout=timeout,
                auth=auth,
            )

        transport = StreamableHttpTransport(MCP_URL, httpx_client_factory=factory)
        return Client(transport, mode=mode)


@asynccontextmanager
async def _serving(provider: FakeProvider) -> AsyncGenerator[_Http]:
    app = build_http_app(_server(provider))
    async with app.router.lifespan_context(app):
        yield _Http(app)


def _rpc_result(response: httpx2.Response) -> dict[str, Any]:
    """Return the JSON-RPC message of a JSON or SSE response body."""
    body = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        return json.loads(data[-1])
    return json.loads(body)


def _call_payload(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _contract(tool: Any) -> dict[str, Any]:
    """The part of a listed tool that makes up the contract, without metadata."""
    return {
        "name": tool.name,
        "title": tool.title,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "annotations": tool.annotations.model_dump(exclude_none=True),
    }


def _result_view(result: Any) -> dict[str, Any]:
    """The part of a tool result that makes up the contract, without metadata."""
    return {
        "is_error": result.is_error,
        "content": [item.text for item in result.content],
        "structured_content": result.structured_content,
    }


def _without_request_id(view: dict[str, Any]) -> dict[str, Any]:
    """Blank the per-call request ID of an error view so two calls can be compared."""
    if not view["is_error"]:
        return view
    payload = json.loads(view["content"][0])
    payload["error"]["request_id"] = "<request-id>"
    return {**view, "content": [json.dumps(payload)]}


def _scripted_provider() -> _CountingProvider:
    return _CountingProvider(
        search_outcomes=[SEARCH_RESULT, ProviderError("unavailable")],
        analyze_url_outcomes=[ANALYZE_RESULT],
    )


async def _exercise(client: Client) -> dict[str, Any]:
    async with client:
        tools = await client.list_tools()
        search_ok = await client.call_tool("search", {"query": QUERY}, raise_on_error=False)
        search_err = await client.call_tool("search", {"query": QUERY}, raise_on_error=False)
        analyze = await client.call_tool(
            "analyze_url", {"url": TARGET_URL, "question": QUESTION}, raise_on_error=False
        )
        return {
            "tools": [_contract(tool) for tool in tools],
            "calls": [
                _without_request_id(_result_view(result))
                for result in (search_ok, search_err, analyze)
            ],
            "protocol_version": client.protocol_version,
        }


# AC5: HTTP serves the same contract as the in-memory client, without session state


def test_ac5_http_returns_the_same_contract_as_the_in_memory_client() -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        in_memory = await _exercise(Client(_server(_scripted_provider())))
        async with _serving(_scripted_provider()) as http:
            over_http = await _exercise(http.client("auto"))
        return in_memory, over_http

    in_memory, over_http = asyncio.run(scenario())

    assert over_http["tools"] == in_memory["tools"]
    assert over_http["calls"] == in_memory["calls"]
    assert [tool["name"] for tool in over_http["tools"]] == ["search", "analyze_url"]
    assert over_http["calls"][0]["is_error"] is False
    assert over_http["calls"][1]["is_error"] is True


def test_ac5_http_keeps_no_session_state() -> None:
    async def scenario() -> tuple[httpx2.Response, httpx2.Response]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as http, http.raw() as raw:
            initialize = await raw.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": HANDSHAKE_PROTOCOL_VERSIONS[-1],
                        "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"},
                    },
                },
                headers=RPC_HEADERS,
            )
            # No initialize before, no session ID sent: the call is still served.
            call = await raw.post(
                "/mcp", json=_call_payload("search", {"query": QUERY}), headers=RPC_HEADERS
            )
            return initialize, call

    initialize, call = asyncio.run(scenario())

    assert initialize.status_code == 200
    assert "mcp-session-id" not in initialize.headers
    assert call.status_code == 200
    assert "mcp-session-id" not in call.headers
    assert _rpc_result(call)["result"]["structuredContent"]["answer"] == SEARCH_RESULT.answer


# AC6: health endpoints


def test_ac6_health_live_and_ready_answer_200_without_calling_gemini() -> None:
    async def scenario() -> tuple[int, int, int]:
        provider = _CountingProvider()
        async with _serving(provider) as http, http.raw() as raw:
            live = await raw.get("/health/live")
            ready = await raw.get("/health/ready")
            return live.status_code, ready.status_code, provider.calls

    assert asyncio.run(scenario()) == (200, 200, 0)


# AC7 / EC1 / EC2: Origin validation


def test_ac7_invalid_origin_gets_403_and_is_not_processed() -> None:
    async def scenario() -> tuple[int, int]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as http, http.raw() as raw:
            response = await raw.post(
                "/mcp",
                json=_call_payload("search", {"query": QUERY}),
                headers={**RPC_HEADERS, "Origin": "http://evil.example"},
            )
            return response.status_code, provider.calls

    assert asyncio.run(scenario()) == (403, 0)


def test_ac7_request_without_origin_is_processed() -> None:
    async def scenario() -> tuple[int, dict[str, Any], int]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as http, http.raw() as raw:
            response = await raw.post(
                "/mcp", json=_call_payload("search", {"query": QUERY}), headers=RPC_HEADERS
            )
            return response.status_code, _rpc_result(response), provider.calls

    status, message, calls = asyncio.run(scenario())

    assert status == 200
    assert message["result"]["isError"] is False
    assert calls == 1


def test_ec1_tool_list_request_without_origin_is_processed() -> None:
    async def scenario() -> tuple[int, list[str]]:
        async with _serving(_CountingProvider()) as http, http.raw() as raw:
            response = await raw.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers=RPC_HEADERS,
            )
            tools = _rpc_result(response)["result"]["tools"]
            return response.status_code, [tool["name"] for tool in tools]

    assert asyncio.run(scenario()) == (200, ["search", "analyze_url"])


@pytest.mark.parametrize(
    "origin",
    ["http://testserver", "HTTP://TESTSERVER", "http://testserver:80"],
)
def test_ec2_origin_equal_to_the_server_address_is_processed(origin: str) -> None:
    async def scenario() -> tuple[int, int]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as http, http.raw() as raw:
            response = await raw.post(
                "/mcp",
                json=_call_payload("search", {"query": QUERY}),
                headers={**RPC_HEADERS, "Origin": origin},
            )
            return response.status_code, provider.calls

    assert asyncio.run(scenario()) == (200, 1)


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "",
        "http://evil.example",
        "https://testserver",
        "http://testserver:8080",
        "http://testserver.evil.example",
    ],
)
def test_ec2_any_other_origin_gets_403(origin: str) -> None:
    async def scenario() -> tuple[int, int]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as http, http.raw() as raw:
            response = await raw.post(
                "/mcp",
                json=_call_payload("search", {"query": QUERY}),
                headers={**RPC_HEADERS, "Origin": origin},
            )
            return response.status_code, provider.calls

    assert asyncio.run(scenario()) == (403, 0)


# AC8: both protocol generations receive the same tool contract


def test_ac8_modern_and_older_revision_clients_receive_the_same_contract() -> None:
    async def scenario() -> tuple[dict[str, Any], dict[str, Any]]:
        async with _serving(_scripted_provider()) as http:
            legacy = await _exercise(http.client("legacy"))
        async with _serving(_scripted_provider()) as http:
            modern = await _exercise(http.client(MODERN_REVISION))
        return legacy, modern

    legacy, modern = asyncio.run(scenario())

    assert modern["protocol_version"] == MODERN_REVISION
    assert legacy["protocol_version"] in HANDSHAKE_PROTOCOL_VERSIONS
    assert legacy["tools"] == modern["tools"]
    assert legacy["calls"] == modern["calls"]
    assert [tool["name"] for tool in modern["tools"]] == ["search", "analyze_url"]


# AC9: stable order over HTTP and for both generations


def test_ac9_tools_list_order_is_stable_over_http_for_both_revisions() -> None:
    async def names(client: Client) -> list[list[str]]:
        async with client:
            return [[tool.name for tool in await client.list_tools()] for _ in range(3)]

    async def scenario() -> list[list[str]]:
        async with _serving(FakeProvider()) as http:
            return [*await names(http.client("legacy")), *await names(http.client(MODERN_REVISION))]

    assert asyncio.run(scenario()) == [["search", "analyze_url"]] * 6
