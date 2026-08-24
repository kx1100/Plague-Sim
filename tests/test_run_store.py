"""
Tests for the run record.

A run is written once and published forever, so the properties worth pinning
are the ones a reader cannot check later: that the provenance is actually
there, that a re-run cannot silently overwrite an earlier one, and that no
credential rides along.
"""

import json
from argparse import Namespace
from datetime import datetime, timezone

import pytest

from tools.bench_local import Budget, metric_means, outcome_counts, health_totals
from tools import run_store


WHEN = datetime(2026, 8, 23, 21, 5, 0, tzinfo=timezone.utc)

MANIFEST = {
    "id": "plague-sim",
    "name": "Plague Sim",
    "binding_vow": {"version": "1.0.0"},
    "scoring": {
        "primary_metric": "victory_progress",
        "metrics": [
            {"name": "victory_progress", "type": "terminal_field", "field": "victory_progress"},
            {"name": "dead_pct", "type": "terminal_field", "field": "dead_pct"},
        ],
    },
}


def make_args(**overrides):
    args = Namespace(
        model="ollama/llama3.2",
        max_steps=600, history=8, skip_idle=True, temperature=0.0,
        max_tokens=1024, effort="medium", thinking="adaptive",
        ollama_think="auto", retries=2, rng_seed=None,
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        ollama_host="http://localhost:11434",
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def make_episode(seed="India", **overrides):
    episode = {
        "seed": seed, "rng_seed": seed, "steps": 42, "done": True, "truncated": None,
        "wall_time_seconds": 208.4,
        "usage": {"calls": 41, "tokens_in": 65000, "tokens_out": 820, "tokens_cached": 0},
        "health": dict(accepted=38, rejected_unknown=0, rejected_illegal=3,
                       passed=0, auto_passed=1, unparsed=0),
        "score": {"outcome": "cured", "day": 298, "victory_progress": 0.9116,
                  "dead_pct": 25.67},
        "turns": [],
    }
    episode.update(overrides)
    return episode


def build(args=None, episodes=None, budget=None, runs_dir=None, **overrides):
    args = args or make_args()
    episodes = episodes if episodes is not None else [make_episode()]
    budget = budget or Budget(max_calls=0, max_cost=0, price_in=0, price_out=0)
    kwargs = dict(
        run_id=run_store.allocate_run_id(args.model, runs_dir or run_store.RUNS_DIR, WHEN),
        args=args,
        agent_description="ollama/llama3.2 at http://localhost:11434",
        system_prompt="You are the agent in the 'Plague Sim' benchmark environment.",
        manifest=MANIFEST,
        manifest_text=json.dumps(MANIFEST),
        seeds=[ep["seed"] for ep in episodes],
        episodes=episodes,
        budget=budget,
        metrics=metric_means(MANIFEST, episodes),
        outcomes=outcome_counts(episodes),
        health=health_totals(episodes),
        wall_time=625.0,
        when=WHEN,
    )
    kwargs.update(overrides)
    return run_store.build_run_record(**kwargs)


# ── Provenance ────────────────────────────────────────────────────────────────

def test_the_record_carries_every_protocol_setting():
    """
    A setting that is not written down is a setting nobody can reproduce, and
    the whole point of freezing the protocol is that it is identical between
    models. Missing one here is how two runs stop being comparable.
    """
    protocol = build()["protocol"]
    for key in ("seeds", "max_steps", "history", "skip_idle", "temperature",
                "max_tokens", "effort", "thinking", "ollama_think", "retries"):
        assert key in protocol, f"{key} missing from the run record"
    assert protocol["skip_idle"] is True
    assert protocol["temperature"] == 0.0
    assert protocol["seeds"] == ["India"]


def test_the_record_identifies_the_environment_it_ran_against():
    environment = build()["environment"]
    assert environment["domain_id"] == "plague-sim"
    assert environment["binding_vow_version"] == "1.0.0"
    assert environment["primary_metric"] == "victory_progress"
    assert len(environment["manifest_sha256"]) == 64
    assert "sha" in environment["git"] and "dirty" in environment["git"]


def test_the_system_prompt_is_embedded_in_full():
    """Publishing it is better science than describing it — and it is the one
    input identical on all ~600 calls of an episode."""
    protocol = build()["protocol"]
    assert protocol["system_prompt"].startswith("You are the agent")
    assert len(protocol["system_prompt_sha256"]) == 64


def test_results_and_per_episode_detail_both_survive():
    record = build(episodes=[make_episode("India"), make_episode("USA")])
    assert record["result"]["episodes_completed"] == 2
    assert record["result"]["outcomes"] == {"cured": 2}
    assert record["result"]["metrics"]["victory_progress"]["mean"] == pytest.approx(0.9116)
    assert record["result"]["action_health"]["rejected_illegal"] == 6
    assert [ep["seed"] for ep in record["episodes"]] == ["India", "USA"]
    assert record["episodes"][0]["wall_time_seconds"] == 208.4
    assert record["episodes"][0]["usage"]["tokens_out"] == 820


def test_a_stopped_run_says_so():
    record = build(stopped="budget")
    assert record["result"]["stopped"] == "budget"


def test_cost_is_null_rather_than_zero_when_prices_are_unknown():
    """A local model is free and an unpriced one is unmeasured. 0.0 would read
    as 'free' for both."""
    unpriced = build()["result"]["usage"]["estimated_cost_usd"]
    assert unpriced is None

    budget = Budget(max_calls=0, max_cost=0, price_in=5.0, price_out=25.0)
    budget.record(tokens_in=1_000_000, tokens_out=100_000)
    priced = build(budget=budget)["result"]["usage"]["estimated_cost_usd"]
    assert priced == pytest.approx(7.5)


# ── Redaction ─────────────────────────────────────────────────────────────────

def test_only_the_name_of_the_key_variable_is_stored(monkeypatch):
    secret = "sk-" + "x" * 40
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    args = make_args(model="openai/gemini-2.5-flash", api_key_env="GEMINI_API_KEY")
    record = build(args=args)

    assert record["model"]["api_key_env"] == "GEMINI_API_KEY"
    assert secret not in json.dumps(record)


def test_the_record_pins_down_what_the_tag_resolved_to():
    """
    `ollama/llama3.2` is whatever `latest` points at on the day. A run
    published permanently under a name that can be repointed is not a
    reproducible result, so the digest and the weights go in the record.
    """
    record = build(model_provenance={
        "resolved_from": "llama3.2", "parameter_size": "3.2B",
        "quantization_level": "Q4_K_M", "digest": "a80c4f17acd5",
    })
    assert record["model"]["details"]["digest"] == "a80c4f17acd5"
    assert record["model"]["details"]["parameter_size"] == "3.2B"


def test_a_backend_that_cannot_identify_itself_still_records_a_detail_block():
    """Best effort: an absent answer is an empty block, never a missing key."""
    assert build()["model"]["details"] == {}


def test_reference_policies_report_no_model_details():
    from tools.bench_local import PolicyAgent
    assert PolicyAgent("expert").provenance() == {}


def test_local_backends_record_no_key_at_all():
    record = build()
    assert record["model"]["api_key_env"] is None
    assert record["model"]["base_url"] is None
    assert record["model"]["host"] == "http://localhost:11434"


@pytest.mark.parametrize("url, expected", [
    # Google's OpenAI-compatible layer: the path is the provenance, keep it.
    ("https://generativelanguage.googleapis.com/v1beta/openai",
     "https://generativelanguage.googleapis.com/v1beta/openai"),
    # Some providers put the key in the query string, and some in a path
    # segment. Neither may reach a committed file.
    ("https://example.com/v1?key=" + "A" * 39, "https://example.com/v1?[redacted]"),
    ("https://example.com/v1/" + "k" * 45, "https://example.com/v1/[redacted]"),
    ("https://user:pw@example.com:8443/v1", "https://example.com:8443/v1"),
])
def test_base_url_is_scrubbed(url, expected):
    assert run_store.redact_url(url) == expected


def test_the_scrubbed_url_is_what_lands_in_the_record():
    args = make_args(model="openai/gpt-5", base_url="https://example.com/v1?key=" + "A" * 39)
    assert build(args=args)["model"]["base_url"] == "https://example.com/v1?[redacted]"


def test_provider_keys_are_found_and_hashes_are_not():
    assert run_store.find_provider_keys("token = 'sk-ant-" + "a" * 30 + "'")
    assert run_store.find_provider_keys("AIza" + "B" * 35)
    # A sha256 is 64 opaque characters and appears in every record.
    assert run_store.find_provider_keys("a" * 64) == []


# ── Files on disk ─────────────────────────────────────────────────────────────

def test_a_rerun_on_the_same_day_does_not_overwrite_the_first(tmp_path):
    first = run_store.allocate_run_id("ollama/llama3.2", tmp_path, WHEN)
    assert first == "2026-08-23-ollama-llama3-2"
    run_store.save_run(build(runs_dir=tmp_path, run_id=first), tmp_path)

    second = run_store.allocate_run_id("ollama/llama3.2", tmp_path, WHEN)
    assert second == "2026-08-23-ollama-llama3-2-2"


def test_run_slug_is_safe_as_a_directory_name():
    assert run_store.run_slug("ollama/qwen3:8b") == "ollama-qwen3-8b"
    assert run_store.run_slug("anthropic/claude-opus-5") == "anthropic-claude-opus-5"


def test_the_saved_record_reads_back_as_json(tmp_path):
    record = build(runs_dir=tmp_path)
    path = run_store.save_run(record, tmp_path)
    assert path == tmp_path / record["run_id"] / "run.json"
    assert json.loads(path.read_text(encoding="utf-8")) == record


def test_the_index_lists_what_a_reader_needs_to_compare_models(tmp_path):
    record = build(runs_dir=tmp_path)
    path = run_store.save_run(record, tmp_path)
    index = json.loads(
        run_store.append_to_index(record, path, tmp_path).read_text(encoding="utf-8")
    )
    entry = index["runs"][0]
    assert entry["model"] == "ollama/llama3.2"
    assert entry["path"] == f"{record['run_id']}/run.json"
    assert entry["metrics"]["victory_progress"]["mean"] == pytest.approx(0.9116)
    # Action health rides beside the score on purpose: 3 illegal moves is a
    # result about the model, and a reader must see it at the same moment.
    assert entry["action_health"]["rejected_illegal"] == 3


def test_the_index_accumulates_runs_and_replaces_a_resave(tmp_path):
    first = build(runs_dir=tmp_path)
    run_store.append_to_index(first, run_store.save_run(first, tmp_path), tmp_path)

    other = build(args=make_args(model="ollama/gemma3:4b"), runs_dir=tmp_path)
    run_store.append_to_index(other, run_store.save_run(other, tmp_path), tmp_path)

    # Saving the first one again must update its entry, not duplicate it.
    run_store.append_to_index(first, run_store.save_run(first, tmp_path), tmp_path)

    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert [entry["model"] for entry in index["runs"]] == [
        "ollama/llama3.2", "ollama/gemma3:4b",
    ]


def test_a_corrupt_index_is_moved_aside_not_discarded(tmp_path):
    (tmp_path / "index.json").write_text("{not json", encoding="utf-8")
    record = build(runs_dir=tmp_path)
    path = run_store.append_to_index(record, run_store.save_run(record, tmp_path), tmp_path)

    assert json.loads(path.read_text(encoding="utf-8"))["runs"][0]["run_id"] == record["run_id"]
    assert (tmp_path / "index.json.corrupt").read_text(encoding="utf-8") == "{not json"
