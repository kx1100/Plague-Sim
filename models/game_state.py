import random

from models.disease import Disease
from models.world_builder import build_world

# Fraction of humanity that may remain healthy and still count as full saturation.
#
# Internal spread is exponential decay of the healthy population, so it
# approaches zero asymptotically and never actually arrives -- requiring
# literally every human would make `infected_all` unreachable by construction
# rather than by difficulty. 0.1% of 7.09B is ~7M stragglers.
_SATURATION_THRESHOLD = 0.001

# Share of humanity that must be dead for the premium `extinct` outcome.
_EXTINCTION_THRESHOLD = 0.95


class GameState:
    def __init__(self, rng: random.Random | None = None):
        # One generator per game, so episodes run back to back in a single
        # process are independent of each other and of their order. Drawing
        # from the module-level `random` instead made episode N depend on
        # episodes 1..N-1, which quietly invalidates any comparison between
        # two agents that were not run in exactly the same sequence.
        self.rng = rng if rng is not None else random.Random()
        self.day = 0
        self.dna = 0
        self.cure_progress = 0.0
        self.infection_milestones_awarded = 0  # cumulative infection bubbles paid
        self.death_milestones_awarded = 0      # cumulative death bubbles paid
        self.dna_earned = 0                    # lifetime DNA granted (excludes start)
        self.game_over = False
        self.outcome = None  # "cured" | "extinct" | "infected_all" | "died_out"
        self.disease = Disease()
        self.countries = build_world()

    # ── Aggregates ────────────────────────────────────────────────────────────

    def total_population(self) -> int:
        return sum(c.population for c in self.countries.values())

    def total_infected(self) -> int:
        return sum(c.infected for c in self.countries.values())

    def total_dead(self) -> int:
        return sum(c.dead for c in self.countries.values())

    def infected_countries(self) -> int:
        return sum(1 for c in self.countries.values() if c.infected > 0)

    def percentage_infected(self) -> float:
        total = self.total_population()
        return 0.0 if total == 0 else self.total_infected() / total

    def percentage_dead(self) -> float:
        total = self.total_population()
        return 0.0 if total == 0 else self.total_dead() / total

    def score(self) -> dict:
        total = self.total_population()
        infected = self.total_infected()
        dead = self.total_dead()
        return {
            "day": self.day,
            "infected_pct": round(infected / total * 100, 2),
            "dead_pct": round(dead / total * 100, 2),
            "affected_pct": round((infected + dead) / total * 100, 2),
            "countries_infected": self.infected_countries(),
            "total_countries": len(self.countries),
            "cure_progress_pct": round(self.cure_progress * 100, 2),
            "game_over": self.game_over,
            "outcome": self.outcome,
        }

    # ── Simulation tick ───────────────────────────────────────────────────────

    def step(self) -> None:
        from simulation.spread import (
            spread_inside_country,
            spread_land_borders,
            spread_air_routes,
            spread_sea_routes,
        )
        from simulation.deaths import process_deaths
        from simulation.dna import generate_dna
        from simulation.cure import update_awareness, update_cure

        # Snapshot which countries are infected before spread (for DNA events)
        previously_infected = {
            name for name, c in self.countries.items() if c.infected > 0
        }

        for country in self.countries.values():
            spread_inside_country(country, self.disease)

        spread_land_borders(self.countries, self.disease)
        spread_air_routes(self.countries, self.disease, self.rng)
        spread_sea_routes(self.countries, self.disease, self.rng)

        newly_infected_countries = sum(
            1
            for name, c in self.countries.items()
            if c.infected > 0 and name not in previously_infected
        )

        # Track deaths this tick for DNA events
        dead_before = self.total_dead()

        for country in self.countries.values():
            process_deaths(country, self.disease)

        deaths_this_tick = self.total_dead() - dead_before

        update_awareness(self)
        generate_dna(self, newly_infected_countries, deaths_this_tick)
        update_cure(self)

        self.day += 1
        self._check_game_over()

    # ── Win / loss ────────────────────────────────────────────────────────────

    def _check_game_over(self) -> None:
        if self.cure_progress >= 1.0:
            self.game_over = True
            self.outcome = "cured"
            return

        total_pop = self.total_population()
        total_healthy = sum(c.healthy for c in self.countries.values())
        if total_healthy <= total_pop * _SATURATION_THRESHOLD:
            self.game_over = True
            self.outcome = (
                "extinct"
                if self.total_dead() / total_pop > _EXTINCTION_THRESHOLD
                else "infected_all"
            )
            return

        # Disease died out before spreading meaningfully
        if self.total_infected() == 0 and self.day > 30:
            self.game_over = True
            self.outcome = "died_out"
