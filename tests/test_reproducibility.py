"""
Reproducibility of an episode.

The point of the benchmark is comparing one agent's score to another's, and
that comparison is only meaningful if both agents faced the same world. These
tests pin down the three properties that makes true: the same seed replays
exactly, episode order does not matter, and an unseeded episode records enough
to be replayed later.
"""

import random

from env import PlagueEnv
from models.game_state import GameState
from simulation.spread import spread_air_routes


def _play(seed, rng_seed=None, days=120, policy=None):
    env = PlagueEnv()
    obs = env.reset(seed, rng_seed=rng_seed)
    for _ in range(days):
        obs, _, done, _ = env.step(policy(obs) if policy else None)
        if done:
            break
    return env


def test_same_seed_replays_exactly():
    assert _play("USA").final_score() == _play("USA").final_score()


def test_episode_order_does_not_change_a_score():
    """
    The regression this whole commit exists for: episodes drawing from the
    module-level generator made episode N depend on episodes 1..N-1, so a
    model's score moved depending on which seeds ran before it.
    """
    alone = _play("USA").final_score()
    _play("India")
    _play("Brazil")
    after_others = _play("USA").final_score()
    assert alone == after_others


def test_two_agents_meet_the_same_world():
    """A paired comparison is only paired if the worlds match."""
    passive = _play("Egypt")
    active = _play("Egypt", policy=lambda obs: None)
    assert passive.game.rng.random() == active.game.rng.random()


def test_unseeded_episode_records_a_replayable_seed():
    env = PlagueEnv()
    env.reset(None)
    assert env.rng_seed is not None
    replay = _play(None, rng_seed=env.rng_seed, days=0)
    assert replay._seed_country == env._seed_country


def test_rng_seed_overrides_the_country_seed():
    """Same country, different worlds — for repeats on one seed."""
    a = _play("USA", rng_seed=1).final_score()
    b = _play("USA", rng_seed=2).final_score()
    assert a["day"] == b["day"]          # both ran the same number of days
    assert a != b


def test_module_random_no_longer_drives_the_simulation():
    """
    Seeding the global generator must not change an episode, or a caller that
    happens to use `random` for something else silently perturbs the world.
    """
    random.seed(1)
    a = _play("USA").final_score()
    random.seed(999)
    b = _play("USA").final_score()
    assert a == b


def test_game_state_defaults_to_its_own_generator():
    """Direct GameState users (scripts, the roster in make_example_replay)."""
    assert isinstance(GameState().rng, random.Random)


def test_spread_still_accepts_the_module_generator():
    """The default keeps one-off callers and older scripts working."""
    game = GameState()
    game.countries["India"].infected = 500_000
    spread_air_routes(game.countries, game.disease)   # no rng argument
