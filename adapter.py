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

from data.traits import TRAITS, get_affordable_traits
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
            obs = _env.observation() if _env.game is not None else {}
            self._send_json({"render": obs})
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
            action_error = None
            if action is not None:
                evolved = _env.game.disease.evolved
                affordable = get_affordable_traits(evolved, _env.game.dna)
                # Normalise natural-language output from weak models.
                # Matching against affordable only means already-evolved tiers
                # are skipped and the next available tier is returned instead.
                normalised = self._fuzzy_trait(action, affordable)
                if normalised and normalised != action:
                    action = normalised
                if action in evolved:
                    action_error = f"'{action}' is already evolved."
                    action = None
                elif action not in TRAITS:
                    action_error = f"'{action}' is not a valid trait ID."
                    action = None
                elif action not in affordable:
                    action_error = f"'{action}' is not available (prereqs unmet or insufficient DNA)."
                    action = None
            obs, reward, done, info = _env.step(action)
            if action_error:
                info["action_error"] = action_error
                info["available_traits"] = list(get_affordable_traits(
                    _env.game.disease.evolved, _env.game.dna
                ).keys())
            response = {
                "observation": obs,
                "reward": round(reward, 6),
                "done": done,
                "info": info,
            }
            if done:
                for key in ("plague_score", "affected_pct", "dead_pct",
                            "days_to_infect_50pct", "outcome", "day"):
                    if key in info:
                        response[key] = info[key]
            self._send_json(response)

        elif self.path == "/close":
            _env.game = None
            self._send_json({"status": "closed"})

        else:
            self._send_json({"error": f"Unknown route: {self.path}"}, status=404)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _fuzzy_trait(raw: str, affordable: dict) -> str | None:
        """
        Try to extract a trait ID from a natural-language action string,
        matching only against affordable (unevolved + affordable) traits so that
        already-evolved traits are never returned.

        Matching passes (most → least strict):
          1. Exact trait ID present in affordable
          2. Trait ID appears as substring (case-insensitive)
          3. Trait ID stem (digits stripped) appears in raw alpha chars
             e.g. "cold_resist" → ColdResist2 if ColdResist1 is already evolved
          4. Trait name (alpha only) appears in raw alpha chars
        """
        if raw in affordable:
            return raw
        raw_alpha = "".join(c for c in raw.lower() if c.isalpha())
        raw_lower = raw.lower()

        for tid in affordable:
            if tid.lower() in raw_lower:
                return tid

        for tid in affordable:
            stem = tid.lower().rstrip("0123456789")
            if len(stem) >= 4 and stem in raw_alpha:
                return tid

        for tid in affordable:
            name_alpha = "".join(c for c in TRAITS[tid]["name"].lower() if c.isalpha())
            if len(name_alpha) >= 4 and name_alpha in raw_alpha:
                return tid

        return None

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