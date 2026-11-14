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

[[ $# -ge 4 ]] || {
  echo "usage: scripts/ci/publish-manifest.sh <image> <version> <revision> <digest>..." >&2
  exit 2
}
image=$1
version=$2
revision=$3
shift 3

# A Docker tag: up to 128 characters of [A-Za-z0-9_.-], not starting with "." or "-".
[[ $version =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || {
  echo "version is not a valid image tag: $version" >&2
  exit 2
}
[[ $revision =~ ^[0-9a-f]{40}$ ]] || {
  echo "revision is not a 40-character lowercase hex SHA: $revision" >&2
  exit 2
}
sources=()
for digest in "$@"; do
  [[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || {
    echo "digest is not sha256:<64 lowercase hex>: $digest" >&2
    exit 2
  }
  sources+=("$image@$digest")
done
docker buildx version >/dev/null 2>&1 || {
  echo "Docker Buildx is not available" >&2
  exit 2
}

docker buildx imagetools create \
  --tag "$image:$version" --tag "$image:$revision" "${sources[@]}" || exit 1
docker buildx imagetools inspect "$image:$version" || exit 1
