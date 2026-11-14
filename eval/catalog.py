"""Ground-truth catalog format and validator (ADR 0005, issues #3 and #36).

This module defines the case format of ``eval/cases/`` and validates it.
It is deliberately not part of a package: the eval script from #10 imports
or executes it directly, and it never imports ``gemini_search_mcp``. Each
case is one YAML file whose name equals the case ``id`` plus ``.yaml``;
the per-case format is enforced by the Pydantic models below, the rules
that span several cases (unique ids, file naming, minimum distribution,
pairing of base cases and their variants) by :func:`validate_catalog`.

Invoke as ``uv run python eval/catalog.py [--strict]``: exit code 0 when
there are no errors (warnings allowed), otherwise non-zero. Every finding
names file, field and rule.
"""

import argparse
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

CASES_DIR = Path(__file__).resolve().parent / "cases"
"""Directory holding the case files, one ``<id>.yaml`` file per case."""

CASE_SUFFIX = ".yaml"
"""Required file name extension of every case file (not ``.yml``)."""

STALE_DAYS = 90
"""A ``current_fact`` case is stale when its ``ground_truth_date`` is older
than this many days; staleness is a warning, never an error."""

ERROR_CODES: tuple[str, ...] = (
    "invalid_input",
    "url_not_allowed",
    "url_unreachable",
    "url_unsafe",
    "upstream_unavailable",
    "upstream_error",
    "internal_error",
)
"""Every error code from ADR 0007; the only codes allowed in
``error:<code>`` values of ``expected_outcome``."""

MINIMUM_DISTRIBUTION: dict[str, int] = {
    "stable_fact": 6,
    "current_fact": 6,
    "tech_docs": 6,
    "german": 4,
    "english": 4,
    "honest_unknown": 4,
    "url_html": 4,
    "url_pdf": 4,
    "url_failure": 3,
}
"""Minimum number of cases per category from ADR 0005 (41 cases in total);
only checked in strict mode."""

ANSWER_WITH_SOURCES = "answer_with_sources"
"""``expected_outcome`` of a ``search`` case whose question asks for sources
(ADR 0005); never allowed for ``analyze_url``."""

ANALYZE_URL_EXPECTED_OUTCOME_PATTERN = (
    "^(?:answer|honest_unknown|error:(?:" + "|".join(ERROR_CODES) + "))$"
)
"""Full-match pattern for ``expected_outcome`` of an ``analyze_url`` case:
``answer``, ``honest_unknown`` or ``error:<code>`` with a code from ADR 0007."""

EXPECTED_OUTCOME_PATTERN = (
    "^(?:answer|"
    + ANSWER_WITH_SOURCES
    + "|honest_unknown|error:(?:"
    + "|".join(ERROR_CODES)
    + "))$"
)
"""Full-match pattern for ``expected_outcome`` of a ``search`` case:
``answer``, ``answer_with_sources``, ``honest_unknown`` or ``error:<code>``
with a code from ADR 0007."""

SOURCES_SUFFIX = (
    "Answer only from Google Search results. Cite the primary source of truth "
    "(official documentation, standards body or publisher of record) where the "
    "answer can be checked."
)
"""Text a ``-sources`` variant appends to the query of its base case (ADR 0005)."""

FACT_SUFFIX = (
    "Answer only with a fact a source confirms; if none does, say it is not publicly known."
)
"""Text a ``-fact`` variant appends to the query of its base case (ADR 0005)."""

VARIANT_SEPARATOR = "\n\n"
"""What stands between the base query and the suffix in a variant's query:
one blank line."""


