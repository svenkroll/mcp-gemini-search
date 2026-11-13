"""Acceptance tests for the citation offset probe (issue #29).

The script ``eval/probe_citation_offsets.py`` is not part of a package, so it
is loaded from its file path. Everything runs offline: a fake interactions
client returns hand-written interactions, and fake sleep/clock boundaries
replace all real waiting. Keys and sentinel strings in fixtures are obviously
fake.

Acceptance criteria (AC) and known edge cases (EC) are numbered in the order of
the issue. AC6 (README) is a review criterion and AC7 (live run) is manual;
neither has a test.
"""

import asyncio
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx2 as httpx
import pytest
from google.genai import interactions
from google.genai._gaos.lib.compat_errors import APIStatusError

from gemini_search_mcp.config import Settings
from gemini_search_mcp.gemini_client import GeminiProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO_ROOT / "eval" / "probe_citation_offsets.py"
TODAY = date(2026, 11, 13)

# Obviously fake values; they never leave this test process.
FAKE_KEY = "fake-gemini-key-AIzaSyFAKE0123456789"
FAKE_MODEL = "fake-model-for-probe"
LIVE_ENVIRON = {"LIVE": "1", "GEMINI_API_KEY": FAKE_KEY, "GEMINI_MODEL": FAKE_MODEL}

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


def _load_probe() -> Any:
    spec = importlib.util.spec_from_file_location("probe_citation_offsets", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["probe_citation_offsets"] = module
    spec.loader.exec_module(module)
    return module


probe = _load_probe()


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*CONFIG_VARIABLES, "LIVE"):
        monkeypatch.delenv(name, raising=False)


# --- helpers ----------------------------------------------------------------


class _Sleeper:
    async def __call__(self, delay: float) -> None:
        return None


