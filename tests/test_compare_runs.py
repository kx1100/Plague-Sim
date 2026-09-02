"""
Tests for the paired comparison.

The claim this project publishes is "the benchmark separates a hosted model
from careless play", and the arithmetic behind that sentence is the one part a
reader cannot check by eye. What is pinned here is therefore not the formatting
but the reasoning: that seeds are matched by name, that a missing score is
dropped rather than silently paired against the wrong game, that the two
readings of the same data are both reported, and that the published interval
does not move between runs of the script.
"""

import json

import pytest

from tools import compare_runs, run_store


SEEDS = ["India", "China", "USA", "Brazil", "Egypt",
         "Russia", "Australia", "Madagascar", "Germany", "Indonesia"]


def make_record(scores: dict[str, float | None], metric="victory_progress") -> dict:
    """A run record cut down to what the comparison reads: the per-episode
    terminal fields, and the mapping from metric name to field."""
    return {
        "result": {"metrics": {metric: {"field": metric, "mean": 0.0}}},
        "episodes": [
            {"seed": seed, "terminal_info": {metric: value}}
            for seed, value in scores.items()
        ],
    }


def make_entry(run_id="run", label="model", ci95=None, metric="victory_progress") -> dict:
    return {
        "run_id": run_id, "model": run_id, "label": label, "episodes": 10,
        "metrics": {metric: {"mean": 0.0, "ci95": ci95}},
        "action_health": {"rates": {"rejected_rate": 0.0}},
    }


def compare(a_scores, b_scores, metric="victory_progress", a_ci=None, b_ci=None):
    return compare_runs.compare(
        make_entry("a", "A", a_ci, metric), make_entry("b", "B", b_ci, metric),
        make_record(a_scores, metric), make_record(b_scores, metric), metric,
    )


# ── Pairing ───────────────────────────────────────────────────────────────────

def test_seeds_pair_by_name_not_by_position():
    """Two runs may list their episodes in any order -- a re-run after a crash
    resumes from the middle. Pairing by position would compare India against
    Egypt and report the difference between two worlds as a model result."""
    a = dict(zip(SEEDS, [0.9] * 10))
    b = {seed: 0.5 for seed in reversed(SEEDS)}
    b["India"] = 0.1
    result = compare(a, b)

    assert result["seeds"] == SEEDS
    assert result["values"]["b"][SEEDS.index("India")] == 0.1


def test_a_seed_only_one_run_played_is_dropped_and_n_says_so():
    """A stopped run keeps its finished episodes, so comparing against one is
    normal. What must never happen is nine differences reported as ten."""
    a = dict(zip(SEEDS, [0.9] * 10))
    b = {seed: 0.8 for seed in SEEDS[:6]}
    result = compare(a, b)

    assert result["n"] == 6
    assert "Australia" not in result["seeds"]


def test_a_null_score_drops_that_pair_alone():
    """`days_to_infect_50pct` is null for an episode that never infected half
    the world -- exactly what a weak model does -- so this metric can pair over
    fewer seeds than the run has, and the report has to say so rather than
    treat the null as a zero."""
    a = {seed: 200.0 for seed in SEEDS}
    b = {seed: 250.0 for seed in SEEDS}
    b["Egypt"] = None
    result = compare(a, b, metric="days_to_infect_50pct")

    assert result["n"] == 9
    assert "Egypt" not in result["seeds"]
    assert all(isinstance(value, float) for value in result["values"]["b"])


# ── The two readings ──────────────────────────────────────────────────────────

def test_the_paired_test_separates_runs_whose_independent_intervals_overlap():
    """
    The case the hosted re-run actually produced, and the reason this script
    exists: one run beats the other on nearly every seed by a consistent
    margin, while both runs vary so much across seeds that their independent
    intervals overlap. Reported as one number, the answer flips depending on
    which test is quoted -- so both are computed and the verdict names them.
    """
    a = {seed: value for seed, value in zip(SEEDS, [0.60, 0.70, 0.80, 0.90, 1.00,
                                                    0.65, 0.75, 0.85, 0.95, 0.70])}
    b = {seed: value - 0.05 for seed, value in a.items()}
    result = compare(a, b, a_ci=[0.70, 0.90], b_ci=[0.65, 0.85])

    assert result["separated"]["paired"] is True
    assert result["separated"]["independent"] is False
    assert result["independent_ci95"]["overlap"] is True
    assert "paired test" in compare_runs.verdict(result)
    assert "overlap" in compare_runs.verdict(result)


def test_identical_runs_are_not_separated():
    scores = dict(zip(SEEDS, [0.5 + i / 100 for i in range(10)]))
    result = compare(scores, dict(scores))

    assert result["mean"]["diff"] == 0.0
    assert result["separated"]["paired"] is False
    assert "not separated" in compare_runs.verdict(result)


def test_a_tie_on_a_seed_counts_as_neither_a_win_nor_a_loss():
    """Two runs reaching the same day on a seed have not been told apart on it,
    and folding that into the win rate as a loss would understate the model
    while pretending the sample is bigger than it is."""
    a = dict(zip(SEEDS, [0.9] * 10))
    b = dict(zip(SEEDS, [0.8] * 9 + [0.9]))
    result = compare(a, b)

    assert result["seeds_won"] == {
        "wins": 9, "decided": 9, "n": 10,
        "wilson95": compare_runs.wilson(9, 9),
    }


