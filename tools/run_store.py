"""
run_store.py — write a benchmark run to disk so it outlives the terminal.

A sweep is hours of wall time and, on a paid backend, real money. Printing it
to a scrollback that a closed window destroys is not a result. Worse, the plan
is to run the models ONCE and publish the output permanently, so a run record
has to be self-describing: months later, "gemma3 scored 0.90" is worth nothing
unless the file also says which seeds, which settings, which manifest and which
commit produced it.

Layout:
    runs/<date>-<model>/run.json    one record per run, provenance included
    runs/index.json                 the list the showcase and stats read

Both are tracked in git. They are summaries -- the bulky per-turn replays are
published separately.

Redaction: a record stores the *name* of the API-key environment variable and
never its value, and --base-url is scrubbed of userinfo, query string and
key-shaped path segments, because some providers carry the key in the URL. The
key itself is never read here.
"""

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
SCHEMA_VERSION = "1"

# Everything that changes what the model was asked to do. All of it goes in the
# record: a setting nobody wrote down is a setting nobody can reproduce, and
# the protocol is frozen precisely so these do not drift between models.
_PROTOCOL_KEYS = (
    "max_steps", "history", "skip_idle", "temperature", "max_tokens",
    "effort", "thinking", "ollama_think", "retries", "rng_seed",
)

# Prefixes real providers use. Matched only for redaction inside URLs, and by
# tests/test_no_secrets.py against the tracked tree.
SECRET_PREFIXES = (
    "sk-", "sk_", "AIza", "ghp_", "gho_", "github_pat_", "xoxb-", "xoxp-",
    "AKIA", "hf_", "gsk_", "r8_", "pplx-",
)
_PROVIDER_KEY = re.compile(
    r"(?:" + "|".join(re.escape(p) for p in SECRET_PREFIXES) + r")[A-Za-z0-9_\-]{12,}"
)
# Anything long and opaque, for the one place it is safe to be aggressive: a
# URL path segment. Applied to file contents it would flag every sha256 in
# every record, so the tree scan uses the prefix rule alone.
_KEY_SHAPED = re.compile(_PROVIDER_KEY.pattern + r"|[A-Za-z0-9_\-]{40,}")


# ── Redaction ─────────────────────────────────────────────────────────────────

def looks_like_a_key(text: str) -> bool:
    return bool(_KEY_SHAPED.fullmatch(text.strip()))


def find_provider_keys(text: str) -> list[str]:
    """Credentials pasted where they do not belong. Prefix-matched, so a hash
    or a minified bundle does not read as a leak."""
    return _PROVIDER_KEY.findall(text)


def redact_url(url: str | None) -> str | None:
    """
    Keep what identifies the endpoint, drop what could carry a credential.

    The path survives because it is the provenance -- `/v1beta/openai` is how a
    reader knows Gemini was reached through its OpenAI-compatible layer -- but
    any single segment long enough to be a key is replaced, as are userinfo and
    the whole query string.
    """
    if not url:
        return url
    parts = urlsplit(url)
    host = parts.hostname or ""
    netloc = f"{host}:{parts.port}" if parts.port else host
    path = "/".join(
        "[redacted]" if looks_like_a_key(segment) else segment
        for segment in parts.path.split("/")
    )
    return urlunsplit(
        (parts.scheme, netloc, path, "[redacted]" if parts.query else "", "")
    )


# ── Provenance ────────────────────────────────────────────────────────────────

def git_provenance(root: Path = ROOT) -> dict:
    """
    The commit the run was made from, and whether the tree was clean. A dirty
    tree does not invalidate a run, but a reader deserves to know the SHA does
    not fully describe the code that produced it.
    """
    def git(*args):
        try:
            out = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"sha": git("rev-parse", "HEAD"), "dirty": None if status is None else bool(status)}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_slug(model: str) -> str:
    """`ollama/llama3.2:3b` -> `ollama-llama3-2-3b`, safe as a directory name."""
    return re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-") or "run"


def allocate_run_id(model: str, runs_dir: Path = RUNS_DIR,
                    when: datetime | None = None) -> str:
    """
    `<date>-<model>`, suffixed on collision. Two runs of the same model on one
    day is a normal thing to do -- a re-run after a crash, or a settings change
    -- and neither may quietly overwrite the other.
    """
    when = when or datetime.now(timezone.utc)
    base = f"{when:%Y-%m-%d}-{run_slug(model)}"
    candidate, index = base, 1
    while (runs_dir / candidate).exists():
        index += 1
        candidate = f"{base}-{index}"
    return candidate


# ── The record ────────────────────────────────────────────────────────────────

