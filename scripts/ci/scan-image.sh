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

echo "not implemented" >&2
exit 1
