#!/usr/bin/env bash
# Aggregate the results of the container CI jobs into the single required
# `container` check (build policy of docs/adr/0011-container-and-ci.md).
#
# Usage:
#   scripts/ci/require-success.sh <name>=<result> [<name>=<result> ...]
#   e.g. scripts/ci/require-success.sh changes=success amd64=skipped
#
# Arguments:
#   <name>=<result>  One pair per needed job; <result> is a GitHub Actions job
#                    result: success, skipped, failure or cancelled.
#
# Behavior:
#   Passes when every result is "success" or "skipped" (skipped means the
#   build policy did not select the job). Any other value fails.
#
# Environment: none.
#
# Output:
#   stdout: one line per pair, "<name>: <result>".
#   stderr: on failure, the names whose result is neither success nor skipped.
#   No files are written.
#
# Exit codes:
#   0  every job succeeded or was skipped
#   1  at least one job failed, was cancelled or reported an unknown result
#   2  usage error (no argument or an argument without "=")
#
# Prerequisites: Bash only.
set -euo pipefail

[[ $# -ge 1 ]] || {
  echo "usage: scripts/ci/require-success.sh <name>=<result> [<name>=<result> ...]" >&2
  exit 2
}

for pair in "$@"; do
  [[ $pair == *=* ]] || {
    echo "argument without '=': $pair" >&2
    exit 2
  }
done

failed=()
for pair in "$@"; do
  name=${pair%%=*}
  result=${pair#*=}
  echo "$name: $result"
  case $result in
    success | skipped) ;;
    *) failed+=("$name") ;;
  esac
done

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "not successful: ${failed[*]}" >&2
  exit 1
fi
