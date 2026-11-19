"""Reproduction and acceptance tests for the reported server version (issue #81).

``serverInfo.version`` of the MCP ``initialize`` response must be the version of
this package, read from the installed distribution metadata, not the version of
the FastMCP framework.

Issue edge cases covered here:

- EC1: the reported version is ``project.version`` from ``pyproject.toml``
- EC2: a pre-release version is passed through unchanged
- EC3: ``__version__`` is resolved at import; the tests reload the package
"""

import asyncio
import importlib
import importlib.metadata
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

import gemini_search_mcp
from gemini_search_mcp.config import Settings
from gemini_search_mcp.provider import FakeProvider
from gemini_search_mcp.server import SERVER_NAME, build_server

DISTRIBUTION_NAME = "gemini-search-mcp"
PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


@pytest.fixture
def reload_package() -> Iterator[Any]:
    """Reload ``gemini_search_mcp`` with a patched ``importlib.metadata.version``.

    The real value is restored after the test, so other tests see the real version.
    """
    patcher = pytest.MonkeyPatch()

    def reload_with(replacement: Any) -> Any:
        patcher.setattr(importlib.metadata, "version", replacement)
        return importlib.reload(gemini_search_mcp)

    yield reload_with
    patcher.undo()
    importlib.reload(gemini_search_mcp)


async def _server_info(mode: str) -> Any:
    settings = Settings(gemini_api_key="fake-gemini-key-AIzaSyFAKE0123456789")
    server = build_server(settings, FakeProvider(), resolver=_identity_resolver)
    async with Client(server, mode=mode) as client:
        return client.server_info


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_reproduce_server_info_reports_package_version(mode: str) -> None:
    info = asyncio.run(_server_info(mode))

    assert info.name == SERVER_NAME == "gemini-search-mcp"
    assert info.version == importlib.metadata.version(DISTRIBUTION_NAME)


def test_ec3_missing_distribution_metadata_falls_back_to_unknown(reload_package: Any) -> None:
    def missing(name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(name)

    module = reload_package(missing)

    assert module.__version__ == "0+unknown"


def test_ec2_pre_release_version_is_passed_through_unchanged(reload_package: Any) -> None:
    module = reload_package(lambda name: "1.0.0rc1")

    assert module.__version__ == "1.0.0rc1"


def test_ec1_version_equals_project_version_from_pyproject() -> None:
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]

    assert gemini_search_mcp.__version__ == project["version"]
