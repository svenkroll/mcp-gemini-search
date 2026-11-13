"""Acceptance tests for the bearer token access control of ``/mcp`` (issue #9, ADR 0008).

The app from ``build_http_app`` is driven in-process through an ASGI transport,
so no port is opened and there is no network access. The scripted provider
replaces Gemini. The tokens below are obviously fake values.

Issue edge cases covered here:

- EC1: scheme in lower case, ``bearer <token>``, is accepted
- EC2: ``Bearer `` with an empty value gets 401
- EC3: the correct token with an appended character, or only a prefix, gets 401
- EC4: the correct token with surrounding whitespace gets 401
- EC5: a health endpoint called with a wrong token answers 200
"""

import asyncio
import io
import logging
import re
from collections.abc import AsyncGenerator, Iterable, Iterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from gemini_search_mcp.config import Settings
from gemini_search_mcp.provider import (
    Citation,
    FakeProvider,
    ProviderError,
    SearchResult,
    UrlAnalysisResult,
    Usage,
)
from gemini_search_mcp.server import (
    TOOL_CALL_LOGGER_NAME,
    build_http_app,
    build_server,
    configure_logging,
)

# Obviously fake values; they never leave this test process.
FAKE_KEY = "fake-gemini-key-for-auth-tests"
TOKEN = "fake-bearer-token-for-auth-tests-0123456789"  # noqa: S105 - fixture value, not a secret
WRONG_TOKEN = "wrong-bearer-token-for-auth-tests-9876543210"  # noqa: S105 - fixture value

BASE_URL = "http://testserver"
RPC_HEADERS = {"Accept": "application/json, text/event-stream"}
QUERY = "capital of france"

SEARCH_RESULT = SearchResult(
    answer="Paris is the capital of France.",
    citations=[
        Citation(url="https://example.com/paris", title="Paris", start_index=0, end_index=5)
    ],
    search_queries=["capital of france"],
    usage=Usage(input_tokens=11, output_tokens=22),
    model="fake-model-search",
)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANALYZE_URL_ENABLED", "LOG_QUERIES", "MCP_TRANSPORT", "MCP_BEARER_TOKEN"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def log_stream() -> Iterator[io.StringIO]:
    """Route the process JSON logging at debug level into a buffer, then restore it."""
    root = logging.getLogger()
    tool_logger = logging.getLogger(TOOL_CALL_LOGGER_NAME)
    saved_handlers = list(root.handlers)
    saved_levels = (root.level, tool_logger.level)
    stream = io.StringIO()
    configure_logging("debug", stream)
    try:
        yield stream
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_levels[0])
        tool_logger.setLevel(saved_levels[1])


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


class _CountingProvider(FakeProvider):
    """Scripted provider that counts how often Gemini would have been called."""

    def __init__(self, search_outcomes: list[SearchResult | ProviderError] | None = None) -> None:
        analyze_outcomes: list[UrlAnalysisResult | ProviderError] = []
        super().__init__(search_outcomes or [], analyze_outcomes)
        self.calls = 0

    async def search(self, query: str) -> SearchResult:
        self.calls += 1
        return await super().search(query)


@asynccontextmanager
async def _serving(provider: FakeProvider) -> AsyncGenerator[httpx2.AsyncClient]:
    settings = Settings(
        gemini_api_key=SecretStr(FAKE_KEY),
        mcp_transport="http",
        mcp_bearer_token=SecretStr(TOKEN),
    )
    app = build_http_app(build_server(settings, provider, resolver=_identity_resolver))
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url=BASE_URL) as client,
    ):
        yield client


def _search_call() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search", "arguments": {"query": QUERY}},
    }


async def _post_mcp(client: httpx2.AsyncClient, authorization: str | None) -> httpx2.Response:
    headers = dict(RPC_HEADERS)
    if authorization is not None:
        headers["Authorization"] = authorization
    return await client.post("/mcp", json=_search_call(), headers=headers)


async def _assert_auth_is_enforced(client: httpx2.AsyncClient) -> None:
    """Prove access control is on in this app, so a 200 elsewhere is not a missing guard."""
    _assert_rejected(await _post_mcp(client, f"Bearer {WRONG_TOKEN}"))


def _assert_rejected(response: httpx2.Response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"].split(" ")[0].rstrip(",") == "Bearer"


def _rejects(authorization: str | None) -> tuple[httpx2.Response, int]:
    async def scenario() -> tuple[httpx2.Response, int]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as client:
            return await _post_mcp(client, authorization), provider.calls

    return asyncio.run(scenario())


# AC1: missing, other scheme, wrong token and token prefix are answered with 401


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(None, id="no-header"),
        pytest.param(f"Basic {TOKEN}", id="other-scheme"),
        pytest.param(TOKEN, id="no-scheme"),
        pytest.param(f"Bearer {WRONG_TOKEN}", id="wrong-token"),
        pytest.param(f"Bearer {TOKEN[:-1]}", id="token-prefix"),
        pytest.param(f"Bearer {TOKEN[:8]}", id="short-token-prefix"),
    ],
)
def test_ac1_mcp_answers_401_with_www_authenticate_bearer(authorization: str | None) -> None:
    response, provider_calls = _rejects(authorization)

    _assert_rejected(response)
    assert provider_calls == 0


