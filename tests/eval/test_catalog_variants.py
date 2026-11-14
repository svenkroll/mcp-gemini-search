"""Tests for ``answer_with_sources`` and the variant pairing rules (issue #36).

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order
of issue #36: AC1 (the new outcome), AC3 (strict mode), EC1
(``answer_with_sources`` on ``analyze_url``), EC2 (variant without base, base
without variant, wrong suffix, variant of a variant) and EC3 (``-fact`` on an
``answer`` case, ``-sources`` on an ``honest_unknown`` case). AC2 and AC4 are
in ``test_run_eval_applicability.py``, AC5 in
``test_answer_with_sources_scope.py``.

The catalog module is not a package, so it is loaded from its file path. The
tests build their catalogs in ``tmp_path``; only the last test reads the
repository's own ``eval/cases/``.
"""

import importlib.util
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "eval" / "catalog.py"
TODAY = date(2026, 11, 14)


def _load_catalog_module() -> Any:
    spec = importlib.util.spec_from_file_location("eval_catalog", CATALOG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_catalog"] = module
    spec.loader.exec_module(module)
    return module


catalog = _load_catalog_module()

_PREFIX = {
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

ANSWER_BASE = "search-stable-001"
SOURCES_VARIANT = "search-stable-001-sources"
UNKNOWN_BASE = "search-honest-unknown-001"
FACT_VARIANT = "search-honest-unknown-001-fact"


def _base_case(category: str, number: int) -> dict[str, Any]:
    case_id = f"{_PREFIX[category]}-{number:03d}"
    case: dict[str, Any] = {
        "id": case_id,
        "tool": "search",
        "category": category,
        "input": {"query": f"Question for {case_id}?"},
        "expected": f"Expected statement of {case_id}.",
        "allowed_sources": ["example.org"],
        "ground_truth_date": "2026-11-12",
        "expected_outcome": "answer",
    }
    if category.startswith("url_"):
        case["tool"] = "analyze_url"
        case["input"] = {"url": f"https://example.org/{case_id}", "question": "What does it say?"}
    if category == "honest_unknown":
        case["expected_outcome"] = "honest_unknown"
    elif category == "url_failure":
        case["expected_outcome"] = "error:url_unreachable"
    return case


def _sources_variant(base: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "id": base["id"] + "-sources",
        "input": {"query": base["input"]["query"] + "\n\n" + catalog.SOURCES_SUFFIX},
        "expected_outcome": "answer_with_sources",
    }


def _fact_variant(base: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "id": base["id"] + "-fact",
        "input": {"query": base["input"]["query"] + "\n\n" + catalog.FACT_SUFFIX},
        "expected": "The tool states that the figure is not publicly known and gives no figure.",
        "expected_outcome": "honest_unknown",
    }


def _correct_catalog() -> dict[str, dict[str, Any]]:
    """Return a catalog that passes ``--strict``, keyed by case id."""
    cases: dict[str, dict[str, Any]] = {}
    for category, count in catalog.MINIMUM_DISTRIBUTION.items():
        for number in range(1, count + 1):
            base = _base_case(category, number)
            cases[base["id"]] = base
            if base["tool"] == "search" and base["expected_outcome"] == "answer":
                variant = _sources_variant(base)
                cases[variant["id"]] = variant
            elif base["tool"] == "search":
                variant = _fact_variant(base)
                cases[variant["id"]] = variant
    return cases


def _write(cases_dir: Path, cases: dict[str, dict[str, Any]]) -> None:
    for case in cases.values():
        (cases_dir / f"{case['id']}.yaml").write_text(
            yaml.safe_dump(case, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )


def _errors(cases_dir: Path, *, strict: bool) -> list[Any]:
    findings = catalog.validate_catalog(cases_dir, strict=strict, today=TODAY)
    return [finding for finding in findings if finding.severity == "error"]


def _strict_errors(tmp_path: Path, cases: dict[str, dict[str, Any]]) -> list[tuple[str, str, str]]:
    _write(tmp_path, cases)
    return [
        (finding.file, finding.field, finding.rule) for finding in _errors(tmp_path, strict=True)
    ]


# --- AC1 / EC1: the new outcome ----------------------------------------------


def test_ac1_answer_with_sources_is_accepted_for_search(tmp_path: Path) -> None:
    case = _sources_variant(_base_case("stable_fact", 1))
    _write(tmp_path, {case["id"]: case})

    assert _errors(tmp_path, strict=False) == []
    (loaded,) = catalog.load_catalog(tmp_path)
    assert loaded.expected_outcome == "answer_with_sources"


def test_ac1_ec1_answer_with_sources_is_rejected_for_analyze_url(tmp_path: Path) -> None:
    case = {**_base_case("url_html", 1), "expected_outcome": "answer_with_sources"}
    _write(tmp_path, {case["id"]: case})

    (error,) = _errors(tmp_path, strict=False)

    assert error.file == "analyze-url-html-001.yaml"
    assert error.field == "expected_outcome"
    assert "answer_with_sources (tool search only)" in error.rule
    assert str(error) == f"error: {error.file}: {error.field}: {error.rule}"
    with pytest.raises(catalog.CatalogError, match=r"analyze-url-html-001\.yaml: expected_outcome"):
        catalog.load_catalog(tmp_path)


def test_ac1_unknown_outcome_rule_lists_answer_with_sources(tmp_path: Path) -> None:
    case = {**_base_case("stable_fact", 1), "expected_outcome": "answer_with_source"}
    _write(tmp_path, {case["id"]: case})

    (error,) = _errors(tmp_path, strict=False)

    assert (error.file, error.field) == ("search-stable-001.yaml", "expected_outcome")
    assert "answer_with_sources" in error.rule


def test_ac1_suffix_constants_have_the_text_of_the_issue() -> None:
    assert catalog.SOURCES_SUFFIX == (
        "Answer only from Google Search results. Cite the primary source of truth "
        "(official documentation, standards body or publisher of record) where the "
        "answer can be checked."
    )
    assert catalog.FACT_SUFFIX == (
        "Answer only with a fact a source confirms; if none does, say it is not publicly known."
    )


# --- AC3: strict mode --------------------------------------------------------


def test_ac3_strict_accepts_a_correct_catalog(tmp_path: Path) -> None:
    cases = _correct_catalog()

    assert len(cases) == 41 + 26 + 4
    assert _strict_errors(tmp_path, cases) == []


def test_ac3_pairing_rules_are_not_checked_without_strict(tmp_path: Path) -> None:
    cases = _correct_catalog()
    del cases[SOURCES_VARIANT]
    del cases[UNKNOWN_BASE]
    _write(tmp_path, cases)

    assert _errors(tmp_path, strict=False) == []


def test_ac3_ec2_answer_case_without_sources_variant(tmp_path: Path) -> None:
    cases = _correct_catalog()
    del cases[SOURCES_VARIANT]

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{ANSWER_BASE}.yaml",
            "id",
            f"a search answer case requires the variant case {SOURCES_VARIANT}",
        )
    ]


def test_ac3_ec2_honest_unknown_case_without_fact_variant(tmp_path: Path) -> None:
    cases = _correct_catalog()
    del cases[FACT_VARIANT]

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{UNKNOWN_BASE}.yaml",
            "id",
            f"a search honest_unknown case requires the variant case {FACT_VARIANT}",
        )
    ]


