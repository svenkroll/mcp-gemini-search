"""Tests for the metric applicability by tool and outcome (issue #36).

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order
of issue #36: AC2 (applicability table including tool errors), AC4 (rates only
over the cases a metric applies to, go/no-go unchanged), EC4 (a ``search``
``answer`` case that returns sources anyway) and EC5 (every case of a metric
``n/a``). AC1 and AC3 are in ``test_catalog_variants.py``.

The script is not a package, so it is loaded from its file path. Nothing here
starts a server or touches the network.
"""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_EVAL_PATH = REPO_ROOT / "eval" / "run_eval.py"


def _load_run_eval() -> Any:
    spec = importlib.util.spec_from_file_location("run_eval", RUN_EVAL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_eval"] = module
    spec.loader.exec_module(module)
    return module


run_eval = _load_run_eval()

ALLOWED = ["rfc-editor.org"]
ALLOWED_URL = "https://www.rfc-editor.org/rfc/rfc1035"
OTHER_URL = "https://example.com/blog"
REDIRECT_URL = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"

# (tool, expected_outcome) -> (correctness, groundedness, source_quality, honesty)
TABLE = [
    ("search", "answer", ("manual", "n/a", "n/a", "n/a")),
    ("search", "answer_with_sources", ("manual", "manual", "automatic", "n/a")),
    ("analyze_url", "answer", ("manual", "manual", "automatic", "n/a")),
    ("search", "honest_unknown", ("n/a", "n/a", "n/a", "manual")),
    ("analyze_url", "honest_unknown", ("n/a", "n/a", "n/a", "manual")),
    ("search", "error:invalid_input", ("automatic", "n/a", "n/a", "n/a")),
    ("analyze_url", "error:url_unreachable", ("automatic", "n/a", "n/a", "n/a")),
]


def _error_json(code: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": "Short message.", "request_id": "req-1"}}


def _checks(
    tool: str,
    expected_outcome: str,
    *,
    outcome: str = "ok",
    sources: list[str] | None = None,
    error_code: str | None = None,
) -> tuple[str, str, str, str]:
    checks = run_eval.automatic_checks(
        tool=tool,
        expected_outcome=expected_outcome,
        outcome=outcome,
        sources=sources or [],
        error_json=_error_json(error_code) if error_code else None,
        allowed_sources=ALLOWED,
    )
    return tuple(checks[metric] for metric in run_eval.METRICS)


def _record(case_id: str, tool: str, expected_outcome: str, checks: tuple[str, ...]) -> Any:
    return run_eval.CaseRecord(
        id=case_id,
        tool=tool,
        category="stable_fact",
        expected_outcome=expected_outcome,
        input={"query": "Question?"},
        expected="Expected statement.",
        allowed_sources=ALLOWED,
        outcome="ok",
        structured_content={"answer": "The answer.", "sources": [], "search_queries": []},
        error_json=None,
        failure=None,
        latency_ms=10,
        input_tokens=None,
        output_tokens=None,
        model=None,
        checks=dict(zip(run_eval.METRICS, checks, strict=True)),
    )


# --- AC2: applicability ------------------------------------------------------


@pytest.mark.parametrize(("tool", "expected_outcome", "expected"), TABLE)
def test_ac2_applicability_follows_the_table(
    tool: str, expected_outcome: str, expected: tuple[str, str, str, str]
) -> None:
    result = run_eval.applicability(tool, expected_outcome)

    assert tuple(result[metric] for metric in run_eval.METRICS) == expected


@pytest.mark.parametrize(
    ("tool", "expected_outcome"),
    [
        ("analyze_url", "answer_with_sources"),
        ("search", "maybe"),
        ("search", "error:"),
        ("fetch", "answer"),
    ],
)
def test_ac2_applicability_rejects_what_the_table_does_not_list(
    tool: str, expected_outcome: str
) -> None:
    with pytest.raises(ValueError, match=r"."):
        run_eval.applicability(tool, expected_outcome)


def test_ac2_successful_calls_leave_exactly_the_manual_metrics_open() -> None:
    sources = [ALLOWED_URL]

    assert _checks("search", "answer", sources=sources) == ("manual", "n/a", "n/a", "n/a")
    assert _checks("search", "answer_with_sources", sources=sources) == (
        "manual",
        "manual",
        "pass",
        "n/a",
    )
    assert _checks("analyze_url", "answer", sources=sources) == ("manual", "manual", "pass", "n/a")
    assert _checks("search", "honest_unknown", sources=sources) == ("n/a", "n/a", "n/a", "manual")


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ([], "fail"),
        ([OTHER_URL], "fail"),
        ([ALLOWED_URL, OTHER_URL], "pass"),
        ([ALLOWED_URL, REDIRECT_URL], "fail"),
    ],
    ids=["no-source", "only-other", "allowed-and-other", "redirect"],
)
def test_ac2_answer_with_sources_decides_source_quality_from_the_returned_sources(
    sources: list[str], expected: str
) -> None:
    assert _checks("search", "answer_with_sources", sources=sources) == (
        "manual",
        "manual",
        expected,
        "n/a",
    )