@dataclass(frozen=True, slots=True)
class VariantKind:
    """One kind of variant case of a ``search`` base case (ADR 0005).

    Attributes:
        id_suffix: what the variant's id appends to the id of its base case.
            In strict mode an id ending with it always denotes a variant.
        base_outcome: ``expected_outcome`` of the base case. Every ``search``
            case with this outcome that is not a variant itself needs exactly
            one variant of this kind.
        outcome: ``expected_outcome`` of the variant.
        query_suffix: text appended to the base query after
            :data:`VARIANT_SEPARATOR`.
        suffix_name: name of the constant holding ``query_suffix``, used in
            rule texts.
        same_expected: whether the variant must repeat the base's ``expected``.
    """

    id_suffix: str
    base_outcome: str
    outcome: str
    query_suffix: str
    suffix_name: str
    same_expected: bool


VARIANT_KINDS: tuple[VariantKind, ...] = (
    VariantKind(
        id_suffix="-sources",
        base_outcome="answer",
        outcome=ANSWER_WITH_SOURCES,
        query_suffix=SOURCES_SUFFIX,
        suffix_name="SOURCES_SUFFIX",
        same_expected=True,
    ),
    VariantKind(
        id_suffix="-fact",
        base_outcome="honest_unknown",
        outcome="honest_unknown",
        query_suffix=FACT_SUFFIX,
        suffix_name="FACT_SUFFIX",
        same_expected=False,
    ),
)
"""Both variant kinds of ADR 0005: ``<id>-sources`` for a ``search`` ``answer``
case and ``<id>-fact`` for a ``search`` ``honest_unknown`` case. The pairing
rules are only checked in strict mode."""

Category = Literal[
    "stable_fact",
    "current_fact",
    "tech_docs",
    "german",
    "english",
    "honest_unknown",
    "url_html",
    "url_pdf",
    "url_failure",
]
"""Every category from ADR 0005, identical to the keys of
:data:`MINIMUM_DISTRIBUTION`."""


class SearchInput(BaseModel):
    """Input of a ``search`` case (ADR 0003, ADR 0005).

    Exactly one field, ``query``. Any other key — including ``url``,
    ``question`` or an unknown key — makes the case invalid, because
    ``input`` must match ``tool``. ``max_sources`` is a runtime option and
    is not part of a case.
    """

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)


class AnalyzeUrlInput(BaseModel):
    """Input of an ``analyze_url`` case (ADR 0004, ADR 0005).

    Exactly the two fields ``url`` and ``question``. Any other key —
    including ``query`` — makes the case invalid, because ``input`` must
    match ``tool``.
    """

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1)
    question: str = Field(min_length=1)


class _CaseFields(BaseModel):
    """Fields every case shares regardless of ``tool`` (ADR 0005).

    Never instantiated directly; use :class:`SearchCase`,
    :class:`AnalyzeUrlCase` or the :data:`Case` union. Unknown keys are
    errors, so a mistyped field name cannot pass silently. Field rules:

    - ``id``: non-empty; must equal the file name stem and be unique across
      the catalog (checked by :func:`validate_catalog`, not by the model).
    - ``category``: one of the categories from ADR 0005.
    - ``expected``: the core statement in one sentence, or the expected
      behavior for unknowns and errors; non-empty.
    - ``allowed_sources``: non-empty list of allowed domains; for
      ``analyze_url`` cases it contains the host of the analyzed test URL.
    - ``ground_truth_date``: ISO date (``YYYY-MM-DD``) of the core
      statement's reference date.
    - ``expected_outcome``: ``answer``, ``honest_unknown`` or
      ``error:<code>`` with a code from ADR 0007, for ``search`` also
      ``answer_with_sources`` (:data:`EXPECTED_OUTCOME_PATTERN`,
      :data:`ANALYZE_URL_EXPECTED_OUTCOME_PATTERN`).
    - ``draft``: optional flag for example cases; ``true`` is an error in
      strict mode (checked by :func:`validate_catalog`, not by the model).
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: Category
    expected: str = Field(min_length=1)
    allowed_sources: list[str] = Field(min_length=1)
    ground_truth_date: date
    expected_outcome: str = Field(pattern=EXPECTED_OUTCOME_PATTERN)
    draft: bool = False


class SearchCase(_CaseFields):
    """A ground-truth case for the ``search`` tool (ADR 0003, ADR 0005).

    ``tool`` is the union discriminator and must be given in the file;
    ``input`` must be a :class:`SearchInput` mapping.
    """

    tool: Literal["search"]
    input: SearchInput


class AnalyzeUrlCase(_CaseFields):
    """A ground-truth case for the ``analyze_url`` tool (ADR 0004, ADR 0005).

    ``tool`` is the union discriminator and must be given in the file;
    ``input`` must be an :class:`AnalyzeUrlInput` mapping.
    ``expected_outcome`` must not be ``answer_with_sources``, which exists
    only for ``search``.
    """

    tool: Literal["analyze_url"]
    input: AnalyzeUrlInput
    expected_outcome: str = Field(pattern=ANALYZE_URL_EXPECTED_OUTCOME_PATTERN)


Case = Annotated[SearchCase | AnalyzeUrlCase, Field(discriminator="tool")]
"""A ground-truth case for either tool, discriminated by ``tool``.

