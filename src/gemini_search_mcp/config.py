"""Configuration loaded from environment variables per ADR 0010.

This is the only module that reads the environment. It exports one
pydantic-settings model with every variable, default and rule from ADR 0010,
plus startup helpers that fail before a port is opened. Error messages name
only the variable and the rule, never a value, so secrets cannot leak.
"""

import sys
from enum import StrEnum
from typing import Annotated, NoReturn

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    """Raised when required configuration is missing or violates a rule."""


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Transport(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


def _rule_message(variable: str, rule: str) -> str:
    # Validation errors are reported by variable and rule; values never appear.
    return f"{variable}: {rule}"


class Settings(BaseSettings):
    """Validated application settings with the names from ADR 0010."""

    model_config = SettingsConfigDict(extra="ignore")

    gemini_api_key: SecretStr = Field(validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(
        default="gemini-3.8-flash", min_length=1, validation_alias="GEMINI_MODEL"
    )
    gemini_timeout_seconds: Annotated[int, Field(ge=1, le=300)] = Field(
        default=60, validation_alias="GEMINI_TIMEOUT_SECONDS"
    )
    gemini_max_concurrency: Annotated[int, Field(ge=1, le=32)] = Field(
        default=4, validation_alias="GEMINI_MAX_CONCURRENCY"
    )
    gemini_max_retries: Annotated[int, Field(ge=0, le=5)] = Field(
        default=2, validation_alias="GEMINI_MAX_RETRIES"
    )
    log_queries: bool = Field(default=False, validation_alias="LOG_QUERIES")
    log_level: LogLevel = Field(default=LogLevel.INFO, validation_alias="LOG_LEVEL")
    mcp_transport: Transport = Field(default=Transport.STDIO, validation_alias="MCP_TRANSPORT")
    mcp_host: str = Field(default="127.0.0.1", min_length=1, validation_alias="MCP_HOST")
    mcp_port: Annotated[int, Field(ge=1, le=65535)] = Field(
        default=8000, validation_alias="MCP_PORT"
    )
    mcp_bearer_token: SecretStr | None = Field(default=None, validation_alias="MCP_BEARER_TOKEN")

    @model_validator(mode="after")
    def _validate_rules(self) -> Settings:
        if self.gemini_api_key.get_secret_value() == "":
            raise ValueError(_rule_message("GEMINI_API_KEY", "must not be empty"))
        if self.mcp_transport is Transport.HTTP:
            token = (
                self.mcp_bearer_token.get_secret_value()
                if self.mcp_bearer_token is not None
                else ""
            )
            if token == "":
                raise ValueError(
                    _rule_message("MCP_BEARER_TOKEN", "is required when MCP_TRANSPORT is http")
                )
            if len(token) < 32:
                raise ValueError(
                    _rule_message("MCP_BEARER_TOKEN", "must be at least 32 characters long")
                )
        return self


class ConfigErrorDetail:
    """One configuration problem, named by variable and rule only."""

    __slots__ = ("rule", "variable")

    def __init__(self, variable: str, rule: str) -> None:
        self.variable = variable
        self.rule = rule

    def __str__(self) -> str:
        return f"{self.variable}: {self.rule}"


_REQUIRED_RULES: dict[str, str] = {"GEMINI_API_KEY": "required, must not be empty"}
_TOO_SHORT_RULES: dict[str, str] = {
    "GEMINI_MODEL": "must not be empty",
    "MCP_HOST": "must not be empty",
    "MCP_BEARER_TOKEN": "must be at least 32 characters long",
}
_BOUNDARY_RULES: dict[str, str] = {
    "GEMINI_TIMEOUT_SECONDS": "must be between 1 and 300",
    "GEMINI_MAX_CONCURRENCY": "must be between 1 and 32",
    "GEMINI_MAX_RETRIES": "must be between 0 and 5",
    "MCP_PORT": "must be between 1 and 65535",
}

# Used when an error points at a variable without a more specific rule, e.g.
# when a boolean or enum value cannot be parsed.
_GENERIC_RULE = "has an invalid value"


def _describe_error(error: ValidationError) -> ConfigErrorDetail:
    for item in error.errors():
        loc = item["loc"]
        error_type = item["type"]
        if not loc:
            # A model validator rejected the settings; its message names the
            # variable and the rule, so reuse the text instead of ever touching
            # potentially secret input values.
            message = str((item.get("ctx") or {}).get("error", item["msg"]))
            variable, separator, rule = message.partition(" ")
            return ConfigErrorDetail(variable.rstrip(":") if separator else "configuration", rule)
        variable = str(loc[0])
        if error_type == "missing":
            rule = _REQUIRED_RULES.get(variable, "is required")
        elif error_type in {"too_short", "string_too_short"}:
            rule = _TOO_SHORT_RULES.get(variable, _GENERIC_RULE)
        elif error_type in {"greater_than_equal", "less_than_equal"}:
            rule = _BOUNDARY_RULES.get(variable, _GENERIC_RULE)
        else:
            rule = _GENERIC_RULE
        return ConfigErrorDetail(variable, rule)
    return ConfigErrorDetail("configuration", _GENERIC_RULE)


def load_settings() -> Settings:
    """Load and validate settings from the environment.

    Raises:
        ConfigError: if a required variable is missing or empty or a rule is
            violated. The message names the variable and the rule only.
    """
    try:
        return Settings()
    except ValidationError as error:
        raise ConfigError(str(_describe_error(error))) from None


def load_settings_or_exit() -> Settings:
    """Load settings, or print the problem to stderr and exit with code 2."""
    try:
        return load_settings()
    except ConfigError as error:
        _exit_before_start(str(error))


def _exit_before_start(message: str) -> NoReturn:
    print(f"configuration error: {message}", file=sys.stderr)
    sys.exit(2)


__all__ = [
    "ConfigError",
    "LogLevel",
    "Settings",
    "Transport",
    "load_settings",
    "load_settings_or_exit",
]
