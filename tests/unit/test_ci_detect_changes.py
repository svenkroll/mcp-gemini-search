"""Unit tests for scripts/ci/detect-changes.sh (build policy of ADR 0011)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "detect-changes.sh"

# git and bash are required prerequisites: a missing binary fails the tests.
GIT = shutil.which("git") or "git"
BASH = shutil.which("bash") or "bash"


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    subprocess.run(  # noqa: S603 - fixed git binary, test-controlled arguments
        [GIT, "-C", str(repo), *args], check=True, env=env, capture_output=True
    )


def _detect(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    env.pop("GITHUB_OUTPUT", None)
    return subprocess.run(  # noqa: S603 - fixed bash binary, repository script
        [BASH, str(SCRIPT), base, "HEAD"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _repo_with_change(tmp_path: Path, changed: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    target = repo / changed
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("change\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")
    return repo


def test_non_ascii_path_under_src_selects_amd64_build(tmp_path: Path) -> None:
    repo = _repo_with_change(tmp_path, "src/gemini_search_mcp/ü.py")

    result = _detect(repo, "HEAD~1")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_amd64=true",
        "build_arm64=false",
        "proxy_test=false",
    ]
    assert "nothing to build" not in result.stderr


def test_ec4_unrelated_change_selects_nothing(tmp_path: Path) -> None:
    repo = _repo_with_change(tmp_path, "docs/notes.md")

    result = _detect(repo, "HEAD~1")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_amd64=false",
        "build_arm64=false",
        "proxy_test=false",
    ]
    assert result.stderr.strip() == "container: nothing to build"


@pytest.mark.parametrize(
    "changed",
    [
        "scripts/ci/detect-changes.sh",
        "scripts/ci/proxy-stub/backend.py",
        ".github/workflows/ci.yml",
    ],
)
def test_ci_tooling_change_selects_every_container_step(tmp_path: Path, changed: str) -> None:
    repo = _repo_with_change(tmp_path, changed)

    result = _detect(repo, "HEAD~1")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_amd64=true",
        "build_arm64=true",
        "proxy_test=true",
    ]
