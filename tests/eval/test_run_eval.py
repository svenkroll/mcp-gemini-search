"""Acceptance tests for the eval script (issue #10, ADR 0005).

The script ``eval/run_eval.py`` is not part of a package, so it is loaded from
its file path. Everything runs without network access and without a real
Gemini key: the end-to-end tests drive the in-memory FastMCP server built with
the ``FakeProvider``; the few tests that start a process use a tiny local
Python script, never the real server. Keys in fixtures are obviously fake.

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order of
the issue. AC8 (README) is a review criterion and AC9 (smoke run) is manual;
neither has a test.
"""

import asyncio
import importlib.util
import json
import logging
import re
import sys
import textwrap
from collections.abc import Iterable, Iterator, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastmcp import FastMCP
from fastmcp.client.transports import ClientTransport, FastMCPTransport, StdioTransport
from fastmcp.exceptions import ToolError

from gemini_search_mcp.config import Settings
from gemini_search_mcp.provider import (
    Citation,
    FakeProvider,
    Retrieval,
    SearchResult,
    UrlAnalysisResult,
    Usage,
)
from gemini_search_mcp.server import TOOL_CALL_LOGGER_NAME, build_server, configure_logging

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_EVAL_PATH = REPO_ROOT / "eval" / "run_eval.py"
TODAY = date(2026, 11, 13)

# Obviously fake values; they never leave this test process.
FAKE_KEY = "fake-gemini-key-AIzaSyFAKE0123456789"
FAKE_BEARER = "fake-bearer-value-" + "x" * 20
FAKE_OTHER = "fake-other-secret-value-12345"
FAKE_CONFIG_MODEL = "fake-model-config"
FAKE_REPORTED_MODEL = "fake-model-reported"

CONFIG_VARIABLES = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GEMINI_TIMEOUT_SECONDS",
    "GEMINI_MAX_CONCURRENCY",
    "GEMINI_MAX_RETRIES",
    "ANALYZE_URL_ENABLED",
    "LOG_QUERIES",
    "LOG_LEVEL",
    "MCP_TRANSPORT",
    "MCP_HOST",
    "MCP_PORT",
    "MCP_BEARER_TOKEN",
)

LIVE_ENVIRON = {"LIVE": "1", "GEMINI_API_KEY": FAKE_KEY}


def _load_run_eval() -> Any:
    spec = importlib.util.spec_from_file_location("run_eval", RUN_EVAL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_eval"] = module
    spec.loader.exec_module(module)
    return module


run_eval = _load_run_eval()


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*CONFIG_VARIABLES, "LIVE"):
        monkeypatch.delenv(name, raising=False)


# --- helpers: catalog -------------------------------------------------------

_CATEGORY_PREFIX = {
    "stable_fact": "search-stable",
    "current_fact": "search-current",
    "tech_docs": "search-techdocs",
    "german": "search-german",
    "english": "search-english",
    "honest_unknown": "search-honest-unknown",
    "url_html": "analyze-url-html",
    "url_pdf": "analyze-url-pdf",
    "url_failure": "analyze-url-failure",
}


def _case_data(category: str, number: int) -> dict[str, Any]:
    prefix = _CATEGORY_PREFIX[category]
    case_id = f"{prefix}-{number:03d}"
    if category.startswith("url_"):
        tool = "analyze_url"
        case_input = {
            "url": f"https://example.com/{case_id}",
            "question": f"What does {case_id} say?",
        }
        allowed = ["example.com"]
    else:
        tool = "search"
        case_input = {"query": f"Question for {case_id}?"}
        allowed = ["rfc-editor.org"]
    outcome = "answer"
    if category == "honest_unknown":
        outcome = "honest_unknown"
    elif category == "url_failure":
        outcome = "error:url_unreachable"
    return {
        "id": case_id,
        "tool": tool,
        "category": category,
        "input": case_input,
        "expected": f"Expected statement of {case_id}.",
        "allowed_sources": allowed,
        "ground_truth_date": "2026-11-12",
        "expected_outcome": outcome,
    }


def _write_catalog(
    cases_dir: Path, overrides: Mapping[str, Mapping[str, Any]] | None = None
) -> None:
    """Write a catalog that passes ``--strict`` (minimum distribution, no drafts)."""
    cases_dir.mkdir(parents=True, exist_ok=True)
    minimum = run_eval.catalog.MINIMUM_DISTRIBUTION
    for category, count in minimum.items():
        for number in range(1, count + 1):
            data = _case_data(category, number)
            data.update((overrides or {}).get(data["id"], {}))
            (cases_dir / f"{data['id']}.yaml").write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )


def _cases(cases_dir: Path, ids: Iterable[str]) -> list[Any]:
    return run_eval.select_cases(run_eval.catalog.load_catalog(cases_dir), list(ids))


# --- helpers: records, verdicts, run directories ----------------------------

ANSWER_CHECKS = {
    "correctness": "manual",
    "groundedness": "manual",
    "source_quality": "pass",
    "honesty": "n/a",
}
HONEST_CHECKS = {
    "correctness": "n/a",
    "groundedness": "n/a",
    "source_quality": "n/a",
    "honesty": "manual",
}
ERROR_CHECKS = {
    "correctness": "pass",
    "groundedness": "n/a",
    "source_quality": "n/a",
    "honesty": "n/a",
}


def _error_json(code: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": "Short message.", "request_id": "req-1"}}


def _record(
    case_id: str = "search-stable-001",
    *,
    expected_outcome: str = "answer",
    checks: Mapping[str, str] | None = None,
    outcome: str = "ok",
    answer: str = "The answer.",
    latency_ms: int = 100,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    model: str | None = None,
) -> Any:
    structured: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    failure: str | None = None
    if outcome == "ok":
        structured = {"answer": answer, "sources": [], "search_queries": []}
    elif outcome == "tool_error":
        error = _error_json("url_unreachable")
    else:
        failure = "timeout after 1 s"
    return run_eval.CaseRecord(
        id=case_id,
        tool="search",
        category="stable_fact",
        expected_outcome=expected_outcome,
        input={"query": f"Question for {case_id}?"},
        expected="Expected statement.",
        allowed_sources=["rfc-editor.org"],
        outcome=outcome,
        structured_content=structured,
        error_json=error,
        failure=failure,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model=model,
        checks=dict(checks if checks is not None else ANSWER_CHECKS),
    )


def _run_data(case_ids: list[str], *, models: list[str] | None = None) -> Any:
    return run_eval.RunData(
        name="t",
        date=TODAY.isoformat(),
        commit="abc1234",
        catalog_hash="0" * 64,
        models=models if models is not None else ["fake-model-reported"],
        settings={"GEMINI_MODEL": "default", "call_timeout_seconds": "180.0"},
        case_ids=case_ids,
    )


def _write_run_dir(base: Path, records: list[Any]) -> Path:
    """Write the three input files of ``score`` the way ``run`` does."""
    run_dir = base / "2026-11-13-t"
    run_dir.mkdir(parents=True)
    for record in records:
        run_eval.append_record(run_dir / run_eval.RESULTS_FILE, record)
    data = _run_data([record.id for record in records])
    (run_dir / run_eval.RUN_DATA_FILE).write_text(json.dumps(data.to_json_dict()), encoding="utf-8")
    (run_dir / run_eval.REVIEW_FILE).write_text(
        run_eval.render_review(records, data), encoding="utf-8"
    )
    return run_dir


def _fill(review: str, values: Mapping[tuple[str, str], str]) -> str:
    """Fill ``- verdict <metric>:`` lines of the given (case id, metric) pairs.

    Lines inside fenced code blocks are left untouched.
    """
    out: list[str] = []
    case_id: str | None = None
    fence: int | None = None
    for line in review.splitlines():
        fence_match = re.match(r"^(`{3,})", line)
        if fence is None and fence_match:
            fence = len(fence_match.group(1))
        elif fence is not None and re.fullmatch(f"`{{{fence},}}", line.strip()):
            fence = None
        elif fence is None:
            heading = re.match(r"^## Case (.+)$", line)
            if heading:
                case_id = heading.group(1).strip()
            verdict = re.match(r"^- verdict ([a-z_]+):\s*$", line)
            if verdict and case_id is not None:
                key = (case_id, verdict.group(1))
                if key in values:
                    line = f"- verdict {key[1]}: {values[key]}"
        out.append(line)
    return "\n".join(out) + "\n"


def _verdicts(metric: str, *, passed: int, failed: int = 0, na: int = 0) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for count, value in ((passed, "pass"), (failed, "fail"), (na, "n/a")):
        for _ in range(count):
            row = dict.fromkeys(run_eval.METRICS, "n/a")
            row[metric] = value
            rows.append(row)
    return rows


def _rate(rates: list[Any], metric: str) -> Any:
    return next(rate for rate in rates if rate.metric == metric)


# --- helpers: in-memory server ----------------------------------------------


async def _identity_resolver(urls: Iterable[str], /) -> Mapping[str, str | None]:
    return {url: url for url in urls}


class _InMemoryServer:
    """Transport factory: the in-memory server with a ``FakeProvider``.

    Logs the ADR 0007 JSON lines into the log file the script asks for, like
    the real server's stderr, and records what the script passed in.
    """

    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider
        self.calls: list[tuple[dict[str, str], Path]] = []
        self._streams: list[Any] = []

    def __call__(self, env: Mapping[str, str], log_path: Path) -> ClientTransport:
        self.calls.append((dict(env), log_path))
        stream = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        self._streams.append(stream)
        configure_logging("info", stream)
        settings = Settings(
            gemini_api_key=FAKE_KEY,
            gemini_model=FAKE_CONFIG_MODEL,
            analyze_url_enabled=True,
        )
        server = build_server(settings, self.provider, resolver=_identity_resolver)
        return FastMCPTransport(server)

    def close(self) -> None:
        for stream in self._streams:
            stream.close()


@pytest.fixture
def in_memory() -> Iterator[Any]:
    """Build in-memory transport factories; restore process logging afterwards."""
    root = logging.getLogger()
    tool_logger = logging.getLogger(TOOL_CALL_LOGGER_NAME)
    saved_handlers = list(root.handlers)
    saved_levels = (root.level, tool_logger.level)
    created: list[_InMemoryServer] = []

    def make(provider: FakeProvider) -> _InMemoryServer:
        factory = _InMemoryServer(provider)
        created.append(factory)
        return factory

    try:
        yield make
    finally:
        for factory in created:
            factory.close()
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_levels[0])
        tool_logger.setLevel(saved_levels[1])


