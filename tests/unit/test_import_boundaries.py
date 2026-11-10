"""Import boundary test for the layers from ADR 0009.

The table below encodes which top-level packages each module under
``src/gemini_search_mcp/`` may import. Modules that do not exist yet are
skipped, so the test grows with later issues.
"""

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "gemini_search_mcp"
PACKAGE = "gemini_search_mcp"

# ADR 0009 module table: module -> allowed third-party and sibling imports. The
# standard library is allowed everywhere and therefore not listed.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "config": frozenset({"pydantic", "pydantic_settings"}),
    "provider": frozenset({"pydantic"}),
    "gemini_client": frozenset({"provider", "config", "google"}),
    "urlpolicy": frozenset({"pydantic", "httpx"}),
    "tools": frozenset({"provider", "urlpolicy", "config"}),
    "server": frozenset({"provider", "config", "gemini_client", "urlpolicy", "tools", "fastmcp"}),
}

# Only the server may import FastMCP, and only the adapter may import the
# Gemini SDK. Checked as an explicit rule on top of the table.
FORBIDDEN_FOR_ALL_OTHERS = frozenset({"fastmcp", "google"})


def _top_level(name: str) -> str:
    return name.split(".", 1)[0]


def _is_standard_library(module: str) -> bool:
    return module in sys.stdlib_module_names


