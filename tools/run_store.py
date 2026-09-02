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

# Judgements a person adds to an index entry after the run: which run a later
# one replaces, and why. The harness never writes them -- it cannot know -- so
# a re-save must carry them across rather than flatten them back to the
# measured facts. `superseded_by` is the one that matters: a run kept as
# evidence of a defect must not be read as a citable score, and deleting it
# instead would destroy the evidence.
CURATED_KEYS = ("superseded_by", "note")

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

def git_provenance(root: Path = ROOT, ignore: Path | None = None) -> dict:
    """
    The commit the run was made from, and whether the tree was clean. A dirty
    tree does not invalidate a run, but a reader deserves to know the SHA does
    not fully describe the code that produced it.

    `ignore` is the run output directory, and excluding it is the whole reason
    this takes an argument: `runs/` is untracked until someone commits it, so a
    run that writes there would see its own output and report the tree dirty.
    Every record in a sweep would carry a false alarm, and a flag that is always
    true tells a reader nothing.
    """
    def git(*args):
        try:
            out = subprocess.run(
                ["git", *args], cwd=root, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    status_args = ["status", "--porcelain"]
    if ignore is not None:
        try:
            relative = ignore.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            relative = None          # a --runs-dir outside the repo cannot dirty it
        if relative:
            status_args += ["--", ".", f":(exclude){relative}"]

    status = git(*status_args)
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
    model_provenance=None, stopped=None, when=None, runs_dir=None,
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
            # What the tag actually resolved to. `ollama/llama3.2` is a moving
            # target; the digest and parameter count are not.
            "details": model_provenance or {},
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
            "git": git_provenance(ignore=runs_dir or RUNS_DIR),
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
                # The strings, not just the tally. A record that says 42% were
                # rejected without saying what they were cannot be acted on.
                "rejections": ep.get("rejections") or [],
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


def display_label(model: dict) -> str:
    """
    What to call this model on screen.

    `model.id` names the *protocol*, not the vendor: `openai/gemma-4-31b-it` is
    Google's Gemma reached through an OpenAI-compatible layer, and a picker
    showing the raw id tells a reader it was an OpenAI model. The host is the
    fact that settles it, so it goes in the label rather than a click away in
    the record. Ollama is named for the same reason in reverse -- `gemma3:4b`
    run locally and `gemma-4-31b-it` run hosted are different claims.
    """
    backend, name = model["backend"], model["name"]
    if backend == "openai":
        host = urlsplit(model.get("base_url") or "").hostname
        return f"{name} @ {host}" if host else name
    if backend == "ollama":
        return f"{name} (ollama)"
    return model["id"]


def index_entry(record: dict, run_path: Path, runs_dir: Path) -> dict:
    """The summary the showcase's model picker and the stats script read."""
    result = record["result"]
    return {
        "run_id": record["run_id"],
        "path": run_path.relative_to(runs_dir).as_posix(),
        "recorded_at": record["recorded_at"],
        "model": record["model"]["id"],
        "label": display_label(record["model"]),
        # Where the model actually answered from. Two runs of the same weights
        # in different places are not the same measurement.
        "endpoint": record["model"].get("base_url") or record["model"].get("host"),
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

    `CURATED_KEYS` survive the replacement: they are a person's judgement about
    a run, not a measurement of it, so regenerating the entry from the record
    must not quietly un-supersede a run somebody retired.
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
            carried = {k: existing[k] for k in CURATED_KEYS if k in existing}
            runs[position] = {**entry, **carried}
            break
    else:
        runs.append(entry)
    doc["schema_version"] = SCHEMA_VERSION
    doc["runs"] = runs
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return index_path


# ── Reading a published sweep back ────────────────────────────────────────────

def read_index(runs_dir: Path = RUNS_DIR) -> list[dict]:
    """Every recorded run, in the order it was made. Superseded ones included:
    filtering is the caller's decision, and `compare_runs.py` still has to be
    able to name one explicitly to show what a defect cost."""
    index_path = runs_dir / "index.json"
    if not index_path.exists():
        return []
    doc = json.loads(index_path.read_text(encoding="utf-8"))
    runs = doc.get("runs")
    return runs if isinstance(runs, list) else []


def load_record(entry: dict, runs_dir: Path = RUNS_DIR) -> dict:
    """The full record behind an index entry -- the per-episode detail the
    index deliberately does not carry."""
    return json.loads((runs_dir / entry["path"]).read_text(encoding="utf-8"))


def resolve(spec: str, runs_dir: Path = RUNS_DIR, entries: list[dict] | None = None) -> dict:
    """
    Find a run from what a person would type: a run id, or a model id.

    A model id resolves to that model's newest run that has not been
    superseded, because the everyday question is "how did gemma-4 do" and the
    answer must never quietly be the retired record. Naming a superseded run's
    id directly still works -- that is a deliberate act, and comparing a run
    against the one that replaced it is exactly how the cost of a defect gets
    measured.
    """
    entries = read_index(runs_dir) if entries is None else entries
    for entry in entries:
        if entry.get("run_id") == spec:
            return entry

    matches = [e for e in entries if e.get("model") == spec or e.get("label") == spec]
    if not matches:
        known = ", ".join(sorted({e.get("model", "?") for e in entries})) or "none"
        raise KeyError(f"no run matches {spec!r}. Recorded models: {known}")
    live = [e for e in matches if not e.get("superseded_by")]
    if not live:
        retired = matches[-1]
        raise KeyError(
            f"every run of {spec!r} is superseded (latest by "
            f"{retired['superseded_by']!r}). Name a run id to use it anyway."
        )
    return max(live, key=lambda e: (e.get("recorded_at") or "", e.get("run_id") or ""))