def test_ac2_tool_error_on_a_search_answer_case_fails_correctness_only() -> None:
    checks = _checks("search", "answer", outcome="tool_error", error_code="upstream_unavailable")

    assert checks == ("fail", "n/a", "n/a", "n/a")


def test_ac2_tool_error_on_answer_with_sources_fails_three_metrics() -> None:
    checks = _checks(
        "search", "answer_with_sources", outcome="tool_error", error_code="upstream_unavailable"
    )

    assert checks == ("fail", "fail", "fail", "n/a")


def test_ac2_tool_error_on_an_analyze_url_answer_case_fails_three_metrics() -> None:
    checks = _checks("analyze_url", "answer", outcome="tool_error", error_code="url_unreachable")

    assert checks == ("fail", "fail", "fail", "n/a")


def test_ac2_tool_error_decides_an_error_case_by_its_code() -> None:
    hit = _checks("search", "error:invalid_input", outcome="tool_error", error_code="invalid_input")
    miss = _checks(
        "search", "error:invalid_input", outcome="tool_error", error_code="upstream_error"
    )

    assert hit == ("pass", "n/a", "n/a", "n/a")
    assert miss == ("fail", "n/a", "n/a", "n/a")


@pytest.mark.parametrize(("tool", "expected_outcome", "applies"), TABLE)
def test_ac2_failed_call_fails_exactly_the_metrics_that_apply(
    tool: str, expected_outcome: str, applies: tuple[str, str, str, str]
) -> None:
    checks = _checks(tool, expected_outcome, outcome="call_failed")

    assert checks == tuple("n/a" if how == "n/a" else "fail" for how in applies)


@pytest.mark.parametrize(
    "sources",
    [[], [ALLOWED_URL], [OTHER_URL], [REDIRECT_URL]],
    ids=["none", "allowed", "other", "redirect"],
)
def test_ec4_search_answer_case_scores_nothing_from_returned_sources(sources: list[str]) -> None:
    assert _checks("search", "answer", sources=sources) == ("manual", "n/a", "n/a", "n/a")


def test_ec4_review_asks_only_for_correctness_of_a_search_answer_case() -> None:
    records = [
        _record("search-stable-001", "search", "answer", ("manual", "n/a", "n/a", "n/a")),
        _record(
            "search-stable-001-sources",
            "search",
            "answer_with_sources",
            ("manual", "manual", "pass", "n/a"),
        ),
    ]
    data = run_eval.RunData(
        name="t",
        date="2026-11-14",
        commit="abc1234",
        catalog_hash="0" * 64,
        models=[],
        settings={},
        case_ids=[record.id for record in records],
    )

    review = run_eval.render_review(records, data)
    _, plain, with_sources = review.split("\n## Case ")
    assert plain.startswith("search-stable-001\n")
    assert with_sources.startswith("search-stable-001-sources\n")

    assert "- verdict correctness:" in plain
    assert "- verdict groundedness:" not in plain
    assert "- verdict correctness:" in with_sources
    assert "- verdict groundedness:" in with_sources


# --- AC4: rates and go/no-go -------------------------------------------------


def _mixed_run() -> tuple[list[Any], dict[str, dict[str, str]]]:
    """A run with one case per table row and its manual verdicts.

    The ``search`` ``answer`` case fails correctness and returned no allowed
    source; the other answer cases pass everything.
    """
    records = [
        _record("plain", "search", "answer", ("manual", "n/a", "n/a", "n/a")),
        _record("sources", "search", "answer_with_sources", ("manual", "manual", "pass", "n/a")),
        _record("url", "analyze_url", "answer", ("manual", "manual", "fail", "n/a")),
        _record("unknown", "search", "honest_unknown", ("n/a", "n/a", "n/a", "manual")),
        _record("error", "analyze_url", "error:url_unreachable", ("pass", "n/a", "n/a", "n/a")),
    ]
    manual = {
        "plain": {"correctness": "fail"},
        "sources": {"correctness": "pass", "groundedness": "pass"},
        "url": {"correctness": "pass", "groundedness": "fail"},
        "unknown": {"honesty": "pass"},
        "error": {},
    }
    return records, manual


def test_ac4_each_rate_counts_only_the_cases_the_metric_applies_to() -> None:
    records, manual = _mixed_run()

    report = run_eval.build_score_report(records, manual)

    counted = {rate.metric: (rate.passed, rate.total) for rate in report.rates}
    assert counted == {
        "correctness": (3, 4),
        "groundedness": (1, 2),
        "source_quality": (1, 2),
        "honesty": (1, 1),
    }
    assert report.case_count == 5