def imported_modules(source: str) -> Iterator[str]:
    """Yield every module name imported by ``source``, including relative imports."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield "." * node.level + (node.module or "")
            elif node.module:
                yield node.module


def violations(module: str, source: str) -> list[str]:
    """Return the imports of ``source`` that the ADR 0009 table forbids for ``module``."""
    allowed = ALLOWED_IMPORTS.get(module, frozenset())
    found: list[str] = []
    for imported in imported_modules(source):
        top = _top_level(imported)
        if top == PACKAGE:
            parts = imported.split(".")
            sibling = parts[1] if len(parts) > 1 else ""
            if sibling in ALLOWED_IMPORTS and sibling not in allowed and sibling != module:
                found.append(f"{imported} (imports {sibling}, which is not allowed)")
        elif _is_standard_library(top):
            continue
        elif (top in FORBIDDEN_FOR_ALL_OTHERS and top not in allowed) or top not in allowed:
            found.append(imported)
    return found


def _existing_modules() -> list[str]:
    return sorted(path.stem for path in SOURCE_ROOT.glob("*.py") if path.stem in ALLOWED_IMPORTS)


def test_import_table_covers_every_existing_layered_module() -> None:
    layered = _existing_modules()
    assert {"config", "provider"} <= set(layered)
    assert "fakes" not in ALLOWED_IMPORTS


@pytest.mark.parametrize("module", _existing_modules())
def test_module_respects_import_boundaries(module: str) -> None:
    source = (SOURCE_ROOT / f"{module}.py").read_text(encoding="utf-8")
    assert violations(module, source) == []


@pytest.mark.parametrize(
    ("module", "source", "forbidden"),
    [
        ("provider", "import fastmcp\n", "fastmcp"),
        ("provider", "from fastmcp import FastMCP\n", "fastmcp"),
        ("provider", "import google.genai\n", "google.genai"),
        ("provider", "from google import genai\n", "google"),
        ("provider", "from google.genai import types\n", "google.genai"),
        ("provider", "import httpx\n", "httpx"),
        ("provider", "from gemini_search_mcp.config import Settings\n", "config"),
        ("config", "from gemini_search_mcp.provider import SearchProvider\n", "provider"),
        ("config", "import fastmcp\n", "fastmcp"),
        ("provider", "from gemini_search_mcp.gemini_client import GeminiClient\n", "gemini_client"),
        ("urlpolicy", "import google.genai\n", "google.genai"),
        ("tools", "from gemini_search_mcp.server import create_server\n", "server"),
        ("gemini_client", "import fastmcp\n", "fastmcp"),
        ("server", "import google.genai\n", "google.genai"),
    ],
)
def test_rule_fails_on_synthetic_violating_source(module: str, source: str, forbidden: str) -> None:
    found = violations(module, source)
    assert found, f"expected {module} importing {forbidden} to be rejected"
    assert any(forbidden in item for item in found)


@pytest.mark.parametrize(
    ("module", "source"),
    [
        ("provider", "from dataclasses import dataclass\nfrom typing import Protocol\n"),
        ("provider", "import pydantic\n"),
        ("config", "from pydantic_settings import BaseSettings\n"),
        ("gemini_client", "import google.genai\nfrom gemini_search_mcp.config import Settings\n"),
        ("gemini_client", "from gemini_search_mcp.provider import SearchProvider\n"),
        ("urlpolicy", "import httpx\nimport pydantic\n"),
        (
            "tools",
            "from gemini_search_mcp.provider import SearchProvider\n"
            "from gemini_search_mcp.urlpolicy import check_url\n"
            "from gemini_search_mcp.config import Settings\n",
        ),
        ("server", "import fastmcp\nfrom gemini_search_mcp.tools import search\n"),
    ],
)
def test_rule_accepts_allowed_source(module: str, source: str) -> None:
    assert violations(module, source) == []


def test_rule_detects_relative_import_of_foreign_sibling() -> None:
    assert violations("provider", "from .gemini_client import GeminiClient\n")


def test_boundary_constants() -> None:
    assert _top_level("google.genai") == "google"
    assert list(imported_modules("import a.b\nfrom c import d\n")) == ["a.b", "c"]


# --- Additional coverage: AC5 synthetic cases for provider.py and fakes ---


@pytest.mark.parametrize(
    ("source", "forbidden"),
    [
        ("import fastmcp", "fastmcp"),
        ("import fastmcp as fm", "fastmcp"),
        ("from fastmcp import FastMCP", "fastmcp"),
        ("import google.genai", "google.genai"),
        ("import google.genai as genai", "google.genai"),
        ("from google import genai", "google"),
        ("from google.genai import types", "google.genai"),
        ("if True:\n    import fastmcp\n", "fastmcp"),
        ("def load() -> None:\n    from google.genai import types\n", "google.genai"),
    ],
)
def test_provider_synthetic_source_with_fastmcp_or_gemini_is_a_violation(
    source: str, forbidden: str
) -> None:
    found = violations("provider", source)
    assert found, f"provider must not import {forbidden}: {source!r}"
    assert any(forbidden in item for item in found)


def test_provider_synthetic_violation_in_a_larger_module_is_detected() -> None:
    source = (
        "from dataclasses import dataclass\n"
        "from typing import Protocol\n"
        "import fastmcp\n"
        "from google.genai import types\n"
        "\n"
        "class SearchProvider(Protocol): ...\n"
    )
    found = violations("provider", source)
    assert any("fastmcp" in item for item in found)
    assert any("google.genai" in item for item in found)


def test_existing_provider_module_has_no_such_imports() -> None:
    source = (SOURCE_ROOT / "provider.py").read_text(encoding="utf-8")
    assert violations("provider", source) == []
    assert "fastmcp" not in source
    assert "google" not in source


@pytest.mark.parametrize("module", ["config", "provider", "gemini_client", "urlpolicy", "tools"])
def test_fastmcp_is_a_violation_outside_the_server(module: str) -> None:
    assert any("fastmcp" in item for item in violations(module, "import fastmcp\n"))


def test_server_may_import_fastmcp() -> None:
    assert violations("server", "import fastmcp\n") == []


def test_fakes_module_is_not_bound_to_the_gemini_sdk_or_fastmcp() -> None:
    # ``fakes`` is test support, not a layer with a row in ADR 0009, so the
    # table helper does not police it. It must still stay on the domain
    # provider and the standard library.
    assert "fakes" not in ALLOWED_IMPORTS
    source = (SOURCE_ROOT / "fakes.py").read_text(encoding="utf-8")
    imported = {_top_level(name) for name in imported_modules(source)}
    assert "fastmcp" not in imported
    assert "google" not in imported
    allowed = (sys.stdlib_module_names | {PACKAGE}) - {"fastmcp", "google"}
    assert imported <= allowed
