"""Application settings loaded from environment variables (ADR 0010).

This module is the only one that reads the environment. It maps the variables
of ADR 0010 without a prefix, applies their defaults and rules, and never
exposes a secret value: ``GEMINI_API_KEY`` and ``MCP_BEARER_TOKEN`` are typed
as ``SecretStr`` and never appear in ``repr``, ``str``, error messages or logs.
Invalid configuration is reported as :class:`ConfigError`, which names only
the variable and the violated rule, never the value. The entry point variant
:class:`load_settings_or_exit` turns that error into a stderr message and
exit code 2.
"""

import sys
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["debug", "info", "warning", "error"]
"""Allowed values for ``LOG_LEVEL`` (compared case-insensitively)."""

Transport = Literal["stdio", "http"]
"""Allowed values for ``MCP_TRANSPORT`` (compared case-insensitively)."""


class ConfigError(Exception):
    """Configuration violates a rule from ADR 0010.

    Raised instead of a process exit so that code other than the entry point
    can load the configuration and handle the failure.

    Attributes:
        variable: upper-case environment variable name, e.g. ``GEMINI_API_KEY``.
        rule: short text of the violated rule, e.g. ``must not be empty``.

    ``str(exc)`` is always ``"<VARIABLE>: <rule>"`` and never contains the
    value of any variable, secret or not.
    """

    def __init__(self, variable: str, rule: str) -> None:
        self.variable = variable
        self.rule = rule
        super().__init__(f"{variable}: {rule}")


_FIELD_VARIABLES: dict[str, str] = {
    "gemini_api_key": "GEMINI_API_KEY",
    "gemini_model": "GEMINI_MODEL",
    "gemini_timeout_seconds": "GEMINI_TIMEOUT_SECONDS",
    "gemini_max_concurrency": "GEMINI_MAX_CONCURRENCY",
    "gemini_max_retries": "GEMINI_MAX_RETRIES",
    "log_queries": "LOG_QUERIES",
    "log_level": "LOG_LEVEL",
    "mcp_transport": "MCP_TRANSPORT",
    "mcp_host": "MCP_HOST",
    "mcp_port": "MCP_PORT",
    "mcp_bearer_token": "MCP_BEARER_TOKEN",
}

_NUMERIC_RANGES: dict[str, tuple[int, int]] = {
    "gemini_timeout_seconds": (1, 300),
    "gemini_max_concurrency": (1, 32),
    "gemini_max_retries": (0, 5),
    "mcp_port": (1, 65535),
}

_INTEGER_ERROR_TYPES = frozenset({"int_parsing", "int_type", "int_from_float"})
_BOUND_ERROR_TYPES = frozenset(
    {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}
)


def _rule_for_error(field: str, error_type: str) -> str:
    """Return the ADR 0010 rule text for one pydantic error, never a value."""
    if field in _NUMERIC_RANGES:
        low, high = _NUMERIC_RANGES[field]
        if error_type in _BOUND_ERROR_TYPES:
            return f"must be between {low} and {high}"
        return "must be an integer"
    if field == "log_queries":
        return "must be a boolean"
    if field == "log_level":
        return "must be one of debug, info, warning, error"
    if field == "mcp_transport":
        return "must be one of stdio or http"
    return "must not be empty"


def _config_error_from_validation(error: ValidationError) -> ConfigError:
    """Translate the first pydantic error into a :class:`ConfigError`.

    Only the field name and a fixed rule text are used; the offending value
    never reaches the resulting exception.
    """
    for detail in error.errors():
        location = detail.get("loc", ())
        field = str(location[0]) if location else ""
        variable = _FIELD_VARIABLES.get(field, field.upper())
        rule = _rule_for_error(field, str(detail.get("type", "")))
        return ConfigError(variable, rule)
    return ConfigError("CONFIG", "is invalid")