def test_ac3_ec2_sources_variant_without_base(tmp_path: Path) -> None:
    cases = _correct_catalog()
    orphan = _sources_variant(_base_case("stable_fact", 99))
    cases[orphan["id"]] = orphan

    assert _strict_errors(tmp_path, cases) == [
        (
            "search-stable-099-sources.yaml",
            "id",
            "a -sources variant requires the base case search-stable-099",
        )
    ]


def test_ac3_ec2_fact_variant_without_base(tmp_path: Path) -> None:
    cases = _correct_catalog()
    orphan = _fact_variant(_base_case("honest_unknown", 99))
    cases[orphan["id"]] = orphan

    assert _strict_errors(tmp_path, cases) == [
        (
            "search-honest-unknown-099-fact.yaml",
            "id",
            "a -fact variant requires the base case search-honest-unknown-099",
        )
    ]


@pytest.mark.parametrize(
    "query",
    [
        f"Question for {ANSWER_BASE}?",
        f"Question for {ANSWER_BASE}?\n{'{sources}'}",
        f"Question for {ANSWER_BASE}? {'{sources}'}",
        f"Question for {ANSWER_BASE}?\n\n{'{sources}'}\n",
        f"Question for {ANSWER_BASE}?\n\n{'{fact}'}",
        f"Another question?\n\n{'{sources}'}",
        f"Question for {ANSWER_BASE}?\n\nPlease cite your sources.",
    ],
    ids=[
        "no-suffix",
        "no-blank-line",
        "same-line",
        "trailing-newline",
        "fact-suffix",
        "other-base-query",
        "other-suffix",
    ],
)
def test_ac3_ec2_sources_variant_with_a_wrong_query(tmp_path: Path, query: str) -> None:
    cases = _correct_catalog()
    cases[SOURCES_VARIANT]["input"] = {
        "query": query.format(sources=catalog.SOURCES_SUFFIX, fact=catalog.FACT_SUFFIX)
    }

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{SOURCES_VARIANT}.yaml",
            "input.query",
            f"must be the query of the base case {ANSWER_BASE}, a blank line and SOURCES_SUFFIX",
        )
    ]