def test_ac4_plain_search_answers_do_not_change_groundedness_or_source_quality() -> None:
    records, manual = _mixed_run()
    for number in range(20):
        case_id = f"plain-{number}"
        records.append(_record(case_id, "search", "answer", ("manual", "n/a", "n/a", "n/a")))
        manual[case_id] = {"correctness": "pass"}

    report = run_eval.build_score_report(records, manual)

    counted = {rate.metric: (rate.passed, rate.total) for rate in report.rates}
    assert counted["correctness"] == (23, 24)
    assert counted["groundedness"] == (1, 2)
    assert counted["source_quality"] == (1, 2)
    assert counted["honesty"] == (1, 1)


def test_ac4_score_reads_only_the_verdicts_of_applicable_metrics(tmp_path: Path) -> None:
    records, manual = _mixed_run()
    data = run_eval.RunData(
        name="t",
        date="2026-11-14",
        commit="abc1234",
        catalog_hash="0" * 64,
        models=[],
        settings={},
        case_ids=[record.id for record in records],
    )
    run_dir = tmp_path / "2026-11-14-t"
    run_dir.mkdir()
    for record in records:
        run_eval.append_record(run_dir / run_eval.RESULTS_FILE, record)
    (run_dir / run_eval.RUN_DATA_FILE).write_text(json.dumps(data.to_json_dict()), encoding="utf-8")
    review = run_eval.render_review(records, data)
    sections = review.split("## Case ")
    filled = [sections[0]]
    for section in sections[1:]:
        case_id = section.split("\n", 1)[0]
        for metric, verdict in manual[case_id].items():
            section = section.replace(f"- verdict {metric}:", f"- verdict {metric}: {verdict}")
        filled.append(section)
    (run_dir / run_eval.REVIEW_FILE).write_text("## Case ".join(filled), encoding="utf-8")

    report = run_eval.score_command(run_dir)

    assert {rate.metric: (rate.passed, rate.total) for rate in report.rates} == {
        "correctness": (3, 4),
        "groundedness": (1, 2),
        "source_quality": (1, 2),
        "honesty": (1, 1),
    }
    text = (run_dir / run_eval.REPORT_FILE).read_text(encoding="utf-8")
    assert "| correctness | 3 | 4 | 75.0% | 85% | not met |" in text
    assert "| honesty | 1 | 1 | 100.0% | 100% | met |" in text
    assert "NO-GO" in text


def test_ac4_thresholds_are_unchanged() -> None:
    assert dict(run_eval.THRESHOLDS) == {
        "correctness": 85,
        "groundedness": 85,
        "source_quality": 90,
        "honesty": 100,
    }


@pytest.mark.parametrize(
    ("metric", "passed", "total", "met"),
    [
        ("correctness", 16, 20, False),
        ("correctness", 17, 20, True),
        ("correctness", 18, 20, True),
        ("groundedness", 16, 20, False),
        ("groundedness", 17, 20, True),
        ("groundedness", 18, 20, True),
        ("source_quality", 17, 20, False),
        ("source_quality", 18, 20, True),
        ("source_quality", 19, 20, True),
        ("honesty", 19, 20, False),
        ("honesty", 20, 20, True),
    ],
)
def test_ac4_go_no_go_around_each_threshold_with_plain_search_cases_mixed_in(
    metric: str, passed: int, total: int, met: bool
) -> None:
    # 20 cases the metric applies to, all other metrics passing. For every
    # metric but correctness, 30 plain ``search`` ``answer`` cases are mixed
    # in; they count for correctness only and must not move the rate.
    verdicts = []
    for number in range(total):
        row = dict.fromkeys(run_eval.METRICS, "pass")
        row[metric] = "pass" if number < passed else "fail"
        verdicts.append(row)
    plain = {
        "correctness": "pass",
        "groundedness": "n/a",
        "source_quality": "n/a",
        "honesty": "n/a",
    }
    if metric != "correctness":
        verdicts += [dict(plain) for _ in range(30)]

    rates = {rate.metric: rate for rate in run_eval.compute_rates(verdicts)}

    assert (rates[metric].passed, rates[metric].total) == (passed, total)
    assert rates[metric].met is met
    assert all(rate.met for name, rate in rates.items() if name != metric)


def test_ec5_metric_with_only_na_cases_has_no_rate_and_is_not_met() -> None:
    records = [
        _record(f"plain-{number}", "search", "answer", ("manual", "n/a", "n/a", "n/a"))
        for number in range(5)
    ]
    manual = {record.id: {"correctness": "pass"} for record in records}

    report = run_eval.build_score_report(records, manual)

    by_metric = {rate.metric: rate for rate in report.rates}
    assert by_metric["correctness"].met is True
    for metric in ("groundedness", "source_quality", "honesty"):
        assert by_metric[metric].total == 0
        assert by_metric[metric].rate_percent is None
        assert by_metric[metric].met is False
    assert report.go is False
