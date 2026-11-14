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

readonly PROJECT="gemini-search-mcp-proxy-test"
readonly URL="http://127.0.0.1:8080/mcp"
readonly PROTOCOL_VERSION="2026-07-28"
readonly METHOD="tools/call"
readonly NAME="search"

[[ $# -eq 0 ]] || {
  echo "usage: scripts/ci/proxy-test.sh" >&2
  exit 2
}

delay=${PROXY_TEST_DELAY_SECONDS:-75}
[[ $delay =~ ^[0-9]+$ && $delay -gt 60 ]] || {
  echo "PROXY_TEST_DELAY_SECONDS: must be an integer greater than 60" >&2
  exit 2
}
export PROXY_TEST_DELAY_SECONDS=$delay

root=$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)
cd "$root"

docker compose version >/dev/null 2>&1 || {
  echo "Docker with Compose v2 is not available" >&2
  exit 2
}

compose() {
  docker compose -p "$PROJECT" -f compose.yaml -f scripts/ci/proxy-stub/compose.yaml "$@"
}

work=$(mktemp -d)
failed=false

cleanup() {
  if [[ $failed == true ]]; then
    compose logs >&2 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT

# fail <check>: report the check; the log is printed by the exit trap.
fail() {
  echo "fail: $1"
  failed=true
  exit 1
}

compose up --detach --wait >/dev/null || fail "stack starts"

# Caddy has no health check: wait until it answers at all.
for ((tries = 0; tries < 30; tries++)); do
  status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 \
    "http://127.0.0.1:8080/health" || true)
  [[ $status != 000 ]] && break
  sleep 1
done

body='{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search","arguments":{"query":"proxy test"}}}'
started=$(date +%s)
curl_exit=0
status=$(curl --silent --show-error --no-buffer --output "$work/response" \
  --write-out '%{http_code}' --max-time "$((delay + 60))" \
  --request POST --header 'Content-Type: application/json' \
  --header 'Accept: application/json, text/event-stream' \
  --header "MCP-Protocol-Version: $PROTOCOL_VERSION" \
  --header "Mcp-Method: $METHOD" \
  --header "Mcp-Name: $NAME" \
  --data "$body" "$URL") || curl_exit=$?
elapsed=$(($(date +%s) - started))

if [[ $curl_exit -eq 0 && $status == 200 ]]; then
  echo "ok: response status 200 and stream complete"
else
  fail "response status 200 and stream complete (curl exit $curl_exit, status ${status:-none})"
fi

if [[ $elapsed -ge $delay ]]; then
  echo "ok: response held for at least ${delay}s through Caddy (${elapsed}s)"
else
  fail "response held for at least ${delay}s through Caddy (${elapsed}s)"
fi

if grep -qF '"result":' "$work/response" && grep -qF '"id":1,' "$work/response"; then
  echo "ok: final result event received"
else
  fail "final result event received"
fi

for pair in "MCP-Protocol-Version:$PROTOCOL_VERSION" "Mcp-Method:$METHOD" "Mcp-Name:$NAME"; do
  expected="\"${pair%%:*}\":\"${pair#*:}\""
  if grep -qF "$expected" "$work/response"; then
    echo "ok: header ${pair%%:*} passed through unchanged"
  else
    fail "header ${pair%%:*} passed through unchanged"
  fi
done
