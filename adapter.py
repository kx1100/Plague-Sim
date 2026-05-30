"""
adapter.py — HTTP server wrapper around PlagueEnv.

Usage:
    python adapter.py --port 8080

Endpoints:
    GET  /health    — liveness check
    POST /reset     — start a new episode  { "seed": <str|int|null> }
    POST /step      — advance one tick      { "action": <trait_id|null> }
    POST /close     — tear down the env
    GET  /render    — human-readable state snapshot
"""

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from env import PlagueEnv

_env = PlagueEnv()


# ── Request handler ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}", file=sys.stderr)

    # ── Routing ───────────────────────────────────────────────────────────────

    def do_GET(self):
        if self.path == "/health":
            self._send_json({"status": "ok", "ready": _env.game is not None})
        elif self.path == "/render":
            self._send_json({"render": _env.render()})
        else:
            self._send_json({"error": f"Unknown route: {self.path}"}, status=404)

    def do_POST(self):
        body = self._read_body()

        if self.path == "/reset":
            seed = body.get("seed", None)
            try:
                obs = _env.reset(seed=seed)
                self._send_json({"observation": obs})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)

        elif self.path == "/step":
            if _env.game is None:
                self._send_json({"error": "Call /reset first."}, status=400)
                return
            action = body.get("action", None)
            obs, reward, done, info = _env.step(action)
            self._send_json({
                "observation": obs,
                "reward": round(reward, 6),
                "done": done,
                "info": info,
            })

        elif self.path == "/close":
            _env.game = None
            self._send_json({"status": "closed"})

        else:
            self._send_json({"error": f"Unknown route: {self.path}"}, status=404)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _send_json(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plague simulation HTTP adapter")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    args = parser.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Plague adapter listening on http://0.0.0.0:{args.port}", file=sys.stderr)
    print("Routes: GET /health /render  |  POST /reset /step /close", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.shutdown()