"""Ground-truth catalog format and validator (ADR 0005, issue #3).

This module defines the case format of ``eval/cases/`` and validates it.
It is deliberately not part of a package: the eval script from #10 imports
or executes it directly, and it never imports ``gemini_search_mcp``. Each
case is one YAML file whose name equals the case ``id`` plus ``.yaml``;
the per-case format is enforced by the Pydantic models below, the rules
that span several cases (unique ids, file naming, minimum distribution)
by :func:`validate_catalog`.

Invoke as ``uv run python eval/catalog.py [--strict]``: exit code 0 when
there are no errors (warnings allowed), otherwise non-zero. Every finding
names file, field and rule.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

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

EXPECTED_OUTCOME_PATTERN = "^(?:answer|honest_unknown|error:(?:" + "|".join(ERROR_CODES) + "))$"
"""Full-match pattern for ``expected_outcome``: ``answer``, ``honest_unknown``
or ``error:<code>`` with a code from ADR 0007."""

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
      ``error:<code>`` with a code from ADR 0007
      (:data:`EXPECTED_OUTCOME_PATTERN`).
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
    """

    tool: Literal["analyze_url"]
    input: AnalyzeUrlInput


Case = Annotated[SearchCase | AnalyzeUrlCase, Field(discriminator="tool")]
"""A ground-truth case for either tool, discriminated by ``tool``.

Because the discriminator binds ``tool`` to the ``input`` model, a case
whose ``input`` does not match its ``tool`` (for example an
``analyze_url`` case whose ``input`` also contains ``query``) is invalid
with the field ``input`` named."""


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
          ``must end with .yaml``.
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
          answer, honest_unknown or error:<code> with a code from ADR
          0007``. An ``input`` that does not match ``tool`` is always one
          of these errors.
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

    Args:
        cases_dir: catalog directory to validate; defaults to the
            repository's own :data:`CASES_DIR`.
        strict: also apply the strict-only errors above.
        today: reference date for the staleness warning.

    Returns:
        All findings, errors and warnings; empty when the catalog is valid.
    """
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