class _RecordingFactory:
    """Transport factory that must never be called in a pre-flight abort test."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, env: Mapping[str, str], log_path: Path) -> ClientTransport:
        self.calls += 1
        raise AssertionError("the transport factory must not be called")


def _search_result(answer: str, urls: list[str], *, usage: Usage, model: str) -> SearchResult:
    citations = [Citation(url=url, title="Title", start_index=0, end_index=3) for url in urls]
    return SearchResult(
        answer=answer,
        citations=citations,
        search_queries=["q"],
        usage=usage,
        model=model,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# E2E case ids; sorted by file name, which is the run order.
E2E_IDS = [
    "analyze-url-failure-001",
    "analyze-url-html-001",
    "search-honest-unknown-001",
    "search-stable-001",
]
E2E_TOKEN_TOTALS = (180, 35)


def _e2e_provider() -> FakeProvider:
    html_url = "https://example.com/analyze-url-html-001"
    failure_url = "https://example.com/analyze-url-failure-001"
    return FakeProvider(
        search_outcomes=[
            _search_result(
                "The figure is not publicly known.",
                [],
                usage=Usage(30, 5),
                model=FAKE_REPORTED_MODEL,
            ),
            _search_result(
                "RFC 1035 was published in November 1987.",
                ["https://www.rfc-editor.org/rfc/rfc1035"],
                usage=Usage(50, 10),
                model=FAKE_REPORTED_MODEL,
            ),
        ],
        analyze_url_outcomes=[
            UrlAnalysisResult(
                answer="unused",
                retrievals=[Retrieval(url=failure_url, status="failed")],
                usage=Usage(1, 1),
                model=FAKE_REPORTED_MODEL,
            ),
            UrlAnalysisResult(
                answer="The page describes the price.",
                retrievals=[Retrieval(url=html_url, status="retrieved")],
                usage=Usage(100, 20),
                model=FAKE_REPORTED_MODEL,
            ),
        ],
    )


class _E2E:
    def __init__(self, tmp_path: Path, factory: _InMemoryServer, environ: dict[str, str]) -> None:
        self.cases_dir = tmp_path / "cases"
        self.runs_dir = tmp_path / "runs"
        self.factory = factory
        self.environ = environ
        _write_catalog(self.cases_dir)

    def run(self, name: str = "e2e") -> Path:
        return _run(
            run_eval.run_command(
                environ=self.environ,
                name=name,
                case_ids=E2E_IDS,
                cases_dir=self.cases_dir,
                runs_dir=self.runs_dir,
                today=TODAY,
                transport_factory=self.factory,
            )
        )


@pytest.fixture
def e2e(tmp_path: Path, in_memory: Any) -> _E2E:
    environ = {
        **LIVE_ENVIRON,
        "GEMINI_MODEL": FAKE_CONFIG_MODEL,
        "MCP_BEARER_TOKEN": FAKE_BEARER,
        "SOME_OTHER_SECRET": FAKE_OTHER,
    }
    return _E2E(tmp_path, in_memory(_e2e_provider()), environ)


E2E_FILLED = {
    ("analyze-url-html-001", "correctness"): "pass",
    ("analyze-url-html-001", "groundedness"): "fail wrong price",
    ("search-honest-unknown-001", "honesty"): "pass",
    ("search-stable-001", "correctness"): "pass matches RFC",
    ("search-stable-001", "groundedness"): "pass",
}


# --- AC1: automatic checks ---------------------------------------------------


@pytest.mark.parametrize(
    ("url", "allowed", "expected"),
    [
        ("https://rfc-editor.org/rfc/rfc1035", ["rfc-editor.org"], True),
        ("https://RFC-Editor.ORG/rfc/rfc1035", ["rfc-editor.org"], True),
        ("https://rfc-editor.org./rfc/rfc1035", ["rfc-editor.org"], True),
        ("https://ietf.org/x", ["rfc-editor.org", "ietf.org"], True),
        ("https://example.com/x", ["rfc-editor.org"], False),
        ("https://evilrfc-editor.org/x", ["rfc-editor.org"], False),
        ("https://rfc-editor.org.evil.com/x", ["rfc-editor.org"], False),
        ("not a url", ["rfc-editor.org"], False),
        ("", ["rfc-editor.org"], False),
    ],
)
def test_ac1_allowed_domain_hits_and_misses(url: str, allowed: list[str], expected: bool) -> None:
    assert run_eval.is_allowed_source(url, allowed) is expected


def test_ec6_subdomain_of_an_allowed_domain_is_within_allowed_sources() -> None:
    assert run_eval.is_allowed_source("https://www.rfc-editor.org/rfc/rfc1035", ["rfc-editor.org"])
    assert (
        run_eval.check_source_quality(
            ["https://www.rfc-editor.org/rfc/rfc1035"], ["rfc-editor.org"]
        )
        == "pass"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbC123",
            True,
        ),
        ("https://VertexAISearch.cloud.google.com/grounding-api-redirect/x", True),
        ("https://www.rfc-editor.org/rfc/rfc1035", False),
        ("https://cloud.google.com/docs", False),
    ],
)
def test_ac1_redirect_url_hits_and_misses(url: str, expected: bool) -> None:
    assert run_eval.is_grounding_redirect(url) is expected


def test_ac1_source_quality_passes_when_every_source_is_allowed() -> None:
    sources = ["https://rfc-editor.org/a", "https://www.ietf.org/b"]
    assert run_eval.check_source_quality(sources, ["rfc-editor.org", "ietf.org"]) == "pass"


def test_ac1_source_quality_fails_when_one_source_is_not_allowed() -> None:
    sources = ["https://rfc-editor.org/a", "https://example.com/b"]
    assert run_eval.check_source_quality(sources, ["rfc-editor.org"]) == "fail"


def test_ac1_source_quality_fails_for_a_redirect_url_even_inside_an_allowed_domain() -> None:
    sources = ["https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbC123"]
    assert run_eval.check_source_quality(sources, ["google.com"]) == "fail"


def test_ac1_error_code_hit_and_misses() -> None:
    expected = "error:url_unreachable"
    assert (
        run_eval.check_error_code(expected, "tool_error", _error_json("url_unreachable")) == "pass"
    )
    assert run_eval.check_error_code(expected, "tool_error", _error_json("url_unsafe")) == "fail"
    assert run_eval.check_error_code(expected, "ok", None) == "fail"
    assert run_eval.check_error_code(expected, "call_failed", None) == "fail"


def test_ac1_returned_sources_of_both_tools() -> None:
    search = {
        "answer": "a",
        "sources": [
            {"title": "t", "url": "https://rfc-editor.org/a", "evidence": []},
            {"title": "t", "url": "https://ietf.org/b", "evidence": []},
        ],
        "search_queries": [],
    }
    analyze = {"answer": "a", "url": "https://example.com/p", "retrieval_status": "retrieved"}

    assert run_eval.returned_sources("search", search) == [
        "https://rfc-editor.org/a",
        "https://ietf.org/b",
    ]
    assert run_eval.returned_sources("analyze_url", analyze) == ["https://example.com/p"]
    assert run_eval.returned_sources("search", None) == []
    assert run_eval.returned_sources("analyze_url", None) == []


def test_ac1_automatic_checks_decide_error_code_and_source_quality() -> None:
    hit = run_eval.automatic_checks(
        expected_outcome="error:url_unreachable",
        outcome="tool_error",
        sources=[],
        error_json=_error_json("url_unreachable"),
        allowed_sources=["example.com"],
    )
    miss = run_eval.automatic_checks(
        expected_outcome="error:url_unreachable",
        outcome="tool_error",
        sources=[],
        error_json=_error_json("url_unsafe"),
        allowed_sources=["example.com"],
    )
    bad_source = run_eval.automatic_checks(
        expected_outcome="answer",
        outcome="ok",
        sources=["https://example.com/x"],
        error_json=None,
        allowed_sources=["rfc-editor.org"],
    )

    assert hit["correctness"] == "pass"
    assert miss["correctness"] == "fail"
    assert bad_source["source_quality"] == "fail"


# --- AC2: applicability ------------------------------------------------------


@pytest.mark.parametrize(
    ("expected_outcome", "has_sources", "expected"),
    [
        ("answer", True, ("manual", "manual", "automatic", "n/a")),
        ("answer", False, ("manual", "manual", "automatic", "n/a")),
        ("honest_unknown", True, ("n/a", "n/a", "automatic", "manual")),
        ("honest_unknown", False, ("n/a", "n/a", "n/a", "manual")),
        ("error:url_unreachable", False, ("automatic", "n/a", "n/a", "n/a")),
        ("error:invalid_input", True, ("automatic", "n/a", "n/a", "n/a")),
    ],
)
def test_ac2_applicability_follows_the_table(
    expected_outcome: str, has_sources: bool, expected: tuple[str, str, str, str]
) -> None:
    result = run_eval.applicability(expected_outcome, has_sources=has_sources)

    assert tuple(result[metric] for metric in run_eval.METRICS) == expected


def test_ac2_applicability_rejects_an_unknown_expected_outcome() -> None:
    with pytest.raises(ValueError, match=r"."):
        run_eval.applicability("maybe", has_sources=False)


def test_ac2_automatic_checks_leave_manual_metrics_open_and_decide_the_rest() -> None:
    answer = run_eval.automatic_checks(
        expected_outcome="answer",
        outcome="ok",
        sources=["https://rfc-editor.org/a"],
        error_json=None,
        allowed_sources=["rfc-editor.org"],
    )
    honest_with_sources = run_eval.automatic_checks(
        expected_outcome="honest_unknown",
        outcome="ok",
        sources=["https://example.com/a"],
        error_json=None,
        allowed_sources=["rfc-editor.org"],
    )
    honest_without_sources = run_eval.automatic_checks(
        expected_outcome="honest_unknown",
        outcome="ok",
        sources=[],
        error_json=None,
        allowed_sources=["rfc-editor.org"],
    )

    assert answer == {
        "correctness": "manual",
        "groundedness": "manual",
        "source_quality": "pass",
        "honesty": "n/a",
    }
    assert honest_with_sources == {
        "correctness": "n/a",
        "groundedness": "n/a",
        "source_quality": "fail",
        "honesty": "manual",
    }
    assert honest_without_sources == HONEST_CHECKS


def test_ac2_answer_case_with_a_tool_error_fails_correctness_and_groundedness() -> None:
    checks = run_eval.automatic_checks(
        expected_outcome="answer",
        outcome="tool_error",
        sources=[],
        error_json=_error_json("upstream_unavailable"),
        allowed_sources=["rfc-editor.org"],
    )

    assert checks["correctness"] == "fail"
    assert checks["groundedness"] == "fail"
    assert checks["honesty"] == "n/a"


def test_ac2_error_case_that_succeeds_fails_correctness() -> None:
    checks = run_eval.automatic_checks(
        expected_outcome="error:url_unreachable",
        outcome="ok",
        sources=["https://example.com/a"],
        error_json=None,
        allowed_sources=["example.com"],
    )

    assert checks == {**ERROR_CHECKS, "correctness": "fail"}


# --- AC3: rates and go/no-go -------------------------------------------------


THRESHOLD_STEPS = [
    ("correctness", 85, -1),
    ("correctness", 85, 0),
    ("correctness", 85, 1),
    ("groundedness", 85, -1),
    ("groundedness", 85, 0),
    ("groundedness", 85, 1),
    ("source_quality", 90, -1),
    ("source_quality", 90, 0),
    ("source_quality", 90, 1),
    ("honesty", 100, -1),
    ("honesty", 100, 0),
]


@pytest.mark.parametrize(("metric", "threshold", "delta"), THRESHOLD_STEPS)
def test_ac3_threshold_just_below_exactly_at_and_just_above(
    metric: str, threshold: int, delta: int
) -> None:
    passed = threshold + delta
    rates = run_eval.compute_rates(_verdicts(metric, passed=passed, failed=100 - passed))

    rate = _rate(rates, metric)
    assert rate.passed == passed
    assert rate.total == 100
    assert rate.rate_percent == pytest.approx(float(passed))
    assert rate.threshold_percent == threshold
    assert rate.met is (delta >= 0)


@pytest.mark.parametrize(
    ("metric", "passed", "total", "met"),
    [
        ("source_quality", 9, 10, True),
        ("source_quality", 63, 70, True),
        ("source_quality", 62, 70, False),
        ("correctness", 17, 20, True),
        ("correctness", 16, 20, False),
        ("groundedness", 34, 40, True),
        ("honesty", 3, 3, True),
        ("honesty", 2, 3, False),
    ],
)
def test_ec7_rate_exactly_at_a_threshold_meets_it(
    metric: str, passed: int, total: int, met: bool
) -> None:
    rates = run_eval.compute_rates(_verdicts(metric, passed=passed, failed=total - passed))

    assert _rate(rates, metric).met is met


def test_ac3_na_cases_do_not_count_in_the_denominator() -> None:
    rates = run_eval.compute_rates(_verdicts("source_quality", passed=9, failed=1, na=5))

    rate = _rate(rates, "source_quality")
    assert (rate.passed, rate.total) == (9, 10)
    assert rate.rate_percent == pytest.approx(90.0)
    assert rate.met is True


def test_ac3_rates_come_in_metric_order() -> None:
    rates = run_eval.compute_rates(_verdicts("honesty", passed=1))

    assert [rate.metric for rate in rates] == list(run_eval.METRICS)


def test_ec8_metric_with_only_na_cases_has_no_rate_and_is_not_met() -> None:
    rates = run_eval.compute_rates(_verdicts("honesty", passed=0, na=4))

    rate = _rate(rates, "honesty")
    assert rate.total == 0
    assert rate.rate_percent is None
    assert rate.met is False


def _all_pass_records(count: int = 20) -> list[Any]:
    all_pass = dict.fromkeys(run_eval.METRICS, "pass")
    return [_record(f"case-{number:03d}", checks=all_pass) for number in range(count)]


def test_ac3_go_when_every_threshold_is_met() -> None:
    report = run_eval.build_score_report(_all_pass_records(), {})

    assert [rate.metric for rate in report.rates] == list(run_eval.METRICS)
    assert all(rate.met for rate in report.rates)
    assert report.go is True
    assert report.case_count == 20


def test_ac3_no_go_when_one_threshold_is_missed() -> None:
    records = _all_pass_records()
    records[0] = _record("case-000", checks={**records[0].checks, "honesty": "fail"})

    report = run_eval.build_score_report(records, {})

    assert _rate(report.rates, "honesty").met is False
    assert report.go is False


def test_ec8_no_go_when_a_metric_has_only_na_cases() -> None:
    records = [
        _record(
            f"case-{number}",
            checks={**ANSWER_CHECKS, "correctness": "pass", "groundedness": "pass"},
        )
        for number in range(5)
    ]

    report = run_eval.build_score_report(records, {})

    assert _rate(report.rates, "honesty").rate_percent is None
    assert report.go is False


def test_ac3_report_merges_manual_verdicts_into_the_rates() -> None:
    records = [_record("case-a"), _record("case-b")]
    manual = {
        "case-a": {"correctness": "pass", "groundedness": "pass"},
        "case-b": {"correctness": "fail", "groundedness": "pass"},
    }

    report = run_eval.build_score_report(records, manual)

    correctness = _rate(report.rates, "correctness")
    groundedness = _rate(report.rates, "groundedness")
    assert (correctness.passed, correctness.total) == (1, 2)
    assert (groundedness.passed, groundedness.total) == (2, 2)


def test_ac3_report_has_latency_percentiles_and_token_totals() -> None:
    records = [
        _record("case-a", latency_ms=10, input_tokens=100, output_tokens=7),
        _record("case-b", latency_ms=50, input_tokens=None, output_tokens=None),
        _record("case-c", latency_ms=30, input_tokens=5, output_tokens=3),
        _record("case-d", latency_ms=20, input_tokens=1, output_tokens=None),
        _record("case-e", latency_ms=40),
    ]
    manual = {record.id: {"correctness": "pass", "groundedness": "pass"} for record in records}

    report = run_eval.build_score_report(records, manual)

    assert report.latency_p50_ms == 30
    assert report.latency_p95_ms == 50
    assert report.input_tokens_total == 106
    assert report.output_tokens_total == 10


def test_ac3_percentile_uses_the_nearest_rank_method() -> None:
    values = [7, 1, 10, 3, 5, 9, 2, 8, 4, 6]

    assert run_eval.percentile(values, 50) == 5
    assert run_eval.percentile(values, 95) == 10
    assert run_eval.percentile(values, 100) == 10
    assert run_eval.percentile([42], 95) == 42
    assert run_eval.percentile([], 50) is None
    for invalid in (0, 101):
        with pytest.raises(ValueError, match=r"."):
            run_eval.percentile(values, invalid)


def test_ac3_final_verdicts_merge_automatic_and_manual_results() -> None:
    record = _record(checks={**ANSWER_CHECKS, "source_quality": "fail"})

    merged = run_eval.final_verdicts(record, {"correctness": "pass", "groundedness": "fail"})

    assert merged == {
        "correctness": "pass",
        "groundedness": "fail",
        "source_quality": "fail",
        "honesty": "n/a",
    }
    with pytest.raises(KeyError):
        run_eval.final_verdicts(record, {"correctness": "pass"})


def test_ec8_report_shows_na_rate_and_not_met() -> None:
    records = [
        _record(
            f"case-{number}",
            checks={**ANSWER_CHECKS, "correctness": "pass", "groundedness": "pass"},
        )
        for number in range(5)
    ]
    report = run_eval.build_score_report(records, {})

    text = run_eval.render_report(report, _run_data([record.id for record in records]))

    honesty_line = next(
        line for line in text.splitlines() if re.search(r"honesty", line, re.IGNORECASE)
    )
    assert "n/a" in honesty_line
    assert "not met" in honesty_line
    assert "NO-GO" in text


def test_ac3_report_shows_met_at_exactly_the_threshold() -> None:
    checks = [
        {**ERROR_CHECKS, "source_quality": "pass" if number < 9 else "fail"} for number in range(10)
    ]
    records = [_record(f"case-{number}", checks=check) for number, check in enumerate(checks)]
    report = run_eval.build_score_report(records, {})

    text = run_eval.render_report(report, _run_data([record.id for record in records]))

    line = next(
        line for line in text.splitlines() if re.search(r"source[_ ]quality", line, re.IGNORECASE)
    )
    assert "90.0%" in line
    assert "not met" not in line


def test_ac3_report_states_go_and_no_go() -> None:
    go = run_eval.build_score_report(_all_pass_records(), {})
    no_go = run_eval.build_score_report(
        [_record("case-a", checks={**ERROR_CHECKS, "correctness": "fail"})], {}
    )
    data = _run_data(["case-a"])

    go_text = run_eval.render_report(go, data)
    no_go_text = run_eval.render_report(no_go, data)

    assert "NO-GO" not in go_text
    assert "GO" in go_text
    assert "NO-GO" in no_go_text


# --- review.md: rendering and parsing ----------------------------------------


def test_ac4_review_has_a_section_and_verdict_lines_for_every_manual_metric() -> None:
    records = [
        _record("case-a"),
        _record("case-b", expected_outcome="honest_unknown", checks=HONEST_CHECKS),
        _record("case-c", expected_outcome="error:url_unreachable", checks=ERROR_CHECKS),
    ]

    text = run_eval.render_review(records, _run_data(["case-a", "case-b", "case-c"]))
    lines = [line.rstrip() for line in text.splitlines()]

    for case_id in ("case-a", "case-b", "case-c"):
        assert f"## Case {case_id}" in lines
    assert lines.count("- verdict correctness:") == 1
    assert lines.count("- verdict groundedness:") == 1
    assert lines.count("- verdict honesty:") == 1
    assert "- verdict source_quality:" not in lines


def test_ac6_review_shows_the_run_data() -> None:
    data = run_eval.RunData(
        name="smoke",
        date="2026-11-13",
        commit="abc1234def",
        catalog_hash="f" * 64,
        models=["model-one"],
        settings={"GEMINI_MODEL": "model-one", "call_timeout_seconds": "180.0"},
        case_ids=["case-a"],
    )

    text = run_eval.render_review([_record("case-a")], data)

    for fact in ("abc1234def", "2026-11-13", "f" * 64, "model-one"):
        assert fact in text


def test_ac4_parse_returns_the_filled_in_verdicts() -> None:
    records = [
        _record("case-a"),
        _record("case-b", expected_outcome="honest_unknown", checks=HONEST_CHECKS),
        _record("case-c", expected_outcome="error:url_unreachable", checks=ERROR_CHECKS),
    ]
    review = run_eval.render_review(records, _run_data(["case-a", "case-b", "case-c"]))
    filled = _fill(
        review,
        {
            ("case-a", "correctness"): "pass",
            ("case-a", "groundedness"): "fail the date is wrong",
            ("case-b", "honesty"): "pass",
        },
    )

    parsed = run_eval.parse_review(filled, records)

    assert parsed == {
        "case-a": {"correctness": "pass", "groundedness": "fail"},
        "case-b": {"honesty": "pass"},
        "case-c": {},
    }


def test_ec9_parse_names_case_and_metric_of_an_empty_verdict() -> None:
    records = [_record("case-a"), _record("case-b")]
    review = run_eval.render_review(records, _run_data(["case-a", "case-b"]))
    filled = _fill(
        review,
        {
            ("case-a", "correctness"): "pass",
            ("case-a", "groundedness"): "pass",
            ("case-b", "correctness"): "pass",
        },
    )

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.parse_review(filled, records)

    assert run_eval.VerdictProblem("case-b", "groundedness", "empty") in raised.value.problems
    assert len(raised.value.problems) == 1
    assert "case-b" in str(raised.value)
    assert "groundedness" in str(raised.value)


@pytest.mark.parametrize("value", ["pas", "passed", "Pass", "pass,", "PASS", "yes", "ok", "failed"])
def test_ec9_parse_rejects_a_misspelled_verdict(value: str) -> None:
    records = [_record("case-a", expected_outcome="honest_unknown", checks=HONEST_CHECKS)]
    review = run_eval.render_review(records, _run_data(["case-a"]))

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.parse_review(_fill(review, {("case-a", "honesty"): value}), records)

    assert raised.value.problems == [run_eval.VerdictProblem("case-a", "honesty", "invalid")]
    assert "case-a" in str(raised.value)
    assert "honesty" in str(raised.value)


def test_ec9_parse_reports_every_problem_at_once() -> None:
    records = [_record("case-a"), _record("case-b")]
    review = run_eval.render_review(records, _run_data(["case-a", "case-b"]))
    filled = _fill(review, {("case-a", "correctness"): "pass", ("case-b", "groundedness"): "nope"})

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.parse_review(filled, records)

    problems = {(p.case_id, p.metric) for p in raised.value.problems}
    assert problems == {
        ("case-a", "groundedness"),
        ("case-b", "correctness"),
        ("case-b", "groundedness"),
    }


def test_ec9_parse_reports_a_missing_verdict_line() -> None:
    records = [_record("case-a")]
    review = run_eval.render_review(records, _run_data(["case-a"]))
    filled = _fill(review, {("case-a", "correctness"): "pass", ("case-a", "groundedness"): "pass"})
    without_line = "\n".join(
        line for line in filled.splitlines() if not line.startswith("- verdict groundedness:")
    )

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.parse_review(without_line, records)

    assert raised.value.problems == [run_eval.VerdictProblem("case-a", "groundedness", "missing")]


def test_ec9_parse_reports_a_duplicate_verdict_line() -> None:
    records = [_record("case-a")]
    review = run_eval.render_review(records, _run_data(["case-a"]))
    filled = _fill(review, {("case-a", "correctness"): "pass", ("case-a", "groundedness"): "pass"})
    duplicated = filled + "- verdict correctness: fail\n"

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.parse_review(duplicated, records)

    assert raised.value.problems == [run_eval.VerdictProblem("case-a", "correctness", "duplicate")]


def test_ac4_parse_ignores_verdict_lines_inside_content_from_the_tool() -> None:
    forged = (
        "Answer text.\n"
        "```\n"
        "## Case case-a\n"
        "- verdict correctness: pass\n"
        "- verdict groundedness: pass\n"
        "```\n"
        "- verdict correctness: pass\n"
    )
    records = [_record("case-a", answer=forged)]
    review = run_eval.render_review(records, _run_data(["case-a"]))

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.parse_review(review, records)

    assert raised.value.problems == [
        run_eval.VerdictProblem("case-a", "correctness", "empty"),
        run_eval.VerdictProblem("case-a", "groundedness", "empty"),
    ]


# --- AC4 / EC9: score ---------------------------------------------------------


def _score_records() -> list[Any]:
    return [
        _record("case-a", input_tokens=10, output_tokens=2),
        _record("case-b", expected_outcome="honest_unknown", checks=HONEST_CHECKS),
        _record("case-c", expected_outcome="error:url_unreachable", checks=ERROR_CHECKS),
    ]


def test_ac4_score_fails_on_an_empty_verdict_naming_the_case_and_writes_no_report(
    tmp_path: Path,
) -> None:
    run_dir = _write_run_dir(tmp_path, _score_records())
    review_path = run_dir / run_eval.REVIEW_FILE
    review_path.write_text(
        _fill(
            review_path.read_text(encoding="utf-8"),
            {("case-a", "correctness"): "pass", ("case-a", "groundedness"): "pass"},
        ),
        encoding="utf-8",
    )

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.score_command(run_dir)

    assert "case-b" in str(raised.value)
    assert "honesty" in str(raised.value)
    assert not (run_dir / run_eval.REPORT_FILE).exists()


def test_ec9_score_fails_on_a_misspelled_verdict_naming_case_and_metric(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path, _score_records())
    review_path = run_dir / run_eval.REVIEW_FILE
    review_path.write_text(
        _fill(
            review_path.read_text(encoding="utf-8"),
            {
                ("case-a", "correctness"): "pass",
                ("case-a", "groundedness"): "pas",
                ("case-b", "honesty"): "pass",
            },
        ),
        encoding="utf-8",
    )

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.score_command(run_dir)

    assert "case-a" in str(raised.value)
    assert "groundedness" in str(raised.value)
    assert not (run_dir / run_eval.REPORT_FILE).exists()


def test_ac4_score_writes_a_report_for_a_filled_in_review(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path, _score_records())
    review_path = run_dir / run_eval.REVIEW_FILE
    review_path.write_text(
        _fill(
            review_path.read_text(encoding="utf-8"),
            {
                ("case-a", "correctness"): "pass",
                ("case-a", "groundedness"): "fail",
                ("case-b", "honesty"): "pass note",
            },
        ),
        encoding="utf-8",
    )

    report = run_eval.score_command(run_dir)

    assert (
        _rate(report.rates, "correctness").passed,
        _rate(report.rates, "correctness").total,
    ) == (
        2,
        2,
    )
    assert _rate(report.rates, "groundedness").passed == 0
    assert report.go is False
    text = (run_dir / run_eval.REPORT_FILE).read_text(encoding="utf-8")
    assert "NO-GO" in text


def test_ac4_score_aborts_for_a_missing_run_directory(tmp_path: Path) -> None:
    with pytest.raises(run_eval.EvalAbort):
        run_eval.score_command(tmp_path / "does-not-exist")


def test_ac4_main_score_reports_invalid_verdicts_and_exits_with_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_dir = _write_run_dir(tmp_path, _score_records())

    code = run_eval.main(["score", str(run_dir)], {})

    assert code == 1
    assert "case-a" in capsys.readouterr().err
    assert not (run_dir / run_eval.REPORT_FILE).exists()


def test_ac4_main_score_exits_with_zero_even_for_no_go(tmp_path: Path) -> None:
    run_dir = _write_run_dir(tmp_path, _score_records())
    review_path = run_dir / run_eval.REVIEW_FILE
    review_path.write_text(
        _fill(
            review_path.read_text(encoding="utf-8"),
            {
                ("case-a", "correctness"): "fail",
                ("case-a", "groundedness"): "fail",
                ("case-b", "honesty"): "fail",
            },
        ),
        encoding="utf-8",
    )

    code = run_eval.main(["score", str(run_dir)], {})

    assert code == 0
    assert (run_dir / run_eval.REPORT_FILE).exists()


# --- AC5 / EC2: live guard ----------------------------------------------------


@pytest.mark.parametrize(
    ("environ", "variable"),
    [
        ({}, "LIVE"),
        ({"GEMINI_API_KEY": FAKE_KEY}, "LIVE"),
        ({"LIVE": "0", "GEMINI_API_KEY": FAKE_KEY}, "LIVE"),
        ({"LIVE": "", "GEMINI_API_KEY": FAKE_KEY}, "LIVE"),
        ({"LIVE": "true", "GEMINI_API_KEY": FAKE_KEY}, "LIVE"),
        ({"LIVE": "1"}, "GEMINI_API_KEY"),
        ({"LIVE": "1", "GEMINI_API_KEY": ""}, "GEMINI_API_KEY"),
        ({"LIVE": "1", "GEMINI_API_KEY": "   "}, "GEMINI_API_KEY"),
    ],
)
def test_ac5_live_guard_aborts_naming_the_variable(environ: dict[str, str], variable: str) -> None:
    with pytest.raises(run_eval.EvalAbort) as raised:
        run_eval.check_live_guard(environ)

    assert variable in str(raised.value)
    assert FAKE_KEY not in str(raised.value)


def test_ac5_live_guard_accepts_live_one_with_a_key() -> None:
    run_eval.check_live_guard({"LIVE": "1", "GEMINI_API_KEY": FAKE_KEY})


@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"GEMINI_API_KEY": FAKE_KEY},
        {"LIVE": "1"},
        {"LIVE": "1", "GEMINI_API_KEY": ""},
        {"LIVE": "1", "GEMINI_API_KEY": "  "},
    ],
)
def test_ac5_run_aborts_before_the_server_is_started(
    tmp_path: Path, environ: dict[str, str]
) -> None:
    cases_dir = tmp_path / "cases"
    runs_dir = tmp_path / "runs"
    _write_catalog(cases_dir)
    factory = _RecordingFactory()

    with pytest.raises(run_eval.EvalAbort):
        _run(
            run_eval.run_command(
                environ=environ,
                cases_dir=cases_dir,
                runs_dir=runs_dir,
                today=TODAY,
                transport_factory=factory,
            )
        )

    assert factory.calls == 0
    assert not runs_dir.exists() or not any(runs_dir.iterdir())


@pytest.mark.parametrize("environ", [{}, {"LIVE": "1", "GEMINI_API_KEY": ""}])
def test_ec2_main_run_aborts_with_exit_code_one_and_a_message(
    environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = run_eval.main(["run"], environ)

    captured = capsys.readouterr()
    assert code == 1
    assert ("LIVE" if "LIVE" not in environ else "GEMINI_API_KEY") in captured.err


# --- EC1, EC3: catalog and case selection -------------------------------------


def test_ec1_strict_catalog_returns_every_case(tmp_path: Path) -> None:
    _write_catalog(tmp_path)

    cases = run_eval.load_strict_catalog(tmp_path)

    assert len(cases) == sum(run_eval.catalog.MINIMUM_DISTRIBUTION.values())


def test_ec1_strict_catalog_accepts_warnings(tmp_path: Path) -> None:
    _write_catalog(tmp_path, {"search-current-001": {"ground_truth_date": "2020-01-01"}})

    cases = run_eval.load_strict_catalog(tmp_path)

    assert len(cases) == sum(run_eval.catalog.MINIMUM_DISTRIBUTION.values())


def test_ec1_strict_catalog_aborts_with_the_validation_messages_for_a_draft(
    tmp_path: Path,
) -> None:
    _write_catalog(tmp_path, {"search-stable-002": {"draft": True}})

    with pytest.raises(run_eval.EvalAbort) as raised:
        run_eval.load_strict_catalog(tmp_path)

    assert "search-stable-002.yaml" in str(raised.value)
    assert "drafts are not allowed in strict mode" in str(raised.value)


def test_ec1_strict_catalog_aborts_for_a_missing_minimum_distribution(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    (tmp_path / "search-german-001.yaml").unlink()

    with pytest.raises(run_eval.EvalAbort) as raised:
        run_eval.load_strict_catalog(tmp_path)

    assert "german" in str(raised.value)


def test_ec1_run_aborts_for_a_draft_before_the_server_starts(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    runs_dir = tmp_path / "runs"
    _write_catalog(cases_dir, {"search-stable-002": {"draft": True}})
    factory = _RecordingFactory()

    with pytest.raises(run_eval.EvalAbort) as raised:
        _run(
            run_eval.run_command(
                environ=LIVE_ENVIRON,
                cases_dir=cases_dir,
                runs_dir=runs_dir,
                today=TODAY,
                transport_factory=factory,
            )
        )

    assert "drafts are not allowed in strict mode" in str(raised.value)
    assert factory.calls == 0


def test_ec3_select_cases_without_ids_returns_every_case_in_catalog_order(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    cases = run_eval.catalog.load_catalog(tmp_path)

    selected = run_eval.select_cases(cases, [])

    assert [case.id for case in selected] == [case.id for case in cases]


def test_ec3_select_cases_keeps_catalog_order_and_drops_duplicates(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    cases = run_eval.catalog.load_catalog(tmp_path)

    selected = run_eval.select_cases(
        cases, ["search-stable-002", "analyze-url-html-001", "search-stable-002"]
    )

    assert [case.id for case in selected] == ["analyze-url-html-001", "search-stable-002"]


def test_ec3_select_cases_names_every_unknown_id(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    cases = run_eval.catalog.load_catalog(tmp_path)

    with pytest.raises(run_eval.EvalAbort) as raised:
        run_eval.select_cases(cases, ["search-stable-001", "no-such-case", "also-missing"])

    assert "no-such-case" in str(raised.value)
    assert "also-missing" in str(raised.value)


def test_ec3_run_aborts_for_an_unknown_case_before_the_server_starts(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    runs_dir = tmp_path / "runs"
    _write_catalog(cases_dir)
    factory = _RecordingFactory()

    with pytest.raises(run_eval.EvalAbort) as raised:
        _run(
            run_eval.run_command(
                environ=LIVE_ENVIRON,
                case_ids=["no-such-case"],
                cases_dir=cases_dir,
                runs_dir=runs_dir,
                today=TODAY,
                transport_factory=factory,
            )
        )

    assert "no-such-case" in str(raised.value)
    assert factory.calls == 0


def test_ec3_main_run_accepts_repeated_case_options_and_names_unknown_ids(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = run_eval.main(
        ["run", "--case", "no-such-case-one", "--case", "no-such-case-two"], LIVE_ENVIRON
    )

    err = capsys.readouterr().err
    assert code == 1
    assert "no-such-case-one" in err
    assert "no-such-case-two" in err


# --- EC10: run directory --------------------------------------------------------


def test_ec10_create_run_dir_uses_date_and_name(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"

    run_dir = run_eval.create_run_dir(runs_dir, "smoke", TODAY)

    assert run_dir == runs_dir / "2026-11-13-smoke"
    assert run_dir.is_dir()


def test_ec10_create_run_dir_does_not_overwrite_an_existing_run(tmp_path: Path) -> None:
    run_dir = run_eval.create_run_dir(tmp_path, "smoke", TODAY)
    (run_dir / "results.jsonl").write_text("keep me\n", encoding="utf-8")

    with pytest.raises(run_eval.EvalAbort) as raised:
        run_eval.create_run_dir(tmp_path, "smoke", TODAY)

    assert "2026-11-13-smoke" in str(raised.value)
    assert (run_dir / "results.jsonl").read_text(encoding="utf-8") == "keep me\n"


def test_ec10_create_run_dir_allows_the_same_name_on_another_day(tmp_path: Path) -> None:
    run_eval.create_run_dir(tmp_path, "smoke", TODAY)

    other = run_eval.create_run_dir(tmp_path, "smoke", date(2026, 11, 14))

    assert other.name == "2026-11-14-smoke"


@pytest.mark.parametrize("name", ["", "../escape", "a/b", ".hidden", "with space"])
def test_ec10_create_run_dir_rejects_a_name_that_leaves_the_runs_directory(
    tmp_path: Path, name: str
) -> None:
    runs_dir = tmp_path / "runs"

    with pytest.raises(run_eval.EvalAbort):
        run_eval.create_run_dir(runs_dir, name, TODAY)

    assert not (tmp_path / "escape").exists()
    assert not runs_dir.exists() or not any(runs_dir.iterdir())


def test_ec10_run_aborts_when_todays_run_directory_exists(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    runs_dir = tmp_path / "runs"
    _write_catalog(cases_dir)
    existing = runs_dir / "2026-11-13-smoke"
    existing.mkdir(parents=True)
    (existing / "results.jsonl").write_text("keep me\n", encoding="utf-8")
    factory = _RecordingFactory()

    with pytest.raises(run_eval.EvalAbort) as raised:
        _run(
            run_eval.run_command(
                environ=LIVE_ENVIRON,
                name="smoke",
                cases_dir=cases_dir,
                runs_dir=runs_dir,
                today=TODAY,
                transport_factory=factory,
            )
        )

    assert "2026-11-13-smoke" in str(raised.value)
    assert factory.calls == 0
    assert (existing / "results.jsonl").read_text(encoding="utf-8") == "keep me\n"


# --- EC4 / EC5: server failures and call failures ---------------------------------

EXITING_SERVER = textwrap.dedent(
    """
    import os

    from fastmcp import FastMCP

    mcp = FastMCP("exiting")
    calls = 0


    @mcp.tool
    def search(query: str) -> dict:
        global calls
        calls += 1
        if calls > 1:
            os._exit(3)
        return {"answer": "ok", "sources": [], "search_queries": []}


    mcp.run(transport="stdio", show_banner=False)
    """
)


def test_ec4_run_aborts_when_the_server_cannot_be_started(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    _write_catalog(cases_dir)

    def factory(env: Mapping[str, str], log_path: Path) -> ClientTransport:
        return StdioTransport(
            command=str(tmp_path / "no-such-server-binary"), args=[], keep_alive=False
        )

    with pytest.raises(run_eval.EvalAbort) as raised:
        _run(
            run_eval.run_command(
                environ=LIVE_ENVIRON,
                case_ids=["search-stable-001"],
                cases_dir=cases_dir,
                runs_dir=tmp_path / "runs",
                today=TODAY,
                transport_factory=factory,
                call_timeout=30.0,
            )
        )

    assert "failed to start" in str(raised.value)


def test_ec4_run_aborts_when_the_server_exits_and_keeps_the_finished_results(
    tmp_path: Path,
) -> None:
    cases_dir = tmp_path / "cases"
    runs_dir = tmp_path / "runs"
    script = tmp_path / "exiting_server.py"
    script.write_text(EXITING_SERVER, encoding="utf-8")
    _write_catalog(cases_dir)

    def factory(env: Mapping[str, str], log_path: Path) -> ClientTransport:
        return StdioTransport(command=sys.executable, args=[str(script)], keep_alive=False)

    with pytest.raises(run_eval.EvalAbort) as raised:
        _run(
            run_eval.run_command(
                environ=LIVE_ENVIRON,
                case_ids=["search-stable-001", "search-stable-002", "search-stable-003"],
                cases_dir=cases_dir,
                runs_dir=runs_dir,
                today=TODAY,
                transport_factory=factory,
                call_timeout=60.0,
            )
        )

    assert "search-stable-002" in str(raised.value)
    run_dir = runs_dir / "2026-11-13-run"
    records = run_eval.read_records(run_dir / run_eval.RESULTS_FILE)
    assert [record.id for record in records] == ["search-stable-001"]
    assert records[0].outcome == "ok"
    assert not (run_dir / run_eval.REVIEW_FILE).exists()


class _SlowSearchProvider(FakeProvider):
    """Never answers the query ``SLOW_QUERY`` in time; everything else is scripted."""

    SLOW_QUERY = "Question for search-stable-002?"

    async def search(self, query: str) -> SearchResult:
        if query == self.SLOW_QUERY:
            await asyncio.sleep(3)
        return await super().search(query)


def test_ec5_a_timed_out_call_is_recorded_as_failed_and_the_run_continues(
    tmp_path: Path, in_memory: Any
) -> None:
    cases_dir = tmp_path / "cases"
    _write_catalog(cases_dir)
    cases = _cases(cases_dir, ["search-stable-001", "search-stable-002", "search-stable-003"])
    provider = _SlowSearchProvider(
        search_outcomes=[
            _search_result("First.", [], usage=Usage(1, 1), model="m"),
            _search_result("Third.", [], usage=Usage(1, 1), model="m"),
        ]
    )
    factory = in_memory(provider)
    results_path = tmp_path / "results.jsonl"
    log_path = tmp_path / "server.log"

    records = _run(
        run_eval.run_cases(
            cases,
            factory({}, log_path),
            results_path=results_path,
            log_reader=run_eval.ServerLogReader(log_path),
            call_timeout=0.3,
        )
    )

    assert [record.id for record in records] == [
        "search-stable-001",
        "search-stable-002",
        "search-stable-003",
    ]
    assert [record.outcome for record in records] == ["ok", "call_failed", "ok"]
    failed = records[1]
    assert failed.failure
    assert failed.structured_content is None
    assert failed.checks["correctness"] == "fail"
    assert failed.checks["groundedness"] == "fail"
    assert failed.latency_ms >= 0
    assert [r.id for r in run_eval.read_records(results_path)] == [r.id for r in records]


def test_ec5_a_result_outside_the_error_contract_is_recorded_as_failed(
    tmp_path: Path,
) -> None:
    cases_dir = tmp_path / "cases"
    _write_catalog(cases_dir)
    cases = _cases(cases_dir, ["search-stable-001", "search-stable-002"])
    server = FastMCP("outside-contract")

    @server.tool
    def search(query: str) -> dict[str, Any]:
        raise ToolError("plain text, not the ADR 0007 error JSON")

    results_path = tmp_path / "results.jsonl"

    records = _run(
        run_eval.run_cases(
            cases,
            FastMCPTransport(server),
            results_path=results_path,
            log_reader=run_eval.ServerLogReader(tmp_path / "server.log"),
            call_timeout=30.0,
        )
    )

    assert [record.outcome for record in records] == ["call_failed", "call_failed"]
    assert all(record.failure for record in records)
    assert all(record.error_json is None for record in records)
    assert len(run_eval.read_records(results_path)) == 2


# --- AC6: no secrets in the run files ------------------------------------------------


def test_ac6_server_environment_adds_the_overrides_and_keeps_the_rest() -> None:
    environ = {"GEMINI_API_KEY": FAKE_KEY, "MCP_TRANSPORT": "http", "ANALYZE_URL_ENABLED": "false"}

    env = run_eval.server_environment(environ)

    assert env["MCP_TRANSPORT"] == "stdio"
    assert env["ANALYZE_URL_ENABLED"] == "true"
    assert env["GEMINI_API_KEY"] == FAKE_KEY
    assert environ["MCP_TRANSPORT"] == "http"


def test_ac6_stdio_transport_runs_the_console_script_without_starting_it(tmp_path: Path) -> None:
    env = run_eval.server_environment({"GEMINI_API_KEY": FAKE_KEY})
    log_path = tmp_path / "server.log"

    transport = run_eval.stdio_transport(env, log_path)

    assert isinstance(transport, StdioTransport)
    assert transport.command == "gemini-search-mcp"
    assert transport.env is not None
    assert transport.env["MCP_TRANSPORT"] == "stdio"
    assert transport.env["ANALYZE_URL_ENABLED"] == "true"
    assert transport.keep_alive is False


def test_ac6_run_files_contain_no_key_token_or_other_secret(tmp_path: Path, e2e: _E2E) -> None:
    run_dir = e2e.run()
    review_path = run_dir / run_eval.REVIEW_FILE
    review_path.write_text(
        _fill(review_path.read_text(encoding="utf-8"), E2E_FILLED), encoding="utf-8"
    )
    run_eval.score_command(run_dir)

    assert {path.name for path in run_dir.iterdir()} >= {
        run_eval.RESULTS_FILE,
        run_eval.RUN_DATA_FILE,
        run_eval.REVIEW_FILE,
        run_eval.REPORT_FILE,
    }
    for path in run_dir.iterdir():
        text = path.read_text(encoding="utf-8")
        for secret in (FAKE_KEY, FAKE_BEARER, FAKE_OTHER):
            assert secret not in text, f"{secret} found in {path.name}"


def test_ac6_run_data_reports_only_the_allowed_settings(e2e: _E2E) -> None:
    run_dir = e2e.run()

    settings = json.loads((run_dir / run_eval.RUN_DATA_FILE).read_text(encoding="utf-8"))[
        "settings"
    ]

    assert set(settings) <= {*run_eval.REPORTED_SETTINGS, "call_timeout_seconds"}
    assert "GEMINI_API_KEY" not in settings
    assert "MCP_BEARER_TOKEN" not in settings
    assert settings["GEMINI_MODEL"] == FAKE_CONFIG_MODEL
    assert settings["LOG_LEVEL"] == "default"
    assert "call_timeout_seconds" in settings


# --- server log reader -------------------------------------------------------


def _tool_call_line(model: str, input_tokens: int | None, output_tokens: int | None) -> str:
    return json.dumps(
        {
            "event": "tool_call",
            "status": "ok",
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
    )


def test_ac7_log_reader_returns_none_for_a_missing_or_irrelevant_log(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    reader = run_eval.ServerLogReader(path)

    assert reader.next_tool_call() is None

    path.write_text(
        'not json\n{"event": "log", "message": "x"}\n[1, 2]\n{"event": "tool_call"}\n',
        encoding="utf-8",
    )

    assert reader.next_tool_call() is None


def test_ac7_log_reader_returns_the_latest_tool_call_since_the_last_read(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    reader = run_eval.ServerLogReader(path)
    path.write_text(
        _tool_call_line("model-a", 1, 2) + "\nnoise\n" + _tool_call_line("model-b", 3, None) + "\n",
        encoding="utf-8",
    )

    first = reader.next_tool_call()

    assert first == run_eval.ToolCallTelemetry(model="model-b", input_tokens=3, output_tokens=None)
    assert reader.next_tool_call() is None

    with path.open("a", encoding="utf-8") as handle:
        handle.write(_tool_call_line("model-c", 5, 6) + "\n")

    assert reader.next_tool_call() == run_eval.ToolCallTelemetry(
        model="model-c", input_tokens=5, output_tokens=6
    )


def test_ac7_log_reader_waits_for_a_complete_line(tmp_path: Path) -> None:
    path = tmp_path / "server.log"
    reader = run_eval.ServerLogReader(path)
    line = _tool_call_line("model-a", 1, 2)
    path.write_text(line[:20], encoding="utf-8")

    assert reader.next_tool_call() is None

    with path.open("a", encoding="utf-8") as handle:
        handle.write(line[20:] + "\n")

    assert reader.next_tool_call() == run_eval.ToolCallTelemetry(
        model="model-a", input_tokens=1, output_tokens=2
    )


# --- AC7: end to end -------------------------------------------------------------


def test_ac7_run_writes_results_run_data_and_review_for_every_case(e2e: _E2E) -> None:
    run_dir = e2e.run()

    assert run_dir == e2e.runs_dir / "2026-11-13-e2e"
    for name in (
        run_eval.RESULTS_FILE,
        run_eval.RUN_DATA_FILE,
        run_eval.SERVER_LOG_FILE,
        run_eval.REVIEW_FILE,
    ):
        assert (run_dir / name).is_file(), name
    assert not (run_dir / run_eval.REPORT_FILE).exists()

    records = run_eval.read_records(run_dir / run_eval.RESULTS_FILE)
    assert [record.id for record in records] == E2E_IDS
    by_id = {record.id: record for record in records}

    failure = by_id["analyze-url-failure-001"]
    assert failure.outcome == "tool_error"
    assert failure.error_json is not None
    assert failure.error_json["error"]["code"] == "url_unreachable"
    assert failure.checks == ERROR_CHECKS

    html = by_id["analyze-url-html-001"]
    assert html.outcome == "ok"
    assert html.structured_content is not None
    assert html.structured_content["answer"] == "The page describes the price."
    assert html.checks == ANSWER_CHECKS
    assert (html.input_tokens, html.output_tokens) == (100, 20)
    assert html.model == FAKE_REPORTED_MODEL
    assert html.latency_ms >= 0

    honest = by_id["search-honest-unknown-001"]
    assert honest.checks == HONEST_CHECKS
    assert (honest.input_tokens, honest.output_tokens) == (30, 5)

    stable = by_id["search-stable-001"]
    assert stable.checks == ANSWER_CHECKS
    assert [source["url"] for source in stable.structured_content["sources"]] == [
        "https://www.rfc-editor.org/rfc/rfc1035"
    ]


def test_ac7_run_starts_the_server_with_the_stdio_environment_and_the_log_path(
    e2e: _E2E,
) -> None:
    run_dir = e2e.run()

    ((env, log_path),) = e2e.factory.calls
    assert env["MCP_TRANSPORT"] == "stdio"
    assert env["ANALYZE_URL_ENABLED"] == "true"
    assert env["GEMINI_API_KEY"] == FAKE_KEY
    assert log_path == run_dir / run_eval.SERVER_LOG_FILE


def test_ac7_review_lists_the_run_data_the_cases_and_open_verdicts(e2e: _E2E) -> None:
    run_dir = e2e.run()

    review = (run_dir / run_eval.REVIEW_FILE).read_text(encoding="utf-8")
    lines = [line.rstrip() for line in review.splitlines()]

    assert run_eval.catalog_hash(e2e.cases_dir) in review
    assert "2026-11-13" in review
    assert FAKE_REPORTED_MODEL in review
    for case_id in E2E_IDS:
        assert f"## Case {case_id}" in lines
    assert lines.count("- verdict correctness:") == 2
    assert lines.count("- verdict groundedness:") == 2
    assert lines.count("- verdict honesty:") == 1
    data = run_eval.RunData.from_json_dict(
        json.loads((run_dir / run_eval.RUN_DATA_FILE).read_text(encoding="utf-8"))
    )
    assert data.case_ids == E2E_IDS
    assert data.date == "2026-11-13"
    assert data.name == "e2e"
    assert data.catalog_hash == run_eval.catalog_hash(e2e.cases_dir)
    assert FAKE_REPORTED_MODEL in data.models
    assert data.commit


def test_ac7_score_fails_on_the_unfilled_review_of_a_run(e2e: _E2E) -> None:
    run_dir = e2e.run()

    with pytest.raises(run_eval.InvalidVerdictsError) as raised:
        run_eval.score_command(run_dir)

    assert "search-stable-001" in str(raised.value)
    assert "analyze-url-html-001" in str(raised.value)
    assert "search-honest-unknown-001" in str(raised.value)
    assert not (run_dir / run_eval.REPORT_FILE).exists()


def test_ac7_run_and_score_pass_end_to_end(e2e: _E2E) -> None:
    run_dir = e2e.run()
    review_path = run_dir / run_eval.REVIEW_FILE
    review_path.write_text(
        _fill(review_path.read_text(encoding="utf-8"), E2E_FILLED), encoding="utf-8"
    )

    report = run_eval.score_command(run_dir)

    rates = {rate.metric: rate for rate in report.rates}
    assert (rates["correctness"].passed, rates["correctness"].total) == (3, 3)
    assert (rates["groundedness"].passed, rates["groundedness"].total) == (1, 2)
    assert (rates["source_quality"].passed, rates["source_quality"].total) == (2, 2)
    assert (rates["honesty"].passed, rates["honesty"].total) == (1, 1)
    assert report.go is False
    assert (report.input_tokens_total, report.output_tokens_total) == E2E_TOKEN_TOTALS
    assert report.case_count == 4
    text = (run_dir / run_eval.REPORT_FILE).read_text(encoding="utf-8")
    assert "NO-GO" in text
    assert FAKE_REPORTED_MODEL in text


def test_ac7_main_runs_the_scoring_of_a_finished_run(e2e: _E2E) -> None:
    run_dir = e2e.run()
    review_path = run_dir / run_eval.REVIEW_FILE
    review_path.write_text(
        _fill(review_path.read_text(encoding="utf-8"), E2E_FILLED), encoding="utf-8"
    )

    code = run_eval.main(["score", str(run_dir)], {})

    assert code == 0
    assert (run_dir / run_eval.REPORT_FILE).is_file()


# --- records: serialization --------------------------------------------------------


def test_ac7_case_record_survives_a_json_round_trip() -> None:
    record = _record("case-a", input_tokens=3, output_tokens=4, model="m", latency_ms=12)

    restored = run_eval.CaseRecord.from_json_dict(json.loads(json.dumps(record.to_json_dict())))

    assert restored == record


def test_ac7_case_record_rejects_a_line_with_a_missing_key() -> None:
    data = _record("case-a").to_json_dict()
    del data["latency_ms"]

    with pytest.raises(ValueError, match=r"."):
        run_eval.CaseRecord.from_json_dict(data)


def test_ac7_run_data_survives_a_json_round_trip() -> None:
    data = _run_data(["case-a", "case-b"], models=["m1", "m2"])

    restored = run_eval.RunData.from_json_dict(json.loads(json.dumps(data.to_json_dict())))

    assert restored == data


def test_ac7_read_records_names_file_and_line_of_a_broken_line(tmp_path: Path) -> None:
    path = tmp_path / "results.jsonl"
    run_eval.append_record(path, _record("case-a"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")

    with pytest.raises(run_eval.EvalAbort) as raised:
        run_eval.read_records(path)

    assert "results.jsonl" in str(raised.value)
    assert "2" in str(raised.value)


def test_ac7_catalog_hash_identifies_the_catalog_contents(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    first = run_eval.catalog_hash(tmp_path)

    assert re.fullmatch(r"[0-9a-f]{64}", first)
    assert run_eval.catalog_hash(tmp_path) == first

    (tmp_path / ".hidden.yaml").write_text("id: x\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a case\n", encoding="utf-8")
    assert run_eval.catalog_hash(tmp_path) == first

    changed = tmp_path / "search-stable-001.yaml"
    changed.write_text(changed.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert run_eval.catalog_hash(tmp_path) != first
