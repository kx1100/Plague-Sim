"""
compare_runs.py — decide whether a sweep actually told two models apart.

Every model in this benchmark plays the *same ten seeds*, and each episode
derives its world from its own seed, so run A's `Egypt` and run B's `Egypt` are
the same game played twice. That pairing is the whole reason the sweep is worth
anything at ten episodes: seed difficulty varies far more than the models do --
`policy/random` scores 0.79 on Egypt and 0.95 on Russia -- and an unpaired
comparison spends its entire sample budget rediscovering that spread instead of
measuring the models.

The record already carries an independent 95% interval per run, which is the
right thing to print beside a single mean and the wrong thing to compare two
runs with: it asks "could these two samples have come from one population",
throwing the pairing away. On the hosted Gemma re-run the difference is
decisive -- the independent intervals overlap `policy/random`'s and the paired
test clears zero by three standard errors. Both are reported here, always, and
labelled, so the weaker reading can never be quoted as if it were the finding.

    python tools/compare_runs.py                       # everything vs policy/random
    python tools/compare_runs.py openai/gemma-4-31b-it  # one model vs the baseline
    python tools/compare_runs.py A --against B          # any two runs
    python tools/compare_runs.py A --against B --metric dead_pct
    python tools/compare_runs.py --json showcase/data/stats.json

Arguments are run ids or model ids. A model id resolves to that model's newest
run that has not been superseded; naming a superseded run's id explicitly still
works, which is how the cost of the reply-parser defect was measured.

Nothing here re-runs anything or reads the environment. It reads `runs/` and
prints; the numbers it produces are a function of committed files alone.
"""

import argparse
import json
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import run_store                              # noqa: E402
from tools.bench_local import T95, _force_utf8_output     # noqa: E402

# Fixed, and deliberately not a flag with a random default: a published
# interval that moves when you re-run the script is not a published interval.
# 20k resamples puts the Monte Carlo error on a percentile bound well below the
# fourth decimal, which is finer than anything reported.
BOOTSTRAP_RESAMPLES = 20_000
BOOTSTRAP_SEED = 0

DEFAULT_BASELINE = "policy/random"

# `victory_progress` ceilings near expert play, so it is reported with the
# metrics that still separate models up there: how much of the affected
# population died, and how fast the world was taken.
DEFAULT_METRICS = ("victory_progress", "extinction_progress", "dead_pct",
                   "days_to_infect_50pct")


# ── Statistics ────────────────────────────────────────────────────────────────

def wilson(successes: int, trials: int, z: float = 1.96) -> list[float] | None:
    """
    Interval for a proportion that survives small samples and the ends.

    Ten seeds means a win rate is 0/10, 1/10, ... and the textbook normal
    interval is nonsense there -- at 10/10 it reports [1.0, 1.0], claiming
    certainty from ten coin flips. Wilson keeps a finite width at the ends,
    which is what a reader needs from "won every seed".
    """
    if trials <= 0:
        return None
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def bootstrap_ci(values: list[float], resamples: int = BOOTSTRAP_RESAMPLES,
                 seed: int = BOOTSTRAP_SEED) -> list[float] | None:
    """
    Percentile interval on the mean difference, resampled seed-wise.

    The t interval beside it assumes the ten differences are normal. Ten of
    anything cannot demonstrate that, and these differences are bounded above
    by the distance to a ceiling the strong models are already near, so the
    distribution is skewed by construction. Where the two intervals agree, the
    conclusion does not rest on the assumption; where they disagree, that is
    itself the finding.
    """
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        sum(rng.choice(values) for _ in range(n)) / n for _ in range(resamples)
    )
    return [round(means[int(0.025 * resamples)], 6),
            round(means[int(0.975 * resamples)], 6)]


def t_interval(values: list[float]) -> list[float] | None:
    """Student's t interval on the mean, matching what the run records store so
    a difference and a mean are read on the same scale."""
    n = len(values)
    if n < 2:
        return None
    mean = statistics.mean(values)
    half = T95.get(n - 1, 1.96) * statistics.stdev(values) / math.sqrt(n)
    return [round(mean - half, 6), round(mean + half, 6)]


def excludes_zero(interval: list[float] | None) -> bool:
    return bool(interval) and (interval[0] > 0 or interval[1] < 0)


