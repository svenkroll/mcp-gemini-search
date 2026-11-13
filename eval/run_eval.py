"""Evaluation script: automatic checks and manual scoring (ADR 0005, issue #10).

Two subcommands, no evaluation framework and no LLM judge:

``run``
    Validates the catalog with ``--strict``, starts the server via stdio with
    the console script ``gemini-search-mcp``, calls the tool of every selected
    case over MCP with the FastMCP client and writes the run directory
    ``eval/runs/<date>-<name>/``:

    - ``results.jsonl``: one :class:`CaseRecord` per line, appended as soon as
      the case has finished, so an aborted run keeps every finished case;
    - ``run.json``: the :class:`RunData` of the run;
    - ``server.log``: the server's stderr, which carries the ADR 0007 JSON log
      lines (the MCP SDK diverts the server's stdout to stderr in stdio mode);
      tokens and model of each call are read from its ``tool_call`` line,
      because the tool outputs of ADR 0003 and ADR 0004 carry neither;
    - ``review.md``: overview, run data and one section per case with empty
      manual verdict lines that the project owner fills in by hand.

    Only works with ``LIVE=1`` and a non-empty ``GEMINI_API_KEY``.

``score <run-dir>``
    Reads ``results.jsonl``, ``run.json`` and the filled-in ``review.md``,
    computes the rate per metric, p50/p95 latency, token totals and go/no-go
    against :data:`THRESHOLDS`, and writes ``report.md`` into the run
    directory.

Metrics, applicability and automatic checks follow the table of issue #10:

=================  ===========  ============  ===========================  =======
expected_outcome   correctness  groundedness  source_quality               honesty
=================  ===========  ============  ===========================  =======
``answer``         manual       manual        automatic                    n/a
``honest_unknown`` n/a          n/a           automatic, n/a w/o sources   manual
``error:<code>``   automatic    n/a           n/a                          n/a
=================  ===========  ============  ===========================  =======

Like :mod:`catalog`, this file is not part of a package and never imports
``gemini_search_mcp``: it measures exactly what an MCP client receives.
Invoke as ``uv run python eval/run_eval.py run|score ...``. Never writes
``GEMINI_API_KEY``, ``MCP_BEARER_TOKEN`` or any other secret into a file it
produces.
"""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Literal
from urllib.parse import urlsplit

from fastmcp import Client
from fastmcp.client.transports import ClientTransport, StdioTransport
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, REQUEST_TIMEOUT

_EVAL_DIR = Path(__file__).resolve().parent
_CATALOG_MODULE_NAME = "eval_catalog"


