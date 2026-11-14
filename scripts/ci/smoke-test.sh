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

port=${SMOKE_TEST_PORT:-18000}
start_timeout=${SMOKE_TEST_START_TIMEOUT:-30}

[[ $# -eq 1 ]] || {
  echo "usage: scripts/ci/smoke-test.sh <image>" >&2
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
[[ $port =~ ^[0-9]+$ && $start_timeout =~ ^[0-9]+$ ]] || {
  echo "SMOKE_TEST_PORT and SMOKE_TEST_START_TIMEOUT must be integers" >&2
  exit 2
}

suffix="$$"
missing_key_container="gemini-search-mcp-smoke-missing-key-$suffix"
server_container="gemini-search-mcp-smoke-server-$suffix"

cleanup() {
  docker rm --force "$missing_key_container" "$server_container" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# fail <check>: report the check, print the server log and end the script.
fail() {
  echo "fail: $1"
  if docker container inspect "$server_container" >/dev/null 2>&1; then
    docker logs "$server_container" >&2 2>&1
  fi
  exit 1
}

# Dummy values for this run only; they are not real secrets and are not printed.
# They reach the containers by name, not by value, so they stay off command lines.
GEMINI_API_KEY="dummy-key-for-smoke-test"
MCP_BEARER_TOKEN=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
export GEMINI_API_KEY MCP_BEARER_TOKEN

# Check 1: the image runs as a numeric, non-root user.
user=$(docker image inspect --format '{{.Config.User}}' "$image")
user_part=${user%%:*}
if [[ $user_part =~ ^[0-9]+$ && $user_part != 0 ]]; then
  echo "ok: non-root numeric user"
else
  fail "non-root numeric user (configured user: '${user}')"
fi

# Check 2: a missing GEMINI_API_KEY ends the start with exit code 2 and a log
# line that names the variable.
exit_code=0
log=$(docker run --name "$missing_key_container" --env MCP_BEARER_TOKEN "$image" 2>&1) || exit_code=$?
if [[ $exit_code -eq 2 && $log == *GEMINI_API_KEY* ]]; then
  echo "ok: missing GEMINI_API_KEY exits with code 2 and names the variable"
else
  echo "container log: $log" >&2
  fail "missing GEMINI_API_KEY exits with code 2 and names the variable (exit code $exit_code)"
fi

# Check 3: a start with a read-only root filesystem serves /health/ready.
docker run --detach --name "$server_container" --read-only \
  --publish "127.0.0.1:$port:8000" \
  --env GEMINI_API_KEY --env MCP_BEARER_TOKEN "$image" >/dev/null ||
  fail "read-only container starts"
ready=false
for ((waited = 0; waited < start_timeout; waited++)); do
  status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 2 \
    "http://127.0.0.1:$port/health/ready" || true)
  if [[ $status == 200 ]]; then
    ready=true
    break
  fi
  sleep 1
done
if [[ $ready == true ]]; then
  echo "ok: read-only start answers /health/ready with 200"
else
  fail "read-only start answers /health/ready with 200 (last status ${status:-none})"
fi

# Check 4: /mcp without a token is rejected.
status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 10 \
  --request POST --header 'Content-Type: application/json' \
  --header 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-test","version":"0"}}}' \
  "http://127.0.0.1:$port/mcp" || true)
if [[ $status == 401 ]]; then
  echo "ok: /mcp without a token answers 401"
else
  fail "/mcp without a token answers 401 (status ${status:-none})"
fi
