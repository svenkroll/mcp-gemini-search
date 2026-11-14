"""Acceptance test for the tool texts over both transports (issue #37, EC2).

The in-memory client stands for the transport-independent server (stdio serves the
same server object); the Streamable HTTP app is driven in-process through an ASGI
transport, once per protocol generation. No network access and no Gemini key.
"""

import asyncio
from collections.abc import AsyncGenerator, Iterable, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport

from gemini_search_mcp.config import Settings
from gemini_search_mcp.provider import FakeProvider
from gemini_search_mcp.server import build_http_app, build_server

FAKE_KEY = "fake-gemini-key-for-description-tests"
BASE_URL = "http://testserver"
MCP_URL = f"{BASE_URL}/mcp"
MODERN_REVISION = "2026-07-28"
FACT_SUFFIX_START = "Answer only with a fact a source confirms"


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


def _server() -> FastMCP:
    settings = Settings(gemini_api_key=FAKE_KEY, analyze_url_enabled=True)
    return build_server(settings, FakeProvider(), resolver=_identity_resolver)


@asynccontextmanager
async def _serving() -> AsyncGenerator[Any]:
    app = build_http_app(_server())
    async with app.router.lifespan_context(app):
        yield app


def _http_client(app: Any, mode: str) -> Client:
    def factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
        **_: Any,
    ) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    return Client(StreamableHttpTransport(MCP_URL, httpx_client_factory=factory), mode=mode)


async def _descriptions_per_call(client: Client) -> list[dict[str, str | None]]:
    async with client:
        return [
            {tool.name: tool.description for tool in await client.list_tools()} for _ in range(3)
        ]


def test_ec2_texts_are_identical_over_every_transport_and_on_every_tools_list_call() -> None:
    async def scenario() -> list[list[dict[str, str | None]]]:
        runs = [await _descriptions_per_call(Client(_server()))]
        async with _serving() as app:
            runs.append(await _descriptions_per_call(_http_client(app, "legacy")))
            runs.append(await _descriptions_per_call(_http_client(app, MODERN_REVISION)))
        return runs

    runs = asyncio.run(scenario())
    calls = [call for run in runs for call in run]

    assert len(calls) == 9
    assert all(call == calls[0] for call in calls)
    assert set(calls[0]) == {"search", "analyze_url"}
    # The identical texts are the new ones of issue #37.
    assert FACT_SUFFIX_START in str(calls[0]["search"])
    assert "truncat" in str(calls[0]["analyze_url"]).lower()
