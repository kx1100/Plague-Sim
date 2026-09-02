"""
Tests for what the showcase publishes.

The load-bearing claim on that page is that an exhibition episode is *not* the
scored sweep: the ten seeds that produced the numbers were never recorded turn
by turn, so anything watchable was played again. If that separation slips —
a replay published on a seed nobody chose, a run quietly dropped from the table
because its episode is missing — the page starts making a claim the records do
not support. That is what is pinned here, along with the trimming, which is only
allowed to remove what the page provably does not read.
"""

import json

import pytest

from tools import publish_showcase, run_store


def turn(step, world=True):
    """One exported turn, in the shape tools/bench_local.py writes."""
    board = {"day": step, "dna": 3, "cure_progress": 0.1, "infected_pct": 1.0,
             "dead_pct": 0.0, "victory_progress": 0.01, "countries_infected": 4,
             "evolved_traits": ["Air1"]}
    return {
        "step": step,
        "observation": dict(board, day=step - 1),
        "board_before": dict(board, day=step - 1),
        "board_after": board,
        "reasoning": "spread first", "action": "Air1", "reward": 0.1,
        "terminated": False,
        "info": {"day": step, "dna": 3, "cure_progress": 0.1, "outcome": None,
                 "action_accepted": True,
                 **({"world": [[1.0, 0.0]] * 71} if world else {})},
    }


def export(seed="India", turns=12, model="policy/expert"):
    return {
        "schema_version": "1",
        "run": {"config": {"model": model}},
        "generated_by": "tools/bench_local.py",
        "episodes": [{"id": "ep1-" + str(seed), "seed": seed, "rng_seed": seed,
                      "action_health": {"accepted": turns},
                      "terminal_info": {"outcome": "cured", "victory_progress": 0.88}}],
        "replay": {"ep1-" + str(seed): [turn(i + 1) for i in range(turns)]},
    }


def make_runs_dir(tmp_path, models=("policy/random", "openai/gemma-4-31b-it"),
                  superseded=None):
    """A runs/ directory holding one record per model, with the index a real
    sweep would have left behind."""
    entries = []
    for index, model in enumerate(models):
        run_id = f"2026-09-0{index + 1}-{run_store.run_slug(model)}"
        record = {
            "run_id": run_id,
            "model": {"id": model, "backend": model.split("/")[0],
                      "name": model.split("/")[1], "base_url": None, "host": None},
            "environment": {"primary_metric": "victory_progress",
                            "git": {"sha": "abc123", "dirty": False}},
            "recorded_at": f"2026-09-0{index + 1}T00:00:00Z",
            "result": {
                "episodes_completed": 3,
                "metrics": {"victory_progress": {"field": "victory_progress",
                                                 "mean": 0.8 + index / 10,
                                                 "ci95": [0.7, 0.9]}},
                "outcomes": {"cured": 3},
                "action_health": {"accepted": 30, "rates": {"rejected_rate": 0.0}},
                "wall_time_seconds": 120.0,
            },
            "episodes": [
                {"seed": seed, "terminal_info": {"victory_progress": 0.8 + index / 10 + n / 100}}
                for n, seed in enumerate(["India", "China", "USA"])
            ],
        }
        path = tmp_path / run_id / "run.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        entry = run_store.index_entry(record, path, tmp_path)
        if superseded and model == superseded[0]:
            entry["superseded_by"] = superseded[1]
            entry["note"] = "reply parser ate its moves"
        entries.append(entry)
    (tmp_path / "index.json").write_text(
        json.dumps({"schema_version": "1", "runs": entries}), encoding="utf-8")
    return tmp_path


# ── Trimming ──────────────────────────────────────────────────────────────────

def test_the_map_keeps_the_first_the_last_and_every_fifth_frame():
    """The page holds the last frame it saw, so the dropped days render
    identically -- but the first has nothing to fall back to and the last is the
    frame a reader stares at, so neither may go."""
    turns = [turn(i + 1) for i in range(12)]
    trimmed, kept = publish_showcase.trim_turns(turns, every=5)

    has_world = [index for index, t in enumerate(trimmed) if "world" in t["info"]]
    assert has_world == [0, 5, 10, 11]
    assert kept == 4


def test_trimming_drops_only_boards_the_page_never_reads():
    """`board_before` and `observation` are the same pre-action board, and the
    UI reads `board_after`. Dropping the one the UI *would* fall back to when
    `board_after` is missing would be a different matter, so that case keeps it."""
    trimmed, _ = publish_showcase.trim_turns([turn(1)])
    assert "board_before" not in trimmed[0]
    assert "observation" not in trimmed[0]
    assert trimmed[0]["board_after"]["evolved_traits"] == ["Air1"]

    without_after = turn(2)
    without_after.pop("board_after")
    kept, _ = publish_showcase.trim_turns([without_after])
    assert "observation" in kept[0]


