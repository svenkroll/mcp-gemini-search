"""Import boundary checks from the module table in ADR 0009.

The module table is encoded below and checked with the AST, so no import is
executed. Modules that do not exist yet are skipped; the test grows as later
issues add modules. Synthetic cases prove the checker rejects a
``provider`` module that imports ``fastmcp`` or ``google.genai``.
"""

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = "gemini_search_mcp"
PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / PACKAGE

# ADR 0009: module -> modules (and, for stdlib, package groups) it may import.
# Self-imports are always allowed and listed here for completeness.
# pydantic is part of pydantic-settings, so config may use both; fakes is the
# test double of the provider interface and therefore sits at the same layer.
ALLOWED_IMPORTS: dict[str, frozenset[str]] = {
    "config": frozenset({"stdlib", "pydantic_settings", "pydantic"}),
    "provider": frozenset({"stdlib", "pydantic"}),
    "fakes": frozenset({"stdlib", "pydantic", "provider"}),
    "gemini_client": frozenset({"stdlib", "provider", "config", "google.genai"}),
    "urlpolicy": frozenset({"stdlib", "pydantic", "httpx"}),
    "tools": frozenset({"stdlib", "provider", "urlpolicy", "config"}),
    "server": frozenset(
        {"stdlib", "config", "provider", "gemini_client", "urlpolicy", "tools", "fastmcp"}
    ),
}

# The package root re-exports its version only; it stays free of imports
# outside the standard library.
PACKAGE_ROOT_ALLOWED: frozenset[str] = frozenset({"stdlib"})

STDLIB_MODULES = frozenset(sys.stdlib_module_names)


def _imported_modules(tree: ast.AST) -> set[str]:
    """Return top-level module names imported as third-party or first-party."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _classify(module_name: str) -> tuple[str, str]:
    """Return (category, name) for a top-level module name."""
    top = module_name.split(".", 1)[0]
    if top == PACKAGE:
        # gemini_search_mcp.tools -> sibling module "tools"
        parts = module_name.split(".")
        sibling = parts[1] if len(parts) > 1 else ""
        return "sibling", sibling
    if top in STDLIB_MODULES:
        return "stdlib", top
    return "external", top


def find_boundary_violations(source: str, module: str) -> list[str]:
    """Return human-readable violations of ADR 0009 for ``source`` of ``module``."""
    allowed = ALLOWED_IMPORTS[module]
    violations: list[str] = []
    for imported in sorted(_imported_modules(ast.parse(source))):
        category, name = _classify(imported)
        if category == "stdlib" and "stdlib" in allowed:
            continue
        if category == "sibling" and name in allowed:
            continue
        if category == "external" and imported.split(".", 1)[0] in {
            item.split(".", 1)[0] for item in allowed
        }:
            continue
        violations.append(f"{module} must not import {imported}")
    return violations


def test_module_table_matches_package() -> None:
    existing = {path.stem for path in PACKAGE_DIR.glob("*.py")}
    unknown = existing - set(ALLOWED_IMPORTS) - {"__init__"}
    assert not unknown, f"modules without an ADR 0009 entry: {sorted(unknown)}"


def test_package_root_respects_import_boundary() -> None:
    source = (PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8")
    violations = [
        f"__init__ must not import {imported}"
        for imported in sorted(_imported_modules(ast.parse(source)))
        if _classify(imported)[0] != "stdlib"
    ]
    assert {"stdlib"} == PACKAGE_ROOT_ALLOWED
    assert violations == []


@pytest.mark.parametrize("module", sorted(ALLOWED_IMPORTS))
def test_module_respects_import_boundary(module: str) -> None:
    path = PACKAGE_DIR / f"{module}.py"
    if not path.is_file():
        pytest.skip(f"{module} does not exist yet")
    assert find_boundary_violations(path.read_text(encoding="utf-8"), module) == []


@pytest.mark.parametrize(
    "source",
    [
        "import fastmcp\n",
        "from fastmcp import FastMCP\n",
        "import google.genai\n",
        "from google import genai\n",
        "from google.genai import types\n",
    ],
    ids=[
        "fastmcp-import",
        "fastmcp-from",
        "google-genai-import",
        "google-from",
        "google-genai-from",
    ],
)
def test_provider_rejects_outer_layer_imports(source: str) -> None:
    violations = find_boundary_violations(source, "provider")
    assert violations, f"expected a violation for synthetic source: {source!r}"


def test_provider_accepts_allowed_imports() -> None:
    source = "import dataclasses\nfrom typing import Protocol\nfrom pydantic import BaseModel\n"
    assert find_boundary_violations(source, "provider") == []


def test_import_boundary_allows_own_package_modules() -> None:
    source = "from gemini_search_mcp.provider import SearchResult\n"
    assert find_boundary_violations(source, "tools") == []