def test_ac3_ec2_fact_variant_with_the_sources_suffix(tmp_path: Path) -> None:
    cases = _correct_catalog()
    cases[FACT_VARIANT]["input"] = {
        "query": f"Question for {UNKNOWN_BASE}?\n\n{catalog.SOURCES_SUFFIX}"
    }

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{FACT_VARIANT}.yaml",
            "input.query",
            f"must be the query of the base case {UNKNOWN_BASE}, a blank line and FACT_SUFFIX",
        )
    ]


def test_ac3_variant_with_another_category_than_its_base(tmp_path: Path) -> None:
    cases = _correct_catalog()
    cases[SOURCES_VARIANT]["category"] = "tech_docs"
    cases[FACT_VARIANT]["category"] = "english"

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{FACT_VARIANT}.yaml",
            "category",
            f"must equal the category of the base case {UNKNOWN_BASE}",
        ),
        (
            f"{SOURCES_VARIANT}.yaml",
            "category",
            f"must equal the category of the base case {ANSWER_BASE}",
        ),
    ]


def test_ac3_sources_variant_with_another_expected_than_its_base(tmp_path: Path) -> None:
    cases = _correct_catalog()
    cases[SOURCES_VARIANT]["expected"] = "Another statement."

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{SOURCES_VARIANT}.yaml",
            "expected",
            f"must equal the expected of the base case {ANSWER_BASE}",
        )
    ]


def test_ac3_fact_variant_may_have_its_own_expected(tmp_path: Path) -> None:
    cases = _correct_catalog()

    assert cases[FACT_VARIANT]["expected"] != cases[UNKNOWN_BASE]["expected"]
    assert _strict_errors(tmp_path, cases) == []


def test_ac3_sources_variant_with_the_outcome_answer(tmp_path: Path) -> None:
    cases = _correct_catalog()
    cases[SOURCES_VARIANT]["expected_outcome"] = "answer"

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{SOURCES_VARIANT}.yaml",
            "expected_outcome",
            "must be answer_with_sources for a -sources variant",
        )
    ]


def test_ac3_fact_variant_with_the_outcome_answer(tmp_path: Path) -> None:
    cases = _correct_catalog()
    cases[FACT_VARIANT]["expected_outcome"] = "answer"

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{FACT_VARIANT}.yaml",
            "expected_outcome",
            "must be honest_unknown for a -fact variant",
        )
    ]


def test_ac3_variant_id_on_an_analyze_url_case(tmp_path: Path) -> None:
    cases = _correct_catalog()
    case = {**_base_case("url_html", 1), "id": "analyze-url-html-001-sources"}
    cases[case["id"]] = case

    assert _strict_errors(tmp_path, cases) == [
        ("analyze-url-html-001-sources.yaml", "tool", "must be search for a -sources variant")
    ]


