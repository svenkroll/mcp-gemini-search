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
#   all three    scripts/ci/ (including scripts/ci/proxy-stub/), .github/workflows/
#                (the CI tooling itself; every step runs)
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

readonly AMD64_PATHS=(Dockerfile .dockerignore pyproject.toml uv.lock src/)
readonly ARM64_PATHS=(Dockerfile .dockerignore uv.lock)
readonly PROXY_PATHS=(Caddyfile compose.yaml)
readonly CI_PATHS=(scripts/ci/ .github/workflows/)

usage() {
  echo "usage: scripts/ci/detect-changes.sh <base-ref> [<head-ref>] | --all" >&2
  exit 2
}

# touches <changed-paths-file> <entry>...: succeeds when a changed path equals
# an entry or lies below a directory entry ending in "/". The file holds
# NUL-delimited paths.
touches() {
  local changed=$1 entry path
  shift
  for entry in "$@"; do
    while IFS= read -r -d '' path; do
      if [[ $entry == */ ]]; then
        [[ $path == "$entry"* ]] && return 0
      else
        [[ $path == "$entry" ]] && return 0
      fi
    done <"$changed"
  done
  return 1
}

[[ $# -ge 1 && $# -le 2 ]] || usage

build_amd64=false
build_arm64=false
proxy_test=false

if [[ $1 == --all ]]; then
  [[ $# -eq 1 ]] || usage
  build_amd64=true
  build_arm64=true
  proxy_test=true
else
  [[ $1 != -* ]] || usage
  base=$1
  head=${2:-HEAD}
  git rev-parse --verify --quiet "${base}^{commit}" >/dev/null || {
    echo "unknown ref: $base" >&2
    exit 2
  }
  git rev-parse --verify --quiet "${head}^{commit}" >/dev/null || {
    echo "unknown ref: $head" >&2
    exit 2
  }
  changed=$(mktemp)
  trap 'rm -f "$changed"' EXIT
  # --no-renames lists both sides of a rename, so a moved file still matches.
  # -z with quotePath off lists paths unquoted, also non-ASCII ones.
  git -c core.quotePath=false diff --name-only -z --no-renames "${base}...${head}" -- \
    >"$changed" || exit 2
  if touches "$changed" "${CI_PATHS[@]}"; then
    build_amd64=true
    build_arm64=true
    proxy_test=true
  fi
  if touches "$changed" "${AMD64_PATHS[@]}"; then build_amd64=true; fi
  if touches "$changed" "${ARM64_PATHS[@]}"; then build_arm64=true; fi
  if touches "$changed" "${PROXY_PATHS[@]}"; then proxy_test=true; fi
fi

printf '%s\n' "build_amd64=$build_amd64" "build_arm64=$build_arm64" "proxy_test=$proxy_test"
if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  printf '%s\n' "build_amd64=$build_amd64" "build_arm64=$build_arm64" \
    "proxy_test=$proxy_test" >>"$GITHUB_OUTPUT"
fi

if [[ $build_amd64 == false && $build_arm64 == false && $proxy_test == false ]]; then
  echo "container: nothing to build" >&2
else
  echo "container: build_amd64=$build_amd64 build_arm64=$build_arm64 proxy_test=$proxy_test" >&2
fi
