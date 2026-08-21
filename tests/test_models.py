"""Structural tests for the world, country, disease, and trait data."""

import pytest

from data.traits import TRAITS, get_available_traits, get_affordable_traits
from models.country import Country
from models.disease import Disease
from models.game_state import GameState
from models.world_builder import build_world


# ── World construction ────────────────────────────────────────────────────────

def test_world_creation():
    game = GameState()
    assert len(game.countries) == 71
    assert "USA" in game.countries
    assert "India" in game.countries


def test_world_population_total():
    assert sum(c.population for c in build_world().values()) == 7_093_316_000


def test_borders_are_bidirectional():
    """build_world() mirrors the one-directional raw border data."""
    world = build_world()
    for name, country in world.items():
        for neighbor in country.borders:
            if neighbor in world:
                assert name in world[neighbor].borders, (
                    f"{name} borders {neighbor} but not vice versa"
                )


def test_borders_reference_real_countries():
    world = build_world()
    for name, country in world.items():
        for neighbor in country.borders:
            assert neighbor in world, f"{name} borders unknown country {neighbor}"


def test_no_country_borders_itself():
    world = build_world()
    for name, country in world.items():
        assert name not in country.borders


# ── Country arithmetic ────────────────────────────────────────────────────────

def _country(**kwargs) -> Country:
    defaults = dict(
        name="Test", population=1000, climate="temperate", wealth=0.5,
        airports=1, ports=1, borders=[],
    )
    defaults.update(kwargs)
    return Country(**defaults)


def test_country_health():
    game = GameState()
    usa = game.countries["USA"]
    usa.infected = 1000
    assert usa.healthy == usa.population - 1000


def test_healthy_accounts_for_dead():
    c = _country(infected=100, dead=50)
    assert c.healthy == 850


def test_infection_ratio_excludes_dead_from_denominator():
    c = _country(population=1000, infected=250, dead=500)
    assert c.infection_ratio == pytest.approx(0.5)


def test_infection_ratio_zero_when_nobody_alive():
    c = _country(population=1000, infected=0, dead=1000)
    assert c.infection_ratio == 0.0


def test_death_ratio_zero_population():
    assert _country(population=0).death_ratio == 0.0


def test_death_ratio():
    assert _country(population=1000, dead=250).death_ratio == pytest.approx(0.25)


# ── Disease / trait data ──────────────────────────────────────────────────────

def test_trait_evolution_applies_effects():
    disease = Disease()
    disease.evolve("Air1", TRAITS["Air1"])
    assert disease.air_transmission == 1
    assert disease.infectivity > 1.0
    assert "Air1" in disease.evolved


def test_trait_prereqs_reference_real_traits():
    for tid, trait in TRAITS.items():
        for prereq in trait["prereqs"]:
            assert prereq in TRAITS, f"{tid} requires unknown trait {prereq}"


def test_trait_tree_is_acyclic_and_reachable():
    """Every trait must be reachable from a zero-prereq root."""
    resolved: set[str] = set()
    for _ in range(len(TRAITS) + 1):
        newly = {
            tid for tid, t in TRAITS.items()
            if tid not in resolved and all(p in resolved for p in t["prereqs"])
        }
        if not newly:
            break
        resolved |= newly
    unreachable = set(TRAITS) - resolved
    assert not unreachable, f"unreachable (cyclic?) traits: {unreachable}"


def test_trait_schema():
    valid_trees = {"transmission", "symptom", "ability"}
    stats = set(vars(Disease()))
    for tid, trait in TRAITS.items():
        assert trait["tree"] in valid_trees, f"{tid} has bad tree {trait['tree']}"
        assert trait["cost"] > 0, f"{tid} is free"
        assert trait["desc"], f"{tid} has no description"
        for stat in trait["effects"]:
            assert stat in stats, f"{tid} targets unknown Disease stat {stat}"


# ── Trait availability helpers ────────────────────────────────────────────────

def test_available_traits_respect_prereqs():
    available = get_available_traits(set())
    assert "Air1" in available
    assert "Air2" not in available          # needs Air1
    assert "ExtremeBioaerosol" not in available   # needs Air2 + Water2

    available = get_available_traits({"Air1"})
    assert "Air1" not in available          # already evolved
    assert "Air2" in available


def test_available_traits_need_all_prereqs():
    """ExtremeBioaerosol needs both Air2 and Water2, not either."""
    partial = {"Air1", "Air2"}
    assert "ExtremeBioaerosol" not in get_available_traits(partial)
    full = partial | {"Water1", "Water2"}
    assert "ExtremeBioaerosol" in get_available_traits(full)


def test_affordable_traits_filter_on_dna():
    assert get_affordable_traits(set(), 0) == {}
    affordable = get_affordable_traits(set(), 9)
    assert "Air1" in affordable                      # costs 9
    assert all(t["cost"] <= 9 for t in affordable.values())