def build_run_record(
    *, run_id, args, agent_description, system_prompt, manifest, manifest_text,
    seeds, episodes, budget, metrics, outcomes, health, wall_time,
    stopped=None, when=None,
) -> dict:
    """
    Assemble everything needed to read this run back cold: what was run, how,
    against which environment, and what came out.
    """
    when = when or datetime.now(timezone.utc)
    backend, _, model = args.model.partition("/")
    uses_key = backend == "openai"

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "recorded_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": {
            "id": args.model,
            "backend": backend,
            "name": model,
            "description": agent_description,
            # The name of the variable, never its value. Local backends need no
            # key at all, and this stays null for them.
            "api_key_env": args.api_key_env if uses_key else None,
            "base_url": redact_url(args.base_url) if uses_key else None,
            "host": args.ollama_host if backend == "ollama" else None,
        },
        "environment": {
            "domain_id": manifest["id"],
            "domain_name": manifest["name"],
            "binding_vow_version": manifest["binding_vow"]["version"],
            "primary_metric": manifest["scoring"]["primary_metric"],
            "manifest_sha256": _sha256(manifest_text),
            "git": git_provenance(),
        },
        "protocol": {
            "seeds": list(seeds),
            "episodes_requested": len(seeds),
            **{key: getattr(args, key, None) for key in _PROTOCOL_KEYS},
            # Embedded in full, deliberately. It is the one input identical on
            # every call of every episode, and publishing it is better science
            # than describing it.
            "system_prompt": system_prompt,
            "system_prompt_sha256": _sha256(system_prompt),
        },
        "result": {
            "episodes_completed": len(episodes),
            "stopped": stopped,
            "wall_time_seconds": round(wall_time, 1),
            "metrics": metrics,
            "outcomes": outcomes,
            "action_health": health,
            "usage": {
                "calls": budget.calls,
                "tokens_in": budget.tokens_in,
                "tokens_out": budget.tokens_out,
                "tokens_cached": budget.tokens_cached,
                "days_auto_passed": budget.skipped,
                # Only meaningful where prices are known: a local model has no
                # cost and an unpriced one has no estimate, and 0.0 would read
                # as "free" for both.
                "estimated_cost_usd": round(budget.cost, 4) if budget.priced else None,
            },
        },
        # Per-episode detail, minus the turn-by-turn replay: enough for the
        # paired per-seed statistics, small enough to commit.
        "episodes": [
            {
                "seed": ep["seed"],
                "rng_seed": ep["rng_seed"],
                "steps": ep["steps"],
                "done": ep["done"],
                "truncated": ep["truncated"],
                "wall_time_seconds": ep.get("wall_time_seconds"),
                "usage": ep.get("usage"),
                "action_health": ep["health"],
                "terminal_info": ep["score"],
            }
            for ep in episodes
        ],
    }


def save_run(record: dict, runs_dir: Path = RUNS_DIR) -> Path:
    path = runs_dir / record["run_id"] / "run.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def index_entry(record: dict, run_path: Path, runs_dir: Path) -> dict:
    """The summary the showcase's model picker and the stats script read."""
    result = record["result"]
    return {
        "run_id": record["run_id"],
        "path": run_path.relative_to(runs_dir).as_posix(),
        "recorded_at": record["recorded_at"],
        "model": record["model"]["id"],
        "backend": record["model"]["backend"],
        "episodes": result["episodes_completed"],
        "primary_metric": record["environment"]["primary_metric"],
        "metrics": result["metrics"],
        "outcomes": result["outcomes"],
        # Carried into the index deliberately: a reader comparing two models
        # needs to see that one of them made 36 illegal moves at the same
        # moment they see its score, not a click away.
        "action_health": result["action_health"],
        "wall_time_seconds": result["wall_time_seconds"],
        "git_sha": record["environment"]["git"]["sha"],
    }


def append_to_index(record: dict, run_path: Path, runs_dir: Path = RUNS_DIR) -> Path:
    """
    Add (or replace) this run's entry. Replacing by `run_id` keeps a re-save
    idempotent, and replacing it *in place* keeps the list in the order the
    runs were made and the git diff down to the entry that changed. A corrupt
    index is moved aside rather than silently discarded, since it is the only
    list of what has been run.
    """
    index_path = runs_dir / "index.json"
    doc = {"schema_version": SCHEMA_VERSION, "runs": []}
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded.get("runs"), list):
                doc = loaded
        except (json.JSONDecodeError, AttributeError):
            index_path.replace(index_path.with_suffix(".json.corrupt"))

    entry = index_entry(record, run_path, runs_dir)
    runs = list(doc["runs"])
    for position, existing in enumerate(runs):
        if existing.get("run_id") == entry["run_id"]:
            runs[position] = entry
            break
    else:
        runs.append(entry)
    doc["schema_version"] = SCHEMA_VERSION
    doc["runs"] = runs
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return index_path
