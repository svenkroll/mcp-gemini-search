"""Unit tests for the repository quality tooling configuration."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PINNED_SHA = re.compile(r"^\s*uses:\s*[\w.-]+/[\w.-]+@([0-9a-f]{40})(\s|$)")


def _workflow_files() -> list[Path]:
    return sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))


def test_at_least_one_workflow_exists() -> None:
    assert _workflow_files(), "expected at least one GitHub Actions workflow"


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_workflow_uses_sha_pinned_actions(workflow: Path) -> None:
    for line in workflow.read_text(encoding="utf-8").splitlines():
        if "uses:" in line:
            assert PINNED_SHA.match(line), f"action not pinned to commit SHA: {line.strip()}"


def test_env_example_uses_placeholders_only() -> None:
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assignments = [
        line for line in lines if line and not line.lstrip().startswith("#") and "=" in line
    ]
    assert assignments, "expected documented variables in .env.example"
    for line in assignments:
        _, _, value = line.partition("=")
        assert value.strip() == "", f"unexpected non-empty value in .env.example: {line}"


@pytest.mark.parametrize(
    "required_path",
    [
        "uv.lock",
        "Makefile",
        ".pre-commit-config.yaml",
        "README.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "docs/techdebt.md",
        ".gitignore",
    ],
)
def test_required_scaffold_files_exist(required_path: str) -> None:
    assert (REPO_ROOT / required_path).is_file()


def test_no_claude_md_exists() -> None:
    assert not (REPO_ROOT / "CLAUDE.md").exists()