Because the discriminator binds ``tool`` to the ``input`` model, a case
whose ``input`` does not match its ``tool`` (for example an
``analyze_url`` case whose ``input`` also contains ``query``) is invalid
with the field ``input`` named."""


_CASE_ADAPTER = TypeAdapter(Case)
"""Validates one parsed YAML mapping against the :data:`Case` union."""

_MAPPING_RULE = "must be a YAML mapping at the top level"
"""Rule text for a case file whose YAML is not a mapping."""

_CATEGORY_RULE = "must be one of " + ", ".join(MINIMUM_DISTRIBUTION)
"""Rule text for an unknown category, listing every allowed category."""

_INPUT_RULES: dict[str, str] = {
    "search": "must contain exactly query for tool search",
    "analyze_url": "must contain exactly url and question for tool analyze_url",
}
"""Rule text for an ``input`` that does not match the case's ``tool``."""

_EXPECTED_OUTCOME_RULE = (
    "must be answer, answer_with_sources (tool search only), honest_unknown or "
    "error:<code> with a code from ADR 0007"
)
"""Rule text for an ``expected_outcome`` that is unknown or not allowed for
the case's ``tool``."""


def _rule_for(field: str, tool: str | None) -> str:
    """Return the rule text for a model violation of ``field`` (issue #3)."""
    if field.startswith("input."):
        return "must not be empty"
    if field == "input":
        return _INPUT_RULES.get(tool, "must match the tool")
    if field in {"id", "expected"}:
        return "must not be empty"
    if field == "tool":
        return "must be search or analyze_url"
    if field == "category":
        return _CATEGORY_RULE
    if field == "allowed_sources":
        return "must be a non-empty list of domains"
    if field == "ground_truth_date":
        return "must be an ISO date"
    if field == "expected_outcome":
        return _EXPECTED_OUTCOME_RULE
    if field == "draft":
        return "must be true or false"
    return "must be an ADR 0005 field"


def _finding_for(error: Mapping[str, Any], filename: str, tool: str | None) -> Finding:
    """Turn one Pydantic error into a finding with a dotted field path.

    Pydantic reports the union discriminator as the first location element
    for errors inside a member model (for example
    ``("search", "input", "url")``); the discriminator itself is reported
    with an empty location.
    """
    parts = [str(part) for part in error["loc"]]
    if error["type"] in {"union_tag_invalid", "union_tag_not_found"}:
        field = "tool"
    elif len(parts) >= 2:
        path = parts[1:]
        if path[0] == "input":
            # A missing key, an extra key or a non-mapping ``input`` means the
            # input does not match the tool; an invalid value names the field.
            mismatch = len(path) == 1 or error["type"] in {"extra_forbidden", "missing"}
            field = "input" if mismatch else f"input.{path[1]}"
        else:
            field = path[0]
    elif parts and parts[0] in _INPUT_RULES:
        field = "tool"
    else:
        field = "file"
    return Finding("error", filename, field, _rule_for(field, tool))


