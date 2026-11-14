#!/usr/bin/env bash
# Smoke-test a locally built server image (docs/adr/0011-container-and-ci.md,
# docs/adr/0010-configuration.md).
#
# Usage (from any directory inside the repository):
#   docker build -t gemini-search-mcp:ci .
#   scripts/ci/smoke-test.sh <image>
#
# Arguments:
#   <image>  Reference of the server image in the local Docker daemon.
#
# Checks, in this order; the first failing check ends the script:
#   1. Non-root: `docker image inspect` reports a configured user whose user
#      part is numeric and not 0.
#   2. Missing key: a container started with a dummy MCP_BEARER_TOKEN and
#      without GEMINI_API_KEY exits with code 2, and its log contains
#      "GEMINI_API_KEY".
#   3. Read-only start: a container started detached with --read-only (no
#      tmpfs, no volumes), a dummy GEMINI_API_KEY and a dummy
#      MCP_BEARER_TOKEN of at least 32 characters generated per run, with
#      container port 8000 published on 127.0.0.1:<SMOKE_TEST_PORT>, answers
#      GET /health/ready with HTTP 200 within SMOKE_TEST_START_TIMEOUT seconds.
#   4. Authentication: POST /mcp with a JSON-RPC initialize body and without
#      an Authorization header answers HTTP 401.
#   The image's own defaults (MCP_TRANSPORT=http, MCP_HOST=0.0.0.0) are not
#   overridden. No dummy value is a real secret; none is printed.
#
# Environment:
#   SMOKE_TEST_PORT           Optional. Host port, default 18000.
#   SMOKE_TEST_START_TIMEOUT  Optional. Seconds to wait for readiness,
#                             default 30.
#
# Output:
#   stdout: one line per check, "ok: <check>" or "fail: <check>".
#   On failure the server container log is printed to stderr.
#   Side effects: starts containers; every container is removed on exit,
#   also on failure.
#
# Exit codes:
#   0  all checks passed
#   1  a check failed
#   2  usage error, image not found locally or Docker not available
#
# Prerequisites: Docker, curl.
set -euo pipefail

echo "not implemented" >&2
exit 1
