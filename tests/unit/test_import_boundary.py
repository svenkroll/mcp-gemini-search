"""Import boundary check for ADR 0009 (issue #2, AC5).

The ADR 0009 table fixes which layer may import which module. This module
enforces it for every layer module under ``src/gemini_search_mcp/``. Layers
that do not exist yet are skipped until a later issue creates them, so the
check grows with the code base. The synthetic cases below prove that the check
itself rejects forbidden imports.
"""

import ast
import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "gemini_search_mcp"
INTERNAL_PACKAGE = "gemini_search_mcp"

# Third-party packages each layer may import, per the ADR 0009 module table.
ALLOWED_THIRD_PARTY: dict[str, frozenset[str]] = {
    "config": frozenset({"pydantic", "pydantic_settings"}),
    "provider": frozenset({"pydantic"}),
    "gemini_client": frozenset({"google"}),
    "urlpolicy": frozenset({"pydantic", "httpx"}),
    "tools": frozenset(),
    "server": frozenset({"fastmcp", "pydantic", "pydantic_settings", "httpx", "google"}),
}

# Sibling modules each layer may import, per the ADR 0009 module table.
ALLOWED_INTERNAL: dict[str, frozenset[str]] = {
    "config": frozenset(),
    "provider": frozenset(),
    "gemini_client": frozenset({"provider", "config"}),
    "urlpolicy": frozenset(),
    "tools": frozenset({"provider", "urlpolicy", "config"}),
    "server": frozenset({"provider", "config", "gemini_client", "urlpolicy", "tools"}),
}


def _imported_modules(source: str) -> set[str]:
    """Return the absolute modules imported by ``source``.

    Relative imports stay inside the package and are not reported here.
    """
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module)
    return imported


def _violations(module: str, source: str) -> list[str]:
    """Return the imports of ``source`` that the ADR 0009 table forbids."""
    allowed_third_party = ALLOWED_THIRD_PARTY[module]
    allowed_internal = ALLOWED_INTERNAL[module]
    violations: list[str] = []
    for imported in sorted(_imported_modules(source)):
        parts = imported.split(".")
        root = parts[0]
        if root == INTERNAL_PACKAGE:
            sibling = parts[1] if len(parts) > 1 else ""
            if sibling not in allowed_internal:
                violations.append(imported)
        elif root in sys.stdlib_module_names or root in allowed_third_party:
            continue
        else:
            violations.append(imported)
    return violations


def _existing_layer_modules() -> list[str]:
    return sorted(module for module in ALLOWED_THIRD_PARTY if (SRC_ROOT / f"{module}.py").is_file())


@pytest.mark.parametrize("module", _existing_layer_modules())
def test_ac5_layer_modules_respect_the_adr_0009_import_table(module: str) -> None:
    source = (SRC_ROOT / f"{module}.py").read_text(encoding="utf-8")
    assert _violations(module, source) == []


@pytest.mark.parametrize(
    ("import_line", "expected"),
    [
        ("import fastmcp", ["fastmcp"]),
        ("from fastmcp import FastMCP", ["fastmcp"]),
        ("import google.genai", ["google.genai"]),
        ("from google.genai import types", ["google.genai"]),
    ],
)
def test_ac5_provider_boundary_rejects_fastmcp_and_gemini_sdk(
    import_line: str,
    expected: list[str],
) -> None:
    source = f'"""Synthetic provider source."""\n{import_line}\n'
    assert _violations("provider", source) == expected
