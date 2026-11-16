"""Tests for scripts/ci/renovate-check.sh.

The script validates `renovate.json` and runs a Renovate extraction dry run,
both in the pinned official Renovate image (ADR 0011, sections "Single source"
and "Build policy"). Docker is not available in the test environment: a stub
`docker` executable placed first on PATH records its calls and imitates
`docker compose config --images` and `docker run`.

The script is copied into a throwaway git repository, so `renovate.json` can
be present or missing independently of the real repository.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "renovate-check.sh"

# git and bash are required prerequisites: a missing binary fails the tests.
GIT = shutil.which("git") or "git"
BASH = shutil.which("bash") or "bash"

IMAGE = "ghcr.io/renovatebot/renovate:44.242.0@sha256:" + "ab12" * 16
VALIDATOR_OUTPUT = "VALIDATOR-OUTPUT-MARKER"
EXTRACTION_OUTPUT = "EXTRACTION-OUTPUT-MARKER"
LEAK_CANARY = "secret-value-must-not-leak"
CALL_MARKER = "--call--"

# The stub logs every call as CALL_MARKER followed by one argument per line.
# `compose ... config --images` prints STUB_IMAGE. A `docker run` is classified
# by its command: the validator prints VALIDATOR_OUTPUT, the extraction prints
# EXTRACTION_OUTPUT. STUB_FAIL selects what fails: validator, extraction,
# compose or all (an unreachable daemon).
_DOCKER_STUB = f"""#!/usr/bin/env bash
{{
  echo "{CALL_MARKER}"
  for arg in "$@"; do echo "arg=$arg"; done
}} >> "$STUB_LOG"
fail=${{STUB_FAIL:-}}
if [[ $fail == all ]]; then
  echo "Cannot connect to the Docker daemon" >&2
  exit 1
fi
case " $* " in
  *" renovate-config-validator "*)
    echo "{VALIDATOR_OUTPUT}"
    [[ $fail == validator ]] && exit 1
    exit 0
    ;;
  *" --dry-run=extract "*)
    echo "{EXTRACTION_OUTPUT}"
    [[ $fail == extraction ]] && exit 1
    exit 0
    ;;
  *" config "*)
    [[ $fail == compose ]] && exit 1
    echo "$STUB_IMAGE"
    exit 0
    ;;
