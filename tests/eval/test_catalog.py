"""Acceptance tests for the ground-truth catalog format and validator (issue #3).

The catalog module is deliberately not a package, so it is loaded from its
file path. The tests drive it through its public functions only and build
their catalogs in ``tmp_path``; the repository's own ``eval/cases/`` is used
only by the AC1 test.
"""

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / "eval" / "catalog.py"
TODAY = date(2026, 11, 12)


def _load_catalog_module() -> Any:
    spec = importlib.util.spec_from_file_location("eval_catalog", CATALOG_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["eval_catalog"] = module
    spec.loader.exec_module(module)
    return module


catalog = _load_catalog_module()


def _search_case(**overrides: object) -> dict[str, object]:
    """Return a valid ``search`` case, with ``overrides`` applied on top."""
    case: dict[str, object] = {
        "id": "search-stable-001",
        "tool": "search",
        "category": "stable_fact",
        "input": {"query": "In which year was RFC 1035 published?"},
        "expected": "RFC 1035 was published in November 1987.",
        "allowed_sources": ["rfc-editor.org"],
        "ground_truth_date": "2026-11-10",
        "expected_outcome": "answer",
    }
    case.update(overrides)
    return case


def _analyze_url_case(**overrides: object) -> dict[str, object]:
    """Return a valid ``analyze_url`` case, with ``overrides`` applied on top."""
    case: dict[str, object] = {
        "id": "analyze-url-html-001",
        "tool": "analyze_url",
        "category": "url_html",
        "input": {
            "url": "https://www.rfc-editor.org/rfc/rfc1035.html",
            "question": "Which protocol does RFC 1035 specify?",
        },
        "expected": "RFC 1035 specifies the Internet's Domain Name System (DNS).",
        "allowed_sources": ["rfc-editor.org"],
        "ground_truth_date": "2026-11-10",
        "expected_outcome": "answer",
    }
    case.update(overrides)
    return case


def _write_case(
    cases_dir: Path,
    case: dict[str, object],
    filename: str | None = None,
) -> str:
    """Write ``case`` as YAML and return the file name used."""
    cases_dir.mkdir(parents=True, exist_ok=True)
    name = filename if filename is not None else f"{case['id']}.yaml"
    (cases_dir / name).write_text(yaml.safe_dump(case, sort_keys=False), encoding="utf-8")
    return name


def _write_raw(cases_dir: Path, filename: str, content: str) -> str:
    cases_dir.mkdir(parents=True, exist_ok=True)
    (cases_dir / filename).write_text(content, encoding="utf-8")
    return filename


def _errors(findings: list[Any]) -> list[Any]:
    return [finding for finding in findings if finding.severity == "error"]


def _warnings(findings: list[Any]) -> list[Any]:
    return [finding for finding in findings if finding.severity == "warning"]


def _matching(findings: list[Any], *, file: str, field: str) -> list[Any]:
    return [finding for finding in findings if finding.file == file and finding.field == field]


def _validate(cases_dir: Path, *, strict: bool = False) -> list[Any]:
    return catalog.validate_catalog(cases_dir, strict=strict, today=TODAY)


def test_ac1_example_cases_are_valid() -> None:
    findings = catalog.validate_catalog(catalog.CASES_DIR, today=TODAY)
    assert _errors(findings) == []

    cases = catalog.load_catalog(catalog.CASES_DIR)
    assert {case.category for case in cases} == set(catalog.MINIMUM_DISTRIBUTION)


def test_ac2_missing_required_field_names_file_and_field(tmp_path: Path) -> None:
    case = _search_case()
    del case["expected"]
    filename = _write_case(tmp_path, case)

    errors = _errors(_validate(tmp_path))

    matching = _matching(errors, file=filename, field="expected")
    assert matching, f"expected an error for {filename}: expected, got {errors}"
    assert matching[0].rule


def test_ac2_input_not_matching_tool_names_file_and_field(tmp_path: Path) -> None:
    case = _search_case(
        input={
            "query": "In which year was RFC 1035 published?",
            "url": "https://www.rfc-editor.org/rfc/rfc1035.html",
        }
    )
    filename = _write_case(tmp_path, case)

    errors = _errors(_validate(tmp_path))

    matching = [
        finding
        for finding in errors
        if finding.file == filename
        and (finding.field == "input" or finding.field.startswith("input."))
    ]
    assert matching, f"expected an error naming input in {filename}, got {errors}"
    assert matching[0].rule


def test_ac2_invalid_expected_outcome_names_file_and_field(tmp_path: Path) -> None:
    filename = _write_case(tmp_path, _search_case(expected_outcome="maybe"))

    errors = _errors(_validate(tmp_path))

    matching = _matching(errors, file=filename, field="expected_outcome")
    assert matching, f"expected an error for expected_outcome in {filename}, got {errors}"
    assert matching[0].rule


def test_ac3_duplicate_id_is_an_error(tmp_path: Path) -> None:
    # Sorted by file name, "dup-001.yaml" comes first and "zz-dup-001.yaml"
    # reuses its id, so the duplicate finding belongs to the second file.
    _write_case(tmp_path, _search_case(id="dup-001"), filename="dup-001.yaml")
    filename = _write_case(tmp_path, _search_case(id="dup-001"), filename="zz-dup-001.yaml")

    errors = _errors(_validate(tmp_path))

    matching = [
        finding
        for finding in _matching(errors, file=filename, field="id")
        if "unique" in finding.rule or "dup-001.yaml" in finding.rule
    ]
    assert matching, f"expected a duplicate-id error for {filename}, got {errors}"


def test_ac3_file_name_different_from_id_is_an_error(tmp_path: Path) -> None:
    case = _search_case(id="search-stable-001")
    filename = _write_case(tmp_path, case, filename="wrong-name.yaml")

    errors = _errors(_validate(tmp_path))

    matching = _matching(errors, file=filename, field="id")
    assert matching, f"expected a file-name error for {filename}, got {errors}"
    assert any("wrong-name" in finding.rule for finding in matching)


def test_ac3_load_catalog_raises_catalog_error_with_error_findings(tmp_path: Path) -> None:
    filename = _write_case(tmp_path, _search_case(expected_outcome="maybe"))

    with pytest.raises(catalog.CatalogError) as excinfo:
        catalog.load_catalog(tmp_path)

    findings = excinfo.value.findings
    assert findings
    assert all(finding.severity == "error" for finding in findings)
    assert any(finding.file == filename for finding in findings)
    assert filename in str(excinfo.value)


def test_ac4_stale_current_fact_warns_but_is_no_error(tmp_path: Path) -> None:
    stale_date = (TODAY - timedelta(days=120)).isoformat()
    filename = _write_case(
        tmp_path,
        _search_case(category="current_fact", ground_truth_date=stale_date),
    )

    findings = _validate(tmp_path)

    assert _errors(findings) == []
    warnings = _warnings(findings)
    assert len(warnings) == 1, warnings
    assert warnings[0].file == filename
    assert warnings[0].field == "ground_truth_date"


def test_ac5_strict_rejects_drafts(tmp_path: Path) -> None:
    filename = _write_case(tmp_path, _search_case(draft=True))

    assert _errors(_validate(tmp_path)) == []

    errors = _errors(_validate(tmp_path, strict=True))
    matching = _matching(errors, file=filename, field="draft")
    assert matching, f"expected a draft error for {filename}, got {errors}"
    assert matching[0].rule


def test_ac5_strict_rejects_too_few_cases_per_category(tmp_path: Path) -> None:
    _write_case(tmp_path, _search_case(category="stable_fact"))

    assert _errors(_validate(tmp_path)) == []

    errors = _errors(_validate(tmp_path, strict=True))
    distribution = [
        finding for finding in errors if finding.file == "catalog" and finding.field == "category"
    ]
    assert distribution, f"expected distribution errors, got {errors}"
    assert any("stable_fact" in finding.rule for finding in distribution)


def test_ec1_empty_cases_dir_is_valid_without_strict(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    assert _validate(cases_dir) == []


def test_ec1_strict_empty_cases_dir_reports_minimum_distribution(tmp_path: Path) -> None:
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    errors = _errors(_validate(cases_dir, strict=True))

    assert len(errors) == len(catalog.MINIMUM_DISTRIBUTION), errors
    assert all(finding.file == "catalog" for finding in errors)
    assert all(finding.field == "category" for finding in errors)


def test_ec2_yml_extension_is_an_error(tmp_path: Path) -> None:
    filename = _write_case(tmp_path, _search_case(id="case"), filename="case.yml")

    errors = _errors(_validate(tmp_path))

    matching = _matching(errors, file=filename, field="file name")
    assert matching, f"expected an extension error for {filename}, got {errors}"
    assert any(".yaml" in finding.rule for finding in matching)


@pytest.mark.parametrize("content", ["", "- one\n- two\n"], ids=["empty", "list"])
def test_ec3_non_mapping_yaml_is_an_error(tmp_path: Path, content: str) -> None:
    filename = _write_raw(tmp_path, "broken.yaml", content)

    errors = _errors(_validate(tmp_path))

    matching = _matching(errors, file=filename, field="file")
    assert matching, f"expected a mapping error for {filename}, got {errors}"
    assert matching[0].rule


@pytest.mark.parametrize(
    ("days", "expected_warnings"), [(90, 0), (91, 1)], ids=["90-days", "91-days"]
)
def test_ec4_current_fact_staleness_boundary(
    tmp_path: Path,
    days: int,
    expected_warnings: int,
) -> None:
    reference = (TODAY - timedelta(days=days)).isoformat()
    _write_case(
        tmp_path,
        _search_case(category="current_fact", ground_truth_date=reference),
    )

    findings = _validate(tmp_path)

    assert _errors(findings) == []
    warnings = _warnings(findings)
    assert len(warnings) == expected_warnings, warnings
    if warnings:
        assert warnings[0].field == "ground_truth_date"


def test_ec5_unknown_error_code_names_expected_outcome(tmp_path: Path) -> None:
    filename = _write_case(tmp_path, _search_case(expected_outcome="error:timeout"))

    errors = _errors(_validate(tmp_path))

    matching = _matching(errors, file=filename, field="expected_outcome")
    assert matching, f"expected an error for expected_outcome in {filename}, got {errors}"
    assert matching[0].rule


def test_ec6_empty_allowed_sources_is_an_error(tmp_path: Path) -> None:
    filename = _write_case(tmp_path, _search_case(allowed_sources=[]))

    errors = _errors(_validate(tmp_path))

    matching = _matching(errors, file=filename, field="allowed_sources")
    assert matching, f"expected an error for allowed_sources in {filename}, got {errors}"
    assert matching[0].rule


def test_ec7_analyze_url_input_with_query_is_an_error(tmp_path: Path) -> None:
    case = _analyze_url_case(
        input={
            "url": "https://www.rfc-editor.org/rfc/rfc1035.html",
            "question": "Which protocol does RFC 1035 specify?",
            "query": "RFC 1035 protocol",
        }
    )
    filename = _write_case(tmp_path, case)

    errors = _errors(_validate(tmp_path))

    matching = [
        finding
        for finding in errors
        if finding.file == filename
        and (finding.field == "input" or finding.field.startswith("input."))
    ]
    assert matching, f"expected an input mismatch error for {filename}, got {errors}"
    assert matching[0].rule


@pytest.mark.parametrize("name", [".DS_Store", ".gitkeep", "._search-stable-001.yaml"])
def test_hidden_files_in_cases_dir_are_ignored(tmp_path: Path, name: str) -> None:
    _write_raw(tmp_path, name, "not a case")

    assert _validate(tmp_path) == []
