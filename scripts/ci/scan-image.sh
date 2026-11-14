#!/usr/bin/env bash
# Scan a locally available container image with Trivy as defined in
# docs/adr/0011-container-and-ci.md.
#
# Usage (from any directory inside the repository):
#   scripts/ci/scan-image.sh <image>
#
# Arguments:
#   <image>  Reference of an image present in the local Docker daemon, e.g.
#            gemini-search-mcp:ci (the image the CI build step loaded).
#
# Behavior:
#   Runs the official Trivy image, pinned by digest in a readonly variable at
#   the top of this script (the single source of that digest), against the
#   local image. The image is not pulled from or pushed to a registry.
#   - CRITICAL findings fail the scan, whether a fix exists or not.
#   - HIGH findings are printed in the report and do not fail the scan.
#   - Exceptions come only from .trivyignore in the repository root, when the
#     file exists; no other ignore source is used.
#
# Environment:
#   TRIVY_CACHE_DIR  Optional. Host directory for the Trivy vulnerability
#                    database cache; default a temporary directory that is
#                    removed on exit.
#
# Output:
#   stdout: Trivy table report covering CRITICAL and HIGH findings.
#   No files are written outside the cache directory.
#
# Exit codes:
#   0  no CRITICAL finding outside .trivyignore
#   1  at least one CRITICAL finding
#   2  usage error, image not found locally or Docker not available
#
# Prerequisites: Docker; network access to download the Trivy database.
set -euo pipefail

# aquasec/trivy 0.76.2
readonly TRIVY_IMAGE="aquasec/trivy@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb"

[[ $# -eq 1 ]] || {
  echo "usage: scripts/ci/scan-image.sh <image>" >&2
  exit 2
}
image=$1

docker info >/dev/null 2>&1 || {
  echo "Docker is not available" >&2
  exit 2
}
docker image inspect "$image" >/dev/null 2>&1 || {
  echo "image not found locally: $image" >&2
  exit 2
}

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
cache=${TRIVY_CACHE_DIR:-$work/cache}
mkdir -p "$cache"

# Trivy reads an image archive, so it needs neither the Docker socket nor a
# registry; the scanned image is the one that was built.
docker save --output "$work/image.tar" "$image"

args=(
  --quiet
  --rm
  --user "$(id -u):$(id -g)"
  --volume "$work/image.tar:/image.tar:ro"
  --volume "$cache:/cache"
)
trivy_args=(image --cache-dir /cache --input /image.tar --scanners vuln --no-progress --table-mode detailed)
if [[ -f $root/.trivyignore ]]; then
  args+=(--volume "$root/.trivyignore:/.trivyignore:ro")
  trivy_args+=(--ignorefile /.trivyignore)
fi

# Report CRITICAL and HIGH findings without failing, then fail on CRITICAL
# whether a fix exists or not.
docker run "${args[@]}" "$TRIVY_IMAGE" "${trivy_args[@]}" \
  --severity CRITICAL,HIGH --exit-code 0
docker run "${args[@]}" "$TRIVY_IMAGE" "${trivy_args[@]}" \
  --severity CRITICAL --exit-code 1 --skip-db-update --quiet
