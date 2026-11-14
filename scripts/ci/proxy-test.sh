#!/usr/bin/env bash
# Prove that the repository Caddyfile does not cut off long Streamable HTTP
# responses and passes the MCP headers through unchanged
# (docs/adr/0002-mcp-framework-and-transport.md, docs/adr/0008-security.md,
# docs/adr/0011-container-and-ci.md).
#
# Usage (from any directory inside the repository):
#   scripts/ci/proxy-test.sh
#
# Arguments: none.
#
# Behavior:
#   1. Starts the stack with
#        docker compose -p gemini-search-mcp-proxy-test \
#          -f compose.yaml -f scripts/ci/proxy-stub/compose.yaml up -d --wait
#      The repository compose.yaml supplies the Caddy service with its
#      digest-pinned image and the repository Caddyfile unchanged. The
#      override file scripts/ci/proxy-stub/compose.yaml replaces only the
#      `server` service with the fake backend scripts/ci/proxy-stub/backend.py,
#      run in its own digest-pinned Python image (never the server image), so
#      no build, no .env file and no Gemini key are needed.
#   2. Sends one POST /mcp through Caddy at http://127.0.0.1:8080 with the
#      headers MCP-Protocol-Version: 2026-07-28, Mcp-Method: tools/call,
#      Mcp-Name: search and a JSON-RPC tools/call body. The backend delays
#      its final event by PROXY_TEST_DELAY_SECONDS, which the override file
#      passes to it as PROXY_STUB_DELAY_SECONDS.
#   3. Passes when the response has HTTP status 200, took at least
#      PROXY_TEST_DELAY_SECONDS, contains the backend's final JSON-RPC result
#      event, and that result reports all three headers with exactly the sent
#      values.
#
# Environment:
#   PROXY_TEST_DELAY_SECONDS  Optional. Backend delay, default 75; must be
#                             greater than 60.
#
# Output:
#   stdout: "ok: <check>" or "fail: <check>" per check in step 3.
#   On failure the compose logs are printed to stderr.
#   Side effects: starts the compose project gemini-search-mcp-proxy-test and
#   always removes it with its volumes and networks on exit.
#
# Exit codes:
#   0  all checks passed
#   1  a check failed (cut-off response, wrong status, changed or missing header)
#   2  usage error, invalid PROXY_TEST_DELAY_SECONDS or Docker not available
#
# Prerequisites: Docker with Compose v2, curl; host port 8080 free.
set -euo pipefail

echo "not implemented" >&2
exit 1
