#!/usr/bin/env bash
# Lint the Dockerfile with Hadolint; every finding blocks
# (docs/adr/0011-container-and-ci.md).
#
# Usage (from any directory inside the repository):
#   scripts/ci/hadolint.sh [<dockerfile>]
#
# Arguments:
#   <dockerfile>  Path relative to the repository root; default Dockerfile.
#
# Behavior:
#   Runs the official Hadolint image, pinned by digest in a readonly variable
#   at the top of this script (the single source of that digest), with the
#   Dockerfile on stdin and failure threshold "style", so every finding of
#   any severity fails. No repository Hadolint configuration is read and
#   inline "hadolint ignore" pragmas in the Dockerfile are disabled.
#
# Environment: none.
#
# Output:
#   stdout/stderr: Hadolint findings, one per line; nothing on success.
#   No files are written.
#
# Exit codes:
#   0  no findings
#   1  at least one finding
#   2  usage error, missing Dockerfile or Docker not available
#
# Prerequisites: Docker.
set -euo pipefail

# hadolint/hadolint v2.15.1
readonly HADOLINT_IMAGE="hadolint/hadolint@sha256:32dac94127fd60b7b7e3fbfc65e1383b9b5e25c9bfd7b8536de7a539fe68a12d"

[[ $# -le 1 ]] || {
  echo "usage: scripts/ci/hadolint.sh [<dockerfile>]" >&2
  exit 2
}

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
dockerfile="$root/${1:-Dockerfile}"
[[ -f $dockerfile ]] || {
  echo "Dockerfile not found: $dockerfile" >&2
  exit 2
}
docker info >/dev/null 2>&1 || {
  echo "Docker is not available" >&2
  exit 2
}

# The Dockerfile arrives on stdin, so the container sees no repository file and
# reads no repository Hadolint configuration.
docker run --quiet --rm -i "$HADOLINT_IMAGE" hadolint --disable-ignore-pragma --failure-threshold style - <"$dockerfile"