def overlaps(first: list[float] | None, second: list[float] | None) -> bool | None:
    """Whether two independent intervals touch. None when either run did not
    report one -- a single-episode run has a mean and no spread, and 'they do
    not overlap' would be a lie about it."""
    if not first or not second:
        return None
    return first[0] <= second[1] and second[0] <= first[1]


# ── Reading runs ──────────────────────────────────────────────────────────────

def metric_field(record: dict, metric: str) -> str:
    """Metric name to the terminal field it averages. They coincide today, and
    the manifest is free to rename either, so the record's own mapping wins."""
    stat = (record.get("result", {}).get("metrics") or {}).get(metric) or {}
    return stat.get("field", metric)


def per_seed(record: dict, metric: str) -> dict[str, float]:
    field = metric_field(record, metric)
    values = {}
    for episode in record.get("episodes", []):
        value = (episode.get("terminal_info") or {}).get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values[episode["seed"]] = float(value)
    return values


def paired(first: dict, second: dict, metric: str) -> tuple[list[str], list[float], list[float]]:
    """
    The seeds both runs completed *and* both scored on this metric, in the
    order the first run played them.

    Dropping a seed is not a rounding detail: `days_to_infect_50pct` is null
    for an episode that never reached half the world, which is exactly what a
    weak model does, so a metric can silently pair over six seeds when the runs
    have ten. The caller reports `n`, and it is not always ten.
    """
    a, b = per_seed(first, metric), per_seed(second, metric)
    seeds = [s for s in a if s in b]
    return seeds, [a[s] for s in seeds], [b[s] for s in seeds]


def higher_is_better(metric: str) -> bool:
    """`days_to_infect_50pct` is the one metric where less is more -- the
    manifest ranks it ascending, and a sign that reads 'B won' on a faster
    plague would invert the finding."""
    return metric != "days_to_infect_50pct"


# ── The comparison ────────────────────────────────────────────────────────────

def compare(first_entry: dict, second_entry: dict, first: dict, second: dict,
            metric: str) -> dict:
    """Everything the report prints for one metric, and everything `--json`
    hands the showcase. Computed once so the page and the terminal can never
    disagree about a published number."""
    seeds, a_values, b_values = paired(first, second, metric)
    diffs = [a - b for a, b in zip(a_values, b_values)]
    n = len(diffs)
    better = higher_is_better(metric)

    wins = sum(1 for d in diffs if (d > 0) == better and d != 0)
    decided = sum(1 for d in diffs if d != 0)

    bootstrap = bootstrap_ci(diffs)
    t_ci = t_interval(diffs)
    independent = [
        (entry.get("metrics") or {}).get(metric, {}).get("ci95")
        for entry in (first_entry, second_entry)
    ]

    paired_separates = excludes_zero(bootstrap) and excludes_zero(t_ci)
    overlap = overlaps(*independent)

    return {
        "metric": metric,
        "field": metric_field(first, metric),
        "higher_is_better": better,
        "n": n,
        "seeds": seeds,
        "values": {"a": a_values, "b": b_values, "diff": [round(d, 6) for d in diffs]},
        "mean": {
            "a": round(statistics.mean(a_values), 6) if n else None,
            "b": round(statistics.mean(b_values), 6) if n else None,
            "diff": round(statistics.mean(diffs), 6) if n else None,
        },
        "sd_diff": round(statistics.stdev(diffs), 6) if n > 1 else None,
        "sem_diff": round(statistics.stdev(diffs) / math.sqrt(n), 6) if n > 1 else None,
        "t_ci95": t_ci,
        "bootstrap_ci95": bootstrap,
        "bootstrap": {"resamples": BOOTSTRAP_RESAMPLES, "seed": BOOTSTRAP_SEED},
        "seeds_won": {"wins": wins, "decided": decided, "n": n,
                      "wilson95": wilson(wins, decided)},
        "independent_ci95": {"a": independent[0], "b": independent[1],
                             "overlap": overlap},
        "separated": {
            "paired": paired_separates,
            "independent": None if overlap is None else not overlap,
        },
    }


def verdict(result: dict) -> str:
    """One sentence a reader can quote. The awkward case is the real one: on
    the clean Gemma re-run the paired test separates and the independent
    intervals do not, and a report that printed only its preferred answer would
    be the same failure as publishing a mean with no interval."""
    paired_ok = result["separated"]["paired"]
    independent_ok = result["separated"]["independent"]
    if result["n"] < 2:
        return f"{result['n']} paired seeds — nothing can be concluded"
    if paired_ok and independent_ok:
        return "separated — paired test and independent intervals agree"
    if paired_ok and independent_ok is False:
        return ("separated on the paired test; independent intervals overlap. "
                "The runs share their seeds, so the paired test is the one that "
                "applies — but the weaker reading belongs in the record")
    if not paired_ok and independent_ok:
        return ("independent intervals clear each other while the paired "
                "differences do not — treat as not separated and look for a "
                "seed the two runs did not both play")
    return "not separated — the paired differences are consistent with zero"


