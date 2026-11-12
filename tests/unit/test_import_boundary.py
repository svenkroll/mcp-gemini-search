"""Import boundary check for ADR 0009 (issue #2, AC5).

The ADR 0009 table fixes which layer may import which module. This module
enforces it for every layer under ``src/gemini_search_mcp/``, whether the layer
is a single module file or a package directory, and for the package root
``__init__.py``. Layers that do not exist yet are skipped until a later issue
creates them, so the check grows with the code base. The synthetic cases below
prove that the check itself rejects forbidden imports.
"""

import ast
import sys
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "gemini_search_mcp"
INTERNAL_PACKAGE = "gemini_search_mcp"
ROOT_MODULE = "__init__"

# Third-party packages each layer may import, per the ADR 0009 module table.
ALLOWED_THIRD_PARTY: dict[str, frozenset[str]] = {
    "config": frozenset({"pydantic", "pydantic_settings"}),
    "provider": frozenset({"pydantic"}),
    "gemini_client": frozenset({"google"}),
    "urlpolicy": frozenset({"pydantic", "httpx"}),
    "tools": frozenset(),
    "server": frozenset({"fastmcp", "pydantic", "pydantic_settings", "httpx", "google"}),
    # The package root is not a layer: it may re-export the layers below it,
    # but it must not import a third-party package itself.
    ROOT_MODULE: frozenset(),
}

# Sibling modules each layer may import, per the ADR 0009 module table.
ALLOWED_INTERNAL: dict[str, frozenset[str]] = {
    "config": frozenset(),
    "provider": frozenset(),
    "gemini_client": frozenset({"provider", "config"}),
    "urlpolicy": frozenset(),
    "tools": frozenset({"provider", "urlpolicy", "config"}),
    "server": frozenset({"provider", "config", "gemini_client", "urlpolicy", "tools"}),
    ROOT_MODULE: frozenset({"config", "provider", "gemini_client", "urlpolicy", "tools", "server"}),
}

LAYER_MODULES = tuple(module for module in ALLOWED_THIRD_PARTY if module != ROOT_MODULE)


def _relative_modules(node: ast.ImportFrom, module_path: str, root: Path) -> set[str]:
    """Resolve a relative ``ImportFrom`` node to absolute module names.

    ``module_path`` is the dotted path of the importing file inside the
    package, e.g. ``provider``, ``tools.search`` or ``tools.__init__``. A name
    imported with ``from . import name`` counts as a module import only when
    the package really contains such a module.
    """
    package_parts = [INTERNAL_PACKAGE, *module_path.split(".")[:-1]]
    levels_up = node.level - 1
    if levels_up >= len(package_parts):
        target = node.module or ",".join(alias.name for alias in node.names)
        return {f"{'..' * node.level}{target}"}
    base_parts = package_parts[: len(package_parts) - levels_up]
    if node.module:
        return {".".join([*base_parts, node.module])}
    base_dir = root.joinpath(*base_parts[1:])
    resolved: set[str] = set()
    for alias in node.names:
        if (base_dir / f"{alias.name}.py").is_file() or (base_dir / alias.name).is_dir():
            resolved.add(".".join([*base_parts, alias.name]))
    return resolved


def _imported_modules(source: str, module_path: str, root: Path) -> set[str]:
    """Return the absolute modules imported by ``source``."""
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    imported.add(node.module)
            else:
                imported.update(_relative_modules(node, module_path, root))
    return imported


def _violations(
    layer: str,
    source: str,
    module_path: str | None = None,
    root: Path = SRC_ROOT,
) -> list[str]:
    """Return the imports of ``source`` that the ADR 0009 table forbids."""
    allowed_third_party = ALLOWED_THIRD_PARTY[layer]
    allowed_internal = ALLOWED_INTERNAL[layer]
    imported = _imported_modules(source, module_path or layer, root)
    violations: list[str] = []
    for module in sorted(imported):
        parts = module.split(".")
        root_name = parts[0]
        if root_name == INTERNAL_PACKAGE:
            sibling = parts[1] if len(parts) > 1 else ""
            if sibling == layer:
                # Imports that stay inside the layer's own package are fine.
                continue
            if sibling not in allowed_internal:
                violations.append(module)
        elif root_name in sys.stdlib_module_names or root_name in allowed_third_party:
            continue
        else:
            violations.append(module)
    return violations


def _layer_files(layer: str, root: Path = SRC_ROOT) -> list[Path]:
    """Return the source files of ``layer``, whether a module or a package."""
    module_file = root / f"{layer}.py"
    if module_file.is_file():
        return [module_file]
    package_dir = root / layer
    if package_dir.is_dir():
        return sorted(package_dir.rglob("*.py"))
    return []


def _existing_layer_modules(root: Path = SRC_ROOT) -> list[str]:
    """Return the layers that exist as a module file or a package directory."""
    return sorted(layer for layer in LAYER_MODULES if _layer_files(layer, root))


def _checked_sources(root: Path = SRC_ROOT) -> list[tuple[str, Path, str]]:
    """Return ``(layer, path, module_path)`` for every file the check covers."""
    sources: list[tuple[str, Path, str]] = []
    root_init = root / "__init__.py"
    if root_init.is_file():
        sources.append((ROOT_MODULE, root_init, ROOT_MODULE))
    for layer in _existing_layer_modules(root):
        for path in _layer_files(layer, root):
            module_path = path.relative_to(root).with_suffix("").as_posix().replace("/", ".")
            sources.append((layer, path, module_path))
    return sources


@pytest.mark.parametrize(
    ("layer", "path", "module_path"),
    _checked_sources(),
    ids=[
        f"{layer}:{path.relative_to(SRC_ROOT).as_posix()}" for layer, path, _ in _checked_sources()
    ],
)
def test_ac5_layer_modules_respect_the_adr_0009_import_table(
    layer: str,
    path: Path,
    module_path: str,
) -> None:
    source = path.read_text(encoding="utf-8")
    assert _violations(layer, source, module_path) == []


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


def test_f2_boundary_check_resolves_relative_imports_and_package_layers(tmp_path: Path) -> None:
    """F2: relative imports, layer packages and ``__init__.py`` are checked."""
    # A relative import inside the package is an internal sibling import and
    # must be checked against the table of the importing layer.
    assert _violations("provider", "from .config import Settings") == ["gemini_search_mcp.config"]
    assert _violations("provider", "from . import config") == ["gemini_search_mcp.config"]
    assert _violations("config", "from .provider import SearchProvider") == [
        "gemini_search_mcp.provider"
    ]
    assert _violations("config", "from . import provider") == ["gemini_search_mcp.provider"]

    # A layer that exists as a package is discovered with every module file,
    # including its ``__init__.py``; the package root ``__init__.py`` is part
    # of the checked set as well.
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "__init__.py").write_text(
        "from ..config import Settings\n",
        encoding="utf-8",
    )
    (tools_dir / "search.py").write_text(
        "from .models import SearchTool\nfrom ..gemini_client import GeminiProvider\n",
        encoding="utf-8",
    )
    (tmp_path / "__init__.py").write_text("import fastmcp\n", encoding="utf-8")

    found = {
        (layer, path.relative_to(tmp_path).as_posix()): _violations(
            layer,
            path.read_text(encoding="utf-8"),
            module_path,
            root=tmp_path,
        )
        for layer, path, module_path in _checked_sources(tmp_path)
    }
    assert found == {
        ("__init__", "__init__.py"): ["fastmcp"],
        ("tools", "tools/__init__.py"): [],
        ("tools", "tools/search.py"): ["gemini_search_mcp.gemini_client"],
    }
