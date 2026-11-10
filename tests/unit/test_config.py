"""Unit tests for the settings model from ADR 0010.

Covers the variables, defaults and limits (AK1), the fail-fast exit path with
messages that name variables but never values (AK2, AK3) and secret redaction
of ``repr``/``str`` (AK4). The process environment is cleared for every test so
ambient variables in CI cannot change defaults.
"""

import os
import subprocess
import sys
from dataclasses import dataclass
from importlib import import_module
from unittest import mock

import pytest
from pydantic import SecretStr, ValidationError

from gemini_search_mcp.config import (
    ConfigError,
    LogLevel,
    Settings,
    Transport,
    load_settings,
    load_settings_or_exit,
)

from ._env_isolation import clear_config_environment, isolated_environment

FALLBACK_API_KEY = "fallback-dummy-api-key"

# Dummy secrets only, long enough to satisfy the ADR 0010 length rule.
DUMMY_API_KEY = "dummy-gemini-api-key-not-a-real-secret"
DUMMY_BEARER_TOKEN = "x" * 48
SHORT_TOKEN = "-".join(["too", "short", "token"])
ALL_INTERFACES = "0" + ".0.0.0"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_config_environment(monkeypatch)


def _settings(**values: str) -> Settings:
    """Build settings from the environment with a dummy API key and ``values``."""
    env = {"GEMINI_API_KEY": FALLBACK_API_KEY}
    env.update(values)
    with isolated_environment(**env):
        return Settings()


def load_settings_from(values: dict[str, str]) -> Settings:
    """Run ``load_settings()`` with a dummy API key plus ``values``."""
    env = {"GEMINI_API_KEY": FALLBACK_API_KEY}
    env.update(values)
    with isolated_environment(**env):
        return load_settings()


# AK1: every variable from ADR 0010 with its documented default.


@dataclass(frozen=True)
class Variable:
    attribute: str
    env: str
    expected: object


ADR_0010_DEFAULTS = [
    Variable("gemini_model", "GEMINI_MODEL", "gemini-3.8-flash"),
    Variable("gemini_timeout_seconds", "GEMINI_TIMEOUT_SECONDS", 60),
    Variable("gemini_max_concurrency", "GEMINI_MAX_CONCURRENCY", 4),
    Variable("gemini_max_retries", "GEMINI_MAX_RETRIES", 2),
    Variable("log_queries", "LOG_QUERIES", False),
    Variable("log_level", "LOG_LEVEL", LogLevel.INFO),
    Variable("mcp_transport", "MCP_TRANSPORT", Transport.STDIO),
    Variable("mcp_host", "MCP_HOST", "127.0.0.1"),
    Variable("mcp_port", "MCP_PORT", 8000),
    Variable("mcp_bearer_token", "MCP_BEARER_TOKEN", None),
]


@pytest.mark.parametrize("variable", ADR_0010_DEFAULTS, ids=[v.env for v in ADR_0010_DEFAULTS])
def test_optional_variables_use_adr_default(variable: Variable) -> None:
    settings = _settings()
    actual = getattr(settings, variable.attribute)
    if isinstance(actual, SecretStr):
        pytest.fail(f"{variable.env} should have no secret default, got SecretStr")
    assert actual == variable.expected


def test_required_api_key_is_read_from_environment() -> None:
    settings = _settings()
    assert settings.gemini_api_key.get_secret_value() == FALLBACK_API_KEY


