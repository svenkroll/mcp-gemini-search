"""Tests for scripts/ci/check-release-tag.sh and the release workflow graph.

Section "Release" of ADR 0011: the tag check runs before any build and
the manifest tags are set only after every architecture passed.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "check-release-tag.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"

# git and bash are required prerequisites: a missing binary fails the tests.
GIT = shutil.which("git") or "git"
BASH = shutil.which("bash") or "bash"

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git binary, test-controlled arguments
        [GIT, "-C", str(repo), *args],
        check=True,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit_version(repo: Path, version: str) -> str:
    (repo / "pyproject.toml").write_text(f'[project]\nname = "demo"\nversion = "{version}"\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"version {version}")
    return _git(repo, "rev-parse", "HEAD")


def _repo_on_main(tmp_path: Path, project_version: str, name: str = "repo") -> tuple[Path, str]:
    """Repository whose only commit is on main (also as origin/main)."""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    sha = _commit_version(repo, project_version)
    _git(repo, "update-ref", "refs/remotes/origin/main", sha)
    return repo, sha


def _check(repo: Path, tag: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **_GIT_ENV}
    env.pop("GITHUB_OUTPUT", None)
    env.pop("RELEASE_MAIN_REF", None)
    return subprocess.run(  # noqa: S603 - fixed bash binary, repository script
        [BASH, str(SCRIPT), tag],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_rejected(tmp_path: Path, repo: Path, tag: str) -> None:
    """The tag is rejected, while a valid tag in a control repository passes.

    The control keeps a rejection test from passing for an implementation that
    rejects every tag.
    """
    control, _ = _repo_on_main(tmp_path, "1.0.0", name="control")
    _git(control, "tag", "v1.0.0")
    accepted = _check(control, "v1.0.0")
    assert accepted.returncode == 0, accepted.stderr

    result = _check(repo, tag)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.strip() != ""


@pytest.mark.parametrize(
    ("tag", "project_version"),
    [
        ("v1.0.0", "1.0.0"),
        ("v0.1.0", "0.1.0"),
        ("v1.0.0-rc.1", "1.0.0rc1"),
    ],
)
def test_ac1_accepts_valid_tag_matching_project_version(
    tmp_path: Path, tag: str, project_version: str
) -> None:
    repo, sha = _repo_on_main(tmp_path, project_version)
    _git(repo, "tag", tag)

    result = _check(repo, tag)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"version={tag[1:]}",
        f"revision={sha}",
    ]


def test_ac1_accepts_annotated_tag(tmp_path: Path) -> None:
    repo, sha = _repo_on_main(tmp_path, "1.2.3")
    _git(repo, "tag", "-a", "v1.2.3", "-m", "release")

    result = _check(repo, "v1.2.3")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["version=1.2.3", f"revision={sha}"]


@pytest.mark.parametrize("tag", ["v1", "vtest"])
def test_ec1_rejects_tag_that_is_not_semver(tmp_path: Path, tag: str) -> None:
    repo, _ = _repo_on_main(tmp_path, "1.0.0")
    _git(repo, "tag", tag)

    _assert_rejected(tmp_path, repo, tag)


def test_ec2_rejects_build_metadata(tmp_path: Path) -> None:
    repo, _ = _repo_on_main(tmp_path, "1.0.0")
    _git(repo, "tag", "v1.0.0+build.5")

    _assert_rejected(tmp_path, repo, "v1.0.0+build.5")


def test_ac1_rejects_tag_without_v_prefix(tmp_path: Path) -> None:
    repo, _ = _repo_on_main(tmp_path, "1.0.0")
    _git(repo, "tag", "1.0.0")

    _assert_rejected(tmp_path, repo, "1.0.0")


@pytest.mark.parametrize(
    ("tag", "project_version"),
    [
        ("v1.0.0", "1.0.1"),
        ("v1.0.0", "1.0"),
        ("v1.0.0-rc.1", "1.0.0"),
        ("v1.0.0-rc.1", "1.0.0rc2"),
    ],
)
def test_ec3_rejects_tag_version_differing_from_project_version(
    tmp_path: Path, tag: str, project_version: str
) -> None:
    repo, _ = _repo_on_main(tmp_path, project_version)
    _git(repo, "tag", tag)

    _assert_rejected(tmp_path, repo, tag)


def test_ec4_rejects_tag_on_commit_not_on_main(tmp_path: Path) -> None:
    repo, _ = _repo_on_main(tmp_path, "0.9.0")
    _git(repo, "switch", "-q", "-c", "feature")
    _commit_version(repo, "1.0.0")
    _git(repo, "tag", "v1.0.0")

    _assert_rejected(tmp_path, repo, "v1.0.0")


def test_ec5_prerelease_tag_yields_version_and_revision(tmp_path: Path) -> None:
    repo, sha = _repo_on_main(tmp_path, "1.0.0rc1")
    _git(repo, "tag", "v1.0.0-rc.1")

    result = _check(repo, "v1.0.0-rc.1")

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["version=1.0.0-rc.1", f"revision={sha}"]


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _needs(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _transitive_needs(jobs: dict[str, Any], name: str) -> set[str]:
    seen: set[str] = set()
    pending = list(_needs(jobs[name]))
    while pending:
        current = pending.pop()
        if current not in seen:
            seen.add(current)
            pending.extend(_needs(jobs[current]))
    return seen


def test_ec1_every_other_job_depends_on_tag_check() -> None:
    jobs = _workflow()["jobs"]

    assert "tag-check" in jobs
    for name in jobs:
        if name != "tag-check":
            assert "tag-check" in _transitive_needs(jobs, name), name


def test_ec6_publish_runs_only_after_every_architecture_passed() -> None:
    jobs = _workflow()["jobs"]
    publish = jobs["publish"]

    assert {"image-amd64", "image-arm64"} <= _needs(publish)
    # An `if` could let the job run although a needed job failed.
    assert "if" not in publish