def _load_catalog_module() -> ModuleType:
    """Return the catalog module from issue #3, loaded from its file path.

    ``eval/`` is not a package, so ``import catalog`` only works when this
    file runs as a script. Loading by path works for both the script and the
    tests; an already loaded module under the same name is reused.
    """
    existing = sys.modules.get(_CATALOG_MODULE_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_CATALOG_MODULE_NAME, _EVAL_DIR / "catalog.py")
    if spec is None or spec.loader is None:
        raise ImportError("cannot load eval/catalog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_CATALOG_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


catalog = _load_catalog_module()
"""The catalog module of issue #3 (format, :func:`validate_catalog`, :func:`load_catalog`)."""

CASES_DIR: Path = catalog.CASES_DIR
"""Default catalog directory, ``eval/cases/``."""

RUNS_DIR = _EVAL_DIR / "runs"
"""Directory holding one subdirectory ``<date>-<name>`` per run."""

DEFAULT_RUN_NAME = "run"
"""Run name used when ``--name`` is not given."""

RUN_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
"""Full-match pattern a run name must satisfy; keeps the run directory a
single path component inside :data:`RUNS_DIR`."""

SERVER_COMMAND = "gemini-search-mcp"
"""Console script that starts the server (``[project.scripts]``)."""

SERVER_ENV_OVERRIDES: Mapping[str, str] = {
    "MCP_TRANSPORT": "stdio",
    "ANALYZE_URL_ENABLED": "true",
}
"""Variables set on top of the current environment for the server (ADR 0010)."""

REPORTED_SETTINGS: tuple[str, ...] = (
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_MAX_CONCURRENCY",
    "GEMINI_MAX_RETRIES",
    "ANALYZE_URL_ENABLED",
    "LOG_QUERIES",
    "LOG_LEVEL",
    "MCP_TRANSPORT",
)
"""The only environment variables whose values appear in the run data.

An allowlist of the non-secret ADR 0010 variables: ``GEMINI_API_KEY``,
``MCP_BEARER_TOKEN`` and every variable not listed here never appear."""

CALL_TIMEOUT_SECONDS = 180.0
"""Default client-side timeout of one tool call in seconds; above the server's
own default total budget of 60 seconds per Gemini call (ADR 0006)."""

GROUNDING_REDIRECT_HOSTS: frozenset[str] = frozenset({"vertexaisearch.cloud.google.com"})
"""Hosts of Google grounding redirect URLs (ADR 0003); a returned source on
such a host, or on a subdomain of it, fails source quality."""

RESULTS_FILE = "results.jsonl"
"""File name of the per-case results inside a run directory."""

RUN_DATA_FILE = "run.json"
"""File name of the :class:`RunData` inside a run directory."""

SERVER_LOG_FILE = "server.log"
"""File name of the server's stderr (JSON log lines) inside a run directory."""

REVIEW_FILE = "review.md"
"""File name of the manual review file inside a run directory."""

REPORT_FILE = "report.md"
"""File name of the score report inside a run directory."""

Metric = Literal["correctness", "groundedness", "source_quality", "honesty"]
"""The four metrics of ADR 0005."""

METRICS: tuple[Metric, ...] = ("correctness", "groundedness", "source_quality", "honesty")
"""Every metric, in the order used in ``review.md`` and ``report.md``."""

MANUAL_METRICS: tuple[Metric, ...] = ("correctness", "groundedness", "honesty")
"""Metrics that can be scored by hand; ``source_quality`` is always automatic."""

THRESHOLDS: Mapping[Metric, int] = {
    "correctness": 85,
    "groundedness": 85,
    "source_quality": 90,
    "honesty": 100,
}
"""Go/no-go thresholds of ADR 0005 in whole percent; the only place they are
defined. A metric meets its threshold when its rate is at least this value."""

Applicability = Literal["manual", "automatic", "n/a"]
"""How a metric is decided for a case."""

MetricStatus = Literal["pass", "fail", "n/a", "manual"]
"""Result of the automatic checks for one metric of one case: decided
(``pass``/``fail``), not applicable (``n/a``) or awaiting a manual verdict
(``manual``)."""

ManualVerdict = Literal["pass", "fail"]
"""The only accepted manual verdict values in ``review.md``."""

FinalVerdict = Literal["pass", "fail", "n/a"]
"""Verdict of one metric of one case after merging automatic and manual results."""

CallOutcome = Literal["ok", "tool_error", "call_failed"]
"""How a tool call ended.

``ok``: a result without ``isError``, ``structuredContent`` stored.
``tool_error``: ``isError`` with exactly the ADR 0007 error JSON
(``{"error": {"code", "message", "request_id"}}``) as text, JSON stored.
``call_failed``: anything outside the MCP error contract: a client timeout,
an exception raised by the client while the connection stays up, or an
``isError`` result whose text is not the ADR 0007 error JSON.
"""

VerdictProblemReason = Literal["empty", "invalid", "missing", "duplicate"]
"""Why a manual verdict in ``review.md`` is not usable."""


class EvalAbort(Exception):
    """The eval script stops without completing the subcommand.

    ``str(exc)`` is a short, human-readable reason that names what is wrong
    (the variable, the case id, the directory, the validation findings) and
    never contains a secret value. :func:`main` prints it to stderr and exits
    with code 1.
    """


@dataclass(frozen=True, slots=True)
class VerdictProblem:
    """One unusable manual verdict in ``review.md``.

    Attributes:
        case_id: id of the case whose verdict is unusable.
        metric: the manual metric concerned.
        reason: ``empty`` (verdict line present, no value), ``invalid``
            (value does not start with exactly ``pass`` or ``fail``, e.g.
            ``pas`` or ``passed``), ``missing`` (no verdict line for a metric
            whose status is ``manual``, or no section for the case) or
            ``duplicate`` (more than one verdict line for the same case and
            metric).

    ``str(problem)`` is ``"<case_id>: <metric>: <reason>"``.
    """

    case_id: str
    metric: Metric
    reason: VerdictProblemReason

    def __str__(self) -> str:
        return f"{self.case_id}: {self.metric}: {self.reason}"


class InvalidVerdictsError(EvalAbort):
    """``review.md`` holds at least one unusable manual verdict.

    Attributes:
        problems: every problem, ordered by the case order of
            ``results.jsonl`` and, within a case, by :data:`METRICS`.

    ``str(exc)`` joins the text of every problem with new lines, so it names
    each affected case and metric.
    """

    def __init__(self, problems: Sequence[VerdictProblem]) -> None:
        self.problems = list(problems)
        super().__init__("\n".join(str(problem) for problem in self.problems))


@dataclass(frozen=True, slots=True)
class ToolCallTelemetry:
    """Data of one ADR 0007 ``tool_call`` log line used by the eval.

    Attributes:
        model: the ``model`` field.
        input_tokens: the ``input_tokens`` field, ``None`` when ``null``.
        output_tokens: the ``output_tokens`` field, ``None`` when ``null``.
    """

    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


def _int_or_none(value: Any) -> int | None:
    """Return ``value`` when it is an ``int`` (not a ``bool``), else ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_str(value: Any) -> bool:
    return isinstance(value, str)


def _is_int(value: Any) -> bool:
    return _int_or_none(value) is not None


def _is_non_negative_int(value: Any) -> bool:
    return _is_int(value) and value >= 0


def _is_dict(value: Any) -> bool:
    return isinstance(value, dict)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_str_dict(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


def _is_checks(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(METRICS)
        and all(status in ("pass", "fail", "n/a", "manual") for status in value.values())
    )


def _optional(accept: Callable[[Any], bool]) -> Callable[[Any], bool]:
    """Return a predicate that accepts ``None`` or what ``accept`` accepts."""
    return lambda value: value is None or accept(value)


def _field(data: Mapping[str, Any], key: str, accept: Callable[[Any], bool]) -> Any:
    """Return ``data[key]`` after checking it with ``accept``.

    Raises:
        ValueError: when the key is missing or the value is not accepted.
    """
    if key not in data:
        raise ValueError(f"missing key {key!r}")
    if not accept(data[key]):
        raise ValueError(f"invalid value for key {key!r}")
    return data[key]


class ServerLogReader:
    """Reads the server's JSON log lines incrementally from a file.

    The file is the server's stderr (stdio transport) or, in tests, the
    stream the in-memory server logs to. The file may not exist yet; it is
    then treated as empty.
    """

    def __init__(self, path: Path) -> None:
        """Remember ``path``; reading starts at the beginning of the file."""
        self.path = path
        self._offset = 0

    def next_tool_call(self) -> ToolCallTelemetry | None:
        """Return the telemetry of the latest ``tool_call`` line since the last read.

        Reads every complete line appended since the previous call (the first
        call reads from the start), parses each as JSON and returns the data
        of the last line with ``"event": "tool_call"``. Lines that are not
        JSON objects, other events and lines without a string ``model`` are
        skipped. Returns ``None`` when no such line was appended. Never
        raises for malformed content.
        """
        try:
            with self.path.open("rb") as handle:
                handle.seek(self._offset)
                data = handle.read()
        except OSError:
            return None
        end = data.rfind(b"\n")
        if end < 0:
            return None
        self._offset += end + 1
        latest: ToolCallTelemetry | None = None
        for raw in data[:end].split(b"\n"):
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("event") != "tool_call":
                continue
            model = entry.get("model")
            if not isinstance(model, str):
                continue
            latest = ToolCallTelemetry(
                model=model,
                input_tokens=_int_or_none(entry.get("input_tokens")),
                output_tokens=_int_or_none(entry.get("output_tokens")),
            )
        return latest


@dataclass(frozen=True, slots=True)
class CaseRecord:
    """One line of ``results.jsonl``: input, raw result and automatic checks.

    Attributes:
        id: case id.
        tool: ``search`` or ``analyze_url``.
        category: catalog category.
        expected_outcome: ``answer``, ``honest_unknown`` or ``error:<code>``.
        input: the tool arguments sent, i.e. the case ``input`` mapping
            (``{"query"}`` or ``{"url", "question"}``).
        expected: the case's ``expected`` text.
        allowed_sources: the case's ``allowed_sources``.
        outcome: see :data:`CallOutcome`.
        structured_content: ``structuredContent`` when ``outcome == "ok"``,
            otherwise ``None``.
        error_json: the parsed ADR 0007 error JSON (the whole object with the
            ``error`` key) when ``outcome == "tool_error"``, otherwise
            ``None``.
        failure: short description of the failure when
            ``outcome == "call_failed"`` (exception class name and message, or
            ``"timeout after <n> s"``), otherwise ``None``.
        latency_ms: client-side duration of the call in whole milliseconds,
            ``>= 0``, also for failed calls.
        input_tokens: from the call's ``tool_call`` log line, else ``None``.
        output_tokens: from the call's ``tool_call`` log line, else ``None``.
        model: from the call's ``tool_call`` log line, else ``None``.
        checks: :func:`automatic_checks` result, one entry per metric of
            :data:`METRICS`.
    """

    id: str
    tool: Literal["search", "analyze_url"]
    category: str
    expected_outcome: str
    input: dict[str, str]
    expected: str
    allowed_sources: list[str]
    outcome: CallOutcome
    structured_content: dict[str, Any] | None
    error_json: dict[str, Any] | None
    failure: str | None
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    model: str | None
    checks: dict[Metric, MetricStatus]

    def to_json_dict(self) -> dict[str, Any]:
        """Return the JSON object written as one ``results.jsonl`` line.

        Keys are exactly the attribute names, in declaration order; ``None``
        becomes JSON ``null``. ``CaseRecord.from_json_dict(r.to_json_dict())
        == r``.
        """
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> CaseRecord:
        """Rebuild a record from one parsed ``results.jsonl`` line.

        Raises:
            ValueError: when a key is missing or a value has the wrong type
                or an unknown literal value.
        """
        tool = _field(data, "tool", lambda value: value in ("search", "analyze_url"))
        outcome = _field(
            data, "outcome", lambda value: value in ("ok", "tool_error", "call_failed")
        )
        raw_checks = _field(data, "checks", _is_checks)
        return cls(
            id=_field(data, "id", _is_str),
            tool=tool,
            category=_field(data, "category", _is_str),
            expected_outcome=_field(data, "expected_outcome", _is_str),
            input=dict(_field(data, "input", _is_str_dict)),
            expected=_field(data, "expected", _is_str),
            allowed_sources=list(_field(data, "allowed_sources", _is_str_list)),
            outcome=outcome,
            structured_content=_field(data, "structured_content", _optional(_is_dict)),
            error_json=_field(data, "error_json", _optional(_is_dict)),
            failure=_field(data, "failure", _optional(_is_str)),
            latency_ms=_field(data, "latency_ms", _is_non_negative_int),
            input_tokens=_field(data, "input_tokens", _optional(_is_int)),
            output_tokens=_field(data, "output_tokens", _optional(_is_int)),
            model=_field(data, "model", _optional(_is_str)),
            checks={metric: raw_checks[metric] for metric in METRICS},
        )


@dataclass(frozen=True, slots=True)
class RunData:
    """Run metadata shown in ``review.md`` and ``report.md``; stored as ``run.json``.

    Attributes:
        name: the run name (``--name``).
        date: run date, ISO ``YYYY-MM-DD``; also the prefix of the run
            directory.
        commit: ``git rev-parse HEAD`` of the repository, ``"unknown"`` when
            it cannot be determined.
        catalog_hash: :func:`catalog_hash` of the catalog directory.
        models: distinct ``model`` values of all records, in first-seen
            order; empty when no call reported a model.
        settings: for each name in :data:`REPORTED_SETTINGS`, the value in the
            server environment, or ``"default"`` when unset; plus
            ``"call_timeout_seconds"`` with the client-side timeout. Never
            any other variable, in particular no secret.
        case_ids: ids of the cases run, in run order.
    """

    name: str
    date: str
    commit: str
    catalog_hash: str
    models: list[str]
    settings: dict[str, str]
    case_ids: list[str]

    def to_json_dict(self) -> dict[str, Any]:
        """Return the JSON object of ``run.json``; keys are the attribute names."""
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> RunData:
        """Rebuild run data from parsed ``run.json``.

        Raises:
            ValueError: when a key is missing or a value has the wrong type.
        """
        return cls(
            name=_field(data, "name", _is_str),
            date=_field(data, "date", _is_str),
            commit=_field(data, "commit", _is_str),
            catalog_hash=_field(data, "catalog_hash", _is_str),
            models=list(_field(data, "models", _is_str_list)),
            settings=dict(_field(data, "settings", _is_str_dict)),
            case_ids=list(_field(data, "case_ids", _is_str_list)),
        )


@dataclass(frozen=True, slots=True)
class MetricRate:
    """Rate and threshold result of one metric over a run.

    Attributes:
        metric: the metric.
        passed: number of cases with final verdict ``pass``.
        total: number of cases with final verdict ``pass`` or ``fail``
            (``n/a`` cases are not counted).
        rate_percent: ``100 * passed / total``; ``None`` when ``total == 0``
            (shown as ``n/a``).
        threshold_percent: :data:`THRESHOLDS` value of the metric.
        met: ``True`` exactly when ``total > 0`` and
            ``passed * 100 >= threshold_percent * total`` (exact integer
            comparison, so a rate exactly at the threshold meets it);
            ``False`` when every case is ``n/a``.
    """

    metric: Metric
    passed: int
    total: int
    rate_percent: float | None
    threshold_percent: int
    met: bool


@dataclass(frozen=True, slots=True)
class ScoreReport:
    """Everything ``report.md`` shows besides the run data.

    Attributes:
        rates: one :class:`MetricRate` per metric, in :data:`METRICS` order.
        go: ``True`` exactly when every rate has ``met`` true.
        latency_p50_ms: :func:`percentile` 50 of all records' ``latency_ms``.
        latency_p95_ms: :func:`percentile` 95 of all records' ``latency_ms``.
        input_tokens_total: sum of all non-``None`` ``input_tokens``.
        output_tokens_total: sum of all non-``None`` ``output_tokens``.
        case_count: number of records scored.
    """

    rates: list[MetricRate]
    go: bool
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    input_tokens_total: int
    output_tokens_total: int
    case_count: int


# --- automatic checks -------------------------------------------------------


def applicability(expected_outcome: str, *, has_sources: bool) -> dict[Metric, Applicability]:
    """Return how each metric is decided for a case, per the table of issue #10.

    Args:
        expected_outcome: ``answer``, ``honest_unknown`` or ``error:<code>``.
        has_sources: whether the call returned at least one source (see
            :func:`returned_sources`); only matters for ``honest_unknown``.

    Returns:
        One entry per metric of :data:`METRICS`:

        - ``answer``: correctness ``manual``, groundedness ``manual``,
          source_quality ``automatic``, honesty ``n/a``;
        - ``honest_unknown``: correctness ``n/a``, groundedness ``n/a``,
          source_quality ``automatic`` with sources and ``n/a`` without,
          honesty ``manual``;
        - ``error:<code>``: correctness ``automatic``, every other metric
          ``n/a``.

    Raises:
        ValueError: for any other ``expected_outcome``.
    """
    if expected_outcome == "answer":
        return {
            "correctness": "manual",
            "groundedness": "manual",
            "source_quality": "automatic",
            "honesty": "n/a",
        }
    if expected_outcome == "honest_unknown":
        return {
            "correctness": "n/a",
            "groundedness": "n/a",
            "source_quality": "automatic" if has_sources else "n/a",
            "honesty": "manual",
        }
    if expected_outcome.startswith("error:") and len(expected_outcome) > len("error:"):
        return {
            "correctness": "automatic",
            "groundedness": "n/a",
            "source_quality": "n/a",
            "honesty": "n/a",
        }
    raise ValueError(f"unknown expected_outcome {expected_outcome!r}")


def _host(url: str) -> str | None:
    """Return the lower-case host of ``url`` without a trailing dot, or ``None``."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    return host.rstrip(".") if host else None


def _within(host: str, domain: str) -> bool:
    """Return whether ``host`` equals ``domain`` or is a subdomain of it."""
    return host == domain or host.endswith("." + domain)


def returned_sources(tool: str, structured_content: Mapping[str, Any] | None) -> list[str]:
    """Return the source URLs a successful tool result reports.

    ``search``: the ``url`` of every entry of ``sources`` (ADR 0003), in
    order. ``analyze_url``: a one-element list with ``url`` (ADR 0004).
    ``None`` (no successful result) or missing fields: an empty list.
    """
    if structured_content is None:
        return []
    if tool == "search":
        entries = structured_content.get("sources")
        if not isinstance(entries, list):
            return []
        return [
            entry["url"]
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("url"), str)
        ]
    url = structured_content.get("url")
    return [url] if isinstance(url, str) else []