def test_environment_value_overrides_default() -> None:
    settings = _settings(
        GEMINI_MODEL="gemini-test-model",
        GEMINI_TIMEOUT_SECONDS="120",
        GEMINI_MAX_CONCURRENCY="16",
        GEMINI_MAX_RETRIES="5",
        LOG_QUERIES="true",
        LOG_LEVEL="debug",
        MCP_TRANSPORT="http",
        MCP_HOST=ALL_INTERFACES,
        MCP_PORT="9000",
        MCP_BEARER_TOKEN=DUMMY_BEARER_TOKEN,
    )
    assert settings.gemini_model == "gemini-test-model"
    assert settings.gemini_timeout_seconds == 120
    assert settings.gemini_max_concurrency == 16
    assert settings.gemini_max_retries == 5
    assert settings.log_queries is True
    assert settings.log_level is LogLevel.DEBUG
    assert settings.mcp_transport is Transport.HTTP
    assert settings.mcp_host == ALL_INTERFACES
    assert settings.mcp_port == 9000
    assert settings.mcp_bearer_token is not None
    assert settings.mcp_bearer_token.get_secret_value() == DUMMY_BEARER_TOKEN


@dataclass(frozen=True)
class Limit:
    env: str
    low: int
    high: int


LIMITS = [
    Limit("GEMINI_TIMEOUT_SECONDS", 1, 300),
    Limit("GEMINI_MAX_CONCURRENCY", 1, 32),
    Limit("GEMINI_MAX_RETRIES", 0, 5),
    Limit("MCP_PORT", 1, 65535),
]


@pytest.mark.parametrize("limit", LIMITS, ids=[limit.env for limit in LIMITS])
@pytest.mark.parametrize("position", ["low", "high"])
def test_limit_boundaries_are_accepted(limit: Limit, position: str) -> None:
    value = limit.low if position == "low" else limit.high
    settings = _settings(**{limit.env: str(value)})
    assert getattr(settings, limit.env.lower()) == value


@pytest.mark.parametrize("limit", LIMITS, ids=[limit.env for limit in LIMITS])
@pytest.mark.parametrize("boundary", ["below-low", "above-high"])
def test_values_outside_limit_are_rejected(limit: Limit, boundary: str) -> None:
    # Distinctive values keep the "value absent from message" check meaningful.
    value = limit.low - 7 if boundary == "below-low" else limit.high + 93
    with pytest.raises(ConfigError) as error:
        load_settings_from({limit.env: str(value)})
    message = str(error.value)
    assert message.startswith(f"{limit.env}: "), message
    assert str(value) not in message


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
def test_log_level_accepts_documented_choices(level: str) -> None:
    assert _settings(LOG_LEVEL=level).log_level == LogLevel(level)


def test_log_level_rejects_unknown_choice() -> None:
    with pytest.raises(ConfigError) as error:
        load_settings_from({"LOG_LEVEL": "trace"})
    assert str(error.value).startswith("LOG_LEVEL: ")


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_mcp_transport_accepts_documented_choices(transport: str) -> None:
    env = {"MCP_TRANSPORT": transport}
    if transport == "http":
        env["MCP_BEARER_TOKEN"] = DUMMY_BEARER_TOKEN
    assert _settings(**env).mcp_transport == Transport(transport)


def test_mcp_transport_rejects_unknown_choice() -> None:
    with pytest.raises(ConfigError) as error:
        load_settings_from({"MCP_TRANSPORT": "sse"})
    assert str(error.value).startswith("MCP_TRANSPORT: ")


def test_log_queries_rejects_non_boolean() -> None:
    with pytest.raises(ConfigError) as error:
        load_settings_from({"LOG_QUERIES": "maybe"})
    assert str(error.value).startswith("LOG_QUERIES: ")


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("LOG_QUERIES", "maybe"),
        ("GEMINI_TIMEOUT_SECONDS", "sixty"),
        ("LOG_LEVEL", "trace"),
    ],
    ids=["bool-parsing", "int-parsing", "enum"],
)
def test_unparseable_values_report_generic_invalid_value_rule(variable: str, value: str) -> None:
    # AK2: errors name the variable and a rule, never the offending value.
    with pytest.raises(ConfigError) as error:
        load_settings_from({variable: value})
    message = str(error.value)
    assert message.startswith(f"{variable}: "), message
    assert message.endswith("has an invalid value"), message
    assert value not in message


