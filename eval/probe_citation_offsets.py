"""Live probe: offset base of ``url_citation`` indices (issue #29, input for #20).

Measures against the live Gemini API whether the ``start_index`` and
``end_index`` of ``url_citation`` annotations are relative to the whole answer
(the concatenation of all text blocks that ``GeminiProvider._answer_text``
builds) or to their own text block. The index unit is UTF-8 bytes (ADR 0003).

Requests go through :class:`CapturingProvider`, a :class:`GeminiProvider`
that keeps the raw interaction of its last successful call, so every request
is sent exactly as :meth:`GeminiProvider.search` sends it: API version
``v1`` (``GEMINI_API_VERSION``), the model from ``GEMINI_MODEL``, the prompt
as plain-text input, ``tools=[{"type": "google_search"}]``, no system
instruction, and the adapter's timeout, retry and concurrency limits from the
ADR 0010 settings. The probe evaluates the raw interaction below the adapter
because the adapter output no longer contains block boundaries.

Terms used throughout:

- *block*: every ``TextContent`` of every ``model_output`` step, in the order
  in which ``_answer_text`` concatenates them (step order, then content
  order); text blocks of other step types and non-text content are not
  blocks.
- *offset*: byte offset of a block in the concatenated answer, i.e. the sum
  of the UTF-8 byte lengths of all earlier blocks; *length*: the UTF-8 byte
  length of the block's own text.
- *annotation*: a ``URLCitation`` annotation of a block; every other
  annotation type is ignored (EC3).
- *checked annotation*: an annotation with both ``start_index`` and
  ``end_index`` present (not ``None``) in a block with ``offset > 0``.
  Annotations with a missing index are counted as missing and excluded from
  every hypothesis check and from the classification (EC2).
- *global hypothesis*: ``offset <= start < end <= offset + length``.
- *per-block hypothesis*: ``0 <= start < end <= length``.

Output contains numbers, prompt ids, classifications and error kinds only:
never the answer text, a URL, a title, a search query or the prompt text.
Results go to ``eval/runs/<date>-offset-probe/probe.jsonl``, one
:class:`InteractionRecord` per line; an existing directory aborts the run.

This file is not part of the package; the ADR 0009 layer rules for ``src/``
do not apply to it. It only runs with ``LIVE=1`` and a non-empty
``GEMINI_API_KEY`` and makes paid calls (ADR 0006). Invoke as
``uv run python eval/probe_citation_offsets.py [--prompt-id <id>]...
[--repeat <n>]``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from google.genai import interactions

from gemini_search_mcp.config import Settings
from gemini_search_mcp.gemini_client import Clock, GeminiProvider, InteractionsClient, Sleep
from gemini_search_mcp.provider import ProviderErrorKind

_EVAL_DIR = Path(__file__).resolve().parent

RUNS_DIR = _EVAL_DIR / "runs"
"""Parent directory of the probe run directory."""

RUN_DIR_SUFFIX = "offset-probe"
"""The run directory is ``RUNS_DIR / f"{date}-{RUN_DIR_SUFFIX}"``."""

RESULTS_FILE = "probe.jsonl"
"""File name of the result lines inside the run directory."""

MIN_REPEAT = 1
"""Smallest allowed ``--repeat`` value."""

MAX_REPEAT = 5
"""Largest allowed ``--repeat`` value."""

Classification = Literal["undecidable", "global", "per_block", "inconsistent"]
"""Offset base suggested by one interaction, see :func:`classify`."""

CLASSIFICATIONS: tuple[Classification, ...] = (
    "undecidable",
    "global",
    "per_block",
    "inconsistent",
)
"""All classifications in summary order."""


class ProbeAbort(Exception):
    """The probe stops before or instead of completing the run.

    ``str(exc)`` is a short, human-readable reason naming what is wrong (the
    variable, the prompt id, the directory, the ``--repeat`` value) and never
    contains a secret value. :func:`main` prints it to stderr and exits with
    code 1.
    """


@dataclass(frozen=True, slots=True)
class Prompt:
    """One probe prompt of the versioned prompt set.

    Attributes:
        id: unique, stable prompt id; the only prompt data that reaches the
            output.
        query: the search query sent as plain-text input; never written to
            any output.
    """

    id: str
    query: str


PROMPTS: tuple[Prompt, ...] = ()
"""The versioned prompt set (implementer: at least six prompts).

