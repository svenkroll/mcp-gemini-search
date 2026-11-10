"""Unit tests for the settings model from ADR 0010."""

import os
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import pytest

from gemini_search_mcp.config import (
    EXIT_CONFIG_ERROR,
    ConfigError,
    Settings,
    load_settings,
    load_settings_or_exit,
)

LONG_TOKEN = "t" * 32
SHORT_TOKEN = "t" * 31
SECRET_KEY = "api-key-value-that-must-not-leak"  # noqa: S105 - fixture, not a credential
SECRET_TOKEN = "bearer-token-value-that-must-not-leak"  # noqa: S105 - fixture, not a credential

REPO_ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def environment(**values: str) -> Generator[None]:
    """Replace the process environment for the duration of the block."""
    with pytest.MonkeyPatch.context() as patch:
        for key in list(os.environ):
            patch.delenv(key, raising=False)
        for key, value in values.items():
            patch.setenv(key, value)
        yield


# (variable, valid lower bound, valid upper bound, invalid values below/above, rule)
LIMITS = [
    ("GEMINI_TIMEOUT_SECONDS", "1", "300", ["0", "301", "-1"], "must be between 1 and 300"),
    ("GEMINI_MAX_CONCURRENCY", "1", "32", ["0", "33", "-1"], "must be between 1 and 32"),
    ("GEMINI_MAX_RETRIES", "0", "5", ["-1", "6"], "must be between 0 and 5"),
    ("MCP_PORT", "1", "65535", ["0", "65536", "-1"], "must be between 1 and 65535"),
]


def test_all_defaults_from_the_adr() -> None:
    with environment(GEMINI_API_KEY=SECRET_KEY):
        settings = load_settings()
    assert settings.gemini_model == "gemini-3.8-flash"
    assert settings.gemini_timeout_seconds == 60
    assert settings.gemini_max_concurrency == 4
    assert settings.gemini_max_retries == 2
    assert settings.log_queries is False
    assert settings.log_level == "info"
    assert settings.mcp_transport == "stdio"
    assert settings.mcp_host == "127.0.0.1"
    assert settings.mcp_port == 8000
    assert settings.mcp_bearer_token is None


def test_settings_can_be_built_without_environment() -> None:
    settings = Settings(gemini_api_key=SECRET_KEY)
    assert settings.gemini_timeout_seconds == 60


def test_model_and_host_are_read_from_the_environment() -> None:
    with environment(
        GEMINI_API_KEY=SECRET_KEY,
        GEMINI_MODEL="gemini-test",
        MCP_HOST="0.0.0.0",  # noqa: S104 - value under test, never bound
        LOG_QUERIES="true",
        LOG_LEVEL="debug",
    ):
        settings = load_settings()
    assert settings.gemini_model == "gemini-test"
    assert settings.mcp_host == "0.0.0.0"  # noqa: S104
    assert settings.log_queries is True
    assert settings.log_level == "debug"


@pytest.mark.parametrize(("variable", "low", "high", "invalid", "rule"), LIMITS)
def test_limit_accepts_both_boundaries(
    variable: str, low: str, high: str, invalid: list[str], rule: str
) -> None:
    del invalid, rule
    for value in (low, high):
        with environment(GEMINI_API_KEY=SECRET_KEY, **{variable: value}):
            assert load_settings() is not None


@pytest.mark.parametrize(("variable", "low", "high", "invalid", "rule"), LIMITS)
def test_limit_rejects_values_outside_the_rule(
    variable: str, low: str, high: str, invalid: list[str], rule: str
) -> None:
    del low, high
    for value in invalid:
        with (
            environment(GEMINI_API_KEY=SECRET_KEY, **{variable: value}),
            pytest.raises(ConfigError) as excinfo,
        ):
            load_settings()
        assert excinfo.value.variable == variable
        assert excinfo.value.rule == rule
        assert variable in str(excinfo.value)
        assert f"got {value}" not in str(excinfo.value)


@pytest.mark.parametrize("value", ["trace", "INFO", "", "critical"])
def test_log_level_rule(value: str) -> None:
    with (
        environment(GEMINI_API_KEY=SECRET_KEY, LOG_LEVEL=value),
        pytest.raises(ConfigError) as excinfo,
    ):
        load_settings()
    assert excinfo.value.variable == "LOG_LEVEL"
    assert excinfo.value.rule == "must be one of debug, info, warning, error"


def test_log_queries_rule() -> None:
    with (
        environment(GEMINI_API_KEY=SECRET_KEY, LOG_QUERIES="maybe"),
        pytest.raises(ConfigError) as excinfo,
    ):
        load_settings()
    assert excinfo.value.variable == "LOG_QUERIES"
    assert excinfo.value.rule == "must be a boolean"