def test_the_reasoning_and_the_action_always_survive():
    """They are the episode: a replay that cannot show what the model said and
    did is a chart with a map next to it."""
    trimmed, _ = publish_showcase.trim_turns([turn(i + 1) for i in range(8)])
    assert all(t["reasoning"] == "spread first" for t in trimmed)
    assert all(t["action"] == "Air1" for t in trimmed)


# ── The featured seed ─────────────────────────────────────────────────────────

def test_an_exhibition_on_the_wrong_seed_is_refused():
    """Every model plays the same featured seed, chosen in advance. Let that
    slip and the choice of episode quietly becomes a choice of result."""
    with pytest.raises(SystemExit, match="Egypt"):
        publish_showcase.replay_document(export(seed="Egypt"), None, "India")


def test_an_export_with_no_turns_is_refused():
    empty = export()
    empty["replay"]["ep1-India"] = []
    with pytest.raises(SystemExit, match="no turns"):
        publish_showcase.replay_document(empty, None, "India")


def test_the_published_replay_says_it_is_an_exhibition():
    """On the page and in the file. Its terminal block is its own, and nothing
    downstream may read it as one of the scored ten."""
    document = publish_showcase.replay_document(
        export(), {"run_id": "2026-09-01-policy-expert", "label": "policy/expert"}, "India")

    assert document["kind"] == "exhibition"
    assert document["seed"] == "India"
    assert document["label"] == "policy/expert"
    assert document["episodes"][0]["terminal_info"]["outcome"] == "cured"


# ── The index ─────────────────────────────────────────────────────────────────

def test_a_run_with_no_exhibition_episode_still_appears(tmp_path):
    """Its absence is a fact about what has been published, not about the
    model, and dropping the row would read as the opposite."""
    runs_dir = make_runs_dir(tmp_path)
    index, files = publish_showcase.build(
        runs_dir, {}, "policy/random", ["victory_progress"], "India")

    assert [row["label"] for row in index["runs"]] == ["policy/random", "gemma-4-31b-it"]
    assert all(row["replay"] is None for row in index["runs"])
    assert files == []


def test_an_exhibition_export_is_matched_to_its_run(tmp_path):
    runs_dir = make_runs_dir(tmp_path)
    export_path = tmp_path / "exhibition-policy-random.json"
    export_path.write_text(json.dumps(export(model="policy/random")), encoding="utf-8")

    index, files = publish_showcase.build(
        runs_dir, {"policy-random": export_path}, "policy/random",
        ["victory_progress"], "India")

    published = index["runs"][0]
    assert published["replay"] == published["run_id"]
    assert published["replay_file"] == "policy-random.js"
    assert files and files[0][0].name == "policy-random.js"
    assert "window.PLAGUE_REPLAYS" in files[0][1]


def test_a_superseded_run_is_named_but_never_scored(tmp_path):
    """It stays in the repo as the evidence for a defect. Leaving it in the
    table would publish a score its own record disowns; leaving it out silently
    would look like the number was tidied away."""
    runs_dir = make_runs_dir(
        tmp_path, superseded=("openai/gemma-4-31b-it", "2026-09-03-openai-gemma-4-31b-it"))
    index, _ = publish_showcase.build(
        runs_dir, {}, "policy/random", ["victory_progress"], "India")

    assert [row["model"] for row in index["runs"]] == ["policy/random"]
    assert index["superseded"][0]["superseded_by"] == "2026-09-03-openai-gemma-4-31b-it"
    assert "reply parser" in index["superseded"][0]["note"]


def test_the_baseline_is_marked_and_compared_against_itself_by_nobody(tmp_path):
    runs_dir = make_runs_dir(tmp_path)
    index, _ = publish_showcase.build(
        runs_dir, {}, "policy/random", ["victory_progress"], "India")

    baseline, other = index["runs"]
    assert baseline["is_baseline"] and baseline["paired"] == {}
    assert other["paired"]["victory_progress"]["n"] == 3
    assert "verdict" in other["paired"]["victory_progress"]


def test_the_index_carries_the_bootstrap_settings_it_was_computed_with(tmp_path):
    """A published interval is only reproducible if the page says what produced
    it."""
    index, _ = publish_showcase.build(
        make_runs_dir(tmp_path), {}, "policy/random", ["victory_progress"], "India")

    assert index["bootstrap"] == {"resamples": 20000, "seed": 0}
    assert index["featured_seed"] == "India"
