#!/usr/bin/env bash
# Publish the checked per-architecture digests as one tagged manifest list
# (section "Release" of docs/adr/0011-container-and-ci.md). Runs only after
# every architecture passed its checks.
#
# Usage (after scripts/ci/registry-login.sh):
#   scripts/ci/publish-manifest.sh <image> <version> <revision> <digest>...
#   e.g. scripts/ci/publish-manifest.sh ghcr.io/svenkroll/mcp-gemini-search \
#          1.0.0-rc.1 <40-hex sha> sha256:<amd64> sha256:<arm64>
#
# Arguments:
#   <image>     Repository without tag or digest, e.g.
#               ghcr.io/svenkroll/mcp-gemini-search.
#   <version>   Image tag for the version, the release tag without "v"
#               (output "version" of scripts/ci/check-release-tag.sh).
#   <revision>  Full 40-character lowercase hex commit SHA (output "revision"
#               of scripts/ci/check-release-tag.sh); the second image tag.
#   <digest>    One or more digests "sha256:<64 hex>" already pushed to
#               <image>, one per architecture.
#
# Behavior:
#   1. Validates the arguments before any registry call.
#   2. Runs `docker buildx imagetools create` with exactly the two tags
#      <image>:<version> and <image>:<revision> from the sources
#      <image>@<digest>... . No other tag is created (no latest, no floating
#      tags).
#   3. Prints the result with `docker buildx imagetools inspect
#      <image>:<version>`.
#
# Environment: none (the registry login comes from the Docker client
# configuration).
#
# Output:
#   stdout: the output of imagetools create and inspect.
#   Side effects: creates or moves the two tags in the registry.
#
# Exit codes:
#   0  manifest list created and tagged
#   1  imagetools create or inspect failed
#   2  usage error: fewer than four arguments, <version> not a valid image tag
#      or containing "+", <revision> not 40 lowercase hex characters, or a
#      <digest> not "sha256:<64 lowercase hex>"; or Docker Buildx not available
#
# Prerequisites: Docker with Buildx, logged in to the registry of <image>.
set -euo pipefail

echo "not implemented" >&2
exit 1
