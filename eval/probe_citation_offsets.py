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

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from google.genai import interactions
from pydantic import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from gemini_search_mcp.config import ConfigError, Settings, _config_error_from_validation
from gemini_search_mcp.gemini_client import Clock, GeminiProvider, InteractionsClient, Sleep
from gemini_search_mcp.provider import ProviderError, ProviderErrorKind

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


PROMPTS: tuple[Prompt, ...] = (
    Prompt(
        "long-history-001",
        "Write a detailed, well-structured overview of the history of the Internet from "
        "ARPANET to today. Cover at least six distinct phases, each with its key "
        "technologies, organizations and dates.",
    ),
    Prompt(
        "long-comparison-001",
        "Compare the Rust, Go and Zig programming languages in depth: memory management, "
        "concurrency model, tooling, ecosystem maturity and typical use cases. Give each "
        "language its own section with current facts.",
    ),
    Prompt(
        "multi-part-001",
        "Answer all parts separately, each with its own research: (1) Which version of "
        "Python is the latest stable release and when was it published? (2) What is the "
        "current population of Iceland? (3) Who won the most recent FIFA World Cup and "
        "where was the final played? (4) What is the latest stable Linux kernel version?",
    ),
    Prompt(
        "multi-part-002",
        "I need four current facts, each checked separately: the latest stable version of "
        "PostgreSQL, the latest LTS version of Node.js, the latest stable Kubernetes "
        "release, and the current stable release of Rust.",
    ),
    Prompt(
        "german-umlauts-001",
        "Erkläre ausführlich, wie die Energiewende in Deutschland funktioniert: "
        "Fördermaßnahmen, Netzausbau, Speichertechnologien und aktuelle Ausbauziele für "
        "Wind- und Solarenergie. Nenne Zahlen und Quellen.",
    ),
    Prompt(
        "german-umlauts-002",
        "Welche Sehenswürdigkeiten in Köln, Düsseldorf und Münster sind besonders "
        "empfehlenswert, und wie komme ich mit der Bahn von Köln nach Münster? Beantworte "
        "jeden Teil der Frage einzeln mit aktuellen Angaben.",
    ),
    Prompt(
        "non-bmp-001",
        "Which emoji were added in the most recent Unicode release? List several of them "
        "with their official Unicode names and code points, and explain which characters "
        "the Unicode planes beyond the Basic Multilingual Plane contain, such as the "
        "melting face emoji 🫠.",
    ),
)
"""The versioned prompt set (at least six prompts).

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
        interaction = await super()._send(request_input, tools, system_instruction)
        self.last_interaction = interaction
        return interaction


def check_live_guard(environ: Mapping[str, str]) -> None:
    """Allow a run only with ``LIVE=1`` and a non-empty ``GEMINI_API_KEY``.

    Raises:
        ProbeAbort: when ``environ["LIVE"]`` is not exactly ``"1"``, or when
            ``GEMINI_API_KEY`` is missing, empty or whitespace-only (EC6).
            The message names the variable, never a value.
    """
    if environ.get("LIVE") != "1":
        raise ProbeAbort(
            "LIVE=1 is required: a run makes paid Gemini calls (ADR 0006); no call was made"
        )
    if not environ.get("GEMINI_API_KEY", "").strip():
        raise ProbeAbort(
            "GEMINI_API_KEY is empty or not set: a live run needs a Gemini API key; "
            "no call was made"
        )


class _MappingSettings(Settings):
    """:class:`Settings` that reads only the keyword arguments it is given.

    The process environment is not consulted, so a mapping passed to
    :func:`probe_settings` is the single source; every validator and default of
    :class:`Settings` still applies.
    """

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


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
    values = {
        name: environ[name.upper()] for name in Settings.model_fields if name.upper() in environ
    }
    try:
        return _MappingSettings(**values)
    except ValidationError as error:
        raise ProbeAbort(str(_config_error_from_validation(error))) from None
    except ConfigError as error:
        raise ProbeAbort(str(error)) from None


def select_prompts(prompts: Sequence[Prompt], prompt_ids: Sequence[str]) -> list[Prompt]:
    """Restrict ``prompts`` to ``prompt_ids`` (``--prompt-id``).

    Returns every prompt, in set order, when ``prompt_ids`` is empty;
    otherwise the prompts whose id is in ``prompt_ids``, in set order, each
    once even if given twice.

    Raises:
        ProbeAbort: when an id in ``prompt_ids`` is not in ``prompts``; the
            message names every unknown id.
    """
    if not prompt_ids:
        return list(prompts)
    known = {prompt.id for prompt in prompts}
    unknown = sorted({prompt_id for prompt_id in prompt_ids if prompt_id not in known})
    if unknown:
        raise ProbeAbort(f"unknown --prompt-id: {', '.join(unknown)}")
    wanted = set(prompt_ids)
    return [prompt for prompt in prompts if prompt.id in wanted]


def create_run_dir(runs_dir: Path, today: date) -> Path:
    """Create and return ``runs_dir / f"{today.isoformat()}-{RUN_DIR_SUFFIX}"``.

    Creates ``runs_dir`` when missing.

    Raises:
        ProbeAbort: when the directory already exists (never overwritten);
            the message names the directory.
    """
    run_dir = runs_dir / f"{today.isoformat()}-{RUN_DIR_SUFFIX}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    try:
        run_dir.mkdir()
    except FileExistsError:
        raise ProbeAbort(f"run directory already exists: {run_dir}") from None
    return run_dir


def is_char_boundary(data: bytes, index: int) -> bool:
    """Return whether ``index`` is a UTF-8 character boundary of ``data``.

    True exactly when ``0 <= index <= len(data)`` and either
    ``index == len(data)`` or ``data[index]`` is not a UTF-8 continuation
    byte (``0x80`` to ``0xBF``). So 0 and ``len(data)`` are boundaries, a
    position inside a multi-byte character is not, and a negative or too
    large index is not. Never raises.
    """
    if not 0 <= index <= len(data):
        return False
    return index == len(data) or not 0x80 <= data[index] <= 0xBF


def _hypothesis_counts(
    checked: Sequence[tuple[int, int]], low: int, high: int, reference: bytes
) -> HypothesisCounts:
    """Count fits and boundary hits of ``(start, end)`` pairs for one hypothesis.

    A pair fits when ``low <= start < end <= high``; boundaries are checked in
    ``reference``, the UTF-8 bytes the hypothesis refers to.
    """
    return HypothesisCounts(
        fits=sum(1 for start, end in checked if low <= start < end <= high),
        start_on_boundary=sum(1 for start, _ in checked if is_char_boundary(reference, start)),
        end_on_boundary=sum(1 for _, end in checked if is_char_boundary(reference, end)),
    )


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
    texts: list[tuple[int, int, interactions.TextContent]] = []
    for step_index, step in enumerate(interaction.steps or []):
        if not isinstance(step, interactions.ModelOutputStep):
            continue
        block_index = 0
        for content in step.content or []:
            if isinstance(content, interactions.TextContent):
                texts.append((step_index, block_index, content))
                block_index += 1

    block_bytes = [content.text.encode("utf-8") for _, _, content in texts]
    answer = b"".join(block_bytes)
    records: list[BlockRecord] = []
    offset = 0
    for (step_index, block_index, content), data in zip(texts, block_bytes, strict=True):
        citations = [
            annotation
            for annotation in content.annotations or []
            if isinstance(annotation, interactions.URLCitation)
        ]
        starts = [c.start_index for c in citations if c.start_index is not None]
        ends = [c.end_index for c in citations if c.end_index is not None]
        checked = [
            (c.start_index, c.end_index)
            for c in citations
            if c.start_index is not None and c.end_index is not None
        ]
        length = len(data)
        records.append(
            BlockRecord(
                step_index=step_index,
                block_index=block_index,
                offset=offset,
                length=length,
                url_citations=len(citations),
                min_start=min(starts) if starts else None,
                max_end=max(ends) if ends else None,
                missing_index=len(citations) - len(checked),
                global_hypothesis=(
                    _hypothesis_counts(checked, offset, offset + length, answer)
                    if offset > 0
                    else None
                ),
                per_block_hypothesis=(
                    _hypothesis_counts(checked, 0, length, data) if offset > 0 else None
                ),
            )
        )
        offset += length
    return records


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
    later = [block for block in blocks if block.offset > 0]
    checked = sum(block.url_citations - block.missing_index for block in later)
    global_fits = sum(
        block.global_hypothesis.fits for block in later if block.global_hypothesis is not None
    )
    per_block_fits = sum(
        block.per_block_hypothesis.fits for block in later if block.per_block_hypothesis is not None
    )
    if checked == 0:
        return "undecidable"
    if global_fits == checked and per_block_fits == checked:
        return "undecidable"
    if global_fits == checked:
        return "global"
    if per_block_fits == checked:
        return "per_block"
    return "inconsistent"


def interaction_record(
    prompt_id: str, repeat: int, interaction: interactions.Interaction
) -> InteractionRecord:
    """Build the record of one successful call.

    ``blocks`` is :func:`block_records` of ``interaction``,
    ``classification`` :func:`classify` of those blocks, ``answer_bytes`` the
    sum of the block lengths, ``error_kind`` ``None``.
    """
    blocks = block_records(interaction)
    return InteractionRecord(
        prompt_id=prompt_id,
        repeat=repeat,
        classification=classify(blocks),
        error_kind=None,
        answer_bytes=sum(block.length for block in blocks),
        blocks=blocks,
    )


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
    provider.last_interaction = None
    try:
        await provider.search(prompt.query)
    except ProviderError as error:
        return InteractionRecord(
            prompt_id=prompt.id,
            repeat=repeat,
            classification=None,
            error_kind=error.kind,
            answer_bytes=0,
            blocks=[],
        )
    return interaction_record(prompt.id, repeat, provider.last_interaction)


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
    check_live_guard(environ)
    if not MIN_REPEAT <= repeat <= MAX_REPEAT:
        raise ProbeAbort(f"--repeat must be between {MIN_REPEAT} and {MAX_REPEAT}")
    selected = select_prompts(prompts, prompt_ids)
    settings = probe_settings(environ)
    run_dir = create_run_dir(runs_dir, today or date.today())
    results_path = run_dir / RESULTS_FILE
    provider = CapturingProvider(
        settings, interactions_client=interactions_client, sleep=sleep, now=now
    )

    interactions_count = 0
    counts: dict[Classification, int] = dict.fromkeys(CLASSIFICATIONS, 0)
    errors: dict[str, int] = {}
    with results_path.open("w", encoding="utf-8") as results:
        for prompt in selected:
            for repeat_number in range(1, repeat + 1):
                record = await probe_prompt(provider, prompt, repeat_number)
                results.write(json.dumps(record.to_json_dict()) + "\n")
                results.flush()
                interactions_count += 1
                if record.classification is not None:
                    counts[record.classification] += 1
                if record.error_kind is not None:
                    errors[record.error_kind] = errors.get(record.error_kind, 0) + 1
    return ProbeSummary(
        results_path=results_path, interactions=interactions_count, counts=counts, errors=errors
    )


def render_summary(summary: ProbeSummary) -> str:
    """Return the stdout summary of a run.

    One line per classification in :data:`CLASSIFICATIONS` order as
    ``<classification>: <count>``, then one line per occurred error kind as
    ``error <kind>: <count>`` in ascending kind order, then
    ``total: <interactions>``. Contains numbers, classifications and error
    kinds only; ends with a new line.
    """
    lines = [
        f"{classification}: {summary.counts[classification]}" for classification in CLASSIFICATIONS
    ]
    lines.extend(f"error {kind}: {summary.errors[kind]}" for kind in sorted(summary.errors))
    lines.append(f"total: {summary.interactions}")
    return "\n".join(lines) + "\n"


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
    parser = argparse.ArgumentParser(
        prog="probe_citation_offsets.py",
        description="Measure the offset base of url_citation indices (live, paid calls).",
    )
    parser.add_argument(
        "--prompt-id",
        action="append",
        default=[],
        dest="prompt_ids",
        metavar="ID",
        help="restrict the run to this prompt id (repeatable)",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=MIN_REPEAT,
        metavar="N",
        help=f"repeat every prompt N times ({MIN_REPEAT} to {MAX_REPEAT}, default {MIN_REPEAT})",
    )
    args = parser.parse_args(argv)
    try:
        summary = asyncio.run(
            run_probe(
                environ=os.environ if environ is None else environ,
                prompt_ids=args.prompt_ids,
                repeat=args.repeat,
            )
        )
    except ProbeAbort as abort:
        print(f"error: {abort}", file=sys.stderr)
        return 1
    print(render_summary(summary), end="")
    print(f"results: {summary.results_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