def test_ac1_rejection_carries_no_details() -> None:
    response, _ = _rejects(f"Bearer {WRONG_TOKEN}")

    assert TOKEN not in response.text
    assert WRONG_TOKEN not in response.text
    assert TOKEN not in response.headers["www-authenticate"]


# AC2: with the correct token a tool call works


def test_ac2_correct_token_allows_a_tool_call() -> None:
    async def scenario() -> tuple[httpx2.Response, int]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as client:
            await _assert_auth_is_enforced(client)
            return await _post_mcp(client, f"Bearer {TOKEN}"), provider.calls

    response, provider_calls = asyncio.run(scenario())

    assert response.status_code == 200
    assert SEARCH_RESULT.answer in response.text
    assert provider_calls == 1


# AC3: health endpoints answer 200 without a token


def test_ac3_health_endpoints_answer_200_without_a_token() -> None:
    async def scenario() -> tuple[int, int]:
        async with _serving(_CountingProvider()) as client:
            await _assert_auth_is_enforced(client)
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
            return live.status_code, ready.status_code

    assert asyncio.run(scenario()) == (200, 200)


# AC4: captured logs contain neither token nor authorization header


def test_ac4_logs_contain_neither_token_nor_authorization_header(
    log_stream: io.StringIO,
) -> None:
    async def scenario() -> None:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as client:
            _assert_rejected(await _post_mcp(client, None))
            _assert_rejected(await _post_mcp(client, f"Bearer {WRONG_TOKEN}"))
            _assert_rejected(await _post_mcp(client, f"Bearer {TOKEN[:-1]}"))
            assert (await _post_mcp(client, f"Bearer {TOKEN}")).status_code == 200
            await client.get("/health/live", headers={"Authorization": f"Bearer {WRONG_TOKEN}"})

    asyncio.run(scenario())
    logs = log_stream.getvalue()

    assert logs  # the successful tool call wrote its line, so capturing works
    assert TOKEN not in logs
    assert WRONG_TOKEN not in logs
    assert TOKEN[:-1] not in logs
    assert not re.search(r'(?i)"authorization"\s*:', logs)
    assert not re.search(r"(?i)authorization\s*[:=]", logs)


# EC1: scheme in lower case is accepted


@pytest.mark.parametrize("scheme", ["bearer", "BEARER"])
def test_ec1_scheme_in_another_letter_case_is_accepted(scheme: str) -> None:
    async def scenario() -> tuple[httpx2.Response, int]:
        provider = _CountingProvider(search_outcomes=[SEARCH_RESULT])
        async with _serving(provider) as client:
            await _assert_auth_is_enforced(client)
            return await _post_mcp(client, f"{scheme} {TOKEN}"), provider.calls

    response, provider_calls = asyncio.run(scenario())

    assert response.status_code == 200
    assert SEARCH_RESULT.answer in response.text
    assert provider_calls == 1


# EC2: empty value


@pytest.mark.parametrize("authorization", ["Bearer ", "Bearer"], ids=["empty-value", "no-value"])
def test_ec2_empty_bearer_value_gets_401(authorization: str) -> None:
    response, provider_calls = _rejects(authorization)

    _assert_rejected(response)
    assert provider_calls == 0


# EC3: appended character or prefix


def test_ec3_token_with_an_appended_character_gets_401() -> None:
    response, provider_calls = _rejects(f"Bearer {TOKEN}x")

    _assert_rejected(response)
    assert provider_calls == 0


def test_ec3_prefix_of_the_token_gets_401() -> None:
    response, provider_calls = _rejects(f"Bearer {TOKEN[: len(TOKEN) // 2]}")

    _assert_rejected(response)
    assert provider_calls == 0


# EC4: surrounding whitespace


@pytest.mark.parametrize(
    "authorization",
    [
        pytest.param(f"Bearer  {TOKEN}", id="leading-space"),
        pytest.param(f"Bearer {TOKEN} ", id="trailing-space"),
        pytest.param(f"Bearer {TOKEN}\t", id="trailing-tab"),
        pytest.param(f"Bearer \t{TOKEN}", id="leading-tab"),
    ],
)
def test_ec4_token_with_surrounding_whitespace_gets_401(authorization: str) -> None:
    response, provider_calls = _rejects(authorization)

    _assert_rejected(response)
    assert provider_calls == 0


# EC5: health endpoint with a wrong token


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
def test_ec5_health_endpoint_with_a_wrong_token_answers_200(path: str) -> None:
    async def scenario() -> int:
        async with _serving(_CountingProvider()) as client:
            await _assert_auth_is_enforced(client)
            response = await client.get(path, headers={"Authorization": f"Bearer {WRONG_TOKEN}"})
            return response.status_code

    assert asyncio.run(scenario()) == 200
