"""Tests for simulation mechanics, the env lifecycle, and the HTTP adapter."""

import json
from pathlib import Path

import pytest

from adapter import Handler
from data.traits import TRAITS, get_affordable_traits
from env import PlagueEnv
from models.game_state import GameState
from simulation.actions import evolve_trait, devolve_trait
from simulation import cure
from simulation.cure import update_awareness, update_cure
from simulation.deaths import process_deaths


@pytest.fixture
def game() -> GameState:
    return GameState()


# ── Evolving ──────────────────────────────────────────────────────────────────

def test_evolve_rejects_unknown_trait(game):
    game.dna = 999
    assert evolve_trait(game, "NotATrait") is False
    assert game.dna == 999


def test_evolve_rejects_unmet_prereqs(game):
    game.dna = 999
    assert evolve_trait(game, "Air2") is False      # needs Air1
    assert "Air2" not in game.disease.evolved
    assert game.dna == 999


def test_evolve_rejects_insufficient_dna(game):
    game.dna = TRAITS["Air1"]["cost"] - 1
    assert evolve_trait(game, "Air1") is False
    assert "Air1" not in game.disease.evolved


def test_evolve_rejects_already_evolved(game):
    game.dna = 999
    assert evolve_trait(game, "Air1") is True
    dna_after_first = game.dna
    assert evolve_trait(game, "Air1") is False
    assert game.dna == dna_after_first, "re-evolving must not charge again"


def test_evolve_debits_exact_cost_once(game):
    game.dna = 100
    assert evolve_trait(game, "Air1") is True
    assert game.dna == 100 - TRAITS["Air1"]["cost"]


def test_evolve_applies_effects(game):
    game.dna = 999
    before = game.disease.infectivity
    evolve_trait(game, "Air1")
    expected = before + TRAITS["Air1"]["effects"]["infectivity"]
    assert game.disease.infectivity == pytest.approx(expected)
    assert game.disease.air_transmission == 1


def test_evolve_chain_with_prereqs(game):
    game.dna = 999
    assert evolve_trait(game, "Air1") is True
    assert evolve_trait(game, "Air2") is True
    assert game.disease.air_transmission == 2


def test_reshuffle_rolls_back_cure(game):
    game.dna = 999
    evolve_trait(game, "GeneticHardening1")
    game.cure_progress = 0.9
    evolve_trait(game, "GeneticReShuffle1")
    assert game.cure_progress == pytest.approx(0.65)


def test_reshuffle_cannot_drive_cure_negative(game):
    game.dna = 999
    evolve_trait(game, "GeneticHardening1")
    game.cure_progress = 0.1
    evolve_trait(game, "GeneticReShuffle1")
    assert game.cure_progress == 0.0


# ── Devolving ─────────────────────────────────────────────────────────────────

def test_devolve_reverses_effects_and_refunds(game):
    game.dna = 999
    evolve_trait(game, "Air1")
    infectivity_with = game.disease.infectivity
    dna_before = game.dna

    assert devolve_trait(game, "Air1") == 2
    assert "Air1" not in game.disease.evolved
    assert game.dna == dna_before + 2
    assert game.disease.infectivity < infectivity_with
    assert game.disease.infectivity == pytest.approx(1.0)
    assert game.disease.air_transmission == 0


def test_devolve_unknown_or_unevolved_is_noop(game):
    game.dna = 50
    assert devolve_trait(game, "NotATrait") == 0
    assert devolve_trait(game, "Air1") == 0          # never evolved
    assert game.dna == 50


def test_devolve_clamps_integer_stats_at_zero(game):
    game.dna = 999
    evolve_trait(game, "Air1")
    game.disease.air_transmission = 0                # desync the counter
    devolve_trait(game, "Air1")
    assert game.disease.air_transmission == 0, "int stats must never go negative"


# ── Deaths, awareness, cure ───────────────────────────────────────────────────

def test_no_deaths_without_lethality(game):
    country = game.countries["India"]
    country.infected = 1_000_000
    process_deaths(country, game.disease)
    assert country.dead == 0


def test_deaths_move_people_from_infected_to_dead(game):
    game.disease.lethality = 0.5
    country = game.countries["India"]
    country.infected = 1_000_000
    process_deaths(country, game.disease)
    assert country.dead > 0
    assert country.infected + country.dead == 1_000_000


