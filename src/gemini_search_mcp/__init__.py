"""Gemini Search MCP package.

Placeholder package created by issue #1. It intentionally contains no tool,
provider or server behaviour. Modules are added by later issues.
"""

import importlib.metadata

DISTRIBUTION_NAME = "gemini-search-mcp"
UNKNOWN_VERSION = "0+unknown"


def _resolve_version() -> str:
    """Return the installed distribution version, the only source of the project version.

    Falls back to ``0+unknown`` when the distribution metadata is missing, for
    example when ``src/`` is on ``PYTHONPATH`` without an install.
    """
    try:
        return importlib.metadata.version(DISTRIBUTION_NAME)
    except importlib.metadata.PackageNotFoundError:
        return UNKNOWN_VERSION


__version__ = _resolve_version()
PACKAGE_NAME = "gemini_search_mcp"
