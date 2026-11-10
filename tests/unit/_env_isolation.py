"""Helpers that isolate tests from ambient ``GEMINI_*``, ``MCP_*`` and ``LOG_*``.

``Settings`` reads the real process environment, so a leftover variable in CI
would change defaults. These helpers clear the whole configuration namespace
and install only the values a test intends to use. Values are dummy
placeholders, never real secrets.
"""

from collections.abc import Generator
from contextlib import contextmanager

import pytest

CONFIG_PREFIXES = ("GEMINI_", "MCP_", "LOG_")

# Dummy secrets for tests: long enough for the ADR 0010 length rule, clearly not real.
DUMMY_API_KEY = "dummy-test-api-key"

_backup: dict[str, str | None] = {}


def clear_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every configuration variable from the process environment."""
    import os

    for name in list(os.environ):
        if name.startswith(CONFIG_PREFIXES):
            monkeypatch.delenv(name, raising=False)


def _restore() -> None:
    import os

    for name, value in _backup.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    _backup.clear()


@contextmanager
def isolated_environment(**values: str) -> Generator[None]:
    """Run a block with only ``values`` present in the configuration namespace.

    Works for in-process calls to ``Settings`` and for subprocesses, which
    inherit ``os.environ``.
    """
    import os

    _backup.update(
        (name, os.environ.get(name)) for name in os.environ if name.startswith(CONFIG_PREFIXES)
    )
    for name in list(os.environ):
        if name.startswith(CONFIG_PREFIXES):
            del os.environ[name]
    os.environ.update(values)
    try:
        yield
    finally:
        for name in list(os.environ):
            if name.startswith(CONFIG_PREFIXES):
                del os.environ[name]
        _restore()
