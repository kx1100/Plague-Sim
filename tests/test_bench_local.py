"""
Tests for the local benchmark harness.

The reply parser is what decides what a model actually said, so it is the piece
worth pinning down: everything downstream of it -- the action posted to the
adapter, the score, the ranking -- is only as trustworthy as this.
"""

import pytest

from tools.bench_local import (
    Budget,
    BudgetExceeded,
    aggregate,
    build_system_prompt,
    parse_reply,
    parse_seeds,
)


# ── Reply parsing ─────────────────────────────────────────────────────────────

def test_parses_the_requested_format():
    action, reasoning = parse_reply("REASON: cheap reach first\nACTION: Air1")
    assert action == "Air1"
    assert reasoning == "cheap reach first"


@pytest.mark.parametrize("word", ["null", "NULL", "none", "pass", "wait", "skip", "-"])
def test_pass_words_become_a_null_action(word):
    """
    A null action is a legitimate move, not a parse failure -- the harness must
    not turn "wait and bank DNA" into a rejected action.
    """
    action, _ = parse_reply(f"REASON: banking\nACTION: {word}")
    assert action is None


@pytest.mark.parametrize("raw", [
    "ACTION: `Air1`",
    'ACTION: "Air1"',
    "ACTION: Air1.",
    'ACTION: {"action": "Air1"}',
    "**ACTION:** Air1",
])
def test_strips_the_decoration_models_add(raw):
    action, _ = parse_reply(f"REASON: reach\n{raw}")
    assert action == "Air1"


def test_falls_back_to_the_last_line_without_an_action_label():
    """Weaker models narrate and then name the trait. Take the trait."""
    action, reasoning = parse_reply("I want more reach before symptoms.\nAir1")
    assert action == "Air1"
    assert "reach" in reasoning


def test_keeps_devolve_actions_intact():
    action, _ = parse_reply("REASON: refund\nACTION: devolve:Coughing")
    assert action == "devolve:Coughing"


def test_free_text_is_passed_through_for_the_adapter_to_match():
    """
    Normalisation lives in adapter.py and matches trait names inside free text.
    Parsing must not pre-empt it by discarding text it cannot read, or models
    get scored on format compliance the real harness forgives.
    """
    action, _ = parse_reply("lets go with cold resist")
    assert action == "lets go with cold resist"


def test_empty_reply_is_a_pass_not_a_crash():
    assert parse_reply("") == (None, "")


def test_runaway_reply_is_capped():
    action, reasoning = parse_reply("ACTION: " + "x" * 5000)
    assert len(action) <= 500
    assert len(reasoning) <= 500


# ── Spend guards ──────────────────────────────────────────────────────────────

def test_call_ceiling_stops_the_run():
    budget = Budget(max_calls=2, max_cost=0, price_in=0, price_out=0)
    budget.guard(); budget.record()
    budget.guard(); budget.record()
    with pytest.raises(BudgetExceeded):
        budget.guard()


def test_cost_ceiling_stops_the_run():
    budget = Budget(max_calls=0, max_cost=1.00, price_in=5.00, price_out=25.00)
    budget.guard()
    budget.record(tokens_in=100_000, tokens_out=30_000)   # $0.50 + $0.75
    with pytest.raises(BudgetExceeded):
        budget.guard()


def test_cost_ceiling_is_inert_without_prices():
    """An unpriced model must not be silently treated as free-and-capped."""
    budget = Budget(max_calls=0, max_cost=1.00, price_in=0, price_out=0)
    budget.record(tokens_in=10_000_000, tokens_out=10_000_000)
    budget.guard()


def test_cached_input_is_billed_at_a_tenth():
    budget = Budget(max_calls=0, max_cost=0, price_in=10.00, price_out=0)
    budget.record(tokens_in=0, cached=1_000_000)
    assert budget.cost == pytest.approx(1.00)


# ── Manifest wiring ───────────────────────────────────────────────────────────

def test_metrics_come_from_the_manifest(tmp_path):
    manifest = {
        "scoring": {
            "primary_metric": "victory_progress",
            "metrics": [
                {"name": "victory_progress", "type": "terminal_field", "field": "victory_progress"},
                {"name": "missing", "type": "terminal_field", "field": "not_reported"},
            ],
        }
    }
    episodes = [{"score": {"victory_progress": 0.5}}, {"score": {"victory_progress": 1.0}}]
    rows = dict(aggregate(manifest, episodes))
    assert rows["victory_progress"].startswith("0.7500")
    assert rows["missing"] == "n/a"


def test_incomplete_episodes_are_marked_in_the_count():
    """A budget-stopped episode must not silently dilute a mean."""
    manifest = {"scoring": {"primary_metric": "dead_pct", "metrics": [
        {"name": "dead_pct", "type": "terminal_field", "field": "dead_pct"},
    ]}}
    episodes = [{"score": {"dead_pct": 10.0}}, {"score": {"outcome": None}}]
    assert "n=1" in dict(aggregate(manifest, episodes))["dead_pct"]


def test_system_prompt_carries_the_published_rules():
    import json
    from pathlib import Path
    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "benchanything.json").read_text(encoding="utf-8")
    )
    prompt = build_system_prompt(manifest, None)
    assert manifest["action_rules"][0] in prompt
    assert "victory_progress" in prompt
    assert "ACTION:" in prompt


def test_seeds_accept_names_and_integers():
    assert parse_seeds("USA, India, 42", 3) == ["USA", "India", 42]


def test_seed_list_extends_to_cover_the_episode_count():
    assert len(parse_seeds(None, 14)) == 14