def test_awareness_only_rises_in_infected_countries(game):
    game.countries["India"].infected = 1_000_000
    update_awareness(game)
    assert game.countries["India"].awareness > 0
    assert game.countries["Japan"].awareness == 0


def test_awareness_is_capped_at_one(game):
    for country in game.countries.values():
        country.infected = country.population // 2
        country.awareness = 0.99
    for _ in range(10):
        update_awareness(game)
    assert all(c.awareness <= 1.0 for c in game.countries.values())


def test_cure_needs_awareness(game):
    update_cure(game)
    assert game.cure_progress == 0.0


def test_cure_progresses_once_aware(game):
    for country in game.countries.values():
        country.infected = 1000
        country.awareness = 0.5
    update_cure(game)
    assert game.cure_progress > 0.0


def test_cure_is_capped_at_one(game):
    for country in game.countries.values():
        country.awareness = 1.0
    for _ in range(2000):
        update_cure(game)
    assert game.cure_progress == 1.0


def test_drug_resistance_slows_the_cure():
    baseline, resistant = GameState(), GameState()
    for state in (baseline, resistant):
        for country in state.countries.values():
            country.awareness = 0.5
    resistant.disease.drug_resist = 2
    update_cure(baseline)
    update_cure(resistant)
    assert resistant.cure_progress < baseline.cure_progress


def test_slows_cure_special_is_read_from_trait_data():
    """
    Every trait the data marks `special: "slows_cure"` must actually slow the
    cure. `cure.py` used to hardcode Insanity, which made the data key
    decorative and silent if a second such trait were ever added.
    """
    slowing = [t for t, d in TRAITS.items() if d.get("special") == "slows_cure"]
    assert slowing, "no trait carries slows_cure -- the test has lost its subject"

    for trait_id in slowing:
        baseline, slowed = GameState(), GameState()
        for state in (baseline, slowed):
            for country in state.countries.values():
                country.awareness = 0.5
        # Added straight to `evolved`; the trait's numeric effects are
        # deliberately skipped so only the special is under test.
        slowed.disease.evolved.add(trait_id)
        update_cure(baseline)
        update_cure(slowed)
        assert slowed.cure_progress < baseline.cure_progress, trait_id


def test_slows_cure_traits_stack(monkeypatch):
    """
    Two slowing traits must be worth more than one. Nothing in the tree carries
    a second `slows_cure` today, so the set is patched to prove the penalty is
    per-trait rather than a flat one-off.
    """
    monkeypatch.setattr(cure, "_SLOWS_CURE_TRAITS", frozenset({"Insanity", "Coma"}))
    one, two = GameState(), GameState()
    for state in (one, two):
        for country in state.countries.values():
            country.awareness = 0.5
    one.disease.evolved.add("Insanity")
    two.disease.evolved.update({"Insanity", "Coma"})
    update_cure(one)
    update_cure(two)
    assert two.cure_progress < one.cure_progress


# ── Termination ───────────────────────────────────────────────────────────────

def test_terminates_when_cured(game):
    game.cure_progress = 1.0
    game._check_game_over()
    assert game.game_over and game.outcome == "cured"


def test_terminates_extinct_when_over_95pct_dead(game):
    for country in game.countries.values():
        country.dead = country.population
        country.infected = 0
    game._check_game_over()
    assert game.game_over and game.outcome == "extinct"


def test_terminates_infected_all_when_nobody_healthy(game):
    for country in game.countries.values():
        country.dead = country.population // 10
        country.infected = country.population - country.dead
    game._check_game_over()
    assert game.game_over and game.outcome == "infected_all"


def test_terminates_died_out_after_day_30(game):
    game.day = 31
    game._check_game_over()
    assert game.game_over and game.outcome == "died_out"


def test_no_died_out_before_day_30(game):
    game.day = 10
    game._check_game_over()
    assert not game.game_over


# ── Env lifecycle ─────────────────────────────────────────────────────────────

def test_step_before_reset_raises():
    with pytest.raises(RuntimeError):
        PlagueEnv().step(None)