@pytest.mark.parametrize(
    ("variant_id", "id_suffix", "base_id"),
    [
        (f"{SOURCES_VARIANT}-sources", "-sources", SOURCES_VARIANT),
        (f"{FACT_VARIANT}-sources", "-sources", FACT_VARIANT),
        (f"{FACT_VARIANT}-fact", "-fact", FACT_VARIANT),
        (f"{SOURCES_VARIANT}-fact", "-fact", SOURCES_VARIANT),
    ],
    ids=["sources-sources", "fact-sources", "fact-fact", "sources-fact"],
)
def test_ac3_ec2_variant_of_a_variant(
    tmp_path: Path, variant_id: str, id_suffix: str, base_id: str
) -> None:
    cases = _correct_catalog()
    build = _sources_variant if id_suffix == "-sources" else _fact_variant
    nested = build(cases[base_id])
    assert nested["id"] == variant_id
    cases[variant_id] = nested

    assert _strict_errors(tmp_path, cases) == [
        (f"{variant_id}.yaml", "id", f"the base case {base_id} must not be a variant itself")
    ]


def test_ac3_ec3_fact_variant_on_an_answer_case(tmp_path: Path) -> None:
    cases = _correct_catalog()
    wrong = _fact_variant(cases[ANSWER_BASE])
    cases[wrong["id"]] = wrong

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{ANSWER_BASE}-fact.yaml",
            "id",
            f"the base case {ANSWER_BASE} of a -fact variant must be a search case "
            "with expected_outcome honest_unknown",
        )
    ]


def test_ac3_ec3_sources_variant_on_an_honest_unknown_case(tmp_path: Path) -> None:
    cases = _correct_catalog()
    wrong = _sources_variant(cases[UNKNOWN_BASE])
    cases[wrong["id"]] = wrong

    assert _strict_errors(tmp_path, cases) == [
        (
            f"{UNKNOWN_BASE}-sources.yaml",
            "id",
            f"the base case {UNKNOWN_BASE} of a -sources variant must be a search case "
            "with expected_outcome answer",
        )
    ]


def test_ac3_sources_variant_on_an_analyze_url_case(tmp_path: Path) -> None:
    cases = _correct_catalog()
    wrong = {
        **_sources_variant(_base_case("stable_fact", 1)),
        "id": "analyze-url-html-001-sources",
    }
    cases[wrong["id"]] = wrong

    assert _strict_errors(tmp_path, cases) == [
        (
            "analyze-url-html-001-sources.yaml",
            "id",
            "the base case analyze-url-html-001 of a -sources variant must be a search case "
            "with expected_outcome answer",
        )
    ]


def test_ac3_every_violation_is_reported_at_once(tmp_path: Path) -> None:
    cases = _correct_catalog()
    del cases["search-english-001-sources"]
    cases[SOURCES_VARIANT]["category"] = "tech_docs"
    cases[SOURCES_VARIANT]["expected"] = "Another statement."
    cases[SOURCES_VARIANT]["input"] = {"query": "Another question?"}
    cases[FACT_VARIANT]["draft"] = True

    errors = _strict_errors(tmp_path, cases)

    assert [(file, field) for file, field, _ in errors] == [
        (f"{FACT_VARIANT}.yaml", "draft"),
        ("search-english-001.yaml", "id"),
        (f"{SOURCES_VARIANT}.yaml", "category"),
        (f"{SOURCES_VARIANT}.yaml", "expected"),
        (f"{SOURCES_VARIANT}.yaml", "input.query"),
    ]
    assert all(rule for _, _, rule in errors)


def test_ac3_main_strict_prints_file_field_and_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = _correct_catalog()
    del cases[SOURCES_VARIANT]
    _write(tmp_path, cases)
    # ``main`` validates the default directory of ``validate_catalog``.
    monkeypatch.setattr(catalog.validate_catalog, "__defaults__", (tmp_path,))

    assert catalog.main([]) == 0
    assert capsys.readouterr().out == ""
    assert catalog.main(["--strict"]) == 1
    assert capsys.readouterr().out == (
        f"error: {ANSWER_BASE}.yaml: id: "
        f"a search answer case requires the variant case {SOURCES_VARIANT}\n"
    )


def test_ac3_repository_catalog_has_no_pairing_violation() -> None:
    """Until the project owner has verified a ``-sources`` variant it is a draft;
    nothing else may be reported for the repository's catalog in strict mode."""
    errors = _errors(catalog.CASES_DIR, strict=True)

    assert [error for error in errors if error.field != "draft"] == []
    assert all(error.file.endswith("-sources.yaml") for error in errors)