esac
exit 0
"""


class _Run:
    def __init__(self, result: subprocess.CompletedProcess[str], bin_dir: Path, root: Path) -> None:
        self.result = result
        self.root = root
        self.docker_log = bin_dir / "docker.log"

    @property
    def output(self) -> str:
        return self.result.stdout + self.result.stderr

    @property
    def calls(self) -> list[list[str]]:
        if not self.docker_log.exists():
            return []
        calls: list[list[str]] = []
        for line in self.docker_log.read_text().splitlines():
            if line == CALL_MARKER:
                calls.append([])
            elif line.startswith("arg="):
                calls[-1].append(line.removeprefix("arg="))
        return calls

    @property
    def run_calls(self) -> list[list[str]]:
        return [call for call in self.calls if call and call[0] == "run"]

    def run_call_for(self, marker: str) -> list[list[str]]:
        return [call for call in self.run_calls if marker in call]


def _git_env() -> dict[str, str]:
    return {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _make_repo(tmp_path: Path, *, with_config: bool = True, config: str = "{}\n") -> Path:
    repo = (tmp_path / "repo").resolve()
    ci_dir = repo / "scripts" / "ci"
    ci_dir.mkdir(parents=True)
    shutil.copy(SCRIPT, ci_dir / "renovate-check.sh")
    (ci_dir / "renovate").mkdir()
    (ci_dir / "renovate" / "compose.yaml").write_text(
        f"services:\n  renovate:\n    image: {IMAGE}\n"
    )
    if with_config:
        (repo / "renovate.json").write_text(config)
    subprocess.run(  # noqa: S603 - fixed git binary, test-controlled arguments
        [GIT, "-C", str(repo), "init", "-q", "-b", "main"],
        check=True,
        env=_git_env(),
        capture_output=True,
    )
    return repo


def _run(
    tmp_path: Path,
    *args: str,
    with_config: bool = True,
    cwd_rel: str = "",
    fail: str | None = None,
) -> _Run:
    repo = _make_repo(tmp_path, with_config=with_config)
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir()
    stub = bin_dir / "docker"
    stub.write_text(_DOCKER_STUB)
    stub.chmod(0o755)
    env = {
        **_git_env(),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_LOG": str(bin_dir / "docker.log"),
        "STUB_IMAGE": IMAGE,
        "GITHUB_TOKEN": LEAK_CANARY,
        "RENOVATE_TOKEN": LEAK_CANARY,
        "GH_TOKEN": LEAK_CANARY,
    }
    env.pop("STUB_FAIL", None)
    if fail is not None:
        env["STUB_FAIL"] = fail
    result = subprocess.run(  # noqa: S603 - fixed bash binary, copied repository script
        [BASH, str(repo / "scripts" / "ci" / "renovate-check.sh"), *args],
        cwd=repo / cwd_rel,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return _Run(result, bin_dir, repo)


def _option_values(call: list[str], *names: str) -> list[str]:
    """Values of an option given as `--name value`, `--name=value` or `-x value`."""
    values: list[str] = []
    for index, arg in enumerate(call):
        for name in names:
            if arg == name and index + 1 < len(call):
                values.append(call[index + 1])
            elif arg.startswith(f"{name}=") and name.startswith("--"):
                values.append(arg.removeprefix(f"{name}="))
    return values


def _image_index(call: list[str]) -> int:
    return call.index(IMAGE)


def test_ac3_runs_validator_then_extraction_in_the_pinned_image(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert run.result.returncode == 0, run.output
    assert len(run.run_calls) == 2
    validator, extraction = run.run_calls
    assert IMAGE in validator
    assert IMAGE in extraction
    validator_command = validator[_image_index(validator) + 1 :]
    extraction_command = extraction[_image_index(extraction) + 1 :]
    assert validator_command[0] == "renovate-config-validator"
    assert "--strict" in validator_command
    assert "renovate.json" in validator_command[-1]
    assert extraction_command[0] == "renovate"
    assert "--platform=local" in extraction_command
    assert "--dry-run=extract" in extraction_command
    assert VALIDATOR_OUTPUT in run.output
    assert EXTRACTION_OUTPUT in run.output
    assert run.output.index(VALIDATOR_OUTPUT) < run.output.index(EXTRACTION_OUTPUT)


def test_ac3_containers_have_no_network_and_a_read_only_repository(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert run.result.returncode == 0, run.output
    assert len(run.run_calls) == 2
    for call in run.run_calls:
        assert _option_values(call, "--network", "--net") == ["none"]
        mounts = _option_values(call, "--volume", "-v", "--mount")
        repo_mounts = [mount for mount in mounts if str(run.root) in mount]
        assert len(repo_mounts) == 1, mounts
        mount = repo_mounts[0]
        if mount.startswith("type="):
            assert "readonly" in mount.split(",") or "ro" in mount.split(",")
        else:
            assert mount.split(":")[-1].split(",")[0] == "ro"


def test_ac3_containers_receive_no_token_from_the_environment(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert run.result.returncode == 0, run.output
    assert len(run.run_calls) == 2
    for call in run.run_calls:
        assert "--env-file" not in call
        assert not any(arg.startswith("--env-file=") for arg in call)
        assert LEAK_CANARY not in " ".join(call)
        for assignment in _option_values(call, "--env", "-e"):
            assert "=" in assignment, f"environment pass-through: {assignment}"
            name = assignment.split("=", 1)[0]
            assert name not in {"GITHUB_TOKEN", "RENOVATE_TOKEN", "GH_TOKEN"}


def test_ac3_step_1_failure_gives_exit_1_and_skips_step_2(tmp_path: Path) -> None:
    run = _run(tmp_path, fail="validator")

    assert run.result.returncode == 1
    assert VALIDATOR_OUTPUT in run.output
    assert len(run.run_calls) == 1
    assert EXTRACTION_OUTPUT not in run.output


def test_ac3_step_2_failure_gives_exit_1(tmp_path: Path) -> None:
    run = _run(tmp_path, fail="extraction")

    assert run.result.returncode == 1
    assert len(run.run_calls) == 2


def test_ac3_missing_renovate_json_gives_exit_1_without_docker_call(tmp_path: Path) -> None:
    run = _run(tmp_path, with_config=False)

    assert run.result.returncode == 1
    assert "renovate.json" in run.result.stderr
    assert run.calls == []


@pytest.mark.parametrize("args", [("one",), ("--help",), ("one", "two"), ("",)])
def test_ac3_any_argument_gives_exit_2_without_docker_call(
    tmp_path: Path, args: tuple[str, ...]
) -> None:
    run = _run(tmp_path, *args)

    assert run.result.returncode == 2
    assert run.calls == []


def test_ec1_missing_renovate_json_prints_a_message_naming_the_file(tmp_path: Path) -> None:
    run = _run(tmp_path, with_config=False)

    assert run.result.returncode == 1
    assert "renovate.json" in run.result.stderr
    assert run.calls == []


def test_ec2_invalid_configuration_stops_before_the_extraction(tmp_path: Path) -> None:
    run = _run(tmp_path, fail="validator")

    assert run.result.returncode == 1
    assert run.run_call_for("--dry-run=extract") == []
    assert [call for call in run.run_calls if "renovate-config-validator" in call]


def test_ec3_extraction_failure_shows_renovates_output(tmp_path: Path) -> None:
    run = _run(tmp_path, fail="extraction")

    assert run.result.returncode == 1
    assert EXTRACTION_OUTPUT in run.output


def test_ec4_repository_is_marked_safe_for_git_inside_the_container(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert run.result.returncode == 0, run.output
    assert len(run.run_calls) == 2
    for call in run.run_calls:
        mounts = [m for m in _option_values(call, "--volume", "-v") if str(run.root) in m]
        assert len(mounts) == 1, mounts
        target = mounts[0].split(":")[1]
        environment = _option_values(call, "--env", "-e")
        assert "GIT_CONFIG_COUNT=1" in environment
        assert "GIT_CONFIG_KEY_0=safe.directory" in environment
        assert f"GIT_CONFIG_VALUE_0={target}" in environment


def test_ec5_both_steps_run_without_network(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert run.result.returncode == 0, run.output
    assert len(run.run_calls) == 2
    assert all(_option_values(call, "--network", "--net") == ["none"] for call in run.run_calls)


def test_ec6_subdirectory_call_mounts_the_repository_root(tmp_path: Path) -> None:
    run = _run(tmp_path, cwd_rel="scripts/ci")

    assert run.result.returncode == 0, run.output
    assert len(run.run_calls) == 2
    for call in run.run_calls:
        mounts = _option_values(call, "--volume", "-v")
        assert len([m for m in mounts if m.startswith(f"{run.root}:")]) == 1, mounts


def test_ec7_argument_prints_usage_on_stderr(tmp_path: Path) -> None:
    run = _run(tmp_path, "unexpected")

    assert run.result.returncode == 2
    assert "usage" in run.result.stderr.lower()
    assert run.calls == []


def test_docker_failure_gives_exit_1_without_running_the_steps(tmp_path: Path) -> None:
    run = _run(tmp_path, fail="all")

    assert run.calls, "docker was expected to be called"
    assert run.result.returncode == 1
    assert run.run_calls == []


def test_unreadable_image_reference_gives_exit_1_without_running_the_steps(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path, fail="compose")

    assert run.calls, "the image reference was expected to be read through docker"
    assert run.result.returncode == 1
    assert run.run_calls == []