Chosen to make several text blocks or several searches likely: long answers,
multi-part questions that need several searches, German questions with
umlauts, and one answer likely to contain characters outside the BMP. Ids are
unique. Changing a prompt means a new id, so results stay comparable.
"""


@dataclass(frozen=True, slots=True)
class HypothesisCounts:
    """Counts of one hypothesis over the checked annotations of one block.

    Attributes:
        fits: number of checked annotations whose indices satisfy the
            hypothesis range (see the module docstring).
        start_on_boundary: number of checked annotations whose
            ``start_index`` is a UTF-8 character boundary (see
            :func:`is_char_boundary`) of the reference text: the whole
            answer for the global hypothesis, the block text for the
            per-block hypothesis.
        end_on_boundary: the same for ``end_index``.

    Boundary counts include annotations that do not fit the range; an index
    outside the reference text is not a boundary.
    """

    fits: int
    start_on_boundary: int
    end_on_boundary: int


@dataclass(frozen=True, slots=True)
class BlockRecord:
    """Measurements of one text block; contains numbers only.

    Attributes:
        step_index: 0-based index of the block's ``model_output`` step in
            ``Interaction.steps`` (all step types counted).
        block_index: 0-based index of the block among the ``TextContent``
            items of its step.
        offset: UTF-8 byte offset of the block in the concatenated answer.
        length: UTF-8 byte length of the block text.
        url_citations: number of ``url_citation`` annotations of the block,
            including those with a missing index.
        min_start: smallest ``start_index`` among the block's
            ``url_citation`` annotations that have one; ``None`` when none
            has one.
        max_end: largest ``end_index`` among the block's ``url_citation``
            annotations that have one; ``None`` when none has one.
        missing_index: number of ``url_citation`` annotations whose
            ``start_index`` or ``end_index`` is ``None`` (each annotation
            counted once).
        global_hypothesis: counts of the global hypothesis over the checked
            annotations; ``None`` exactly when ``offset == 0``.
        per_block_hypothesis: counts of the per-block hypothesis over the
            checked annotations; ``None`` exactly when ``offset == 0``.

    For a block with ``offset > 0`` the number of checked annotations is
    ``url_citations - missing_index``.
    """

    step_index: int
    block_index: int
    offset: int
    length: int
    url_citations: int
    min_start: int | None
    max_end: int | None
    missing_index: int
    global_hypothesis: HypothesisCounts | None
    per_block_hypothesis: HypothesisCounts | None


@dataclass(frozen=True, slots=True)
class InteractionRecord:
    """One line of ``probe.jsonl``: one probed interaction or one failed call.

    Attributes:
        prompt_id: id of the probed :class:`Prompt`.
        repeat: 1-based repetition number of the prompt.
        classification: :func:`classify` of ``blocks``; ``None`` exactly
            when ``error_kind`` is set.
        error_kind: ``ProviderError.kind`` of a failed call, else ``None``.
        answer_bytes: UTF-8 byte length of the concatenated answer (sum of
            all block lengths); 0 for a failed call.
        blocks: one :class:`BlockRecord` per block in answer order; empty for
            a failed call and for a response without ``model_output`` step or
            without text (EC1).
    """

    prompt_id: str
    repeat: int
    classification: Classification | None
    error_kind: ProviderErrorKind | None
    answer_bytes: int
    blocks: list[BlockRecord]

    def to_json_dict(self) -> dict[str, Any]:
        """Return the JSON object written as one ``probe.jsonl`` line.

        Keys are exactly the attribute names in declaration order, nested
        records as objects with their attribute names; ``None`` becomes JSON
        ``null``.
        """
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ProbeSummary:
    """Result of one probe run, printed to stdout by :func:`render_summary`.

    Attributes:
        results_path: path of the written ``probe.jsonl``.
        interactions: number of records written (successful and failed).
        counts: number of successful records per classification; always has
            every key of :data:`CLASSIFICATIONS`, missing ones with 0.
        errors: number of failed calls per error kind; only kinds that
            occurred.
    """

    results_path: Path
    interactions: int
    counts: dict[Classification, int]
    errors: dict[str, int]


class CapturingProvider(GeminiProvider):
    """:class:`GeminiProvider` that keeps the raw interaction of its last call.

    Behaves exactly like :class:`GeminiProvider` (same constructor, same
    request parameters, limits and error mapping); additionally every
    successful ``_send`` stores the returned interaction in
    :attr:`last_interaction` before the adapter maps it.

    Attributes:
        last_interaction: the raw interaction of the most recent successful
            call, ``None`` before the first one. A failed call leaves it
            unchanged; callers reset it before each call.
    """

    last_interaction: Any = None

    async def _send(
        self,
        request_input: str,
        tools: list[dict[str, Any]],
        system_instruction: str | None,
    ) -> interactions.Interaction:
        """Delegate to :meth:`GeminiProvider._send` and store its result.

        Postcondition: on success :attr:`last_interaction` is the returned
        interaction; on failure the ``ProviderError`` (or cancellation)
        propagates unchanged and :attr:`last_interaction` is not modified.
        """
        raise NotImplementedError


def check_live_guard(environ: Mapping[str, str]) -> None:
    """Allow a run only with ``LIVE=1`` and a non-empty ``GEMINI_API_KEY``.

    Raises:
        ProbeAbort: when ``environ["LIVE"]`` is not exactly ``"1"``, or when
            ``GEMINI_API_KEY`` is missing, empty or whitespace-only (EC6).
            The message names the variable, never a value.
    """
    raise NotImplementedError


def probe_settings(environ: Mapping[str, str]) -> Settings:
    """Build the adapter settings from the ADR 0010 variables in ``environ``.

    Uses the same variable names, defaults and rules as
    :func:`gemini_search_mcp.config.load_settings`, but reads ``environ``
    instead of the process environment, so tests can pass a mapping.
    Constructs no client and opens no connection.

    Raises:
        ProbeAbort: when a variable violates its rule; the message is the
            ``ConfigError`` text (variable and rule, never a value).
    """
    raise NotImplementedError


def select_prompts(prompts: Sequence[Prompt], prompt_ids: Sequence[str]) -> list[Prompt]:
    """Restrict ``prompts`` to ``prompt_ids`` (``--prompt-id``).

    Returns every prompt, in set order, when ``prompt_ids`` is empty;
    otherwise the prompts whose id is in ``prompt_ids``, in set order, each
    once even if given twice.

    Raises:
        ProbeAbort: when an id in ``prompt_ids`` is not in ``prompts``; the
            message names every unknown id.
    """
    raise NotImplementedError


def create_run_dir(runs_dir: Path, today: date) -> Path:
    """Create and return ``runs_dir / f"{today.isoformat()}-{RUN_DIR_SUFFIX}"``.

    Creates ``runs_dir`` when missing.

    Raises:
        ProbeAbort: when the directory already exists (never overwritten);
            the message names the directory.
    """
    raise NotImplementedError


def is_char_boundary(data: bytes, index: int) -> bool:
    """Return whether ``index`` is a UTF-8 character boundary of ``data``.

    True exactly when ``0 <= index <= len(data)`` and either
    ``index == len(data)`` or ``data[index]`` is not a UTF-8 continuation
    byte (``0x80`` to ``0xBF``). So 0 and ``len(data)`` are boundaries, a
    position inside a multi-byte character is not, and a negative or too
    large index is not. Never raises.
    """
    raise NotImplementedError


def block_records(interaction: interactions.Interaction) -> list[BlockRecord]:
    """Measure every block of ``interaction`` (see the module docstring).

    Walks ``interaction.steps`` (``None`` counts as empty) exactly like
    ``GeminiProvider._answer_text``: only ``ModelOutputStep`` steps, only
    their ``TextContent`` items (``content`` ``None`` counts as empty), in
    step and content order. For each block it fills one
    :class:`BlockRecord`; annotations other than ``URLCitation`` are ignored
    (EC3), ``annotations`` ``None`` counts as empty. For blocks with
    ``offset > 0`` it evaluates both hypotheses over the checked
    annotations, using the UTF-8 bytes of the concatenated answer for the
    global and those of the block text for the per-block boundary checks.

    Returns an empty list for a response without ``model_output`` step or
    without ``TextContent`` (EC1). Never raises for missing optional fields.
    """
    raise NotImplementedError


def classify(blocks: Sequence[BlockRecord]) -> Classification:
    """Classify one interaction from its block records.

    Let ``n`` be the number of checked annotations (sum of
    ``url_citations - missing_index`` over blocks with ``offset > 0``), ``g``
    the sum of ``global_hypothesis.fits`` and ``p`` the sum of
    ``per_block_hypothesis.fits`` over the same blocks. Then:

    - ``undecidable``: ``n == 0`` (no block, annotations only in the first
      block at offset 0 (EC4), or only annotations with a missing index
      (EC2)), or ``g == n`` and ``p == n`` (every checked annotation fits
      both hypotheses, e.g. inside the overlap of the ranges, EC5);
    - ``global``: ``g == n`` and ``p < n``;
    - ``per_block``: ``p == n`` and ``g < n``;
    - ``inconsistent``: every other case.

    Blocks with ``offset == 0`` never influence the result.
    """
    raise NotImplementedError


def interaction_record(
    prompt_id: str, repeat: int, interaction: interactions.Interaction
) -> InteractionRecord:
    """Build the record of one successful call.

    ``blocks`` is :func:`block_records` of ``interaction``,
    ``classification`` :func:`classify` of those blocks, ``answer_bytes`` the
    sum of the block lengths, ``error_kind`` ``None``.
    """
    raise NotImplementedError


async def probe_prompt(
    provider: CapturingProvider, prompt: Prompt, repeat: int
) -> InteractionRecord:
    """Send ``prompt.query`` once via ``provider.search`` and record the result.

    Resets ``provider.last_interaction`` to ``None``, awaits
    ``provider.search(prompt.query)`` and returns
    :func:`interaction_record` of the captured interaction. A
    ``ProviderError`` is not raised but returned as a record with
    ``error_kind`` set to its ``kind``, ``classification`` ``None``,
    ``answer_bytes`` 0 and no blocks. Other exceptions propagate.
    """
    raise NotImplementedError


async def run_probe(
    *,
    environ: Mapping[str, str],
    prompt_ids: Sequence[str] = (),
    repeat: int = 1,
    prompts: Sequence[Prompt] = PROMPTS,
    runs_dir: Path = RUNS_DIR,
    today: date | None = None,
    interactions_client: InteractionsClient | None = None,
    sleep: Sleep | None = None,
    now: Clock | None = None,
) -> ProbeSummary:
    """Run the probe and write ``probe.jsonl``.

    Steps, each aborting with :class:`ProbeAbort` before the next one and
    before any network call:

    1. :func:`check_live_guard` on ``environ`` (AC4, EC6);
    2. ``repeat`` must lie in ``MIN_REPEAT..MAX_REPEAT``, otherwise
       :class:`ProbeAbort` naming ``--repeat``;
    3. :func:`select_prompts` of ``prompts`` with ``prompt_ids``;
    4. :func:`probe_settings` of ``environ``;
    5. :func:`create_run_dir` in ``runs_dir`` with ``today`` (``None`` means
       ``date.today()``);
    6. builds ``CapturingProvider(settings, interactions_client=...,
       sleep=..., now=...)``; ``interactions_client`` ``None`` means the
       adapter's production client, built lazily on the first call. Tests
       inject a fake.
    7. for each selected prompt in set order, repetitions ``1..repeat``
       consecutively: :func:`probe_prompt`, appending the record's
       :meth:`InteractionRecord.to_json_dict` as one JSON line (UTF-8,
       ``\\n``-terminated) to ``run_dir / RESULTS_FILE`` as soon as it is
       finished. A failed call is recorded and the run continues (AC5).

    Returns:
        The :class:`ProbeSummary` of all written records.
    """
    raise NotImplementedError


def render_summary(summary: ProbeSummary) -> str:
    """Return the stdout summary of a run.

    One line per classification in :data:`CLASSIFICATIONS` order as
    ``<classification>: <count>``, then one line per occurred error kind as
    ``error <kind>: <count>`` in ascending kind order, then
    ``total: <interactions>``. Contains numbers, classifications and error
    kinds only; ends with a new line.
    """
    raise NotImplementedError


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Command line entry point.

    Usage::

        probe_citation_offsets.py [--prompt-id <id>]... [--repeat <n>]

    ``--prompt-id`` is repeatable; ``--repeat`` is an integer, default 1.
    Awaits :func:`run_probe` with ``environ`` (``None`` means
    ``os.environ``), prints :func:`render_summary` and then
    ``results: <results_path>`` to stdout. A :class:`ProbeAbort` is printed
    to stderr as ``error: <reason>``.

    Returns:
        0 on success (also when calls failed), 1 on :class:`ProbeAbort`.
        Non-integer arguments exit with code 2 via argparse.
    """
    raise NotImplementedError


if __name__ == "__main__":
    raise SystemExit(main())
