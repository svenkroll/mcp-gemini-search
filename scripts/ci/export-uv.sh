#!/usr/bin/env bash
# Export the uv binaries from the `uv` stage of the Dockerfile, the single
# source of uv (section "Single source" of docs/adr/0011-container-and-ci.md).
#
# Usage (from any directory inside the repository):
#   scripts/ci/export-uv.sh <dest-dir>
#   e.g. scripts/ci/export-uv.sh /tmp/uv
#
# Arguments:
#   <dest-dir>  Directory that receives the exported files. Created by the
#               export if it does not exist. Exactly one argument is required.
#
# Behavior:
#   Validates the arguments before anything else; on a usage error Docker is
#   not called. Resolves the repository root from the location of this script
#   (git rev-parse --show-toplevel), so the result is the same from any working
#   directory inside the repository. Runs
#     docker buildx build --target uv --output type=local,dest=<dest-dir>
#   with the repository root as build context and the Dockerfile there, on the
#   default builder of the Docker installation (works with the default
#   `docker` driver). No --platform: the stage is exported for the platform of
#   the Docker daemon. This is an export, not an image build: no image is
#   loaded or pushed and no cache is configured. After the export it checks
#   that <dest-dir>/uv and <dest-dir>/uvx exist. Existing files of those names
#   are replaced; further exported entries (the distroless image has an `io/`
#   directory) are left in place and ignored. There is no fallback to a
#   download. The binaries are not installed anywhere.
#
# Environment: none.
#
# Output:
#   Files: <dest-dir>/uv and <dest-dir>/uvx (plus any further entries of the
#   stage's filesystem).
#   stdout/stderr: Docker build output; on failure the Docker error or the
#   name of the missing binary on stderr.
#
# Exit codes:
#   0  export succeeded and both uv and uvx exist in <dest-dir>
#   1  the export failed (including Docker daemon not reachable or Buildx not
#      installed) or uv or uvx is missing after the export
#   2  usage error (no argument or more than one argument); usage on stderr
#
# Prerequisites: Docker with Buildx, git.
set -euo pipefail

echo "not implemented" >&2
exit 1
