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
#   any severity fails. No repository Hadolint configuration is read.
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

echo "not implemented" >&2
exit 1
