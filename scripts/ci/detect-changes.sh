#!/usr/bin/env bash
# Decide which steps of the container CI jobs run, from the changed paths
# (build policy of docs/adr/0011-container-and-ci.md).
#
# Usage (from any directory inside the repository):
#   scripts/ci/detect-changes.sh <base-ref> [<head-ref>]
#   scripts/ci/detect-changes.sh --all
#
# Arguments:
#   <base-ref>  Git ref or commit the change is compared against, e.g.
#               origin/main or the pull request base SHA.
#   <head-ref>  Git ref or commit of the change; default HEAD.
#               The changed paths are `git diff --name-only <base-ref>...<head-ref>`
#               (three dots: changes since the merge base).
#   --all       Select every step without looking at a diff (push to main).
#
# Path rules (a path matches when it equals the entry or lies below a
# directory entry ending in "/"):
#   build_amd64  Dockerfile, .dockerignore, pyproject.toml, uv.lock, src/
#                (linux/amd64 build, Hadolint, image scan, smoke test)
#   build_arm64  Dockerfile, .dockerignore, uv.lock
#   proxy_test   Caddyfile, compose.yaml
#
# Environment:
#   GITHUB_OUTPUT  Optional. When set, the three key=value lines are also
#                  appended to this file (GitHub Actions step outputs).
#
# Output:
#   stdout: exactly three lines in this order, each value "true" or "false":
#     build_amd64=<bool>
#     build_arm64=<bool>
#     proxy_test=<bool>
#   stderr: one summary line; when every value is false it is exactly
#     "container: nothing to build"
#   No other side effects; the working tree and the index are not changed.
#
# Exit codes:
#   0  selection printed (also when nothing is selected)
#   2  usage error or a ref that git cannot resolve
#
# Prerequisites: git, and the history of both refs available locally
# (actions/checkout with fetch-depth: 0 in CI).
set -euo pipefail

echo "not implemented" >&2
exit 1