def is_grounding_redirect(url: str) -> bool:
    """Return whether ``url`` is a Google grounding redirect URL.

    True when the URL's host, compared case-insensitively, is in
    :data:`GROUNDING_REDIRECT_HOSTS` or a subdomain of one of them. Never
    raises; an unparsable URL is not a redirect.
    """
    host = _host(url)
    return host is not None and any(_within(host, known) for known in GROUNDING_REDIRECT_HOSTS)


def is_allowed_source(url: str, allowed_sources: Sequence[str]) -> bool:
    """Return whether ``url`` lies within one of the ``allowed_sources`` domains.

    True when the URL's host, compared case-insensitively and without a
    trailing dot, equals an allowed domain or ends with ``"." + domain``
    (``www.rfc-editor.org`` is within ``rfc-editor.org``;
    ``evilrfc-editor.org`` is not). False for a URL without a host or one
    that cannot be parsed. Never raises.
    """
    host = _host(url)
    if host is None:
        return False
    return any(_within(host, domain.lower().rstrip(".")) for domain in allowed_sources)


def check_source_quality(
    sources: Sequence[str], allowed_sources: Sequence[str]
) -> Literal["pass", "fail"]:
    """Decide source quality (ADR 0005) for the returned ``sources``.

    ``pass`` when every source satisfies :func:`is_allowed_source` and none
    satisfies :func:`is_grounding_redirect`; otherwise ``fail``. An empty
    ``sources`` list passes (the rule holds for every returned source); the
    caller decides via :func:`applicability` whether the metric applies.
    """
    for source in sources:
        if not is_allowed_source(source, allowed_sources) or is_grounding_redirect(source):
            return "fail"
    return "pass"


