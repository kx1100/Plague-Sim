from models.disease import Disease
from models.world_builder import build_world


class GameState:
    def __init__(self):
        self.day = 0
        self.dna = 0
        self.cure_progress = 0.0
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
        spread_air_routes(self.countries, self.disease)
        spread_sea_routes(self.countries, self.disease)

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

        total_healthy = sum(c.healthy for c in self.countries.values())
        if total_healthy <= 0:
            self.game_over = True
            total_pop = self.total_population()
            total_dead = self.total_dead()
            self.outcome = (
                "extinct" if total_dead / total_pop > 0.95 else "infected_all"
            )
            return

        # Disease died out before spreading meaningfully
        if self.total_infected() == 0 and self.day > 30:
            self.game_over = True
            self.outcome = "died_out"