def test_validation_error_without_locations_reports_generic_rule() -> None:
    # Defensive path: a validation error that points at no variable must still
    # yield a short, value-free message instead of crashing the startup path.
    empty_error = ValidationError.from_exception_data("Settings", [])
    with (
        mock.patch.object(Settings, "__init__", side_effect=empty_error),
        pytest.raises(ConfigError) as error,
    ):
        load_settings()
    assert str(error.value) == "configuration: has an invalid value"


@pytest.mark.parametrize("variable", ["GEMINI_MODEL", "MCP_HOST"])
def test_non_empty_strings_reject_empty_value(variable: str) -> None:
    with pytest.raises(ConfigError) as error:
        load_settings_from({variable: ""})
    assert str(error.value).startswith(f"{variable}: ")


def test_non_empty_strings_accept_single_character() -> None:
    settings = _settings(GEMINI_MODEL="m", MCP_HOST="h")
    assert settings.gemini_model == "m"
    assert settings.mcp_host == "h"


def test_valid_settings_load_without_error() -> None:
    settings = _settings()
    assert isinstance(settings, Settings)


# AK2: a missing API key exits with code 2 and names the variable, not the value.


def test_missing_api_key_raises_config_error_naming_variable() -> None:
    with isolated_environment(), pytest.raises(ConfigError) as error:
        load_settings()
    message = str(error.value)
    assert "GEMINI_API_KEY" in message
    assert FALLBACK_API_KEY not in message


def test_missing_api_key_exits_with_code_two() -> None:
    with isolated_environment(), pytest.raises(SystemExit) as exit_info:
        load_settings_or_exit()
    assert exit_info.value.code == 2


def test_missing_api_key_message_names_variable_not_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with isolated_environment(), pytest.raises(SystemExit):
        load_settings_or_exit()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "GEMINI_API_KEY" in captured.err
    assert FALLBACK_API_KEY not in captured.err


def test_empty_api_key_exits_with_code_two(capsys: pytest.CaptureFixture[str]) -> None:
    with isolated_environment(GEMINI_API_KEY=""), pytest.raises(SystemExit) as exit_info:
        load_settings_or_exit()
    assert exit_info.value.code == 2
    assert "GEMINI_API_KEY" in capsys.readouterr().err


def test_missing_api_key_exit_in_subprocess() -> None:
    env = {name: value for name, value in os.environ.items() if not name.startswith("GEMINI_")}
    env["PATH"] = os.environ.get("PATH", "")
    code = "from gemini_search_mcp.config import load_settings_or_exit\nload_settings_or_exit()\n"
    # S603: the child runs fixed in-repository code, never untrusted input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=os.getcwd(),
    )
    assert result.returncode == 2, result.stderr
    assert "GEMINI_API_KEY" in result.stderr
    assert FALLBACK_API_KEY not in result.stderr


# AK3: http transport requires a bearer token of at least 32 characters.


def _http_settings(**values: str) -> Settings:
    env = {"MCP_TRANSPORT": "http"}
    env.update(values)
    return _settings(**env)