def _read_case(path: Path) -> tuple[list[Finding], Case | None, str | None]:
    """Read and validate one case file.

    Returns the model errors, the parsed case when valid, and the raw ``id``
    when the file carries one. The raw ``id`` is returned even for an
    otherwise invalid case so that uniqueness and file-name rules still
    apply.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return [Finding("error", path.name, "file", _MAPPING_RULE)], None, None
    if not isinstance(data, dict):
        return [Finding("error", path.name, "file", _MAPPING_RULE)], None, None
    raw_id = data.get("id")
    case_id = raw_id if isinstance(raw_id, str) and raw_id else None
    raw_tool = data.get("tool")
    tool = raw_tool if isinstance(raw_tool, str) and raw_tool in _INPUT_RULES else None
    try:
        case = _CASE_ADAPTER.validate_python(data)
    except ValidationError as exc:
        return [_finding_for(error, path.name, tool) for error in exc.errors()], None, case_id
    return [], case, case_id


def _deduplicate(findings: Sequence[Finding]) -> list[Finding]:
    """Drop exact duplicate findings while preserving their order."""
    seen: set[Finding] = set()
    unique: list[Finding] = []
    for finding in findings:
        if finding not in seen:
            seen.add(finding)
            unique.append(finding)
    return unique


def _variant_kind(case_id: str) -> VariantKind | None:
    """Return the variant kind whose id suffix ``case_id`` ends with, if any."""
    for kind in VARIANT_KINDS:
        if case_id.endswith(kind.id_suffix):
            return kind
    return None


def _variant_findings(cases: Sequence[tuple[str, Case]]) -> list[Finding]:
    """Check the pairing of base cases and variants (strict mode, ADR 0005).

    ``cases`` holds every valid case with its file name, ordered by file
    name. Returns the findings described in :func:`validate_catalog`, in
    that order.
    """
    by_id: dict[str, Case] = {}
    for _, case in cases:
        by_id.setdefault(case.id, case)
    findings: list[Finding] = []

    def error(name: str, field: str, rule: str) -> None:
        findings.append(Finding("error", name, field, rule))

    for name, case in cases:
        kind = _variant_kind(case.id)
        if kind is None:
            if isinstance(case, SearchCase):
                for wanted in VARIANT_KINDS:
                    variant_id = case.id + wanted.id_suffix
                    if case.expected_outcome == wanted.base_outcome and variant_id not in by_id:
                        error(
                            name,
                            "id",
                            f"a search {wanted.base_outcome} case requires the variant case "
                            f"{variant_id}",
                        )
            continue
        suffix = kind.id_suffix
        if not isinstance(case, SearchCase):
            error(name, "tool", f"must be search for a {suffix} variant")
            continue
        if case.expected_outcome != kind.outcome:
            error(name, "expected_outcome", f"must be {kind.outcome} for a {suffix} variant")
        base_id = case.id[: -len(suffix)]
        base = by_id.get(base_id)
        if base is None:
            error(name, "id", f"a {suffix} variant requires the base case {base_id}")
            continue
        if _variant_kind(base_id) is not None:
            error(name, "id", f"the base case {base_id} must not be a variant itself")
            continue
        if not isinstance(base, SearchCase) or base.expected_outcome != kind.base_outcome:
            error(
                name,
                "id",
                f"the base case {base_id} of a {suffix} variant must be a search case "
                f"with expected_outcome {kind.base_outcome}",
            )
            continue
        if case.category != base.category:
            error(name, "category", f"must equal the category of the base case {base_id}")
        if kind.same_expected and case.expected != base.expected:
            error(name, "expected", f"must equal the expected of the base case {base_id}")
        if case.input.query != base.input.query + VARIANT_SEPARATOR + kind.query_suffix:
            error(
                name,
                "input.query",
                f"must be the query of the base case {base_id}, a blank line and "
                f"{kind.suffix_name}",
            )
    return findings


@dataclass(frozen=True, slots=True)
class Finding:
    """One validation result line (issue #3).

    Attributes:
        severity: ``"error"`` or ``"warning"``. At least one error finding
            makes the catalog invalid and the validator exit non-zero;
            warnings alone keep exit code 0.
        file: name of the case file the finding is about, as it appears in
            the validated directory; the literal ``"catalog"`` for findings
            about the catalog as a whole (minimum distribution).
        field: dotted field path inside the case (``expected_outcome``,
            ``input.url``), the field of a file-level rule (``file``,
            ``file name``, ``id``, ``draft``, ``ground_truth_date``) or
            ``category`` for distribution findings.
        rule: short text of the violated rule, never containing case
            content.

    ``str(finding)`` is always ``"<severity>: <file>: <field>: <rule>"``;
    every finding therefore names file, field and rule.
    """

    severity: Literal["error", "warning"]
    file: str
    field: str
    rule: str

    def __str__(self) -> str:
        return f"{self.severity}: {self.file}: {self.field}: {self.rule}"


class CatalogError(Exception):
    """Loading the catalog failed because at least one case is invalid.

    Attributes:
        findings: every error finding, in the order produced by
            :func:`validate_catalog`.

    ``str(exc)`` joins the text of every finding with new lines and
    therefore names file, field and rule for each invalid file. Never
    raised for warnings.
    """

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = list(findings)
        super().__init__("\n".join(str(finding) for finding in self.findings))


def validate_catalog(
    cases_dir: Path = CASES_DIR,
    *,
    strict: bool = False,
    today: date | None = None,
) -> list[Finding]:
    """Validate every case file in ``cases_dir`` and return all findings.

    Preconditions:
        - ``cases_dir`` is the catalog directory. It may be empty or not
          exist; both count as an empty catalog, which is valid without
          ``strict`` and invalid with ``strict`` (minimum distribution).
        - ``today`` is the reference "now" for the staleness warning;
          ``None`` means ``date.today()``.

    Postcondition: the returned list holds one :class:`Finding` per violated
        rule, ordered by file name and, within a file, errors before
        warnings; findings about the catalog as a whole come last. An empty
        list means the catalog is valid.

    Every check (severity, field, rule text):

    Errors (always):
        - A directory entry whose name does not end with ``.yaml`` (for
          example a ``.yml`` file): field ``file name``, rule
          ``must end with .yaml``. Hidden files whose name starts with a
          dot (``.DS_Store``, ``.gitkeep``, editor swap files) are ignored.
        - A file that is not a YAML mapping at the top level (empty file,
          invalid YAML, list or scalar): field ``file``, rule ``must be a
          YAML mapping at the top level``.
        - Case data violating the model rules of :class:`SearchCase` /
          :class:`AnalyzeUrlCase`: field is the dotted field path
          (``id``, ``tool``, ``category``, ``input``,
          ``input.query`` / ``input.url`` / ``input.question``, an unknown
          top-level key, ``expected``, ``allowed_sources``,
          ``ground_truth_date``, ``expected_outcome``), rule text per
          field: ``must not be empty``; ``must be search or analyze_url``;
          ``must be one of <categories>``; ``must contain exactly query for
          tool search`` / ``must contain exactly url and question for tool
          analyze_url``; ``must be an ADR 0005 field``; ``must be a
          non-empty list of domains``; ``must be an ISO date``; ``must be
          answer, answer_with_sources (tool search only), honest_unknown or
          error:<code> with a code from ADR 0007``. An ``input`` that does
          not match ``tool`` is always one of these errors, and so is
          ``answer_with_sources`` on an ``analyze_url`` case.
        - An ``id`` already used by an earlier file (sorted by name):
          field ``id``, rule ``must be unique; also used in <first file>``.
        - A file name stem that differs from ``id``: field ``id``, rule
          ``must equal the file name <stem>``.

    Warnings (always, never affect the exit code):
        - A ``current_fact`` case whose ``ground_truth_date`` is more than
          :data:`STALE_DAYS` days before ``today``; exactly 90 days is not
          stale, 91 days is: field ``ground_truth_date``, rule ``older than
          90 days for a current_fact; refresh the case``.

    Errors only with ``strict=True``:
        - A case with ``draft: true``: field ``draft``, rule ``drafts are
          not allowed in strict mode``.
        - Fewer than :data:`MINIMUM_DISTRIBUTION[category]` valid cases in
          a category (drafts count): file ``catalog``, field ``category``,
          rule ``<category>: at least <n> case(s) required, found <m>``, one
          finding per category below the minimum.
        - The variant pairing rules of :data:`VARIANT_KINDS`, checked over
          the valid cases; ``<suffix>`` is ``-sources`` or ``-fact``. A case
          whose id ends with ``<suffix>`` is a variant, its base id is the
          id without it. These findings follow the per-file findings,
          ordered by file name, and precede the distribution findings:

          - a ``search`` ``answer`` case that is not a variant has no
            ``<id>-sources`` case, or a ``search`` ``honest_unknown`` case
            that is not a variant has no ``<id>-fact`` case: field ``id``,
            rule ``a search <outcome> case requires the variant case
            <id><suffix>`` (ids are unique, so there is never more than
            one);
          - a variant that is not a ``search`` case: field ``tool``, rule
            ``must be search for a <suffix> variant``; nothing else is
            checked for it;
          - a variant whose ``expected_outcome`` is not
            ``answer_with_sources`` (``-sources``) or ``honest_unknown``
            (``-fact``): field ``expected_outcome``, rule ``must be
            <outcome> for a <suffix> variant``;
          - a variant without its base case: field ``id``, rule ``a
            <suffix> variant requires the base case <base id>``;
          - a variant of a variant (``...-sources-sources``,
            ``...-fact-sources``): field ``id``, rule ``the base case
            <base id> must not be a variant itself``;
          - a variant whose base is not a ``search`` case with
            ``expected_outcome`` ``answer`` (``-sources``) or
            ``honest_unknown`` (``-fact``), for example ``-fact`` on an
            ``answer`` case: field ``id``, rule ``the base case <base id>
            of a <suffix> variant must be a search case with
            expected_outcome <outcome>``;
          - a variant whose ``category`` differs from its base: field
            ``category``, rule ``must equal the category of the base case
            <base id>``;
          - a ``-sources`` variant whose ``expected`` differs from its
            base: field ``expected``, rule ``must equal the expected of the
            base case <base id>``;
          - a variant whose query is not exactly the base query,
            :data:`VARIANT_SEPARATOR` and the suffix: field
            ``input.query``, rule ``must be the query of the base case
            <base id>, a blank line and SOURCES_SUFFIX`` (or
            ``FACT_SUFFIX``).

          The last three are only checked against a base of the right kind.

    Args:
        cases_dir: catalog directory to validate; defaults to the
            repository's own :data:`CASES_DIR`.
        strict: also apply the strict-only errors above.
        today: reference date for the staleness warning.

    Returns:
        All findings, errors and warnings; empty when the catalog is valid.
    """
    reference = today if today is not None else date.today()
    findings: list[Finding] = []
    valid_cases: list[tuple[str, Case]] = []
    seen_ids: dict[str, str] = {}
    entries = (
        sorted(cases_dir.iterdir(), key=lambda entry: entry.name) if cases_dir.is_dir() else []
    )
    for entry in entries:
        if not entry.is_file() or entry.name.startswith("."):
            continue
        name = entry.name
        if not name.endswith(CASE_SUFFIX):
            findings.append(Finding("error", name, "file name", f"must end with {CASE_SUFFIX}"))
            continue
        errors, case, case_id = _read_case(entry)
        warnings: list[Finding] = []
        if case_id is not None:
            first_file = seen_ids.get(case_id)
            if first_file is None:
                seen_ids[case_id] = name
            else:
                errors.append(
                    Finding(
                        "error",
                        name,
                        "id",
                        f"must be unique; also used in {first_file}",
                    )
                )
            stem = name[: -len(CASE_SUFFIX)]
            if case_id != stem:
                errors.append(Finding("error", name, "id", f"must equal the file name {stem}"))
        if case is not None:
            valid_cases.append((name, case))
            if (
                case.category == "current_fact"
                and (reference - case.ground_truth_date).days > STALE_DAYS
            ):
                warnings.append(
                    Finding(
                        "warning",
                        name,
                        "ground_truth_date",
                        f"older than {STALE_DAYS} days for a current_fact; refresh the case",
                    )
                )
            if strict and case.draft:
                errors.append(
                    Finding(
                        "error",
                        name,
                        "draft",
                        "drafts are not allowed in strict mode",
                    )
                )
        findings.extend(errors)
        findings.extend(warnings)
    if strict:
        findings.extend(_variant_findings(valid_cases))
        counts = Counter(case.category for _, case in valid_cases)
        for category, minimum in MINIMUM_DISTRIBUTION.items():
            found = counts.get(category, 0)
            if found < minimum:
                findings.append(
                    Finding(
                        "error",
                        "catalog",
                        "category",
                        f"{category}: at least {minimum} case(s) required, found {found}",
                    )
                )
    return _deduplicate(findings)


def load_catalog(cases_dir: Path = CASES_DIR) -> list[Case]:
    """Return every valid case in ``cases_dir``, sorted by file name.

    Reusable entry point for the eval script from #10. Runs the same checks
    as :func:`validate_catalog` without ``strict``.

    Postcondition: on success, the returned cases are valid, have unique
        ids and each file name equals the case ``id``; warnings (for
        example a stale ``current_fact``) do not prevent loading.

    Args:
        cases_dir: catalog directory to load; defaults to the repository's
            own :data:`CASES_DIR`.

    Returns:
        Every case, ordered by file name.

    Raises:
        CatalogError: when validation reports at least one error finding;
            the exception carries every error finding. Never raised for
            warnings or strict-only rules.
    """
    errors = [finding for finding in validate_catalog(cases_dir) if finding.severity == "error"]
    if errors:
        raise CatalogError(errors)
    cases: list[Case] = []
    if not cases_dir.is_dir():
        return cases
    for entry in sorted(cases_dir.iterdir(), key=lambda item: item.name):
        if entry.is_file() and not entry.name.startswith(".") and entry.name.endswith(CASE_SUFFIX):
            data = yaml.safe_load(entry.read_text(encoding="utf-8"))
            cases.append(_CASE_ADAPTER.validate_python(data))
    return cases


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the repository's catalog and report every finding (issue #3).

    Args:
        argv: command line without the program name; the only accepted
            argument is the optional flag ``--strict``. ``None`` reads
            ``sys.argv[1:]``.

    Behavior:
        Validates :data:`CASES_DIR` with ``strict`` taken from the command
        line and prints one line per finding — the :class:`Finding` text,
        which names file, field and rule — to stdout, warnings and errors
        alike.

    Returns:
        0 when no finding has severity ``error`` (warnings alone are
        allowed), 1 otherwise. Invalid arguments terminate the process
        with exit code 2 via argparse.
    """
    parser = argparse.ArgumentParser(
        description="Validate the ground-truth catalog in eval/cases/ (ADR 0005)."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "also reject drafts and enforce the minimum distribution per category "
            "and the pairing of base cases and their variants"
        ),
    )
    args = parser.parse_args(argv)
    findings = validate_catalog(strict=args.strict)
    for finding in findings:
        print(finding)
    return 1 if any(finding.severity == "error" for finding in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
