"""
adapter.py — HTTP server wrapper around PlagueEnv.

Usage:
    python adapter.py            # -> http://localhost:8765
    python adapter.py --port N   # only if something else holds 8765

Endpoints:
    GET  /health    — liveness check
    POST /reset     — start a new episode  { "seed": <str|int|null>,
                                            "rng_seed": <int|str|null> }
    POST /step      — advance one tick      { "action": <trait_id|null> }
    POST /close     — tear down the env
    GET  /render    — human-readable state snapshot
"""

import argparse
import json
import socket
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

from data.traits import TRAITS, get_affordable_traits
from env import PlagueEnv
from simulation.actions import devolvable_traits

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
            rng_seed = body.get("rng_seed", None)
            try:
                obs = _env.reset(seed=seed, rng_seed=rng_seed)
                # Echo the seed actually used. An episode started without one
                # draws its own, and returning it is what lets a harness log a
                # run that can be replayed exactly.
                self._send_json({"observation": obs, "rng_seed": _env.rng_seed})
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=400)

        elif self.path == "/step":
            if _env.game is None:
                self._send_json({"error": "Call /reset first."}, status=400)
                return
            action = body.get("action", None)
            action, action_error = self._validate_action(action, _env.game)
            obs, reward, done, info = _env.step(action)
            if action_error:
                info["action_error"] = action_error
                info["available_traits"] = list(get_affordable_traits(
                    _env.game.disease.evolved, _env.game.dna
                ).keys())
                info["devolve_options"] = devolvable_traits(
                    _env.game.disease.evolved
                )
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
    def _validate_action(action, game) -> tuple[str | None, str | None]:
        """
        Turn a raw action string into one the env accepts, or into an error.

        Returns (action, error). A rejected action becomes None so the step
        still advances a day -- the episode never stalls on a bad output -- and
        the reason is reported back in info.action_error.
        """
        if action is None:
            return None, None

        evolved = game.disease.evolved

        if action.startswith("devolve:"):
            # Devolves used to fall through to the evolve checks below, where
            # the "devolve:" prefix made every one of them fail as "not a valid
            # trait ID" -- an action the spec documents but the adapter, the
            # only path a hosted agent has, always refused.
            trait_id = action[len("devolve:"):].strip()
            if trait_id not in TRAITS:
                return None, f"'{trait_id}' is not a valid trait ID."
            if trait_id not in evolved:
                return None, f"'{trait_id}' is not evolved, so it cannot be devolved."
            if trait_id not in devolvable_traits(evolved):
                return None, (
                    f"'{trait_id}' is a one-time-use trait and is locked in once "
                    f"bought. See observation.devolve_options."
                )
            return f"devolve:{trait_id}", None

        affordable = get_affordable_traits(evolved, game.dna)
        # Normalise natural-language output from weak models.
        # Matching against affordable only means already-evolved tiers
        # are skipped and the next available tier is returned instead.
        normalised = Handler._fuzzy_trait(action, affordable)
        if normalised and normalised != action:
            action = normalised
        if action in evolved:
            return None, f"'{action}' is already evolved."
        if action not in TRAITS:
            return None, f"'{action}' is not a valid trait ID."
        if action not in affordable:
            return None, f"'{action}' is not available (prereqs unmet or insufficient DNA)."
        return action, None

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


# ── Server ─────────────────────────────────────────────────────────────────────

class DualStackServer(HTTPServer):
    """
    Accept IPv6 and IPv4 on one socket.

    An IPv4-only server is why `localhost:8765` cost ~2 seconds per request on
    Windows: `localhost` resolves to ::1 first, that connection has to fail
    before the client retries 127.0.0.1, and a 600-step episode pays for it 600
    times -- which reads as a hung benchmark, not a slow one. Every documented
    client uses the name rather than the address (`curl localhost:8765`,
    `mesocosm doctor --local`), so the fix belongs here. `http.server` does the
    same thing for the same reason.
    """

    address_family = socket.AF_INET6

    # On Windows SO_REUSEADDR does not mean "rebind a port still in TIME_WAIT",
    # it means "bind on top of a live listener": two adapters could then hold
    # 8765 at once, each with its own PlagueEnv, with requests landing on
    # whichever the OS picked. Fail loudly there instead. On POSIX the flag
    # keeps its usual meaning and is what allows a prompt restart.
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass   # v6-only stack; IPv4 clients use 127.0.0.1 explicitly
        return super().server_bind()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plague simulation HTTP adapter")
    # 8765 is what `mesocosm doctor --local` and `mesocosm run local` probe by
    # default, and what LOCAL_DEV.md documents. The old 8080 default meant the
    # documented commands could not find a server started the documented way.
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    args = parser.parse_args()

    try:
        server = DualStackServer(("::", args.port), Handler)
    except OSError:
        # No usable IPv6 stack on this host. Clients that resolve `localhost`
        # to ::1 pay the fallback delay again, but the server still works.
        server = HTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Plague adapter listening on http://localhost:{args.port}", file=sys.stderr)
    print("Routes: GET /health /render  |  POST /reset /step /close", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", file=sys.stderr)
        server.shutdown()