def check_error_code(
    expected_outcome: str, outcome: CallOutcome, error_json: Mapping[str, Any] | None
) -> Literal["pass", "fail"]:
    """Decide correctness of an ``error:<code>`` case.

    ``pass`` exactly when ``outcome == "tool_error"`` and
    ``error_json["error"]["code"]`` equals the ``<code>`` part of
    ``expected_outcome``; ``fail`` for a successful call, a different code
    and ``call_failed``.

    Raises:
        ValueError: when ``expected_outcome`` does not start with ``error:``.
    """
    prefix = "error:"
    if not expected_outcome.startswith(prefix):
        raise ValueError(f"expected_outcome {expected_outcome!r} is not an error outcome")
    if outcome != "tool_error" or error_json is None:
        return "fail"
    error = error_json.get("error")
    code = error.get("code") if isinstance(error, Mapping) else None
    return "pass" if code == expected_outcome[len(prefix) :] else "fail"


def automatic_checks(
    *,
    expected_outcome: str,
    outcome: CallOutcome,
    sources: Sequence[str],
    error_json: Mapping[str, Any] | None,
    allowed_sources: Sequence[str],
) -> dict[Metric, MetricStatus]:
    """Return the status of every metric after the checks that need no LLM.

    Starts from :func:`applicability` with ``has_sources=bool(sources)``:
    ``n/a`` stays ``n/a``, ``manual`` becomes ``manual``, ``automatic`` is
    decided by :func:`check_source_quality` (source_quality) or
    :func:`check_error_code` (correctness of ``error:<code>``). Then:

    - ``answer`` case with ``outcome == "tool_error"``: correctness and
      groundedness are ``fail`` (no manual verdict needed);
    - any case with ``outcome == "call_failed"``: every metric that is not
      ``n/a`` is ``fail``.

    Returns one entry per metric of :data:`METRICS`.
    """
    decided = applicability(expected_outcome, has_sources=bool(sources))
    checks: dict[Metric, MetricStatus] = {}
    for metric in METRICS:
        if decided[metric] == "n/a":
            checks[metric] = "n/a"
        elif decided[metric] == "manual":
            checks[metric] = "manual"
        elif metric == "source_quality":
            checks[metric] = check_source_quality(sources, allowed_sources)
        else:
            checks[metric] = check_error_code(expected_outcome, outcome, error_json)
    if outcome == "call_failed":
        return {metric: "n/a" if status == "n/a" else "fail" for metric, status in checks.items()}
    if expected_outcome == "answer" and outcome == "tool_error":
        checks["correctness"] = "fail"
        checks["groundedness"] = "fail"
    return checks


# --- run --------------------------------------------------------------------


def check_live_guard(environ: Mapping[str, str]) -> None:
    """Allow a live run only with ``LIVE=1`` and a non-empty ``GEMINI_API_KEY``.

    Raises:
        EvalAbort: when ``environ["LIVE"]`` is not exactly ``"1"``, or when
            ``GEMINI_API_KEY`` is missing or empty after stripping
            whitespace. The message names the variable, never a value.
    """
    if environ.get("LIVE") != "1":
        raise EvalAbort(
            "LIVE=1 is required: a run makes paid Gemini calls (ADR 0006); "
            "nothing was started and no call was made"
        )
    if not environ.get("GEMINI_API_KEY", "").strip():
        raise EvalAbort(
            "GEMINI_API_KEY is empty or not set: a live run needs a Gemini API key; "
            "nothing was started and no call was made"
        )


def load_strict_catalog(cases_dir: Path = CASES_DIR) -> list[Any]:
    """Validate ``cases_dir`` with ``strict=True`` and return its cases.

    Returns the ``catalog.load_catalog(cases_dir)`` cases (catalog
    :data:`Case` objects) when strict validation reports no error; warnings
    do not abort.

    Raises:
        EvalAbort: when strict validation reports at least one error (e.g.
            drafts present); the message contains the text of every error
            finding.
    """
    errors = [
        finding
        for finding in catalog.validate_catalog(cases_dir, strict=True)
        if finding.severity == "error"
    ]
    if errors:
        details = "\n".join(str(finding) for finding in errors)
        raise EvalAbort(f"the catalog is not valid with --strict:\n{details}")
    return catalog.load_catalog(cases_dir)


def select_cases(cases: Sequence[Any], case_ids: Sequence[str]) -> list[Any]:
    """Restrict ``cases`` to ``case_ids`` (``--case``).

    Returns every case, in catalog order, when ``case_ids`` is empty;
    otherwise the cases whose id is in ``case_ids``, in catalog order, each
    once even if given twice.

    Raises:
        EvalAbort: when an id in ``case_ids`` is not in ``cases``; the message
            names every unknown id.
    """
    if not case_ids:
        return list(cases)
    known = {case.id for case in cases}
    unknown = sorted({case_id for case_id in case_ids if case_id not in known})
    if unknown:
        raise EvalAbort("unknown case id(s): " + ", ".join(unknown))
    wanted = set(case_ids)
    return [case for case in cases if case.id in wanted]


