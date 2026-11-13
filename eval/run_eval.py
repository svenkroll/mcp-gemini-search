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

import importlib.util
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from fastmcp.client.transports import ClientTransport

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


class ServerLogReader:
    """Reads the server's JSON log lines incrementally from a file.

    The file is the server's stderr (stdio transport) or, in tests, the
    stream the in-memory server logs to. The file may not exist yet; it is
    then treated as empty.
    """

    def __init__(self, path: Path) -> None:
        """Remember ``path``; reading starts at the beginning of the file."""
        raise NotImplementedError

    def next_tool_call(self) -> ToolCallTelemetry | None:
        """Return the telemetry of the latest ``tool_call`` line since the last read.

        Reads every complete line appended since the previous call (the first
        call reads from the start), parses each as JSON and returns the data
        of the last line with ``"event": "tool_call"``. Lines that are not
        JSON objects, other events and lines without a string ``model`` are
        skipped. Returns ``None`` when no such line was appended. Never
        raises for malformed content.
        """
        raise NotImplementedError


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
        raise NotImplementedError

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> CaseRecord:
        """Rebuild a record from one parsed ``results.jsonl`` line.

        Raises:
            ValueError: when a key is missing or a value has the wrong type
                or an unknown literal value.
        """
        raise NotImplementedError


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
        raise NotImplementedError

    @classmethod
    def from_json_dict(cls, data: Mapping[str, Any]) -> RunData:
        """Rebuild run data from parsed ``run.json``.

        Raises:
            ValueError: when a key is missing or a value has the wrong type.
        """
        raise NotImplementedError


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
    raise NotImplementedError


def returned_sources(tool: str, structured_content: Mapping[str, Any] | None) -> list[str]:
    """Return the source URLs a successful tool result reports.

    ``search``: the ``url`` of every entry of ``sources`` (ADR 0003), in
    order. ``analyze_url``: a one-element list with ``url`` (ADR 0004).
    ``None`` (no successful result) or missing fields: an empty list.
    """
    raise NotImplementedError


def is_grounding_redirect(url: str) -> bool:
    """Return whether ``url`` is a Google grounding redirect URL.

    True when the URL's host, compared case-insensitively, is in
    :data:`GROUNDING_REDIRECT_HOSTS` or a subdomain of one of them. Never
    raises; an unparsable URL is not a redirect.
    """
    raise NotImplementedError


def is_allowed_source(url: str, allowed_sources: Sequence[str]) -> bool:
    """Return whether ``url`` lies within one of the ``allowed_sources`` domains.

    True when the URL's host, compared case-insensitively and without a
    trailing dot, equals an allowed domain or ends with ``"." + domain``
    (``www.rfc-editor.org`` is within ``rfc-editor.org``;
    ``evilrfc-editor.org`` is not). False for a URL without a host or one
    that cannot be parsed. Never raises.
    """
    raise NotImplementedError