def test_reset_with_unknown_country_raises():
    with pytest.raises(ValueError):
        PlagueEnv().reset("Atlantis")


def test_reset_seeds_named_country():
    env = PlagueEnv()
    env.reset("India")
    assert env.game.countries["India"].infected > 0
    assert env.game.infected_countries() == 1


def test_integer_seed_is_reproducible():
    def run() -> tuple:
        env = PlagueEnv()
        env.reset(42)
        for _ in range(80):
            env.step(None)
        return env._seed_country, env.game.total_infected(), env.game.cure_progress

    assert run() == run()


def test_observation_shape():
    env = PlagueEnv()
    obs = env.reset("India")
    expected = {
        "day", "dna", "dna_earned", "cure_progress", "infected_pct", "dead_pct",
        "victory_progress", "countries_infected", "evolved_traits",
        "devolve_options", "available_traits", "action_hint",
    }
    assert expected <= set(obs)


def test_observation_matches_the_published_spec():
    """
    Drift guard: benchanything.json is the contract agents are written against,
    so the observation and the spec's field list must name exactly the same
    keys. Adding a key to one without the other is the bug this catches.
    """
    spec = json.loads(
        (Path(__file__).resolve().parents[1] / "benchanything.json").read_text()
    )
    documented = set(spec["binding_vow"]["observation_space"]["fields"])
    env = PlagueEnv()
    obs = env.reset("India")
    assert set(obs) == documented


def test_devolve_options_excludes_one_time_traits():
    """
    Reshuffles are locked in once bought (commit 4), so offering them as devolve
    targets would advertise an action the simulation always rejects.
    """
    env = PlagueEnv()
    env.reset("India")
    game = env.game
    game.dna = 999
    for tid in ("Air1", "GeneticHardening1", "GeneticReShuffle1"):
        assert evolve_trait(game, tid) is True

    obs = env.observation()
    assert "GeneticReShuffle1" in obs["evolved_traits"]
    assert "GeneticReShuffle1" not in obs["devolve_options"]
    assert "Air1" in obs["devolve_options"]

    # Everything offered must actually be accepted.
    for tid in obs["devolve_options"]:
        assert devolve_trait(game, tid) > 0, tid


def test_action_hint_does_not_claim_a_free_trait_when_fully_evolved():
    """
    Regression: `min(..., default=0)` reported "cheapest unevolved trait costs 0"
    once every trait was owned, telling the agent to keep shopping.
    """
    env = PlagueEnv()
    env.reset("India")
    game = env.game
    game.disease.evolved.update(TRAITS)
    game.dna = 0
    hint = env.observation()["action_hint"]
    assert "costs 0" not in hint
    assert "Every trait" in hint


def test_action_hint_lists_affordable_traits():
    env = PlagueEnv()
    obs = env.reset("India")
    assert "Air1" in obs["action_hint"]
    assert obs["action_hint"].endswith("Output exactly one of these trait IDs.")


def test_step_returns_contract():
    env = PlagueEnv()
    env.reset("India")
    obs, reward, done, info = env.step(None)
    assert isinstance(obs, dict)
    assert isinstance(reward, float)
    assert isinstance(done, bool)
    assert {"day", "dna", "cure_progress", "outcome", "action_accepted"} <= set(info)


def test_invalid_action_is_ignored_not_fatal():
    env = PlagueEnv()
    env.reset("India")
    _, _, _, info = env.step("TotallyBogus")
    assert info["action_accepted"] is False


def test_final_score_reports_terminal_fields():
    env = PlagueEnv()
    env.reset("India")
    env.step(None)
    score = env.final_score()
    expected = {
        "outcome", "day", "plague_score", "infected_pct", "dead_pct",
        "affected_pct", "cure_progress_pct", "countries_infected",
        "total_countries", "traits_evolved",
    }
    assert expected <= set(score)


def test_episode_ends_with_timeout_at_max_steps():
    """
    An episode that survives the day cap used to finish with `outcome: None`,
    which benchanything.json defines as "still running". Weak policies now
    routinely reach the cap, so the ending has a name.
    """
    env = PlagueEnv(max_steps=5)
    env.reset("India")
    for _ in range(4):
        _, _, done, info = env.step(None)
        assert done is False
        assert info["outcome"] is None

    _, _, done, info = env.step(None)
    assert done is True
    assert info["outcome"] == "timeout"
    assert env.game.day == 5