def server_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Return the server's environment: ``environ`` plus :data:`SERVER_ENV_OVERRIDES`.

    The overrides replace values already in ``environ``; ``environ`` itself is
    not modified.
    """
    return {**environ, **SERVER_ENV_OVERRIDES}


def stdio_transport(env: Mapping[str, str], log_path: Path) -> ClientTransport:
    """Default transport factory: the console script :data:`SERVER_COMMAND` via stdio.

    Returns a FastMCP ``StdioTransport`` running :data:`SERVER_COMMAND`
    without arguments, with environment ``env``, ``keep_alive=False`` and the
    server's stderr written to ``log_path``. Starts no process by itself.
    """
    return StdioTransport(
        command=SERVER_COMMAND, args=[], env=dict(env), keep_alive=False, log_file=log_path
    )


TransportFactory = Callable[[Mapping[str, str], Path], ClientTransport]
"""Builds the client transport from the server environment and the path of
the server log file; :func:`stdio_transport` by default, an in-memory
transport in tests. Called only after every pre-flight check passed."""


def create_run_dir(runs_dir: Path, name: str, today: date) -> Path:
    """Create and return ``runs_dir / f"{today.isoformat()}-{name}"``.

    Creates ``runs_dir`` when missing.

    Raises:
        EvalAbort: when ``name`` does not fully match
            :data:`RUN_NAME_PATTERN`, or when the directory already exists
            (never overwritten); the message names the directory.
    """
    if not re.fullmatch(RUN_NAME_PATTERN, name):
        raise EvalAbort(f"invalid run name {name!r}: it must match {RUN_NAME_PATTERN}")
    run_dir = runs_dir / f"{today.isoformat()}-{name}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir()
    except FileExistsError:
        raise EvalAbort(
            f"run directory {run_dir} already exists; choose another --name or remove it"
        ) from None
    return run_dir


def catalog_hash(cases_dir: Path = CASES_DIR) -> str:
    """Return the SHA-256 hex digest identifying the catalog contents.

    Hashes every non-hidden ``*.yaml`` file of ``cases_dir`` in file name
    order, each as its file name (UTF-8), a NUL byte, its raw bytes and a NUL
    byte. Independent of which cases a run selects.
    """
    digest = hashlib.sha256()
    files = sorted(cases_dir.iterdir(), key=lambda entry: entry.name) if cases_dir.is_dir() else []
    for entry in files:
        if (
            entry.is_file()
            and not entry.name.startswith(".")
            and entry.name.endswith(catalog.CASE_SUFFIX)
        ):
            digest.update(entry.name.encode("utf-8") + b"\0" + entry.read_bytes() + b"\0")
    return digest.hexdigest()


def git_commit() -> str:
    """Return ``git rev-parse HEAD`` of the repository, or ``"unknown"`` on any failure."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=_EVAL_DIR,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return "unknown"
    commit = completed.stdout.strip()
    return commit if completed.returncode == 0 and commit else "unknown"


def make_record(
    case: Any,
    *,
    outcome: CallOutcome,
    structured_content: dict[str, Any] | None,
    error_json: dict[str, Any] | None,
    failure: str | None,
    latency_ms: int,
    telemetry: ToolCallTelemetry | None,
) -> CaseRecord:
    """Build the :class:`CaseRecord` of one finished call of ``case``.

    Copies the case fields, the call result and the telemetry (``None``
    yields ``None`` for tokens and model) and sets ``checks`` to
    :func:`automatic_checks` with the sources from :func:`returned_sources`.
    """
    sources = returned_sources(case.tool, structured_content)
    return CaseRecord(
        id=case.id,
        tool=case.tool,
        category=str(case.category),
        expected_outcome=case.expected_outcome,
        input=case.input.model_dump(),
        expected=case.expected,
        allowed_sources=list(case.allowed_sources),
        outcome=outcome,
        structured_content=structured_content,
        error_json=error_json,
        failure=failure,
        latency_ms=latency_ms,
        input_tokens=telemetry.input_tokens if telemetry else None,
        output_tokens=telemetry.output_tokens if telemetry else None,
        model=telemetry.model if telemetry else None,
        checks=automatic_checks(
            expected_outcome=case.expected_outcome,
            outcome=outcome,
            sources=sources,
            error_json=error_json,
            allowed_sources=case.allowed_sources,
        ),
    )


def append_record(results_path: Path, record: CaseRecord) -> None:
    """Append ``record`` as one JSON line to ``results_path`` and flush it."""
    with results_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.to_json_dict(), ensure_ascii=False) + "\n")
        handle.flush()


def read_records(results_path: Path) -> list[CaseRecord]:
    """Read every record of a ``results.jsonl`` file, in file order.

    Raises:
        EvalAbort: when the file is missing, a line is not valid JSON or not
            a valid record; the message names the file and the line number.
    """
    try:
        text = results_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvalAbort(f"cannot read {results_path}: {exc}") from exc
    records: list[CaseRecord] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            if not isinstance(data, dict):
                raise ValueError("a record must be a JSON object")
            records.append(CaseRecord.from_json_dict(data))
        except ValueError as exc:
            raise EvalAbort(f"{results_path}: line {number}: {exc}") from exc
    return records


def _server_gone(exc: Exception, client: Client) -> bool:
    """Return whether the failed call means the server connection is lost."""
    closed = isinstance(exc, MCPError) and exc.code == CONNECTION_CLOSED
    return closed or not client.is_connected()


def _describe_failure(exc: Exception, call_timeout: float) -> str:
    """Return the short ``failure`` text of a call that raised ``exc``."""
    if isinstance(exc, TimeoutError) or (isinstance(exc, MCPError) and exc.code == REQUEST_TIMEOUT):
        return f"timeout after {call_timeout:g} s"
    return f"{type(exc).__name__}: {exc}"


def _is_error_json(value: Any) -> bool:
    """Return whether ``value`` is exactly the ADR 0007 error JSON."""
    if not isinstance(value, dict) or set(value) != {"error"}:
        return False
    error = value["error"]
    return (
        isinstance(error, dict)
        and set(error) == {"code", "message", "request_id"}
        and all(isinstance(item, str) for item in error.values())
    )


