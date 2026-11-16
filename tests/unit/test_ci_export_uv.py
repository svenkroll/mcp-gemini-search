"""Tests for scripts/ci/export-uv.sh.

The script exports the `uv` stage of the Dockerfile with the local exporter of
`docker buildx build` (ADR 0011, section "Single source"). Docker is not
available in the test environment: a stub `docker` executable placed first on
PATH records its call and imitates the local exporter.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "export-uv.sh"

# bash is a required prerequisite: a missing binary fails the tests.
BASH = shutil.which("bash") or "bash"

# The stub logs one argument per line plus the working directory. Behavior comes
# from the environment: STUB_FAIL_MESSAGE makes it fail like an unreachable
# daemon, STUB_FILES lists the entries it writes into the exported directory
# (a trailing slash makes a directory).
_DOCKER_STUB = """#!/usr/bin/env bash
{
  echo "cwd=$PWD"
  for arg in "$@"; do echo "arg=$arg"; done
} >> "$STUB_LOG"
if [[ -n "${STUB_FAIL_MESSAGE:-}" ]]; then
  echo "$STUB_FAIL_MESSAGE" >&2
  exit 1
fi
dest=
for arg in "$@"; do
  if [[ $arg == type=local,dest=* ]]; then dest=${arg#type=local,dest=}; fi
done
mkdir -p "$dest"
for entry in ${STUB_FILES:-}; do
  if [[ $entry == */ ]]; then mkdir -p "$dest/$entry"; else echo new > "$dest/$entry"; fi
done
"""

_NETWORK_STUB = """#!/usr/bin/env bash
echo "$0 $*" >> "$STUB_NETWORK_LOG"
exit 0
"""


class _Run:
    def __init__(self, result: subprocess.CompletedProcess[str], bin_dir: Path) -> None:
        self.result = result
        self.docker_log = bin_dir / "docker.log"
        self.network_log = bin_dir / "network.log"

    @property
    def docker_calls(self) -> list[str]:
        return self.docker_log.read_text().splitlines() if self.docker_log.exists() else []

    @property
    def docker_args(self) -> list[str]:
        return [line.removeprefix("arg=") for line in self.docker_calls if line.startswith("arg=")]

    @property
    def docker_cwd(self) -> str:
        return next(
            line.removeprefix("cwd=") for line in self.docker_calls if line.startswith("cwd=")
        )

    @property
    def network_calls(self) -> list[str]:
        return self.network_log.read_text().splitlines() if self.network_log.exists() else []


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    *args: str,
    cwd: Path = REPO_ROOT,
    files: str = "uv uvx io/",
    fail_message: str | None = None,
) -> _Run:
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(exist_ok=True)
    _write_executable(bin_dir / "docker", _DOCKER_STUB)
    for tool in ("curl", "wget"):
        _write_executable(bin_dir / tool, _NETWORK_STUB)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "STUB_LOG": str(bin_dir / "docker.log"),
        "STUB_NETWORK_LOG": str(bin_dir / "network.log"),
        "STUB_FILES": files,
    }
    env.pop("STUB_FAIL_MESSAGE", None)
    if fail_message is not None:
        env["STUB_FAIL_MESSAGE"] = fail_message
    result = subprocess.run(  # noqa: S603 - fixed bash binary, repository script
        [BASH, str(SCRIPT), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return _Run(result, bin_dir)


def test_ec1_missing_dest_dir_is_created_by_the_export(tmp_path: Path) -> None:
    dest = tmp_path / "does" / "not" / "exist"

    run = _run(tmp_path, str(dest))

    assert run.result.returncode == 0, run.result.stderr
    assert (dest / "uv").is_file()
    assert (dest / "uvx").is_file()


def test_ec2_existing_binaries_are_replaced(tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "uv").write_text("old")
    (dest / "uvx").write_text("old")

    run = _run(tmp_path, str(dest))

    assert run.result.returncode == 0, run.result.stderr
    assert (dest / "uv").read_text().strip() == "new"
    assert (dest / "uvx").read_text().strip() == "new"


def test_ec3_further_export_entries_are_ignored(tmp_path: Path) -> None:
    dest = tmp_path / "out"

    run = _run(tmp_path, str(dest), files="uv uvx io/ extra-file")

    assert run.result.returncode == 0, run.result.stderr
    assert (dest / "io").is_dir()
    assert (dest / "uv").is_file()
    assert (dest / "uvx").is_file()


def test_ec4_docker_failure_gives_exit_1_with_the_docker_error_and_no_download(
    tmp_path: Path,
) -> None:
    message = "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"

    run = _run(tmp_path, str(tmp_path / "out"), fail_message=message)

    assert run.result.returncode == 1
    assert message in run.result.stderr
    assert run.docker_calls, "docker was expected to be called"
    assert run.network_calls == []


@pytest.mark.parametrize("files", ["uvx", "uv", ""])
def test_ec4_missing_binary_after_export_gives_exit_1(tmp_path: Path, files: str) -> None:
    run = _run(tmp_path, str(tmp_path / "out"), files=files)

    assert run.result.returncode == 1
    assert run.network_calls == []


def test_ec5_subdirectory_call_uses_the_repository_root(tmp_path: Path) -> None:
    dest = tmp_path / "out"

    run = _run(tmp_path, str(dest), cwd=REPO_ROOT / "scripts" / "ci")

    assert run.result.returncode == 0, run.result.stderr
    args = run.docker_args
    root = str(REPO_ROOT)
    assert root in args, "repository root is the build context"
    assert args[args.index("--file") + 1] == f"{root}/Dockerfile"
    assert args[args.index("--target") + 1] == "uv"
    assert args[args.index("--output") + 1] == f"type=local,dest={dest}"
    assert "--platform" not in args
    assert args[:2] == ["buildx", "build"]


@pytest.mark.parametrize("extra_args", [(), ("one", "two")])
def test_ec6_wrong_argument_count_gives_usage_and_exit_2_without_docker(
    tmp_path: Path, extra_args: tuple[str, ...]
) -> None:
    run = _run(tmp_path, *extra_args)

    assert run.result.returncode == 2
    assert "usage" in run.result.stderr.lower()
    assert run.docker_calls == []
    assert run.network_calls == []