def test_timeout_still_reports_terminal_fields():
    env = PlagueEnv(max_steps=3)
    env.reset("India")
    for _ in range(3):
        _, _, done, info = env.step(None)
    assert done is True
    assert info["score"]["outcome"] == "timeout"
    assert info["score"]["victory_progress"] >= 0.0
    assert info["plague_score"] >= 0.0


def test_timeout_does_not_override_a_real_outcome():
    """max_steps=1 makes both endings land on the same step; `cured` must win."""
    env = PlagueEnv(max_steps=1)
    env.reset("India")
    env.game.cure_progress = 1.0
    _, _, done, info = env.step(None)
    assert done is True
    assert info["outcome"] == "cured"


def test_render_before_reset_is_safe():
    assert "not initialized" in PlagueEnv().render().lower()


# ── Adapter action validation ─────────────────────────────────────────────────

def test_adapter_accepts_a_legal_devolve(game):
    """
    Regression: every 'devolve:<id>' fell through to the evolve checks, where
    the prefix made it fail as "not a valid trait ID". The action the spec
    documents was unreachable through the adapter -- the only path a hosted
    agent has.
    """
    game.dna = 999
    evolve_trait(game, "Air1")
    action, error = Handler._validate_action("devolve:Air1", game)
    assert error is None
    assert action == "devolve:Air1"


def test_adapter_rejects_devolving_a_one_time_trait(game):
    game.dna = 999
    evolve_trait(game, "GeneticHardening1")
    evolve_trait(game, "GeneticReShuffle1")
    action, error = Handler._validate_action("devolve:GeneticReShuffle1", game)
    assert action is None
    assert "one-time-use" in error


def test_adapter_rejects_devolving_an_unevolved_trait(game):
    action, error = Handler._validate_action("devolve:Air1", game)
    assert action is None
    assert "not evolved" in error


def test_adapter_rejects_devolving_an_unknown_trait(game):
    action, error = Handler._validate_action("devolve:Nonsense", game)
    assert action is None
    assert "not a valid trait ID" in error


def test_adapter_passes_null_through(game):
    assert Handler._validate_action(None, game) == (None, None)


def test_adapter_rejects_an_unaffordable_trait(game):
    game.dna = 0
    action, error = Handler._validate_action("Air1", game)
    assert action is None
    assert "not available" in error


# ── Adapter fuzzy trait matching ──────────────────────────────────────────────

def test_fuzzy_exact_match():
    affordable = get_affordable_traits(set(), 999)
    assert Handler._fuzzy_trait("Air1", affordable) == "Air1"


def test_fuzzy_extracts_id_from_prose():
    affordable = {"Air1": TRAITS["Air1"]}
    assert Handler._fuzzy_trait("I will evolve Air1 next.", affordable) == "Air1"


def test_fuzzy_matches_stem_to_next_tier():
    """A bare 'cold_resist' should reach ColdResist2 once tier 1 is evolved."""
    affordable = {"ColdResist2": TRAITS["ColdResist2"]}
    assert Handler._fuzzy_trait("cold_resist", affordable) == "ColdResist2"


def test_fuzzy_matches_on_trait_name():
    affordable = {"DrugResistance1": TRAITS["DrugResistance1"]}
    raw = "going with drug resistance this turn"
    assert Handler._fuzzy_trait(raw, affordable) == "DrugResistance1"


def test_fuzzy_returns_none_when_nothing_matches():
    assert Handler._fuzzy_trait("do nothing this turn", {"Air1": TRAITS["Air1"]}) is None


def test_fuzzy_never_returns_an_evolved_trait():
    """Affordable excludes evolved traits, so a match can never be one."""
    evolved = {"Air1"}
    affordable = get_affordable_traits(evolved, 999)
    assert Handler._fuzzy_trait("Air1", affordable) != "Air1"
    assert all(tid not in evolved for tid in affordable)


# ── One-time-use specials (regression: reshuffle recycling exploit) ───────────

