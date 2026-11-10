"""The settings model, ADR 0010 and .env.example must name the same variables."""

import re
from pathlib import Path

import pytest

from gemini_search_mcp.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "docs" / "adr" / "0010-configuration.md"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
VARIABLE = re.compile(r"`([A-Z][A-Z0-9_]+)`")


def _settings_variables() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def _adr_table_variables() -> set[str]:
    rows = [line for line in ADR.read_text(encoding="utf-8").splitlines() if line.startswith("| `")]
    return {match.group(1) for line in rows if (match := VARIABLE.search(line))}


def _env_example_variables() -> set[str]:
    variables = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and not name.lstrip().startswith("#"):
            variables.add(name.strip())
            assert value.strip() == "", f"placeholder must stay empty: {name}"
    return variables


def test_settings_match_adr_0010_table() -> None:
    assert _settings_variables() == _adr_table_variables()


def test_env_example_matches_settings() -> None:
    assert _env_example_variables() == _settings_variables()


@pytest.mark.parametrize(
    ("variable", "default"),
    [
        ("gemini_model", "gemini-3.8-flash"),
        ("gemini_timeout_seconds", "`60`"),
        ("gemini_max_concurrency", "`4`"),
        ("gemini_max_retries", "`2`"),
        ("log_queries", "`false`"),
        ("log_level", "`info`"),
        ("mcp_transport", "`stdio`"),
        ("mcp_host", "`127.0.0.1`"),
        ("mcp_port", "`8000`"),
    ],
)
def test_adr_documents_the_model_defaults(variable: str, default: str) -> None:
    adr = ADR.read_text(encoding="utf-8")
    row = next(line for line in adr.splitlines() if line.startswith(f"| `{variable.upper()}`"))
    assert default in row
    assert str(Settings.model_fields[variable].default).lower() == default.strip("`")
