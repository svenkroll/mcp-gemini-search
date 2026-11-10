"""Configuration per ADR 0010.

A single pydantic-settings model reads the environment. No other module reads
the environment directly. Error messages name only the variable and the
violated rule, never the value.
"""

import sys
from typing import Annotated, Final, Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

EXIT_CONFIG_ERROR: Final = 2
MIN_BEARER_TOKEN_LENGTH: Final = 32

SettingName = Literal[
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
]

# Field name -> environment variable and violated rule, in ADR 0010 order.
_VARIABLES: Final[dict[str, tuple[SettingName, str]]] = {
    "gemini_api_key": ("GEMINI_API_KEY", "must be set and not empty"),
    "gemini_model": ("GEMINI_MODEL", "must not be empty"),
    "gemini_timeout_seconds": ("GEMINI_TIMEOUT_SECONDS", "must be between 1 and 300"),
    "gemini_max_concurrency": ("GEMINI_MAX_CONCURRENCY", "must be between 1 and 32"),
    "gemini_max_retries": ("GEMINI_MAX_RETRIES", "must be between 0 and 5"),
    "log_queries": ("LOG_QUERIES", "must be a boolean"),
    "log_level": ("LOG_LEVEL", "must be one of debug, info, warning, error"),
    "mcp_transport": ("MCP_TRANSPORT", "must be one of stdio, http"),
    "mcp_host": ("MCP_HOST", "must not be empty"),
    "mcp_port": ("MCP_PORT", "must be between 1 and 65535"),
    "mcp_bearer_token": (
        "MCP_BEARER_TOKEN",
        "is required for MCP_TRANSPORT=http and must be at least "
        f"{MIN_BEARER_TOKEN_LENGTH} characters",
    ),
}


class ConfigError(Exception):
    """A configuration variable is missing or violates its rule from ADR 0010."""

    def __init__(self, variable: str, rule: str) -> None:
        self.variable = variable
        self.rule = rule
        super().__init__(f"Invalid configuration: {variable} {rule}.")


class Settings(BaseSettings):
    """All environment variables from ADR 0010 with their defaults and rules."""

    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    gemini_api_key: SecretStr
    gemini_model: str = "gemini-3.8-flash"
    gemini_timeout_seconds: Annotated[int, Field(ge=1, le=300)] = 60
    gemini_max_concurrency: Annotated[int, Field(ge=1, le=32)] = 4
    gemini_max_retries: Annotated[int, Field(ge=0, le=5)] = 2
    log_queries: bool = False
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: Annotated[int, Field(ge=1, le=65535)] = 8000
    mcp_bearer_token: SecretStr | None = None

    def check_rules(self) -> None:
        """Check the rules that need no value in the error message.

        Raises:
            ConfigError: naming the variable and the violated rule, never the value.
        """
        if not self.gemini_api_key.get_secret_value().strip():
            raise ConfigError("GEMINI_API_KEY", "must be set and not empty")
        if not self.gemini_model.strip():
            raise ConfigError("GEMINI_MODEL", "must not be empty")
        if self.mcp_transport == "http":
            token = self.mcp_bearer_token
            if token is None or len(token.get_secret_value()) < MIN_BEARER_TOKEN_LENGTH:
                variable, rule = _VARIABLES["mcp_bearer_token"]
                raise ConfigError(variable, rule)

    def __repr__(self) -> str:
        fields = ", ".join(f"{name}={value!r}" for name, value in self.model_dump().items())
        return f"Settings({fields})"

    __str__ = __repr__


def _config_error(error: ValidationError) -> ConfigError:
    fields = {str(item["loc"][0]) for item in error.errors() if item["loc"]}
    first = next((name for name in _VARIABLES if name in fields), next(iter(fields), ""))
    variable, rule = _VARIABLES.get(first, (first.upper(), "is invalid"))
    return ConfigError(variable, rule)


def load_settings() -> Settings:
    """Load and validate the settings from the environment.

    Raises:
        ConfigError: naming the variable and the violated rule, never the value.
    """
    try:
        settings = Settings()
    except ValidationError as error:
        raise _config_error(error) from None
    settings.check_rules()
    return settings


def load_settings_or_exit() -> Settings:
    """Load the settings or print the configuration error to stderr and exit with code 2."""
    try:
        return load_settings()
    except ConfigError as error:
        print(error, file=sys.stderr)
        raise SystemExit(EXIT_CONFIG_ERROR) from None
