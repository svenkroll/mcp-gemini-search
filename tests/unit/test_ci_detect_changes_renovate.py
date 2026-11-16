"""Unit tests for the `renovate_check` output of scripts/ci/detect-changes.sh.

ADR 0011, section "Build policy": the Renovate configuration check runs when
`renovate.json` or a CI path (`scripts/ci/`, `.github/workflows/`) changed, and
with `--all`. The output is the fourth line, after the three existing ones.
"""

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


def _env() -> dict[str, str]:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    env.pop("GITHUB_OUTPUT", None)
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed git binary, test-controlled arguments
        [GIT, "-C", str(repo), *args], check=True, env=_env(), capture_output=True
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


def _detect(
    repo: Path, *args: str, github_output: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = _env()
    if github_output is not None:
        env["GITHUB_OUTPUT"] = str(github_output)
    return subprocess.run(  # noqa: S603 - fixed bash binary, repository script
        [BASH, str(SCRIPT), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ac2_only_renovate_json_changed_selects_only_the_renovate_check(tmp_path: Path) -> None:
    repo = _repo_with_change(tmp_path, "renovate.json")

    result = _detect(repo, "HEAD~1", "HEAD")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_amd64=false",
        "build_arm64=false",
        "proxy_test=false",
        "renovate_check=true",
    ]
    assert "nothing to build" not in result.stderr


def test_ac2_only_src_changed_does_not_select_the_renovate_check(tmp_path: Path) -> None:
    repo = _repo_with_change(tmp_path, "src/gemini_search_mcp/server.py")

    result = _detect(repo, "HEAD~1", "HEAD")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_amd64=true",
        "build_arm64=false",
        "proxy_test=false",
        "renovate_check=false",
    ]


@pytest.mark.parametrize(
    "changed",
    [
        "scripts/ci/detect-changes.sh",
        "scripts/ci/renovate/compose.yaml",
        ".github/workflows/ci.yml",
    ],
)
def test_ac2_ci_path_change_selects_the_renovate_check(tmp_path: Path, changed: str) -> None:
    repo = _repo_with_change(tmp_path, changed)

    result = _detect(repo, "HEAD~1", "HEAD")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_amd64=true",
        "build_arm64=true",
        "proxy_test=true",
        "renovate_check=true",
    ]


def test_ac2_all_selects_the_renovate_check(tmp_path: Path) -> None:
    repo = _repo_with_change(tmp_path, "docs/notes.md")

    result = _detect(repo, "--all")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "build_amd64=true",
        "build_arm64=true",
        "proxy_test=true",
        "renovate_check=true",
    ]


@pytest.mark.parametrize("changed", ["Dockerfile", "docs/notes.md", "Caddyfile"])
def test_ec8_change_outside_renovate_json_and_ci_paths_does_not_select_the_renovate_check(
    tmp_path: Path, changed: str
) -> None:
    repo = _repo_with_change(tmp_path, changed)

    result = _detect(repo, "HEAD~1", "HEAD")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[3:] == ["renovate_check=false"]


def test_renovate_check_is_also_appended_to_github_output(tmp_path: Path) -> None:
    repo = _repo_with_change(tmp_path, "renovate.json")
    output = tmp_path / "github-output"

    result = _detect(repo, "HEAD~1", "HEAD", github_output=output)

    assert result.returncode == 0, result.stderr
    assert output.read_text().splitlines() == [
        "build_amd64=false",
        "build_arm64=false",
        "proxy_test=false",
        "renovate_check=true",
    ]
