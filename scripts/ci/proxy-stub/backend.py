"""Fake MCP backend for the proxy test (scripts/ci/proxy-test.sh, ADR 0011).

Test helper only: it runs in its own digest-pinned Python image declared in
``scripts/ci/proxy-stub/compose.yaml`` and never inside the server image. It
uses the Python standard library only and never contacts Gemini.

Contract:

- Listens on ``0.0.0.0:8000`` (the port Caddy proxies to as ``server:8000``).
- ``GET /health`` answers HTTP 200 with an empty body; used by the compose
  health check so ``docker compose up --wait`` returns once it serves.
- ``POST /mcp`` reads the JSON-RPC request body and answers HTTP 200 with
  ``Content-Type: text/event-stream``. It immediately sends and flushes the
  SSE comment line ``: waiting``, then waits ``PROXY_STUB_DELAY_SECONDS``
  seconds, then sends one event ``event: message`` whose ``data`` is the JSON
  object ``{"jsonrpc": "2.0", "id": <request id>, "result":
  {"received_headers": {"MCP-Protocol-Version": ..., "Mcp-Method": ...,
  "Mcp-Name": ...}}}``. Each header value is exactly the value received, or
  ``null`` when the header is missing. Then it closes the stream.
- Any other method or path answers HTTP 404.

Environment:

- ``PROXY_STUB_DELAY_SECONDS``: required, a positive integer.

Exit behavior: a missing or invalid ``PROXY_STUB_DELAY_SECONDS`` prints the
variable name to stderr and exits with code 2 before opening the port.
"""


def main() -> None:
    """Start the fake backend and serve until the process is stopped."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
