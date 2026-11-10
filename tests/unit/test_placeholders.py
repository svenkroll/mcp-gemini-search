"""Unit tests for the documented package placeholders created by issue #1."""

import importlib

import pytest

import gemini_search_mcp

PLACEHOLDER_MODULES = [
    "gemini_search_mcp",
    "gemini_search_mcp.fakes",
    "gemini_search_mcp.gemini_client",
    "gemini_search_mcp.provider",
    "gemini_search_mcp.server",
]


@pytest.mark.parametrize("module_name", PLACEHOLDER_MODULES)
def test_modules_have_docstring(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__doc__ is not None
    assert module.__doc__.strip() != ""


def test_package_exposes_version() -> None:
    assert gemini_search_mcp.__version__ == "0.0.0"
    assert gemini_search_mcp.PACKAGE_NAME == "gemini_search_mcp"


def test_placeholder_constants() -> None:
    client = importlib.import_module("gemini_search_mcp.gemini_client")
    assert client.PROVIDER_NAME == "gemini"
    server = importlib.import_module("gemini_search_mcp.server")
    assert server.SERVER_NAME == "gemini-search-mcp"


def test_config_is_no_longer_a_placeholder() -> None:
    config = importlib.import_module("gemini_search_mcp.config")
    assert not hasattr(config, "ENV_PREFIX")
    assert hasattr(config, "Settings")
    assert hasattr(config, "load_settings")