class _FakeInteractions:
    """Scripted ``InteractionsClient`` double that records every call."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        model: str,
        input: str,
        tools: list[dict[str, Any]],
        system_instruction: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        self.calls.append(
            {
                "model": model,
                "input": input,
                "tools": tools,
                "system_instruction": system_instruction,
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _api_error(status: int) -> APIStatusError:
    request = httpx.Request("POST", "https://gemini.invalid/v1/interactions")
    response = httpx.Response(status, request=request)
    body = {"error": {"code": "fixture", "message": "hand-written fixture error"}}
    error = APIStatusError.generate(status, body, None, response)
    assert isinstance(error, APIStatusError)
    return error


def _url_citation(start: int | None, end: int | None, **extra: Any) -> dict[str, Any]:
    annotation: dict[str, Any] = {
        "type": "url_citation",
        "url": "https://example.com/page",
        "title": "Page",
    }
    if start is not None:
        annotation["start_index"] = start
    if end is not None:
        annotation["end_index"] = end
    annotation.update(extra)
    return annotation


def _text(text: str, *annotations: dict[str, Any]) -> dict[str, Any]:
    return {"type": "text", "text": text, "annotations": list(annotations)}


def _search_call() -> dict[str, Any]:
    return {"type": "google_search_call", "id": "call_1", "arguments": {"queries": ["q"]}}


def _model_output(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"type": "model_output", "content": list(blocks)}


def _interaction(*steps: dict[str, Any]) -> interactions.Interaction:
    payload = {
        "id": "int_probe",
        "status": "completed",
        "model": FAKE_MODEL,
        "steps": list(steps),
    }
    return interactions.Interaction.model_validate(payload)


def _two_blocks(first_len: int, second_len: int, *annotations: dict[str, Any]) -> Any:
    """Two ASCII blocks of the given byte lengths; annotations sit on the second block."""
    return _interaction(
        _search_call(),
        _model_output(_text("a" * first_len), _text("b" * second_len, *annotations)),
    )


def _classification(interaction: interactions.Interaction) -> str:
    return probe.interaction_record("p", 1, interaction).classification


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _run_probe(
    tmp_path: Path,
    outcomes: list[Any],
    *,
    environ: dict[str, str] | None = None,
    prompts: list[Any] | None = None,
    **kwargs: Any,
) -> tuple[Any, _FakeInteractions, Path]:
    fake = _FakeInteractions(outcomes)
    runs_dir = tmp_path / "runs"
    summary = _run(
        probe.run_probe(
            environ=environ if environ is not None else {**LIVE_ENVIRON, "GEMINI_MAX_RETRIES": "0"},
            prompts=prompts if prompts is not None else [probe.Prompt("p1", "Query one?")],
            runs_dir=runs_dir,
            today=TODAY,
            interactions_client=fake,
            sleep=_Sleeper(),
            now=lambda: 0.0,
            **kwargs,
        )
    )
    return summary, fake, runs_dir


def _result_lines(runs_dir: Path) -> list[dict[str, Any]]:
    path = runs_dir / f"{TODAY.isoformat()}-offset-probe" / "probe.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --- AC1: classification ----------------------------------------------------


@pytest.mark.parametrize(
    ("interaction", "expected"),
    [
        # offset 20, length 30: 25..35 fits global only (35 > length 30).
        (_two_blocks(20, 30, _url_citation(25, 35)), "global"),
        # offset 20: 2..8 fits per block only (start < offset).
        (_two_blocks(20, 30, _url_citation(2, 8)), "per_block"),
        # offset 5, length 30: 10..20 lies in the overlap and fits both.
        (_two_blocks(5, 30, _url_citation(10, 20)), "undecidable"),
        # one annotation fits global only, the other per block only.
        (_two_blocks(20, 30, _url_citation(25, 35), _url_citation(2, 8)), "inconsistent"),
        # an annotation fitting neither hypothesis is not consistent with either.
        (_two_blocks(20, 30, _url_citation(100, 120)), "inconsistent"),
    ],
    ids=["global", "per_block", "undecidable", "inconsistent_mixed", "inconsistent_neither"],
)
def test_ac1_fixtures_with_several_blocks_are_classified(
    interaction: interactions.Interaction, expected: str
) -> None:
    """AC1: several blocks, one fixture per classification."""
    assert _classification(interaction) == expected


def test_ac1_block_records_measure_offsets_lengths_and_boundaries() -> None:
    """AC1: block records carry steps, offsets, lengths, counts and UTF-8 boundary counts."""
    # Block 0: five times "Ä" (2 bytes each) = 10 bytes. Block 1: "abcö" = 5 bytes.
    interaction = _interaction(
        _search_call(),
        _model_output(_text("ÄÄÄÄÄ")),
        _search_call(),
        _model_output(
            _text("abcö", _url_citation(11, 13), _url_citation(4, 5)),
        ),
    )

    record = probe.interaction_record("prompt-x", 2, interaction)

    assert record.prompt_id == "prompt-x"
    assert record.repeat == 2
    assert record.error_kind is None
    assert record.answer_bytes == 15
    assert record.classification == "inconsistent"
    first, second = record.blocks
    assert (first.step_index, first.block_index, first.offset, first.length) == (1, 0, 0, 10)
    assert first.global_hypothesis is None
    assert first.per_block_hypothesis is None
    assert (second.step_index, second.block_index, second.offset, second.length) == (3, 0, 10, 5)
    assert second.url_citations == 2
    assert second.min_start == 4
    assert second.max_end == 13
    assert second.missing_index == 0
    # Global: only 11..13 fits; both starts and the end 13 lie on a boundary of the
    # answer, the end 5 lies inside the second "Ä".
    assert second.global_hypothesis.fits == 1
    assert second.global_hypothesis.start_on_boundary == 2
    assert second.global_hypothesis.end_on_boundary == 1
    # Per block: only 4..5 fits; start 4 lies inside "ö", end 5 is the block end.
    assert second.per_block_hypothesis.fits == 1
    assert second.per_block_hypothesis.start_on_boundary == 0
    assert second.per_block_hypothesis.end_on_boundary == 1


def test_ac1_record_serializes_to_json_without_loss() -> None:
    """AC1: the record converts to a JSON-serializable object with null for absent values."""
    interaction = _two_blocks(20, 30, _url_citation(25, 35))

    data = probe.interaction_record("p", 1, interaction).to_json_dict()

    restored = json.loads(json.dumps(data))
    assert restored["prompt_id"] == "p"
    assert restored["classification"] == "global"
    assert restored["error_kind"] is None
    assert restored["blocks"][0]["global_hypothesis"] is None


# --- AC2: request parameters ------------------------------------------------


def test_ac2_request_parameters_equal_those_of_gemini_provider_search(tmp_path: Path) -> None:
    """AC2: the probe sends the request GeminiProvider.search sends for the same query."""
    query = "A distinctive probe query?"
    reference_fake = _FakeInteractions([_two_blocks(1, 1)])
    reference = GeminiProvider(
        Settings(gemini_api_key=FAKE_KEY, gemini_model=FAKE_MODEL, gemini_max_retries=0),
        reference_fake,
        sleep=_Sleeper(),
        now=lambda: 0.0,
    )
    _run(reference.search(query))

    _, probe_fake, _ = _run_probe(
        tmp_path, [_two_blocks(1, 1)], prompts=[probe.Prompt("p1", query)]
    )

    assert len(probe_fake.calls) == 1
    assert probe_fake.calls == reference_fake.calls
    assert probe_fake.calls[0]["model"] == FAKE_MODEL
    assert probe_fake.calls[0]["input"] == query
    assert probe_fake.calls[0]["tools"] == [{"type": "google_search"}]
    assert probe_fake.calls[0]["system_instruction"] is None


# --- AC3: no content in output ----------------------------------------------

SENTINEL_QUERY = "SENTINEL-QUERY-7f3a"
SENTINEL_ANSWER = "SENTINEL-ANSWER-91bc"
SENTINEL_URL = "https://sentinel-url-5d2e.example/secret-path"
SENTINEL_TITLE = "SENTINEL-TITLE-c04d"
SENTINEL_SEARCH_QUERY = "SENTINEL-SEARCHQUERY-2e8f"


def test_ac3_output_and_result_file_contain_no_content_from_the_fixture(tmp_path: Path) -> None:
    """AC3: sentinel answer, URL, title, search query and prompt text never reach any output."""
    interaction = _interaction(
        {
            "type": "google_search_call",
            "id": "call_1",
            "arguments": {"queries": [SENTINEL_SEARCH_QUERY]},
        },
        _model_output(
            _text(f"{SENTINEL_ANSWER} first block. "),
            _text(
                f"{SENTINEL_ANSWER} second block.",
                _url_citation(40, 50, url=SENTINEL_URL, title=SENTINEL_TITLE),
            ),
        ),
    )
    prompts = [probe.Prompt("p1", SENTINEL_QUERY), probe.Prompt("p2", SENTINEL_QUERY)]

    summary, _, runs_dir = _run_probe(tmp_path, [interaction, _api_error(400)], prompts=prompts)

    result_path = runs_dir / f"{TODAY.isoformat()}-offset-probe" / "probe.jsonl"
    result_text = result_path.read_text(encoding="utf-8")
    summary_text = probe.render_summary(summary)
    assert result_text.strip() != ""
    assert summary_text.strip() != ""
    assert "p1" in result_text
    for sentinel in (
        SENTINEL_QUERY,
        SENTINEL_ANSWER,
        SENTINEL_URL,
        SENTINEL_TITLE,
        SENTINEL_SEARCH_QUERY,
        "sentinel-url-5d2e",
    ):
        assert sentinel not in result_text
        assert sentinel not in summary_text


# --- AC4 / EC6: live guard --------------------------------------------------


@pytest.mark.parametrize(
    "environ",
    [
        {"GEMINI_API_KEY": FAKE_KEY},
        {"LIVE": "0", "GEMINI_API_KEY": FAKE_KEY},
        {"LIVE": "", "GEMINI_API_KEY": FAKE_KEY},
        {"LIVE": "1"},
    ],
    ids=["live_missing", "live_zero", "live_empty", "key_missing"],
)
def test_ac4_run_aborts_before_any_network_call(tmp_path: Path, environ: dict[str, str]) -> None:
    """AC4: without LIVE=1 or without a key nothing is sent and no run directory appears."""
    fake = _FakeInteractions([_two_blocks(1, 1)])
    runs_dir = tmp_path / "runs"

    with pytest.raises(probe.ProbeAbort):
        _run(
            probe.run_probe(
                environ=environ,
                prompts=[probe.Prompt("p1", "Query?")],
                runs_dir=runs_dir,
                today=TODAY,
                interactions_client=fake,
                sleep=_Sleeper(),
                now=lambda: 0.0,
            )
        )

    assert fake.calls == []
    assert not runs_dir.exists()


def test_ac4_main_exits_with_code_1_without_live(capsys: pytest.CaptureFixture[str]) -> None:
    """AC4: the command line entry point reports the abort and returns exit code 1."""
    code = probe.main([], {"GEMINI_API_KEY": FAKE_KEY})

    captured = capsys.readouterr()
    assert code == 1
    assert "LIVE" in captured.err
    assert FAKE_KEY not in captured.err
    assert FAKE_KEY not in captured.out


@pytest.mark.parametrize("key", ["", "   "], ids=["empty", "whitespace"])
def test_ec6_live_with_empty_key_aborts_before_any_network_call(
    tmp_path: Path, key: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """EC6: LIVE=1 with an empty key aborts before any network call."""
    environ = {"LIVE": "1", "GEMINI_API_KEY": key}
    fake = _FakeInteractions([_two_blocks(1, 1)])
    runs_dir = tmp_path / "runs"

    with pytest.raises(probe.ProbeAbort):
        _run(
            probe.run_probe(
                environ=environ,
                prompts=[probe.Prompt("p1", "Query?")],
                runs_dir=runs_dir,
                today=TODAY,
                interactions_client=fake,
                sleep=_Sleeper(),
                now=lambda: 0.0,
            )
        )

    assert fake.calls == []
    assert not runs_dir.exists()
    assert probe.main([], environ) == 1
    assert "GEMINI_API_KEY" in capsys.readouterr().err


# --- AC5: API error is recorded, run continues ------------------------------


def test_ac5_api_error_on_one_prompt_is_recorded_and_the_run_continues(tmp_path: Path) -> None:
    """AC5: a rejected call becomes a record with its error kind; the next prompt still runs."""
    good = _two_blocks(20, 30, _url_citation(25, 35))
    prompts = [
        probe.Prompt("p1", "First?"),
        probe.Prompt("p2", "Second?"),
        probe.Prompt("p3", "Third?"),
    ]

    summary, fake, runs_dir = _run_probe(tmp_path, [good, _api_error(400), good], prompts=prompts)

    assert len(fake.calls) == 3
    lines = _result_lines(runs_dir)
    assert [line["prompt_id"] for line in lines] == ["p1", "p2", "p3"]
    assert lines[1]["error_kind"] == "rejected"
    assert lines[1]["classification"] is None
    assert lines[1]["blocks"] == []
    assert lines[0]["error_kind"] is None
    assert lines[2]["classification"] == "global"
    assert summary.interactions == 3
    assert summary.errors == {"rejected": 1}
    assert summary.counts["global"] == 2
    rendered = probe.render_summary(summary)
    assert "rejected" in rendered
    assert "total: 3" in rendered


# --- EC1 to EC5 ---------------------------------------------------------------


@pytest.mark.parametrize(
    "steps",
    [
        [],
        [_search_call()],
        [_model_output()],
        [_model_output({"type": "thought", "signature": "sig"})],
    ],
    ids=["no_steps", "no_model_output", "empty_model_output", "no_text_content"],
)
def test_ec1_response_without_model_output_or_text_has_no_blocks(
    steps: list[dict[str, Any]],
) -> None:
    """EC1: no model_output step or no text is recorded with 0 blocks and undecidable."""
    record = probe.interaction_record("p", 1, _interaction(*steps))

    assert record.blocks == []
    assert record.answer_bytes == 0
    assert record.classification == "undecidable"


def test_ec2_annotations_with_missing_index_are_counted_and_excluded() -> None:
    """EC2: a missing start or end is counted as missing and does not influence the class."""
    interaction = _two_blocks(
        20,
        30,
        _url_citation(25, 35),
        _url_citation(None, 5),
        _url_citation(5, None),
        _url_citation(None, None),
    )

    record = probe.interaction_record("p", 1, interaction)

    block = record.blocks[1]
    assert block.url_citations == 4
    assert block.missing_index == 3
    assert block.global_hypothesis.fits == 1
    assert block.per_block_hypothesis.fits == 0
    assert record.classification == "global"


def test_ec2_only_annotations_with_missing_index_are_undecidable() -> None:
    """EC2: when every annotation lacks an index there is nothing to classify."""
    interaction = _two_blocks(20, 30, _url_citation(None, 5), _url_citation(5, None))

    record = probe.interaction_record("p", 1, interaction)

    assert record.blocks[1].missing_index == 2
    assert record.classification == "undecidable"


def test_ec3_annotations_other_than_url_citation_are_ignored() -> None:
    """EC3: a place citation neither counts nor classifies."""
    place = {
        "type": "place_citation",
        "name": "Somewhere",
        "place_id": "place-1",
        "start_index": 2,
        "end_index": 8,
    }
    interaction = _two_blocks(20, 30, _url_citation(25, 35), place)

    record = probe.interaction_record("p", 1, interaction)

    block = record.blocks[1]
    assert block.url_citations == 1
    assert block.min_start == 25
    assert block.max_end == 35
    assert block.per_block_hypothesis.fits == 0
    assert record.classification == "global"


def test_ec4_annotations_only_in_the_first_block_are_undecidable() -> None:
    """EC4: annotations at offset 0 never decide, whatever their indices."""
    interaction = _interaction(
        _search_call(),
        _model_output(_text("a" * 30, _url_citation(2, 8)), _text("b" * 30)),
    )

    record = probe.interaction_record("p", 1, interaction)

    assert record.blocks[0].url_citations == 1
    assert record.blocks[0].global_hypothesis is None
    assert record.blocks[0].per_block_hypothesis is None
    assert record.classification == "undecidable"


def test_ec5_annotation_in_the_overlap_fits_both_and_does_not_decide() -> None:
    """EC5: an annotation in the overlap is undecidable; another one outside it decides."""
    in_overlap = _url_citation(12, 20)  # offset 10, length 30: fits both ranges
    only_global = _url_citation(35, 40)  # end 40 > length 30

    alone = probe.interaction_record("p", 1, _two_blocks(10, 30, in_overlap))
    together = probe.interaction_record("p", 1, _two_blocks(10, 30, in_overlap, only_global))

    assert alone.blocks[1].global_hypothesis.fits == 1
    assert alone.blocks[1].per_block_hypothesis.fits == 1
    assert alone.classification == "undecidable"
    assert together.classification == "global"