def _classify_result(
    result: Any,
) -> tuple[CallOutcome, dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Return ``(outcome, structured_content, error_json, failure)`` of a tool result."""
    if result.is_error:
        text = next((block.text for block in result.content if hasattr(block, "text")), "")
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if _is_error_json(parsed):
            return "tool_error", None, parsed, None
        return "call_failed", None, None, f"tool error outside the error contract: {text[:200]}"
    if isinstance(result.structured_content, dict):
        return "ok", result.structured_content, None, None
    return "call_failed", None, None, "result without structuredContent"


async def run_cases(
    cases: Sequence[Any],
    transport: ClientTransport,
    *,
    results_path: Path,
    log_reader: ServerLogReader,
    call_timeout: float = CALL_TIMEOUT_SECONDS,
) -> list[CaseRecord]:
    """Call the tool of every case over one MCP session and record the results.

    Opens a FastMCP ``Client`` on ``transport``, then for each case in order:
    calls ``case.tool`` with ``case.input`` as arguments,
    ``raise_on_error=False`` and ``timeout=call_timeout``, measures the
    latency, reads the telemetry via ``log_reader.next_tool_call()``, builds
    the record with :func:`make_record` and appends it to ``results_path``
    before the next case starts. Outcome per :data:`CallOutcome`.

    EC5: a timeout or exception of a single call while the client stays
    connected yields a ``call_failed`` record and the run continues.

    Raises:
        EvalAbort: when the server cannot be started or the session cannot
            be initialized ("server failed to start"), or when the client is
            no longer connected after a call failed ("server exited during
            case <id>"). The message names the results file and the server
            log; every record appended before stays in ``results_path``.

    Returns:
        Every record, in case order.
    """
    records: list[CaseRecord] = []
    where = f"results so far: {results_path}; server log: {log_reader.path}"
    async with AsyncExitStack() as stack:
        client = Client(transport)
        try:
            await stack.enter_async_context(client)
        except Exception as exc:
            raise EvalAbort(
                f"server failed to start ({type(exc).__name__}: {exc}); {where}"
            ) from exc
        for case in cases:
            started = time.perf_counter()
            outcome: CallOutcome
            structured: dict[str, Any] | None = None
            error_json: dict[str, Any] | None = None
            failure: str | None = None
            try:
                result = await client.call_tool(
                    case.tool,
                    case.input.model_dump(),
                    timeout=call_timeout,
                    raise_on_error=False,
                )
            except Exception as exc:
                if _server_gone(exc, client):
                    raise EvalAbort(f"server exited during case {case.id}; {where}") from exc
                outcome = "call_failed"
                failure = _describe_failure(exc, call_timeout)
            else:
                outcome, structured, error_json, failure = _classify_result(result)
            latency_ms = int((time.perf_counter() - started) * 1000)
            record = make_record(
                case,
                outcome=outcome,
                structured_content=structured,
                error_json=error_json,
                failure=failure,
                latency_ms=latency_ms,
                telemetry=log_reader.next_tool_call(),
            )
            append_record(results_path, record)
            records.append(record)
    return records


async def run_command(
    *,
    environ: Mapping[str, str],
    name: str = DEFAULT_RUN_NAME,
    case_ids: Sequence[str] = (),
    cases_dir: Path = CASES_DIR,
    runs_dir: Path = RUNS_DIR,
    today: date | None = None,
    transport_factory: TransportFactory = stdio_transport,
    call_timeout: float = CALL_TIMEOUT_SECONDS,
) -> Path:
    """Subcommand ``run``: execute a live evaluation run and write its files.

    Steps, each aborting with :class:`EvalAbort` before the next one:

    1. :func:`check_live_guard` on ``environ`` (AC5, EC2);
    2. :func:`load_strict_catalog` on ``cases_dir`` (EC1);
    3. :func:`select_cases` with ``case_ids`` (EC3);
    4. :func:`create_run_dir` in ``runs_dir`` with ``name`` and ``today``
       (``None`` means ``date.today()``) (EC10);
    5. ``transport_factory(server_environment(environ), run_dir /
       SERVER_LOG_FILE)`` -- the first step that may start a process or
       touch the network; never reached when a step above aborts;
    6. :func:`run_cases` writing ``results.jsonl`` (EC4, EC5);
    7. writes ``run.json`` (:class:`RunData`) and ``review.md``
       (:func:`render_review`).

    On an abort in step 6 only ``results.jsonl`` and ``server.log`` exist.

    Returns:
        The run directory.
    """
    check_live_guard(environ)
    cases = select_cases(load_strict_catalog(cases_dir), case_ids)
    run_date = today or date.today()
    run_dir = create_run_dir(runs_dir, name, run_date)
    env = server_environment(environ)
    log_path = run_dir / SERVER_LOG_FILE
    transport = transport_factory(env, log_path)
    records = await run_cases(
        cases,
        transport,
        results_path=run_dir / RESULTS_FILE,
        log_reader=ServerLogReader(log_path),
        call_timeout=call_timeout,
    )
    settings = {setting: env.get(setting) or "default" for setting in REPORTED_SETTINGS}
    settings["call_timeout_seconds"] = str(call_timeout)
    run_data = RunData(
        name=name,
        date=run_date.isoformat(),
        commit=git_commit(),
        catalog_hash=catalog_hash(cases_dir),
        models=list(dict.fromkeys(record.model for record in records if record.model)),
        settings=settings,
        case_ids=[record.id for record in records],
    )
    (run_dir / RUN_DATA_FILE).write_text(
        json.dumps(run_data.to_json_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (run_dir / REVIEW_FILE).write_text(render_review(records, run_data), encoding="utf-8")
    return run_dir


# --- review and score -------------------------------------------------------


def _inline(text: str) -> str:
    """Return ``text`` on one line, so it cannot start a new Markdown line."""
    return " ".join(text.split())


def _cell(text: str) -> str:
    """Return ``text`` as the content of one Markdown table cell."""
    return _inline(text).replace("|", "\\|")


def _fenced(text: str) -> list[str]:
    """Return ``text`` in a code fence longer than any backtick run inside it."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return [fence, *text.splitlines(), fence, ""]


def _run_data_lines(*, records_count: int, run_data: RunData) -> list[str]:
    """Return the ``## Run data`` section shared by ``review.md`` and ``report.md``."""
    lines = [
        "## Run data",
        "",
        f"- commit: {_inline(run_data.commit)}",
        f"- date: {_inline(run_data.date)}",
        f"- catalog hash: {_inline(run_data.catalog_hash)}",
        f"- models: {', '.join(_inline(model) for model in run_data.models) or 'unknown'}",
        f"- cases: {records_count}",
    ]
    lines += [
        f"- setting {_inline(key)}: {_inline(value)}" for key, value in run_data.settings.items()
    ]
    return [*lines, ""]


def _case_section(record: CaseRecord) -> list[str]:
    """Return the ``## Case <id>`` section of ``review.md``."""
    lines = [
        f"## Case {record.id}",
        "",
        f"- category: {_inline(record.category)}",
        f"- tool: {record.tool}",
        f"- expected outcome: {_inline(record.expected_outcome)}",
        f"- outcome: {record.outcome}",
        f"- latency: {record.latency_ms} ms",
        "",
    ]
    for key, label in (("query", "Question"), ("url", "URL"), ("question", "Question")):
        if key in record.input:
            lines += [f"### {label}", "", *_fenced(record.input[key])]
    lines += ["### Expected", "", *_fenced(record.expected)]
    lines += ["### Allowed sources", "", *_fenced("\n".join(record.allowed_sources))]
    if record.outcome == "ok":
        label, content = "Answer", _answer_text(record)
    elif record.outcome == "tool_error":
        label, content = "Error JSON", json.dumps(record.error_json, indent=2, ensure_ascii=False)
    else:
        label, content = "Failure", record.failure or ""
    lines += [f"### {label}", "", *_fenced(content)]
    sources = returned_sources(record.tool, record.structured_content)
    lines += ["### Returned sources", "", *_fenced("\n".join(sources))]
    lines += ["### Automatic results", ""]
    lines += [f"- {metric}: {status}" for metric, status in record.checks.items()]
    manual = [metric for metric, status in record.checks.items() if status == "manual"]
    if manual:
        lines += ["", "### Manual verdicts", ""]
        lines += [f"- verdict {metric}:" for metric in manual]
    return [*lines, ""]


def _answer_text(record: CaseRecord) -> str:
    """Return the answer text of a successful call."""
    content = record.structured_content or {}
    answer = content.get("answer")
    return answer if isinstance(answer, str) else json.dumps(content, ensure_ascii=False)


def render_review(records: Sequence[CaseRecord], run_data: RunData) -> str:
    """Return the content of ``review.md``.

    Structure, in this order:

    - ``# Eval review <date>-<name>``;
    - ``## Run data``: commit, date, catalog hash, models (``unknown`` when
      empty), every ``settings`` entry, the case count;
    - ``## Overview``: a Markdown table with one row per case and the
      columns id, category, expected outcome, automatic results (every
      metric whose status is ``pass``, ``fail`` or ``n/a``, as
      ``<metric>: <status>``) and open manual verdicts (the metrics with
      status ``manual``);
    - one section per case, headed exactly ``## Case <id>``, with the
      question (``search``) or URL and question (``analyze_url``),
      ``expected``, ``allowed_sources``, the answer text (``answer`` of the
      structured content; the error JSON for ``tool_error``; the failure for
      ``call_failed``), the returned sources, the automatic results and one
      line ``- verdict <metric>:`` with nothing after the colon for each
      metric whose status is ``manual``.

    Every text that comes from the case, the tool result or the web (input,
    expected, answer, sources, error JSON, failure) is rendered inside a
    fenced code block whose backtick fence is longer than any backtick run
    in that text, so it can never be read as a heading or verdict line.
    Contains no secret.
    """
    lines = [f"# Eval review {run_data.date}-{run_data.name}", ""]
    lines += _run_data_lines(records_count=len(records), run_data=run_data)
    lines += [
        "## How to score",
        "",
        "After the colon of every verdict line below, write `pass` or `fail`, optionally",
        "followed by a short note. An empty or misspelled verdict makes `score` fail.",
        "",
        "## Overview",
        "",
        "| id | category | expected outcome | automatic results | open manual verdicts |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in records:
        automatic = "; ".join(
            f"{metric}: {status}" for metric, status in record.checks.items() if status != "manual"
        )
        open_metrics = ", ".join(
            metric for metric, status in record.checks.items() if status == "manual"
        )
        cells = (
            record.id,
            record.category,
            record.expected_outcome,
            automatic,
            open_metrics or "-",
        )
        lines.append("| " + " | ".join(_cell(cell) for cell in cells) + " |")
    lines.append("")
    for record in records:
        lines += _case_section(record)
    return "\n".join(lines) + "\n"


_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,})")
_FENCE_CLOSE = re.compile(r"^ {0,3}`{3,}\s*$")
_CASE_HEADING = re.compile(r"^## Case (.+?)\s*$")
_VERDICT_LINE = re.compile(r"^- verdict (correctness|groundedness|honesty):(.*)$")
_VERDICT_VALUE = re.compile(r"^(pass|fail)(?:\s.*)?$")


def parse_review(
    text: str, records: Sequence[CaseRecord]
) -> dict[str, dict[Metric, ManualVerdict]]:
    """Read the manual verdicts from a filled-in ``review.md``.

    Parsing rules:

    - lines inside fenced code blocks are ignored;
    - a line ``## Case <id>`` starts the section of case ``<id>``; sections
      of ids not in ``records`` are ignored;
    - inside a case section, a line matching
      ``- verdict <metric>:<value>`` with ``<metric>`` in
      :data:`MANUAL_METRICS` is a verdict line; ``<value>`` is stripped;
      verdict lines for a metric whose status in the record is not
      ``manual`` are ignored;
    - a value is valid when it is exactly ``pass`` or ``fail``, optionally
      followed by whitespace and a free note (``pass matches RFC``);
      ``Pass``, ``pas``, ``passed`` or ``pass,`` are invalid.

    Returns:
        For every record, a mapping from each metric with status ``manual``
        to its verdict; records without manual metrics map to ``{}``.

    Raises:
        InvalidVerdictsError: listing every case and metric whose verdict is
            ``empty``, ``invalid``, ``missing`` or ``duplicate``.
    """
    by_id = {record.id: record for record in records}
    found: dict[tuple[str, Metric], list[str]] = {}
    current: str | None = None
    fence: int | None = None
    for line in text.splitlines():
        if fence is None:
            opening = _FENCE_OPEN.match(line)
            if opening:
                fence = len(opening.group(1))
                continue
            heading = _CASE_HEADING.match(line)
            if heading:
                case_id = heading.group(1)
                current = case_id if case_id in by_id else None
                continue
            verdict = _VERDICT_LINE.match(line)
            if verdict and current is not None:
                found.setdefault((current, verdict.group(1)), []).append(verdict.group(2).strip())
        elif _FENCE_CLOSE.match(line) and len(line.strip()) >= fence:
            fence = None
    problems: list[VerdictProblem] = []
    manual: dict[str, dict[Metric, ManualVerdict]] = {}
    for record in records:
        manual[record.id] = {}
        for metric in METRICS:
            if record.checks[metric] != "manual":
                continue
            values = found.get((record.id, metric), [])
            if not values:
                problems.append(VerdictProblem(record.id, metric, "missing"))
            elif len(values) > 1:
                problems.append(VerdictProblem(record.id, metric, "duplicate"))
            elif not values[0]:
                problems.append(VerdictProblem(record.id, metric, "empty"))
            elif not (match := _VERDICT_VALUE.match(values[0])):
                problems.append(VerdictProblem(record.id, metric, "invalid"))
            else:
                manual[record.id][metric] = match.group(1)
    if problems:
        raise InvalidVerdictsError(problems)
    return manual


def final_verdicts(
    record: CaseRecord, manual: Mapping[Metric, ManualVerdict]
) -> dict[Metric, FinalVerdict]:
    """Merge the automatic checks of ``record`` with its manual verdicts.

    ``pass``, ``fail`` and ``n/a`` from ``record.checks`` are kept; each
    ``manual`` status is replaced by ``manual[metric]``.

    Raises:
        KeyError: when a ``manual`` status has no entry in ``manual``.
    """
    merged: dict[Metric, FinalVerdict] = {}
    for metric in METRICS:
        status = record.checks[metric]
        merged[metric] = manual[metric] if status == "manual" else status
    return merged


def compute_rates(verdicts: Sequence[Mapping[Metric, FinalVerdict]]) -> list[MetricRate]:
    """Return one :class:`MetricRate` per metric of :data:`METRICS`, in that order.

    ``n/a`` verdicts count neither as passed nor in ``total``; thresholds come
    from :data:`THRESHOLDS`; ``met`` as defined in :class:`MetricRate`.
    """
    rates: list[MetricRate] = []
    for metric in METRICS:
        values = [verdict[metric] for verdict in verdicts]
        passed = values.count("pass")
        total = passed + values.count("fail")
        threshold = THRESHOLDS[metric]
        rates.append(
            MetricRate(
                metric=metric,
                passed=passed,
                total=total,
                rate_percent=100 * passed / total if total else None,
                threshold_percent=threshold,
                met=total > 0 and passed * 100 >= threshold * total,
            )
        )
    return rates


def percentile(values: Sequence[int], p: int) -> int | None:
    """Return the ``p``-th percentile of ``values`` by the nearest-rank method.

    The value at 1-based rank ``ceil(p / 100 * n)`` (at least 1) of the
    sorted values; ``None`` for an empty sequence.

    Raises:
        ValueError: when ``p`` is not between 1 and 100.
    """
    if not 1 <= p <= 100:
        raise ValueError(f"percentile must be between 1 and 100, got {p}")
    if not values:
        return None
    rank = max(1, -(-p * len(values) // 100))
    return sorted(values)[rank - 1]


def build_score_report(
    records: Sequence[CaseRecord], manual: Mapping[str, Mapping[Metric, ManualVerdict]]
) -> ScoreReport:
    """Compute rates, go/no-go, latency percentiles and token totals.

    ``manual`` is the :func:`parse_review` result; see :class:`ScoreReport`
    for every field.
    """
    verdicts = [final_verdicts(record, manual.get(record.id, {})) for record in records]
    rates = compute_rates(verdicts)
    latencies = [record.latency_ms for record in records]
    return ScoreReport(
        rates=rates,
        go=all(rate.met for rate in rates),
        latency_p50_ms=percentile(latencies, 50),
        latency_p95_ms=percentile(latencies, 95),
        input_tokens_total=sum(r.input_tokens for r in records if r.input_tokens is not None),
        output_tokens_total=sum(r.output_tokens for r in records if r.output_tokens is not None),
        case_count=len(records),
    )


def render_report(report: ScoreReport, run_data: RunData) -> str:
    """Return the content of ``report.md``.

    Contains the run data (as in :func:`render_review`), a table with one row
    per metric (metric, passed, total, rate with one decimal and ``%`` or
    ``n/a``, threshold, ``met``/``not met``), the overall result ``GO`` or
    ``NO-GO``, p50/p95 latency in ms (``n/a`` when unknown) and the input and
    output token totals. Contains no secret.
    """
    lines = [f"# Eval report {run_data.date}-{run_data.name}", ""]
    lines += _run_data_lines(records_count=report.case_count, run_data=run_data)
    lines += [
        "## Rates",
        "",
        "| metric | passed | total | rate | threshold | result |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for rate in report.rates:
        shown = "n/a" if rate.rate_percent is None else f"{rate.rate_percent:.1f}%"
        result = "met" if rate.met else "not met"
        lines.append(
            f"| {rate.metric} | {rate.passed} | {rate.total} | {shown} "
            f"| {rate.threshold_percent}% | {result} |"
        )
    p50 = "n/a" if report.latency_p50_ms is None else f"{report.latency_p50_ms} ms"
    p95 = "n/a" if report.latency_p95_ms is None else f"{report.latency_p95_ms} ms"
    lines += [
        "",
        "## Result",
        "",
        f"**{'GO' if report.go else 'NO-GO'}**",
        "",
        "## Latency and tokens",
        "",
        f"- latency p50: {p50}",
        f"- latency p95: {p95}",
        f"- input tokens: {report.input_tokens_total}",
        f"- output tokens: {report.output_tokens_total}",
    ]
    return "\n".join(lines) + "\n"


def score_command(run_dir: Path) -> ScoreReport:
    """Subcommand ``score``: score a filled-in run and write ``report.md``.

    Reads :data:`RESULTS_FILE`, :data:`RUN_DATA_FILE` and :data:`REVIEW_FILE`
    from ``run_dir``, parses the manual verdicts, builds the report and
    writes :data:`REPORT_FILE` (overwriting an earlier report).

    Raises:
        InvalidVerdictsError: on any unusable manual verdict; no report is
            written then.
        EvalAbort: when ``run_dir`` or one of the input files is missing or
            malformed; no report is written then.
    """
    if not run_dir.is_dir():
        raise EvalAbort(f"run directory {run_dir} does not exist")
    records = read_records(run_dir / RESULTS_FILE)
    try:
        run_data = RunData.from_json_dict(
            json.loads((run_dir / RUN_DATA_FILE).read_text(encoding="utf-8"))
        )
        review = (run_dir / REVIEW_FILE).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise EvalAbort(f"cannot read the run files in {run_dir}: {exc}") from exc
    report = build_score_report(records, parse_review(review, records))
    (run_dir / REPORT_FILE).write_text(render_report(report, run_data), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Command line entry point.

    Usage::

        run_eval.py run [--case <id>]... [--name <name>]
        run_eval.py score <run-dir>

    Args:
        argv: command line without the program name; ``None`` reads
            ``sys.argv[1:]``.
        environ: environment for ``run``; ``None`` means ``os.environ``.

    Behavior: ``run`` awaits :func:`run_command` and prints the run
    directory; ``score`` calls :func:`score_command` and prints the overall
    result and the report path. An :class:`EvalAbort` is printed to stderr.

    Returns:
        0 on success (for ``score`` independent of go/no-go), 1 on
        :class:`EvalAbort`. Invalid arguments exit with code 2 via argparse.
    """
    parser = argparse.ArgumentParser(
        description="Evaluate the Gemini Search MCP server against the catalog (ADR 0005)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run the catalog cases live (needs LIVE=1)")
    run_parser.add_argument(
        "--case", action="append", metavar="ID", help="run only this case id; repeatable"
    )
    run_parser.add_argument(
        "--name", default=DEFAULT_RUN_NAME, help="run name; default: %(default)s"
    )
    score_parser = commands.add_parser("score", help="score a filled-in run directory")
    score_parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            run_dir = asyncio.run(
                run_command(
                    environ=os.environ if environ is None else environ,
                    name=args.name,
                    case_ids=args.case or [],
                )
            )
            print(f"run directory: {run_dir}")
        else:
            report = score_command(args.run_dir)
            print(f"result: {'GO' if report.go else 'NO-GO'}")
            print(f"report: {args.run_dir / REPORT_FILE}")
    except EvalAbort as abort:
        print(f"error: {abort}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
