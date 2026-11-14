"""Fake MCP backend for the proxy test (scripts/ci/proxy-test.sh, ADR 0011).

Test helper only: it runs in its own digest-pinned Python image declared in
``scripts/ci/proxy-stub/compose.yaml`` and never inside the server image. It
uses the Python standard library only and never contacts Gemini.

Contract:

- Listens on ``0.0.0.0:8000`` (the port Caddy proxies to as ``server:8000``).
- ``GET /health`` answers HTTP 200 with an empty body; used by the compose
  health check so ``docker compose up --wait`` returns once it serves.
- ``POST /mcp`` reads the JSON-RPC request body and selects the response
  mode from the ``Accept`` request header:

  - JSON mode, the way the real server answers revision 2026-07-28 requests:
    when ``Accept`` contains ``application/json`` (e.g. the client default
    ``application/json, text/event-stream``). The stub first waits
    ``PROXY_STUB_DELAY_SECONDS`` seconds without sending anything, not even
    the status line or a header, then answers HTTP 200 with
    ``Content-Type: application/json``, a ``Content-Length`` and the result
    object below as the body. This exercises the proxy's response header
    timeout and its read timeout.
  - SSE mode: when ``Accept`` contains ``text/event-stream`` but not
    ``application/json``. The stub answers HTTP 200 with
    ``Content-Type: text/event-stream`` at once, immediately sends and
    flushes the SSE comment line ``: waiting``, waits
    ``PROXY_STUB_DELAY_SECONDS`` seconds, sends one event ``event: message``
    whose ``data`` is the result object below, and closes the stream. This
    exercises the proxy's read timeout on an open stream and its buffering.
  - Any other ``Accept`` value answers HTTP 406 with an empty body.

  The result object is ``{"jsonrpc": "2.0", "id": <request id>, "result":
  {"received_headers": {"MCP-Protocol-Version": ..., "Mcp-Method": ...,
  "Mcp-Name": ...}}}``. Each header value is exactly the value received, or
  ``null`` when the header is missing. Concurrent requests are served in
  parallel.
- Any other method or path answers HTTP 404.

Environment:

- ``PROXY_STUB_DELAY_SECONDS``: required, a positive integer.

Exit behavior: a missing or invalid ``PROXY_STUB_DELAY_SECONDS`` prints the
variable name to stderr and exits with code 2 before opening the port.
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HOST = "0.0.0.0"  # noqa: S104 - the stub runs in its own container behind Caddy
_PORT = 8000
_HEADERS = ("MCP-Protocol-Version", "Mcp-Method", "Mcp-Name")
_DELAY_VARIABLE = "PROXY_STUB_DELAY_SECONDS"


def _read_delay() -> int:
    """Return the delay from the environment or exit with code 2."""
    raw = os.environ.get(_DELAY_VARIABLE, "")
    if not (raw.isascii() and raw.isdigit() and int(raw) > 0):
        print(f"{_DELAY_VARIABLE}: must be a positive integer", file=sys.stderr)
        raise SystemExit(2)
    return int(raw)


def _make_handler(delay_seconds: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _not_found(self) -> None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:
            if self.path != "/health":
                self._not_found()
                return
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self) -> None:
            if self.path != "/mcp":
                self._not_found()
                return
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            try:
                request_id = json.loads(body).get("id")
            except ValueError, AttributeError:
                request_id = None
            received = {name: self.headers.get(name) for name in _HEADERS}
            result = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"received_headers": received},
            }
            payload = json.dumps(result, separators=(",", ":"))
            accept = (self.headers.get("Accept") or "").lower()

            if "application/json" in accept:
                self._answer_json(payload)
            elif "text/event-stream" in accept:
                self._answer_sse(payload)
            else:
                self.send_response(406)
                self.send_header("Content-Length", "0")
                self.end_headers()

        def _answer_json(self, payload: str) -> None:
            # Nothing is sent, not even the status line, until the delay is over.
            time.sleep(delay_seconds)
            data = payload.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _answer_sse(self, payload: str) -> None:
            # No Content-Length: the stream ends when the connection closes.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b": waiting\n\n")
            self.wfile.flush()
            time.sleep(delay_seconds)
            self.wfile.write(f"event: message\ndata: {payload}\n\n".encode())
            self.wfile.flush()
            self.close_connection = True

        do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = _not_found

    return Handler


def main() -> None:
    """Start the fake backend and serve until the process is stopped."""
    delay_seconds = _read_delay()
    server = ThreadingHTTPServer((_HOST, _PORT), _make_handler(delay_seconds))
    server.serve_forever()


if __name__ == "__main__":
    main()
