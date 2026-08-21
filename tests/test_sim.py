"""Tests for simulation mechanics, the env lifecycle, and the HTTP adapter."""

import pytest

from adapter import Handler
from data.traits import TRAITS, get_affordable_traits
from env import PlagueEnv
from models.game_state import GameState
from simulation.actions import evolve_trait, devolve_trait
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
        "day", "dna", "cure_progress", "infected_pct", "dead_pct",
        "countries_infected", "evolved_traits", "available_traits",
    }
    assert expected <= set(obs)


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


def test_render_before_reset_is_safe():
    assert "not initialized" in PlagueEnv().render().lower()


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