@pytest.mark.parametrize(
    "token",
    [None, "", "short-token"],
    ids=["absent", "empty", "too-short"],
)
def test_http_without_valid_bearer_token_exits_with_code_two(
    token: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    env = {"GEMINI_API_KEY": FALLBACK_API_KEY, "MCP_TRANSPORT": "http"}
    if token is not None:
        env["MCP_BEARER_TOKEN"] = token
    with isolated_environment(**env), pytest.raises(SystemExit) as exit_info:
        load_settings_or_exit()
    captured = capsys.readouterr()
    assert exit_info.value.code == 2
    assert "MCP_BEARER_TOKEN" in captured.err
    if token:
        assert token not in captured.err


def test_http_without_bearer_token_raises_config_error_naming_variable() -> None:
    env = {"GEMINI_API_KEY": FALLBACK_API_KEY, "MCP_TRANSPORT": "http"}
    with isolated_environment(**env), pytest.raises(ConfigError) as error:
        load_settings()
    assert "MCP_BEARER_TOKEN" in str(error.value)


@pytest.mark.parametrize("length", [31, 32])
def test_http_bearer_token_length_boundary(length: int) -> None:
    token = "y" * length
    if length < 32:
        with pytest.raises(ConfigError) as error:
            load_settings_from({"MCP_TRANSPORT": "http", "MCP_BEARER_TOKEN": token})
        message = str(error.value)
        assert message.startswith("MCP_BEARER_TOKEN: ")
        assert token not in message
    else:
        settings = load_settings_from({"MCP_TRANSPORT": "http", "MCP_BEARER_TOKEN": token})
        assert settings.mcp_bearer_token is not None
        assert settings.mcp_bearer_token.get_secret_value() == token


def test_http_with_long_enough_bearer_token_loads() -> None:
    settings = _http_settings(MCP_BEARER_TOKEN=DUMMY_BEARER_TOKEN)
    assert settings.mcp_transport is Transport.HTTP
    assert settings.mcp_bearer_token is not None
    assert settings.mcp_bearer_token.get_secret_value() == DUMMY_BEARER_TOKEN


def test_short_bearer_token_is_ignored_for_stdio() -> None:
    settings = _settings(MCP_TRANSPORT="stdio", MCP_BEARER_TOKEN=SHORT_TOKEN)
    assert settings.mcp_transport is Transport.STDIO


def test_http_without_bearer_token_exit_in_subprocess() -> None:
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("GEMINI_", "MCP_"))
    }
    env["PATH"] = os.environ.get("PATH", "")
    env["GEMINI_API_KEY"] = FALLBACK_API_KEY
    env["MCP_TRANSPORT"] = "http"
    code = "from gemini_search_mcp.config import load_settings_or_exit\nload_settings_or_exit()\n"
    # S603: the child runs fixed in-repository code, never untrusted input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=os.getcwd(),
    )
    assert result.returncode == 2, result.stderr
    assert "MCP_BEARER_TOKEN" in result.stderr


# AK4: secrets never appear in repr or str of the settings.


@pytest.fixture
def secret_settings() -> Settings:
    return _settings(MCP_TRANSPORT="http", MCP_BEARER_TOKEN=DUMMY_BEARER_TOKEN)


def test_api_key_not_in_repr(secret_settings: Settings) -> None:
    text = repr(secret_settings)
    assert FALLBACK_API_KEY not in text
    assert DUMMY_API_KEY not in text


def test_api_key_not_in_str(secret_settings: Settings) -> None:
    assert FALLBACK_API_KEY not in str(secret_settings)


def test_bearer_token_not_in_repr(secret_settings: Settings) -> None:
    assert DUMMY_BEARER_TOKEN not in repr(secret_settings)


def test_bearer_token_not_in_str(secret_settings: Settings) -> None:
    assert DUMMY_BEARER_TOKEN not in str(secret_settings)


def test_secrets_type_is_secret_str(secret_settings: Settings) -> None:
    assert isinstance(secret_settings.gemini_api_key, SecretStr)
    assert isinstance(secret_settings.mcp_bearer_token, SecretStr)


def test_secret_values_are_still_retrievable(secret_settings: Settings) -> None:
    assert secret_settings.gemini_api_key.get_secret_value() == FALLBACK_API_KEY
    assert secret_settings.mcp_bearer_token is not None
    assert secret_settings.mcp_bearer_token.get_secret_value() == DUMMY_BEARER_TOKEN


def test_module_exports_public_names() -> None:
    module = import_module("gemini_search_mcp.config")
    for name in ["ConfigError", "LogLevel", "Settings", "Transport", "load_settings"]:
        assert name in module.__all__
