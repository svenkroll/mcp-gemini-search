"""Unit tests for the repository quality tooling configuration."""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
# Allowed actions per ADR 0011: first-party actions/* plus two named Docker
# actions, each pinned to an exact 40-character commit SHA with a version comment.
ALLOWED_ACTION = re.compile(
    r"^\s*(?:-\s+)?uses:\s*"
    r"(?:actions/[\w.-]+|docker/setup-buildx-action|docker/build-push-action)"
    r"@[0-9a-f]{40}\s+#\s*v\S+\s*$"
)


def _is_allowed_action(line: str) -> bool:
    return ALLOWED_ACTION.match(line) is not None


def _workflow_files() -> list[Path]:
    return sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))


def test_at_least_one_workflow_exists() -> None:
    assert _workflow_files(), "expected at least one GitHub Actions workflow"


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_workflow_uses_sha_pinned_actions(workflow: Path) -> None:
    for line in workflow.read_text(encoding="utf-8").splitlines():
        if "uses:" in line:
            assert _is_allowed_action(line), (
                "action must be on the ADR 0011 list and pinned as "
                f"<action>@<40-char commit SHA> # v<version>: {line.strip()}"
            )


SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


@pytest.mark.parametrize(
    "line",
    [
        f"        uses: actions/checkout@{SHA} # v7.0.1",
        f"      - uses: docker/setup-buildx-action@{SHA} # v3.12.0",
        f"        uses: docker/build-push-action@{SHA} # v6.19.2",
    ],
)
def test_ac3_allowed_actions_pinned_by_sha_are_accepted(line: str) -> None:
    assert _is_allowed_action(line)


@pytest.mark.parametrize(
    "line",
    [
        f"        uses: docker/setup-qemu-action@{SHA} # v3.7.0",
        f"        uses: docker/login-action@{SHA} # v3.6.0",
        f"        uses: aquasecurity/trivy-action@{SHA} # v0.33.1",
        f"        uses: actionsx/checkout@{SHA} # v7.0.1",
    ],
)
def test_ec2_actions_not_on_the_list_are_rejected(line: str) -> None:
    assert not _is_allowed_action(line)


@pytest.mark.parametrize(
    "line",
    [
        "        uses: actions/checkout@v7.0.1",
        "        uses: docker/build-push-action@v6",
        f"        uses: actions/checkout@{SHA[:12]} # v7.0.1",
        f"        uses: actions/checkout@{SHA}",
    ],
)
def test_ec3_tag_pins_short_shas_and_missing_version_comments_are_rejected(
    line: str,
) -> None:
    assert not _is_allowed_action(line)


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


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_workflow_files_are_valid_yaml(workflow: Path) -> None:
    assert yaml.safe_load(workflow.read_text(encoding="utf-8")) is not None
