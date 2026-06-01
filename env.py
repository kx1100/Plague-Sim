"""
env.py — Plague simulation environment (game/task logic).

Hidden state : full GameState (country-level infection, disease internals).
Observation  : aggregate statistics + available actions exposed to the agent.
"""

import random as _random

from models.game_state import GameState
from simulation.actions import evolve_trait, devolve_trait
from data.traits import get_affordable_traits, TRAITS


class PlagueEnv:
    """
    Plague Inc-style benchmark environment.

    reset(seed)  → observation dict
    step(action) → (observation, reward, done, info)
    """

    def __init__(self):
        self.game: GameState | None = None
        self._seed_country: str | None = None
        self._milestones: dict = {}   # tracks days_to_X benchmarks

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def reset(self, seed=None) -> dict:
        """
        seed : country name (str)  → seed that specific country
               integer             → used as random.seed + country index
               None                → random country
        Returns the initial observation.
        """
        self.game = GameState()
        self._milestones = {}

        country_names = sorted(self.game.countries.keys())

        if isinstance(seed, int):
            _random.seed(seed)
            self._seed_country = country_names[seed % len(country_names)]
        elif isinstance(seed, str):
            if seed not in self.game.countries:
                raise ValueError(
                    f"Unknown country '{seed}'. "
                    f"Valid: {', '.join(country_names)}"
                )
            self._seed_country = seed
        else:
            self._seed_country = _random.choice(country_names)

        self.game.countries[self._seed_country].infected = 500_000
        self.game.dna = 15
        return self.observation()

    def step(self, action: str | None = None) -> tuple[dict, float, bool, dict]:
        """
        action : trait_id to evolve (e.g. "Air1"), "devolve:TraitId" to devolve, or None to wait.
        Returns (observation, reward, done, info).
        Invalid actions are silently ignored.
        """
        if self.game is None:
            raise RuntimeError("Call reset() before step().")

        action_result = None
        if action is not None:
            if action.startswith("devolve:"):
                trait_id = action[len("devolve:"):]
                refunded = devolve_trait(self.game, trait_id)
                action_result = refunded > 0
            else:
                action_result = evolve_trait(self.game, action)

        self.game.step()
        self._record_milestones()

        obs = self.observation()
        reward = self._reward()
        done = self.game.game_over
        info = {
            "day": self.game.day,
            "dna": self.game.dna,
            "cure_progress": round(self.game.cure_progress, 4),
            "outcome": self.game.outcome,
            "action_accepted": action_result,
        }
        if done:
            terminal = self.final_score()
            info["score"] = terminal
            info.update(terminal)
        return obs, reward, done, info

    # ── Observation (what the agent sees) ─────────────────────────────────────

    def observation(self) -> dict:
        g = self.game
        return {
            "day": g.day,
            "dna": g.dna,
            "cure_progress": round(g.cure_progress, 4),
            "infected_pct": round(g.percentage_infected() * 100, 2),
            "dead_pct": round(g.percentage_dead() * 100, 2),
            "countries_infected": g.infected_countries(),
            "evolved_traits": sorted(g.disease.evolved),
            "available_traits": {
                tid: {"name": t["name"], "cost": t["cost"], "tree": t["tree"]}
                for tid, t in get_affordable_traits(
                    g.disease.evolved, g.dna
                ).items()
            },
        }

    # ── Render (human-readable snapshot) ──────────────────────────────────────

    def render(self) -> str:
        if self.game is None:
            return "Environment not initialized. Call reset() first."

        g = self.game
        lines = [
            f"Day {g.day:>4} | "
            f"Infected {g.percentage_infected() * 100:>6.2f}% | "
            f"Dead {g.percentage_dead() * 100:>5.2f}% | "
            f"Cure {g.cure_progress * 100:>5.1f}% | "
            f"DNA {g.dna:>5}",
            f"Countries: {g.infected_countries()}/{len(g.countries)} infected",
            f"Traits evolved: {', '.join(sorted(g.disease.evolved)) or 'none'}",
        ]
        if g.game_over:
            lines.append(f"GAME OVER — {g.outcome}")
        return "\n".join(lines)

    # ── Scoring (benchmarking output) ─────────────────────────────────────────

    def final_score(self) -> dict:
        g = self.game
        total = g.total_population()
        infected = g.total_infected()
        dead = g.total_dead()
        return {
            "outcome": g.outcome,
            "day": g.day,
            "plague_score": self._plague_score(),
            "infected_pct": round(infected / total * 100, 2),
            "dead_pct": round(dead / total * 100, 2),
            "affected_pct": round((infected + dead) / total * 100, 2),
            "cure_progress_pct": round(g.cure_progress * 100, 2),
            "countries_infected": g.infected_countries(),
            "total_countries": len(g.countries),
            "traits_evolved": sorted(g.disease.evolved),
            "days_to_infect_25pct": self._milestones.get("25pct"),
            "days_to_infect_50pct": self._milestones.get("50pct"),
            "days_to_infect_75pct": self._milestones.get("75pct"),
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _plague_score(self) -> float:
        """
        Plague Inc score formula (Normal difficulty, Bacteria):
          Score = 10 * [(S * DNA * D * P) / (C * Time) + DeathPercentage * 100]
          S    = disease severity
          DNA  = remaining_dna * 2 + spent_dna (sum of evolved trait costs)
          D    = 4  (Normal difficulty)
          P    = 1  (Bacteria plague adjustment)
          C    = cure progress % clamped to [1, 100]
          Time = game days elapsed (clamped >= 1)
          DeathPercentage = dead / total_population, clamped to [0, 0.9999]
        """
        g = self.game
        total = g.total_population()
        if total == 0:
            return 0.0

        S = g.disease.severity
        spent_dna = sum(TRAITS[tid]["cost"] for tid in g.disease.evolved)
        DNA_val = g.dna * 2 + spent_dna
        D, P = 4, 1
        C = max(1.0, min(100.0, g.cure_progress * 100))
        time_val = max(1, g.day)
        death_pct = min(0.9999, g.total_dead() / total)

        score = 10 * ((S * DNA_val * D * P) / (C * time_val) + death_pct * 100)
        affected_pct = (g.total_infected() + g.total_dead()) / total
        score += affected_pct * 1000
        return round(score, 2)

    def _reward(self) -> float:
        g = self.game
        step_reward = (
            g.percentage_infected()
            + g.percentage_dead() * 2.0
            - g.cure_progress * 0.5
        )
        if g.game_over:
            step_reward += self._plague_score() / 100.0
        return step_reward

    def _action_hint(self, g) -> str:
        affordable = get_affordable_traits(g.disease.evolved, g.dna)
        evolved_list = sorted(g.disease.evolved)
        already = f" Already evolved (do not pick): {', '.join(evolved_list)}." if evolved_list else ""
        if affordable:
            ids = sorted(affordable.keys())
            return (
                f"DNA={g.dna}.{already} "
                f"Traits you can evolve right now: {', '.join(ids)}. "
                f"Output exactly one of these trait IDs."
            )
        cheapest_cost = min(
            (t["cost"] for tid, t in TRAITS.items() if tid not in g.disease.evolved),
            default=0,
        )
        return (
            f"DNA={g.dna}.{already} "
            f"Cheapest unevolved trait costs {cheapest_cost}. "
            f"Cannot evolve anything yet. Output: null"
        )

    def _record_milestones(self) -> None:
        g = self.game
        affected = g.percentage_infected() + g.percentage_dead()
        for label, threshold in [("25pct", 0.25), ("50pct", 0.50), ("75pct", 0.75)]:
            if label not in self._milestones and affected >= threshold:
                self._milestones[label] = g.day