def check_source_quality(
    sources: Sequence[str], allowed_sources: Sequence[str]
) -> Literal["pass", "fail"]:
    """Decide source quality (ADR 0005) for the returned ``sources``.

    ``pass`` when every source satisfies :func:`is_allowed_source` and none
    satisfies :func:`is_grounding_redirect`; otherwise ``fail``. An empty
    ``sources`` list passes (the rule holds for every returned source); the
    caller decides via :func:`applicability` whether the metric applies.
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


# --- run --------------------------------------------------------------------


def check_live_guard(environ: Mapping[str, str]) -> None:
    """Allow a live run only with ``LIVE=1`` and a non-empty ``GEMINI_API_KEY``.

    Raises:
        EvalAbort: when ``environ["LIVE"]`` is not exactly ``"1"``, or when
            ``GEMINI_API_KEY`` is missing or empty after stripping
            whitespace. The message names the variable, never a value.
    """
    raise NotImplementedError


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
    raise NotImplementedError


def select_cases(cases: Sequence[Any], case_ids: Sequence[str]) -> list[Any]:
    """Restrict ``cases`` to ``case_ids`` (``--case``).

    Returns every case, in catalog order, when ``case_ids`` is empty;
    otherwise the cases whose id is in ``case_ids``, in catalog order, each
    once even if given twice.

    Raises:
        EvalAbort: when an id in ``case_ids`` is not in ``cases``; the message
            names every unknown id.
    """
    raise NotImplementedError


def server_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """Return the server's environment: ``environ`` plus :data:`SERVER_ENV_OVERRIDES`.

    The overrides replace values already in ``environ``; ``environ`` itself is
    not modified.
    """
    raise NotImplementedError


def stdio_transport(env: Mapping[str, str], log_path: Path) -> ClientTransport:
    """Default transport factory: the console script :data:`SERVER_COMMAND` via stdio.

    Returns a FastMCP ``StdioTransport`` running :data:`SERVER_COMMAND`
    without arguments, with environment ``env``, ``keep_alive=False`` and the
    server's stderr written to ``log_path``. Starts no process by itself.
    """
    raise NotImplementedError


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
    raise NotImplementedError


def catalog_hash(cases_dir: Path = CASES_DIR) -> str:
    """Return the SHA-256 hex digest identifying the catalog contents.

    Hashes every non-hidden ``*.yaml`` file of ``cases_dir`` in file name
    order, each as its file name (UTF-8), a NUL byte, its raw bytes and a NUL
    byte. Independent of which cases a run selects.
    """
    raise NotImplementedError


def git_commit() -> str:
    """Return ``git rev-parse HEAD`` of the repository, or ``"unknown"`` on any failure."""
    raise NotImplementedError


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
    raise NotImplementedError


def append_record(results_path: Path, record: CaseRecord) -> None:
    """Append ``record`` as one JSON line to ``results_path`` and flush it."""
    raise NotImplementedError


def read_records(results_path: Path) -> list[CaseRecord]:
    """Read every record of a ``results.jsonl`` file, in file order.

    Raises:
        EvalAbort: when the file is missing, a line is not valid JSON or not
            a valid record; the message names the file and the line number.
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


# --- review and score -------------------------------------------------------


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
    raise NotImplementedError


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
    raise NotImplementedError


def final_verdicts(
    record: CaseRecord, manual: Mapping[Metric, ManualVerdict]
) -> dict[Metric, FinalVerdict]:
    """Merge the automatic checks of ``record`` with its manual verdicts.

    ``pass``, ``fail`` and ``n/a`` from ``record.checks`` are kept; each
    ``manual`` status is replaced by ``manual[metric]``.

    Raises:
        KeyError: when a ``manual`` status has no entry in ``manual``.
    """
    raise NotImplementedError


def compute_rates(verdicts: Sequence[Mapping[Metric, FinalVerdict]]) -> list[MetricRate]:
    """Return one :class:`MetricRate` per metric of :data:`METRICS`, in that order.

    ``n/a`` verdicts count neither as passed nor in ``total``; thresholds come
    from :data:`THRESHOLDS`; ``met`` as defined in :class:`MetricRate`.
    """
    raise NotImplementedError


def percentile(values: Sequence[int], p: int) -> int | None:
    """Return the ``p``-th percentile of ``values`` by the nearest-rank method.

    The value at 1-based rank ``ceil(p / 100 * n)`` (at least 1) of the
    sorted values; ``None`` for an empty sequence.

    Raises:
        ValueError: when ``p`` is not between 1 and 100.
    """
    raise NotImplementedError


def build_score_report(
    records: Sequence[CaseRecord], manual: Mapping[str, Mapping[Metric, ManualVerdict]]
) -> ScoreReport:
    """Compute rates, go/no-go, latency percentiles and token totals.

    ``manual`` is the :func:`parse_review` result; see :class:`ScoreReport`
    for every field.
    """
    raise NotImplementedError


def render_report(report: ScoreReport, run_data: RunData) -> str:
    """Return the content of ``report.md``.

    Contains the run data (as in :func:`render_review`), a table with one row
    per metric (metric, passed, total, rate with one decimal and ``%`` or
    ``n/a``, threshold, ``met``/``not met``), the overall result ``GO`` or
    ``NO-GO``, p50/p95 latency in ms (``n/a`` when unknown) and the input and
    output token totals. Contains no secret.
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
