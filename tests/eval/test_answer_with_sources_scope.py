"""``answer_with_sources`` exists only in the evaluation (issue #36, AC5).

The outcome is a label of the evaluation catalog and of ADR 0005. It must
never reach the server: not the code under ``src/``, and therefore no tool
schema and no tool description.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"
NEEDLE = "answer_with_sources"


def _files_containing(root: Path, needle: str) -> list[Path]:
    """Return every file under ``root`` whose bytes contain ``needle``."""
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and needle.encode("utf-8") in path.read_bytes()
    )


def test_ac5_src_does_not_contain_answer_with_sources() -> None:
    assert SRC_DIR.is_dir()
    assert any(SRC_DIR.rglob("*.py"))

    assert _files_containing(SRC_DIR, NEEDLE) == []


def test_ac5_check_fails_when_answer_with_sources_appears_under_src(tmp_path: Path) -> None:
    package = tmp_path / "src" / "gemini_search_mcp" / "tools"
    package.mkdir(parents=True)
    (package / "clean.py").write_text('OUTCOME = "answer"\n', encoding="utf-8")
    offending = package / "search.py"
    offending.write_text('DESCRIPTION = "Use answer_with_sources."\n', encoding="utf-8")

    assert _files_containing(tmp_path / "src", NEEDLE) == [offending]
