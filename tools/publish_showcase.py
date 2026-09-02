"""
publish_showcase.py — build the files the showcase reads with no server.

Two kinds of output, from two kinds of input:

  runs/index.json + runs/*/run.json   ->  showcase/replays/index.js
      every citable run's score, spread, action health and paired comparison
      against the baseline. This is the picker's data and the statistics panel's
      data, computed by tools/compare_runs.py so the page can never disagree
      with the terminal about a published number.

  showcase/data/exhibition-*.json     ->  showcase/replays/<slug>.js
      one watchable episode per model, exported by tools/bench_local.py.

**Exhibition episodes are not the scored sweep, and this file is where that
distinction is enforced.** The sweep did not capture turns -- `run.json` strips
them by design -- so a replay has to be played again, and a replay played again
is a different episode: temperature 0 constrains sampling, it does not promise
that a hosted model answers identically months later. Publishing one as "the
model's India episode from the sweep" would be a quiet fabrication. So every
exhibition carries its own terminal block, is labelled as an exhibition in the
index, and its score is never folded into the ten. What it is for is watching a
model play, which no table can show.

Every exhibition must use the same seed, fixed in advance -- otherwise the
choice of episode becomes a choice of result. This refuses to publish one that
does not, rather than trusting whoever ran it to notice.

Everything is written as `.js` assigning a global, never `.json`: browsers block
`fetch` of a local file from a `file://` page, and a visitor who downloads the
repo and double-clicks `index.html` must still see the runs.

    python tools/bench_local.py --model policy/expert --seeds India --skip-idle \
        --temperature 0 --no-save --export showcase/data/exhibition-policy-expert.json
    python tools/publish_showcase.py
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import compare_runs, run_store                 # noqa: E402
from tools.bench_local import _force_utf8_output          # noqa: E402

SHOWCASE = ROOT / "showcase"
EXPORT_DIR = SHOWCASE / "data"                # gitignored scratch: raw exports
REPLAY_DIR = SHOWCASE / "replays"             # tracked: what the page loads
EXPORT_GLOB = "exhibition-*.json"

# Fixed in advance, and deliberately not "the best episode": `India` is the
# first of the ten protocol seeds, and it happens to be one of the two seeds
# the hosted model *lost* to `policy/random` on. A featured episode chosen
# after the fact is a claim about the model dressed up as an illustration.
FEATURED_SEED = "India"

# Every 5th day. showcase/index.html reuses the last map frame whenever a turn
# omits one, so this is invisible on screen and takes an episode from ~715 KB
# to ~430 KB -- the difference between committing three replays and not.
WORLD_EVERY = 5


# ── Trimming ──────────────────────────────────────────────────────────────────

def trim_turns(turns: list[dict], every: int = WORLD_EVERY) -> tuple[list[dict], int]:
    """
    Drop what the page does not read, keep every frame it draws.

    Three savings, all loss-free. `info.world` is 71 numbers per day and the UI
    holds the last one it saw, so only every `every`-th day needs it -- plus the
    first, which has nothing to fall back to, and the last, which is the frame a
    reader stares at. `board_before` is byte-identical to `observation` in the
    export (both are the pre-action board under the same keys). And `observation`
    itself is only the UI's fallback for an export that lacks `board_after`,
    which this one never does, since `board_after` is the board the map frame
    actually describes.

    What is left is `board_after` per turn, which is irreducible: it carries the
    growing `evolved_traits` list the purchase history is built from.
    """
    kept = 0
    trimmed = []
    for index, turn in enumerate(turns):
        turn = dict(turn)
        turn.pop("board_before", None)
        if turn.get("board_after"):
            turn.pop("observation", None)
        info = dict(turn.get("info") or {})
        last = index == len(turns) - 1
        if info.get("world") is not None:
            if index == 0 or last or (index % every == 0):
                kept += 1
            else:
                info.pop("world")
        turn["info"] = info
        trimmed.append(turn)
    return trimmed, kept


def episode_for_seed(export: dict, seed: str) -> tuple[str, dict, list[dict]] | None:
    """The exported episode played on `seed`, with its id and metadata."""
    for episode in export.get("episodes") or []:
        if str(episode.get("seed")) == str(seed):
            turns = (export.get("replay") or {}).get(episode["id"]) or []
            return episode["id"], episode, turns
    return None


def replay_document(export: dict, entry: dict | None, seed: str) -> dict:
    """
    One episode in the export shape the page already knows how to render, with
    the run it belongs to named on it.
    """
    found = episode_for_seed(export, seed)
    if not found:
        played = ", ".join(str(e.get("seed")) for e in export.get("episodes") or [])
        raise SystemExit(
            f"no episode on seed {seed!r} in this export (it played: {played or 'nothing'}). "
            f"Exhibition episodes all use {FEATURED_SEED} so a viewer compares like with like."
        )
    episode_id, episode, turns = found
    if not turns:
        raise SystemExit(f"episode {episode_id} has no turns — was --export written by a stopped run?")

    trimmed, world_frames = trim_turns(turns)
    model = (export.get("run") or {}).get("config", {}).get("model")
    return {
        "schema_version": "1",
        "kind": "exhibition",
        "run_id": entry["run_id"] if entry else None,
        "model": model,
        "label": (entry or {}).get("label") or model,
        "seed": episode.get("seed"),
        "rng_seed": episode.get("rng_seed"),
        "generated_by": export.get("generated_by"),
        "world_frames": world_frames,
        "episodes": [{
            "id": episode_id,
            "seed": episode.get("seed"),
            "rng_seed": episode.get("rng_seed"),
            "action_health": episode.get("action_health"),
            "terminal_info": episode.get("terminal_info"),
        }],
        "replay": {episode_id: trimmed},
    }


# ── Writing ───────────────────────────────────────────────────────────────────

def write_global(path: Path, statement: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(statement, encoding="utf-8")
    return path.stat().st_size


def replay_js(run_key: str, document: dict) -> str:
    body = json.dumps(document, separators=(",", ":"))
    return (
        "// Generated by tools/publish_showcase.py — do not edit.\n"
        "// One exhibition episode, replayable offline. Not part of the scored sweep.\n"
        "window.PLAGUE_REPLAYS = window.PLAGUE_REPLAYS || {};\n"
        f"window.PLAGUE_REPLAYS[{json.dumps(run_key)}] = {body};\n"
    )


def index_js(document: dict) -> str:
    body = json.dumps(document, indent=1)
    return (
        "// Generated by tools/publish_showcase.py from runs/ — do not edit.\n"
        "// Scores, spread, action health and the paired comparison behind the\n"
        "// picker. The numbers are tools/compare_runs.py's, not the page's.\n"
        f"window.PLAGUE_RUNS = {body};\n"
    )


# ── The index ─────────────────────────────────────────────────────────────────

def run_summary(entry: dict, record: dict, baseline_entry: dict, baseline: dict,
                metrics: list[str], replay: tuple[str, str] | None) -> dict:
    """One model's row: what it scored, how it played, and whether the sweep
    told it apart from the baseline."""
    comparisons = {}
    if entry["run_id"] != baseline_entry["run_id"]:
        for metric in metrics:
            result = compare_runs.compare(entry, baseline_entry, record, baseline, metric)
            comparisons[metric] = {
                "diff": result["mean"]["diff"],
                "bootstrap_ci95": result["bootstrap_ci95"],
                "t_ci95": result["t_ci95"],
                "seeds_won": result["seeds_won"],
                "n": result["n"],
                "separated": result["separated"],
                "verdict": compare_runs.verdict(result),
            }
    return {
        "run_id": entry["run_id"],
        "label": entry.get("label") or entry["model"],
        "model": entry["model"],
        "backend": entry["backend"],
        "endpoint": entry.get("endpoint"),
        "recorded_at": entry["recorded_at"],
        "episodes": entry["episodes"],
        "metrics": {name: entry["metrics"].get(name) for name in metrics
                    if entry.get("metrics")},
        "outcomes": entry.get("outcomes"),
        "action_health": entry.get("action_health"),
        "wall_time_seconds": entry.get("wall_time_seconds"),
        "is_baseline": entry["run_id"] == baseline_entry["run_id"],
        "paired": comparisons,
        # None means "no exhibition episode published for this model" -- the row
        # still belongs in the table, it simply cannot be watched. The file is
        # named separately because the page loads it lazily, by injecting the
        # script tag only for the run a reader actually clicks.
        "replay": replay[0] if replay else None,
        "replay_file": replay[1] if replay else None,
    }


def build(runs_dir: Path, exports: dict[str, Path], baseline: str,
          metrics: list[str], seed: str) -> tuple[dict, list[tuple[Path, str]]]:
    entries = run_store.read_index(runs_dir)
    if not entries:
        raise SystemExit(f"no runs recorded in {runs_dir}")
    baseline_entry = run_store.resolve(baseline, runs_dir, entries)
    baseline_record = run_store.load_record(baseline_entry, runs_dir)

    citable = [e for e in entries if not e.get("superseded_by")]
    files, rows = [], []
    for entry in citable:
        slug = run_store.run_slug(entry["model"])
        export_path = exports.get(slug)
        replay = None
        if export_path:
            export = json.loads(export_path.read_text(encoding="utf-8"))
            document = replay_document(export, entry, seed)
            replay = (entry["run_id"], f"{slug}.js")
            files.append((REPLAY_DIR / replay[1], replay_js(replay[0], document)))
        record = run_store.load_record(entry, runs_dir)
        rows.append(run_summary(entry, record, baseline_entry, baseline_record,
                                metrics, replay))

    index = {
        "schema_version": run_store.SCHEMA_VERSION,
        "featured_seed": seed,
        "baseline": {"run_id": baseline_entry["run_id"],
                     "label": baseline_entry.get("label") or baseline_entry["model"]},
        "primary_metric": metrics[0],
        "metrics": metrics,
        "bootstrap": {"resamples": compare_runs.BOOTSTRAP_RESAMPLES,
                      "seed": compare_runs.BOOTSTRAP_SEED},
        # The retired runs are listed, not hidden: a reader who finds the 09-01
        # record in the repo deserves to learn from the page why it is not in
        # the table, rather than wonder whether it was quietly dropped.
        "superseded": [
            {"run_id": e["run_id"], "label": e.get("label") or e["model"],
             "superseded_by": e["superseded_by"], "note": e.get("note")}
            for e in entries if e.get("superseded_by")
        ],
        "runs": rows,
    }
    return index, files


# ── CLI ───────────────────────────────────────────────────────────────────────

def find_exports(export_dir: Path) -> dict[str, Path]:
    """`exhibition-policy-expert.json` -> the slug `policy-expert`, which is
    what `run_store.run_slug` makes of `policy/expert`."""
    return {path.stem[len("exhibition-"):]: path
            for path in sorted(export_dir.glob(EXPORT_GLOB))}


def main(argv=None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs-dir", default=str(run_store.RUNS_DIR))
    parser.add_argument("--exports", default=str(EXPORT_DIR),
                        help=f"where {EXPORT_GLOB} exports are read from")
    parser.add_argument("--out", default=str(REPLAY_DIR),
                        help="where the page's .js files are written")
    parser.add_argument("--seed", default=FEATURED_SEED,
                        help="the one seed every exhibition episode must use")
    parser.add_argument("--against", default=compare_runs.DEFAULT_BASELINE)
    parser.add_argument("--metric", action="append", dest="metrics")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    exports = find_exports(Path(args.exports))
    index, files = build(
        Path(args.runs_dir), exports, args.against,
        args.metrics or list(compare_runs.DEFAULT_METRICS), args.seed,
    )
    files = [(out_dir / path.name, text) for path, text in files]
    files.append((out_dir / "index.js", index_js(index)))

    total = 0
    for path, text in files:
        total += write_global(path, text)
        print(f"  wrote {path.relative_to(ROOT)}  ({path.stat().st_size / 1024:.0f} KB)")

    watchable = sum(1 for row in index["runs"] if row["replay"])
    print(f"\n  {len(index['runs'])} runs, {watchable} with an exhibition episode "
          f"on seed {index['featured_seed']}, {total / 1024:.0f} KB total")
    missing = [row["label"] for row in index["runs"] if not row["replay"]]
    if missing:
        print("  no exhibition episode yet: " + ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