def test_reshuffle_cannot_be_devolved(game):
    game.dna = 999
    evolve_trait(game, "GeneticHardening1")
    evolve_trait(game, "GeneticReShuffle1")
    dna_before = game.dna

    assert devolve_trait(game, "GeneticReShuffle1") == 0
    assert "GeneticReShuffle1" in game.disease.evolved, "must stay evolved"
    assert game.dna == dna_before, "must not refund"


def test_reshuffle_recycling_cannot_reset_the_cure(game):
    """
    Regression: devolve/re-evolve used to re-fire the rollback, walking the cure
    down 0.90 -> 0.65 -> 0.40 -> 0.15 for 15 net DNA a cycle. It was the highest
    scoring strategy in the game.
    """
    game.dna = 10_000
    evolve_trait(game, "GeneticHardening1")
    game.cure_progress = 0.9
    evolve_trait(game, "GeneticReShuffle1")
    assert game.cure_progress == pytest.approx(0.65)

    for _ in range(3):
        devolve_trait(game, "GeneticReShuffle1")
        evolve_trait(game, "GeneticReShuffle1")
        assert game.cure_progress == pytest.approx(0.65), "rollback re-fired"


def test_reshuffle_special_fires_once_even_if_re_evolved_directly(game):
    """The guard lives on the special, not on devolve, so no path can re-arm it."""
    game.dna = 10_000
    evolve_trait(game, "GeneticHardening1")
    game.cure_progress = 0.9
    evolve_trait(game, "GeneticReShuffle1")

    game.disease.evolved.discard("GeneticReShuffle1")   # bypass devolve entirely
    evolve_trait(game, "GeneticReShuffle1")
    assert game.cure_progress == pytest.approx(0.65)


def test_each_reshuffle_tier_fires_on_its_own(game):
    game.dna = 10_000
    evolve_trait(game, "GeneticHardening1")
    game.cure_progress = 0.9
    evolve_trait(game, "GeneticReShuffle1")
    assert game.cure_progress == pytest.approx(0.65)
    evolve_trait(game, "GeneticReShuffle2")
    assert game.cure_progress == pytest.approx(0.25)


def test_insanity_is_still_devolvable(game):
    """
    Insanity carries a special too, but slows_cure is a passive read from
    `evolved` -- not one-time-use -- so it must stay devolvable.
    """
    game.dna = 10_000
    for tid in ("Insomnia", "Paranoia", "Insanity"):
        assert evolve_trait(game, tid) is True

    assert devolve_trait(game, "Insanity") == 2
    assert "Insanity" not in game.disease.evolved


# ── Saturation threshold and victory progress ─────────────────────────────────

def test_saturation_threshold_ends_the_game(game):
    """
    Internal spread is exponential decay of the healthy population, so it never
    literally reaches zero. A small residue must still count as full saturation.
    """
    total = game.total_population()
    residue = int(total * 0.0005)          # 0.05%, under the 0.1% threshold
    for country in game.countries.values():
        country.infected = country.population
        country.dead = 0
    india = game.countries["India"]
    india.infected = india.population - residue

    game._check_game_over()
    assert game.game_over and game.outcome == "infected_all"


def test_a_real_healthy_population_does_not_end_the_game(game):
    """5% healthy is a live game, not a win."""
    for country in game.countries.values():
        country.infected = int(country.population * 0.95)
        country.dead = 0
    game._check_game_over()
    assert not game.game_over


def test_extinct_outranks_infected_all(game):
    for country in game.countries.values():
        country.dead = country.population
        country.infected = 0
    game._check_game_over()
    assert game.outcome == "extinct"


def test_victory_progress_bounds():
    env = PlagueEnv()
    env.reset("India")
    score = env.final_score()
    assert 0.0 <= score["victory_progress"] <= 1.0
    assert 0.0 <= score["extinction_progress"] <= 1.0


def test_victory_progress_tracks_reach():
    env = PlagueEnv()
    env.reset("India")
    start = env.final_score()["victory_progress"]
    for country in env.game.countries.values():
        country.infected = country.population // 2
    assert env.final_score()["victory_progress"] > start


def test_extinction_progress_reaches_one_at_threshold():
    env = PlagueEnv()
    env.reset("India")
    for country in env.game.countries.values():
        country.dead = country.population
        country.infected = 0
    assert env.final_score()["extinction_progress"] == 1.0