# ── Report ────────────────────────────────────────────────────────────────────

def _signed(value: float | None, places: int = 4) -> str:
    return "n/a" if value is None else f"{value:+.{places}f}"


def _interval(interval: list[float] | None, places: int = 4, sign: bool = True) -> str:
    """Differences are signed, because the sign is the finding. An interval
    around a score is not: `[+0.8873, +0.9666]` reads as a change."""
    if not interval:
        return "n/a"
    mark = "+" if sign else ""
    return f"[{interval[0]:{mark}.{places}f}, {interval[1]:{mark}.{places}f}]"


def render(first_entry: dict, second_entry: dict, results: list[dict],
           show_seeds: bool = True) -> str:
    lines = []
    for entry, side in ((first_entry, "A"), (second_entry, "B")):
        health = (entry.get("action_health") or {}).get("rates") or {}
        rejected = health.get("rejected_rate")
        share = "" if rejected is None else f", {rejected:.1%} of moves rejected"
        lines.append(
            f"{side}  {entry.get('label') or entry['model']}\n"
            f"   {entry['run_id']} — {entry['episodes']} episodes{share}"
        )
    lines.append("")

    for result in results:
        lines.append(f"{result['metric']}  (n={result['n']} paired seeds"
                     + ("" if result["higher_is_better"] else ", lower is better") + ")")
        if show_seeds and result["n"]:
            width = max(len(s) for s in result["seeds"])
            lines.append(f"   {'seed':<{width}}  {'A':>9}  {'B':>9}  {'A-B':>9}")
            for seed, a, b, d in zip(result["seeds"], result["values"]["a"],
                                     result["values"]["b"], result["values"]["diff"]):
                lines.append(f"   {seed:<{width}}  {a:9.4f}  {b:9.4f}  {d:+9.4f}")
        mean = result["mean"]
        if result["n"]:
            lines.append(
                f"   mean       A {mean['a']:.4f}   B {mean['b']:.4f}   "
                f"difference {_signed(mean['diff'])}"
            )
            lines.append(
                f"   paired     95% CI (t) {_interval(result['t_ci95'])}   "
                f"bootstrap {_interval(result['bootstrap_ci95'])}"
            )
            won = result["seeds_won"]
            wilson95 = won["wilson95"]
            band = "n/a" if not wilson95 else f"[{wilson95[0]:.2f}, {wilson95[1]:.2f}]"
            lines.append(
                f"   seeds won  {won['wins']}/{won['decided']}   Wilson 95% {band}"
            )
            independent = result["independent_ci95"]
            state = {True: "OVERLAP", False: "no overlap", None: "n/a"}[independent["overlap"]]
            lines.append(
                f"   unpaired   A {_interval(independent['a'], sign=False)}   "
                f"B {_interval(independent['b'], sign=False)}   {state}"
            )
        lines.append(f"   verdict    {verdict(result)}")
        lines.append("")
    return "\n".join(lines)


def markdown_table(entries: list[dict], results: list[dict], baseline_entry: dict,
                   baseline_result: dict, metric: str) -> str:
    """
    The same table in GitHub markdown, so the README quotes the script instead
    of a number somebody typed once and never re-checked.
    """
    header = (f"| model | episodes | {metric} | 95% CI | vs baseline | "
              f"bootstrap 95% | seeds won | rejected |\n"
              "|---|---:|---:|---|---:|---|---:|---:|")
    rows = []
    ordered = [(baseline_entry, baseline_result)] + list(zip(entries, results))
    for entry, result in ordered:
        health = (entry.get("action_health") or {}).get("rates") or {}
        rejected = health.get("rejected_rate")
        stat = (entry.get("metrics") or {}).get(metric) or {}
        mean = stat.get("mean")
        is_baseline = result is baseline_result
        mark = "" if is_baseline else (" **\\***" if result["separated"]["paired"] else "")
        rows.append(
            f"| {entry.get('label') or entry['model']} | {entry['episodes']} | "
            f"{'n/a' if mean is None else f'{mean:.4f}'} | {_interval(stat.get('ci95'), sign=False)} | "
            + ("baseline |  |  | " if is_baseline else
               f"{_signed(result['mean']['diff'])}{mark} | "
               f"{_interval(result['bootstrap_ci95'])} | "
               f"{result['seeds_won']['wins']}/{result['seeds_won']['decided']} | ")
            + ("n/a |" if rejected is None else f"{rejected:.1%} |")
        )
    return "\n".join([header, *rows])


