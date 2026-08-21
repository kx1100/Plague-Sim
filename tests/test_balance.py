"""
Balance invariants for the DNA economy.

These lock in the fix for the runaway economy that let an agent evolve all 60
traits by day 76 of a ~207-day episode, leaving two thirds of the game with no
legal action but null. Bounds are deliberately loose -- they exist to catch a
regression back to unbounded growth, not to pin exact tuning.

The policy-level score spread lives in tools/calibrate.py, which is slower and
meant to be run by hand after tuning.
"""

import random

import pytest

from data.traits import TRAITS
from env import PlagueEnv
from simulation.dna import generate_dna, _MAX_DNA_PER_DAY

TREE_COST = sum(t["cost"] for t in TRAITS.values())


def _play(policy, seed_country="India", rng_seed=0) -> PlagueEnv:
    random.seed(rng_seed)
    env = PlagueEnv()
    env.reset(seed_country)
    done = False
    while not done and env.game.day < 600:
        _, _, done, _ = env.step(policy(env.observation()))
    return env


def _random_policy(obs):
    affordable = list(obs["available_traits"])
    return random.choice(affordable) if affordable else None


def _pass_policy(obs):
    return None


# ── Budget bounds ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seed_country", ["India", "USA", "Madagascar"])
def test_dna_budget_stays_bounded(seed_country):
    """The whole failure mode was DNA reaching ~1.6M. Nothing may approach that."""
    env = _play(_random_policy, seed_country)
    assert env.game.dna_earned <= 300, (
        f"DNA economy is inflating again: {env.game.dna_earned} earned"
    )


def test_full_tree_is_never_affordable():
    env = _play(_random_policy)
    assert env.game.dna_earned < TREE_COST, (
        "a single episode can fund the entire trait tree, so there are no choices"
    )
    assert len(env.game.disease.evolved) < len(TRAITS)


def test_agent_still_has_choices_late_in_the_episode():
    """Regression: every trait used to be evolved by day 76, leaving only null."""
    env = _play(_random_policy)
    assert len(env.game.disease.evolved) < len(TRAITS)


def test_daily_grant_is_capped():
    """Even an absurd single tick cannot mint more than the daily cap."""
    env = PlagueEnv()
    env.reset("India")
    before = env.game.dna
    generate_dna(env.game, newly_infected_countries=1000, deaths_this_tick=10**9)
    assert env.game.dna - before <= _MAX_DNA_PER_DAY


# ── Nothing accrues passively ─────────────────────────────────────────────────

def test_waiting_earns_nothing_once_the_world_is_saturated():
    """
    The old passive drip paid out in proportion to the infected headcount, so an
    idle agent got richer every day. Reaching everyone must stop paying.
    """
    env = _play(_pass_policy)
    game = env.game
    earned_at_end = game.dna_earned
    for _ in range(50):
        generate_dna(game, newly_infected_countries=0, deaths_this_tick=0)
    assert game.dna_earned == earned_at_end


def test_milestones_pay_once_each():
    env = PlagueEnv()
    env.reset("India")
    game = env.game
    game.countries["India"].infected = game.total_population() // 4

    generate_dna(game, 0, 0)
    first = game.dna_earned
    assert first > 0, "crossing infection milestones should pay"

    for _ in range(10):
        generate_dna(game, 0, 0)
    assert game.dna_earned == first, "milestones must not pay repeatedly"


# ── Score composition ─────────────────────────────────────────────────────────

def test_score_is_not_dominated_by_leftover_dna():
    """
    plague_score used to be 91% the `remaining_dna * 2` term, which rewarded
    hoarding rather than playing.
    """
    env = _play(_random_policy)
    game = env.game
    score = env.final_score()["plague_score"]

    spent = sum(TRAITS[t]["cost"] for t in game.disease.evolved)
    dna_term = 10 * (
        (game.disease.severity * (game.dna * 2 + spent) * 4)
        / (max(1.0, min(100.0, game.cure_progress * 100)) * max(1, game.day))
    )
    assert dna_term < 0.25 * score, (
        f"DNA term is {100 * dna_term / score:.0f}% of the score"
    )
