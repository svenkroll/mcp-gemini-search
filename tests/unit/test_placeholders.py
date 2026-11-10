"""Unit tests for the documented package placeholders created by issue #1."""

import importlib

import pytest

import gemini_search_mcp

PLACEHOLDER_MODULES = [
    "gemini_search_mcp",
    "gemini_search_mcp.config",
    "gemini_search_mcp.gemini_client",
    "gemini_search_mcp.server",
]


@pytest.mark.parametrize("module_name", PLACEHOLDER_MODULES)
def test_placeholder_modules_have_docstring(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__doc__ is not None
    assert module.__doc__.strip() != ""


def test_package_exposes_version() -> None:
    assert gemini_search_mcp.__version__ == "0.0.0"
    assert gemini_search_mcp.PACKAGE_NAME == "gemini_search_mcp"


def test_placeholder_constants() -> None:
    assert importlib.import_module("gemini_search_mcp.config").ENV_PREFIX == "GEMINI_SEARCH_MCP_"
    client = importlib.import_module("gemini_search_mcp.gemini_client")
    assert client.PROVIDER_NAME == "gemini"
    server = importlib.import_module("gemini_search_mcp.server")
    assert server.SERVER_NAME == "gemini-search-mcp"