def summary_row(entry: dict, result: dict, width: int = 44) -> str:
    """One line per model for the table of everything against one baseline."""
    mean = result["mean"]
    mark = "*" if result["separated"]["paired"] else " "
    label = entry.get("label") or entry["model"]
    return (f"  {label:<{width}} {mean['a']:7.4f}  {_signed(mean['diff'])} "
            f"{_interval(result['bootstrap_ci95'])} {mark} "
            f"{result['seeds_won']['wins']}/{result['seeds_won']['decided']}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    # Same reason as the sweep: this report is meant to be piped into a file,
    # and it prints em dashes.
    _force_utf8_output()
    parser = argparse.ArgumentParser(
        description="Paired per-seed comparison of two recorded runs.")
    parser.add_argument("run", nargs="?",
                        help="run id or model id (default: every citable run)")
    parser.add_argument("--against", default=DEFAULT_BASELINE,
                        help=f"the run compared against (default: {DEFAULT_BASELINE})")
    parser.add_argument("--metric", action="append", dest="metrics",
                        help="metric to report; repeatable (default: the four "
                             "the sweep is read on)")
    parser.add_argument("--runs-dir", default=str(run_store.RUNS_DIR))
    parser.add_argument("--no-seeds", action="store_true",
                        help="omit the per-seed table")
    parser.add_argument("--markdown", action="store_true",
                        help="print the summary as a markdown table for the README")
    parser.add_argument("--json", help="write the comparison to this path")
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs_dir)
    entries = run_store.read_index(runs_dir)
    if not entries:
        print(f"no runs recorded in {runs_dir}", file=sys.stderr)
        return 1

    metrics = args.metrics or list(DEFAULT_METRICS)
    try:
        baseline_entry = run_store.resolve(args.against, runs_dir, entries)
        targets = ([run_store.resolve(args.run, runs_dir, entries)] if args.run else
                   [e for e in entries
                    if not e.get("superseded_by") and e["run_id"] != baseline_entry["run_id"]])
    except KeyError as error:
        print(error.args[0], file=sys.stderr)
        return 1

    baseline = run_store.load_record(baseline_entry, runs_dir)
    document = {
        "schema_version": run_store.SCHEMA_VERSION,
        "baseline": {"run_id": baseline_entry["run_id"],
                     "label": baseline_entry.get("label") or baseline_entry["model"]},
        "metrics": metrics,
        "comparisons": [],
    }

    single = len(targets) == 1 and not args.markdown
    primary_results = []
    for entry in targets:
        record = run_store.load_record(entry, runs_dir)
        results = [compare(entry, baseline_entry, record, baseline, metric)
                   for metric in metrics]
        primary_results.append(results[0])
        document["comparisons"].append({
            "run_id": entry["run_id"],
            "label": entry.get("label") or entry["model"],
            "superseded_by": entry.get("superseded_by"),
            "results": {result["metric"]: result for result in results},
        })
        if single:
            print(render(entry, baseline_entry, results, show_seeds=not args.no_seeds))

    if args.markdown:
        # The baseline compared with itself: every difference is zero and the
        # row exists to put the number the others are measured against on the
        # same page as them.
        self_result = compare(baseline_entry, baseline_entry, baseline, baseline, metrics[0])
        print(markdown_table(targets, primary_results, baseline_entry, self_result, metrics[0]))
    elif not single:
        primary = metrics[0]
        width = max(len(c["label"]) for c in document["comparisons"])
        print(f"paired against {document['baseline']['label']} "
              f"({baseline_entry['run_id']}) on {primary}\n")
        print(f"  {'model':<{width}} {'mean':>7}  {'difference':>9} "
              f"{'bootstrap 95%':^22}   won")
        for entry, comparison in zip(targets, document["comparisons"]):
            print(summary_row(entry, comparison["results"][primary], width))
        print("\n  * paired difference clears zero on both intervals")

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        print(f"\n  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