def test_mcp_transport_rule() -> None:
    with (
        environment(GEMINI_API_KEY=SECRET_KEY, MCP_TRANSPORT="websocket"),
        pytest.raises(ConfigError) as excinfo,
    ):
        load_settings()
    assert excinfo.value.variable == "MCP_TRANSPORT"
    assert excinfo.value.rule == "must be one of stdio, http"


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_gemini_api_key_is_rejected(value: str) -> None:
    with environment(GEMINI_API_KEY=value), pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert excinfo.value.variable == "GEMINI_API_KEY"
    assert excinfo.value.rule == "must be set and not empty"


def test_missing_gemini_api_key_names_the_variable() -> None:
    with environment(), pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert excinfo.value.variable == "GEMINI_API_KEY"
    assert str(excinfo.value) == "Invalid configuration: GEMINI_API_KEY must be set and not empty."


def test_empty_gemini_model_is_rejected() -> None:
    with (
        environment(GEMINI_API_KEY=SECRET_KEY, GEMINI_MODEL="  "),
        pytest.raises(ConfigError) as excinfo,
    ):
        load_settings()
    assert excinfo.value.variable == "GEMINI_MODEL"
    assert excinfo.value.rule == "must not be empty"


def test_http_without_bearer_token_is_rejected() -> None:
    with (
        environment(GEMINI_API_KEY=SECRET_KEY, MCP_TRANSPORT="http"),
        pytest.raises(ConfigError) as excinfo,
    ):
        load_settings()
    assert excinfo.value.variable == "MCP_BEARER_TOKEN"


@pytest.mark.parametrize("value", ["", SHORT_TOKEN])
def test_http_with_too_short_bearer_token_is_rejected(value: str) -> None:
    with (
        environment(GEMINI_API_KEY=SECRET_KEY, MCP_TRANSPORT="http", MCP_BEARER_TOKEN=value),
        pytest.raises(ConfigError) as excinfo,
    ):
        load_settings()
    assert excinfo.value.variable == "MCP_BEARER_TOKEN"
    assert "at least 32 characters" in str(excinfo.value)


def test_http_with_valid_bearer_token_is_accepted() -> None:
    with environment(GEMINI_API_KEY=SECRET_KEY, MCP_TRANSPORT="http", MCP_BEARER_TOKEN=LONG_TOKEN):
        settings = load_settings()
    assert settings.mcp_transport == "http"
    assert settings.mcp_bearer_token is not None
    assert settings.mcp_bearer_token.get_secret_value() == LONG_TOKEN


def test_short_bearer_token_is_ignored_for_stdio() -> None:
    with environment(GEMINI_API_KEY=SECRET_KEY, MCP_BEARER_TOKEN=SHORT_TOKEN):
        assert load_settings().mcp_transport == "stdio"


def test_secrets_do_not_appear_in_repr_or_str() -> None:
    with environment(
        GEMINI_API_KEY=SECRET_KEY,
        MCP_TRANSPORT="http",
        MCP_BEARER_TOKEN=SECRET_TOKEN,
    ):
        settings = load_settings()
    for representation in (repr(settings), str(settings)):
        assert SECRET_KEY not in representation
        assert SECRET_TOKEN not in representation
    assert SECRET_KEY not in repr(settings.gemini_api_key)
    assert SECRET_TOKEN not in repr(settings.mcp_bearer_token)


def test_errors_never_contain_values() -> None:
    with (
        environment(GEMINI_API_KEY=SECRET_KEY, MCP_TRANSPORT="http", MCP_BEARER_TOKEN=SHORT_TOKEN),
        pytest.raises(ConfigError) as excinfo,
    ):
        load_settings()
    assert SHORT_TOKEN not in str(excinfo.value)
    assert SECRET_KEY not in str(excinfo.value)


def test_load_settings_or_exit_returns_settings_when_valid() -> None:
    with environment(GEMINI_API_KEY=SECRET_KEY):
        assert load_settings_or_exit().gemini_model == "gemini-3.8-flash"


@pytest.mark.parametrize(
    ("env", "variable"),
    [
        ({}, "GEMINI_API_KEY"),
        ({"GEMINI_API_KEY": ""}, "GEMINI_API_KEY"),
        ({"GEMINI_API_KEY": SECRET_KEY, "MCP_TRANSPORT": "http"}, "MCP_BEARER_TOKEN"),
        (
            {
                "GEMINI_API_KEY": SECRET_KEY,
                "MCP_TRANSPORT": "http",
                "MCP_BEARER_TOKEN": SHORT_TOKEN,
            },
            "MCP_BEARER_TOKEN",
        ),
    ],
)
def test_load_settings_or_exit_exits_with_code_2(
    env: dict[str, str], variable: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with environment(**env), pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == EXIT_CONFIG_ERROR == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert variable in captured.err
    assert SECRET_KEY not in captured.err
    assert SHORT_TOKEN not in captured.err


def test_process_exits_with_code_2_without_api_key() -> None:
    env = {key: value for key, value in os.environ.items() if key != "GEMINI_API_KEY"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from gemini_search_mcp.config import load_settings_or_exit;load_settings_or_exit()",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        check=False,
    )
    assert result.returncode == 2
    assert "GEMINI_API_KEY" in result.stderr
    assert result.stdout == ""
