"""Acceptance tests for the configuration (ADR 0010, issue #2)."""

import pytest

from gemini_search_mcp.config import (
    ConfigError,
    Settings,
    load_settings,
    load_settings_or_exit,
)

CONFIG_VARIABLES = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_MAX_CONCURRENCY",
    "GEMINI_MAX_RETRIES",
    "LOG_QUERIES",
    "LOG_LEVEL",
    "MCP_TRANSPORT",
    "MCP_HOST",
    "MCP_PORT",
    "MCP_BEARER_TOKEN",
)

# Obviously fake values; they never leave this test process.
VALID_KEY = "fake-key-for-unit-tests"
VALID_BEARER = "fake-bearer-value-not-a-real-secret"
SHORT_BEARER = "b" * 31
EXACT_BEARER = "b" * 32

DEFAULT_VALUES = {
    "gemini_model": "gemini-3.8-flash",
    "gemini_timeout_seconds": 60,
    "gemini_max_concurrency": 4,
    "gemini_max_retries": 2,
    "log_queries": False,
    "log_level": "info",
    "mcp_transport": "stdio",
    "mcp_host": "127.0.0.1",
    "mcp_port": 8000,
    "mcp_bearer_token": None,
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Start every test from an environment without any ADR 0010 variable."""
    for name in CONFIG_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _assert_defaults(settings: Settings) -> None:
    for field, expected in DEFAULT_VALUES.items():
        assert getattr(settings, field) == expected, field


def test_ac1_defaults_match_adr_0010(env: pytest.MonkeyPatch) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    settings = load_settings()
    _assert_defaults(settings)


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("GEMINI_TIMEOUT_SECONDS", 1),
        ("GEMINI_TIMEOUT_SECONDS", 300),
        ("GEMINI_MAX_CONCURRENCY", 1),
        ("GEMINI_MAX_CONCURRENCY", 32),
        ("GEMINI_MAX_RETRIES", 0),
        ("GEMINI_MAX_RETRIES", 5),
        ("MCP_PORT", 1),
        ("MCP_PORT", 65535),
    ],
)
def test_ac1_accepts_numeric_limit_boundaries(
    env: pytest.MonkeyPatch,
    variable: str,
    value: int,
) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv(variable, str(value))
    settings = load_settings()
    assert getattr(settings, variable.lower()) == value


@pytest.mark.parametrize(
    ("variable", "value", "rule"),
    [
        ("GEMINI_TIMEOUT_SECONDS", "0", "must be between 1 and 300"),
        ("GEMINI_TIMEOUT_SECONDS", "301", "must be between 1 and 300"),
        ("GEMINI_MAX_CONCURRENCY", "0", "must be between 1 and 32"),
        ("GEMINI_MAX_CONCURRENCY", "33", "must be between 1 and 32"),
        ("GEMINI_MAX_RETRIES", "-1", "must be between 0 and 5"),
        ("GEMINI_MAX_RETRIES", "6", "must be between 0 and 5"),
        ("MCP_PORT", "0", "must be between 1 and 65535"),
        ("MCP_PORT", "65536", "must be between 1 and 65535"),
    ],
)
def test_ac1_rejects_numeric_values_just_outside_limits(
    env: pytest.MonkeyPatch,
    variable: str,
    value: str,
    rule: str,
) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv(variable, value)
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    assert excinfo.value.variable == variable
    assert excinfo.value.rule == rule
    assert str(excinfo.value) == f"{variable}: {rule}"


def test_ac2_missing_api_key_exits_with_code_2(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    stderr = capsys.readouterr().err
    assert stderr.strip() == "GEMINI_API_KEY: must not be empty"
    assert len(stderr.strip().splitlines()) == 1


def test_ac3_http_without_bearer_token_exits_with_code_2(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("MCP_TRANSPORT", "http")
    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    stderr = capsys.readouterr().err
    assert (
        stderr.strip()
        == "MCP_BEARER_TOKEN: must have at least 32 characters when MCP_TRANSPORT is http"
    )


def test_ac3_http_with_too_short_bearer_token_exits_with_code_2(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("MCP_TRANSPORT", "http")
    env.setenv("MCP_BEARER_TOKEN", SHORT_BEARER)
    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    stderr = capsys.readouterr().err
    assert (
        stderr.strip()
        == "MCP_BEARER_TOKEN: must have at least 32 characters when MCP_TRANSPORT is http"
    )
    assert SHORT_BEARER not in stderr


def test_ac4_secrets_never_appear_in_rendering_or_errors(env: pytest.MonkeyPatch) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("MCP_TRANSPORT", "http")
    env.setenv("MCP_BEARER_TOKEN", VALID_BEARER)
    settings = load_settings()

    for rendering in (repr(settings), str(settings)):
        assert VALID_KEY not in rendering
        assert VALID_BEARER not in rendering

    env.setenv("MCP_PORT", "0")
    with pytest.raises(ConfigError) as excinfo:
        load_settings()
    message = str(excinfo.value)
    assert VALID_KEY not in message
    assert VALID_BEARER not in message


def test_ec1_all_variables_empty_as_in_a_copied_env_example(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in CONFIG_VARIABLES:
        env.setenv(name, "")

    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    assert capsys.readouterr().err.strip() == "GEMINI_API_KEY: must not be empty"

    env.setenv("GEMINI_API_KEY", VALID_KEY)
    _assert_defaults(load_settings())


def test_ec2_whitespace_only_api_key_exits_with_code_2(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env.setenv("GEMINI_API_KEY", " \t ")
    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    assert capsys.readouterr().err.strip() == "GEMINI_API_KEY: must not be empty"


def test_ec3_bearer_token_length_boundary(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("MCP_TRANSPORT", "http")

    env.setenv("MCP_BEARER_TOKEN", EXACT_BEARER)
    settings = load_settings()
    assert settings.mcp_transport == "http"
    assert settings.mcp_bearer_token is not None

    env.setenv("MCP_BEARER_TOKEN", SHORT_BEARER)
    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    assert capsys.readouterr().err.strip().startswith("MCP_BEARER_TOKEN: ")


def test_ec4_stdio_accepts_a_set_but_too_short_bearer_token(env: pytest.MonkeyPatch) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("MCP_TRANSPORT", "stdio")
    env.setenv("MCP_BEARER_TOKEN", SHORT_BEARER)
    settings = load_settings()
    assert settings.mcp_transport == "stdio"


def test_ec5_non_numeric_timeout_exits_with_code_2(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("GEMINI_TIMEOUT_SECONDS", "abc")
    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    assert capsys.readouterr().err.strip() == "GEMINI_TIMEOUT_SECONDS: must be an integer"


def test_ec6_non_boolean_log_queries_exits_with_code_2(
    env: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("LOG_QUERIES", "maybe")
    with pytest.raises(SystemExit) as excinfo:
        load_settings_or_exit()
    assert excinfo.value.code == 2
    assert capsys.readouterr().err.strip() == "LOG_QUERIES: must be a boolean"


def test_ec7_upper_case_log_level_and_transport_are_accepted(env: pytest.MonkeyPatch) -> None:
    env.setenv("GEMINI_API_KEY", VALID_KEY)
    env.setenv("LOG_LEVEL", "INFO")
    env.setenv("MCP_TRANSPORT", "HTTP")
    env.setenv("MCP_BEARER_TOKEN", VALID_BEARER)
    settings = load_settings()
    assert settings.log_level == "info"
    assert settings.mcp_transport == "http"
