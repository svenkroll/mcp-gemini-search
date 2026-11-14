#!/usr/bin/env bash
# Log Docker in to a container registry with a token from the environment
# (section "Release" of docs/adr/0011-container-and-ci.md: login with
# GITHUB_TOKEN via docker login in a script, no additional action).
#
# Usage:
#   REGISTRY_USER=<user> REGISTRY_TOKEN=<token> scripts/ci/registry-login.sh <registry>
#   e.g. scripts/ci/registry-login.sh ghcr.io
#   Locally, REGISTRY_TOKEN is a personal access token with write:packages.
#
# Arguments:
#   <registry>  Registry host, e.g. ghcr.io.
#
# Behavior:
#   Runs `docker login <registry> --username "$REGISTRY_USER" --password-stdin`
#   with REGISTRY_TOKEN on stdin. The token never appears on a command line
#   and is never printed.
#
# Environment:
#   REGISTRY_USER   Required. User name (github.actor in CI).
#   REGISTRY_TOKEN  Required. Token (GITHUB_TOKEN in CI); never printed.
#
# Output:
#   stdout/stderr: the output of docker login, no token.
#   Side effects: Docker stores the credentials in its client configuration
#   (~/.docker/config.json by default).
#
# Exit codes:
#   0  logged in
#   1  docker login failed
#   2  usage error, REGISTRY_USER or REGISTRY_TOKEN empty or unset, or Docker
#      not available
#
# Prerequisites: Docker.
set -euo pipefail

echo "not implemented" >&2
exit 1