def test_a_faster_plague_wins_on_the_metric_where_lower_is_better():
    """`days_to_infect_50pct` is ranked ascending by the manifest. A sign
    convention taken from the other metrics would report the faster run as the
    loser -- inverting the finding while looking perfectly plausible."""
    a = {seed: 200.0 for seed in SEEDS}
    b = {seed: 250.0 for seed in SEEDS}
    result = compare(a, b, metric="days_to_infect_50pct")

    assert result["higher_is_better"] is False
    assert result["mean"]["diff"] == -50.0
    assert result["seeds_won"]["wins"] == 10


# ── Reproducibility ───────────────────────────────────────────────────────────

def test_the_bootstrap_interval_does_not_move_between_runs():
    """A published interval that changes when the script is re-run is not a
    published interval. The resample seed is fixed for exactly this."""
    values = [0.1, -0.05, 0.2, 0.0, 0.15, 0.3, -0.1, 0.05, 0.25, 0.12]
    assert compare_runs.bootstrap_ci(values) == compare_runs.bootstrap_ci(values)


def test_wilson_keeps_a_finite_width_when_a_model_wins_every_seed():
    """Ten wins out of ten is not certainty, and the normal interval would say
    it was."""
    low, high = compare_runs.wilson(10, 10)
    assert high == 1.0
    assert 0.5 < low < 0.8


def test_one_episode_supports_no_conclusion():
    result = compare({"India": 0.9}, {"India": 0.5})
    assert result["bootstrap_ci95"] is None
    assert result["separated"]["paired"] is False
    assert "nothing can be concluded" in compare_runs.verdict(result)


def test_an_interval_that_is_missing_is_not_an_interval_that_agrees():
    """A single-episode run has a mean and no spread. 'The intervals do not
    overlap' would be a claim about a comparison that was never made."""
    result = compare(dict(zip(SEEDS, [0.9] * 10)), dict(zip(SEEDS, [0.5] * 10)),
                     a_ci=None, b_ci=[0.4, 0.6])
    assert result["independent_ci95"]["overlap"] is None
    assert result["separated"]["independent"] is None


# ── Against the committed sweep ───────────────────────────────────────────────

@pytest.mark.skipif(not (run_store.RUNS_DIR / "index.json").exists(),
                    reason="no recorded sweep in this tree")
def test_the_published_hosted_result_is_what_the_record_supports():
    """
    The headline claim, asserted against the committed records rather than
    against a fixture: the hosted model beats `random` on the paired test by a
    margin whose interval clears zero, while the independent intervals overlap.
    If a future edit to `runs/` moves either, the sentence in the README and
    PLAN.md has stopped being true and this fails.
    """
    entries = run_store.read_index()
    gemma = run_store.resolve("openai/gemma-4-31b-it", entries=entries)
    random_policy = run_store.resolve("policy/random", entries=entries)
    result = compare_runs.compare(
        gemma, random_policy,
        run_store.load_record(gemma), run_store.load_record(random_policy),
        "victory_progress",
    )

    assert gemma["run_id"] == "2026-09-02-openai-gemma-4-31b-it"   # not the superseded one
    assert result["n"] == 10
    assert result["mean"]["diff"] == pytest.approx(0.0651, abs=5e-4)
    assert result["bootstrap_ci95"][0] > 0
    assert result["t_ci95"][0] > 0
    assert result["independent_ci95"]["overlap"] is True
    assert result["seeds_won"]["wins"] == 8


@pytest.mark.skipif(not (run_store.RUNS_DIR / "index.json").exists(),
                    reason="no recorded sweep in this tree")
def test_the_local_models_were_never_separated_from_careless_play():
    """The other half of the finding, and the one that keeps the first honest:
    the same test run against the 4B local model reports no separation."""
    entries = run_store.read_index()
    gemma3 = run_store.resolve("ollama/gemma3:4b", entries=entries)
    random_policy = run_store.resolve("policy/random", entries=entries)
    result = compare_runs.compare(
        gemma3, random_policy,
        run_store.load_record(gemma3), run_store.load_record(random_policy),
        "victory_progress",
    )

    assert result["separated"]["paired"] is False
    assert result["bootstrap_ci95"][0] < 0 < result["bootstrap_ci95"][1]


def test_the_json_export_carries_the_numbers_the_page_would_render(tmp_path):
    """Commit 18 renders these into the showcase. The page must read the same
    document the terminal printed, not recompute anything of its own."""
    out = tmp_path / "stats.json"
    assert compare_runs.main([
        "openai/gemma-4-31b-it", "--no-seeds", "--json", str(out),
    ]) == 0

    document = json.loads(out.read_text(encoding="utf-8"))
    comparison = document["comparisons"][0]
    assert document["baseline"]["run_id"] == "2026-08-26-policy-random"
    assert comparison["results"]["victory_progress"]["bootstrap_ci95"][0] > 0
    assert comparison["results"]["dead_pct"]["seeds_won"]["wins"] == 10