class Settings(BaseSettings):
    """All configuration of the server, exclusively from the environment.

    Each field maps 1:1 to the environment variable of the same upper-case
    name from ADR 0010; no other module reads the environment. The process
    environment is the only source: no ``.env`` file is read, extra variables
    are ignored.

    Rules per variable (ADR 0010):

    - ``GEMINI_API_KEY``: required, must not be empty or whitespace-only.
    - ``GEMINI_MODEL``: default ``gemini-3.8-flash``, must not be empty.
    - ``GEMINI_TIMEOUT_SECONDS``: default 60, integer from 1 to 300.
    - ``GEMINI_MAX_CONCURRENCY``: default 4, integer from 1 to 32.
    - ``GEMINI_MAX_RETRIES``: default 2, integer from 0 to 5.
    - ``LOG_QUERIES``: default ``False``, must be a boolean.
    - ``LOG_LEVEL``: default ``info``, one of ``debug``, ``info``,
      ``warning``, ``error``, case-insensitive.
    - ``MCP_TRANSPORT``: default ``stdio``, one of ``stdio`` or ``http``,
      case-insensitive.
    - ``MCP_HOST``: default ``127.0.0.1`` (the container sets ``0.0.0.0``).
    - ``MCP_PORT``: default 8000, integer from 1 to 65535.
    - ``MCP_BEARER_TOKEN``: only required with ``MCP_TRANSPORT=http``, then at
      least 32 characters; with ``stdio`` a missing or short token is accepted
      because it is not used.

    A raw value that is empty or whitespace-only counts as unset and falls
    back to the default; for required fields it is an error. Secrets are
    typed ``SecretStr`` and do not appear in ``repr`` or ``str``.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    gemini_api_key: SecretStr
    gemini_model: str = Field(default="gemini-3.8-flash", min_length=1)
    gemini_timeout_seconds: int = Field(default=60, ge=1, le=300)
    gemini_max_concurrency: int = Field(default=4, ge=1, le=32)
    gemini_max_retries: int = Field(default=2, ge=0, le=5)
    log_queries: bool = False
    log_level: LogLevel = "info"
    mcp_transport: Transport = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = Field(default=8000, ge=1, le=65535)
    mcp_bearer_token: SecretStr | None = None

    @model_validator(mode="before")
    @classmethod
    def _blank_value_means_unset(cls, data: Any) -> Any:
        """Treat an empty or whitespace-only raw value as unset.

        Precondition: ``data`` is the raw input mapping with unparsed values.
        Postcondition: every mapping entry whose value is a string consisting
        only of whitespace (including the empty string, as in a copied
        ``.env.example``) is removed, so the field falls back to its default;
        a field without a default then fails validation as missing. Applied to
        all variables, so an empty ``GEMINI_API_KEY`` and one consisting only
        of whitespace both fail like a missing one.
        """
        if not isinstance(data, Mapping):
            return data
        return {
            key: value
            for key, value in data.items()
            if not (isinstance(value, str) and not value.strip())
        }

    @field_validator("log_level", "mcp_transport", mode="before")
    @classmethod
    def _accept_any_letter_case(cls, value: Any) -> Any:
        """Compare ``LOG_LEVEL`` and ``MCP_TRANSPORT`` case-insensitively.

        Precondition: ``value`` is the raw string of ``LOG_LEVEL`` or
        ``MCP_TRANSPORT`` (possibly upper case, e.g. ``INFO`` or ``HTTP``).
        Postcondition: the value is stripped and lower-cased before the
        literal check, so ``INFO`` and ``HTTP`` are accepted. Values that are
        empty or whitespace-only never reach this validator; the blank rule
        above treats them as unset.
        """
        if not isinstance(value, str):
            return value
        return value.strip().lower()

    @model_validator(mode="after")
    def _http_requires_bearer_token(self) -> Self:
        """Enforce the conditional rule for ``MCP_BEARER_TOKEN``.

        Precondition: all field rules passed, ``mcp_transport`` is normalized.
        Postcondition: with ``mcp_transport == "http"`` a missing
        ``mcp_bearer_token`` or one with fewer than 32 characters raises
        ``ConfigError("MCP_BEARER_TOKEN", "must have at least 32 characters
        when MCP_TRANSPORT is http")``; with ``stdio`` any token, including a
        missing or too short one, is accepted. Raises ``ConfigError`` (not a
        ``ValidationError``), which propagates unchanged out of construction.
        """
        if self.mcp_transport == "http":
            token = self.mcp_bearer_token
            if token is None or len(token.get_secret_value()) < 32:
                raise ConfigError(
                    "MCP_BEARER_TOKEN",
                    "must have at least 32 characters when MCP_TRANSPORT is http",
                )
        return self


def load_settings() -> Settings:
    """Load :class:`Settings` from the process environment.

    Raises :class:`ConfigError` naming only the variable and the violated
    rule, never a value, when the environment is invalid:

    - ``GEMINI_API_KEY``: ``must not be empty`` (missing, empty or
      whitespace-only).
    - ``GEMINI_MODEL``: ``must not be empty``.
    - ``GEMINI_TIMEOUT_SECONDS``: ``must be an integer`` or
      ``must be between 1 and 300``.
    - ``GEMINI_MAX_CONCURRENCY``: ``must be an integer`` or
      ``must be between 1 and 32``.
    - ``GEMINI_MAX_RETRIES``: ``must be an integer`` or
      ``must be between 0 and 5``.
    - ``LOG_QUERIES``: ``must be a boolean``.
    - ``LOG_LEVEL``: ``must be one of debug, info, warning, error``.
    - ``MCP_TRANSPORT``: ``must be one of stdio or http``.
    - ``MCP_PORT``: ``must be an integer`` or ``must be between 1 and 65535``.
    - ``MCP_BEARER_TOKEN``: ``must have at least 32 characters when
      MCP_TRANSPORT is http``.

    The first violated rule wins; only one :class:`ConfigError` is raised per
    call, also when several variables are invalid. A :class:`ConfigError`
    raised by the ``MCP_BEARER_TOKEN`` rule propagates unchanged.
    """
    try:
        return Settings()
    except ValidationError as error:
        raise _config_error_from_validation(error) from None


def load_settings_or_exit() -> Settings:
    """Entry point variant of :func:`load_settings`.

    Returns the settings when the configuration is valid. On an invalid
    configuration prints exactly one message to stderr, the
    :class:`ConfigError` text ``"<VARIABLE>: <rule>"`` (naming only the
    variable and the rule, never the value), and raises ``SystemExit`` with
    code 2. Never raises :class:`ConfigError` and never opens a port, so it is
    safe to call first in the server entry point.
    """
    try:
        return load_settings()
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
