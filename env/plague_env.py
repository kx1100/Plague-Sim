import random

from models.game_state import GameState
from simulation.actions import evolve_trait
from data.traits import get_affordable_traits


class PlagueEnv:
    """
    Gym-style environment for LLM/RL benchmarking.

    At each step the agent may evolve one trait (by trait_id) or pass None to wait.
    The observation includes all information an agent needs to make decisions.
    The reward is a proxy for how close the agent is to winning (infecting/killing humanity).
    """

    def __init__(self):
        self.game: GameState | None = None

    def reset(self, seed_country: str = None) -> dict:
        self.game = GameState()
        if seed_country is None:
            seed_country = random.choice(list(self.game.countries.keys()))
        self.game.countries[seed_country].infected = 100
        return self.observation()

    def step(self, action: str | None = None) -> tuple[dict, float, bool, dict]:
        """
        action: trait_id string to evolve, or None to skip.
        Returns: (observation, reward, done, info)
        """
        if action is not None:
            evolve_trait(self.game, action)

        self.game.step()

        obs = self.observation()
        reward = self._reward()
        done = self.game.game_over
        info = {
            "day": self.game.day,
            "dna": self.game.dna,
            "cure_progress": round(self.game.cure_progress, 4),
            "outcome": self.game.outcome,
            "score": self.game.score(),
        }
        return obs, reward, done, info

    def observation(self) -> dict:
        return {
            "day": self.game.day,
            "dna": self.game.dna,
            "cure_progress": round(self.game.cure_progress, 4),
            "infected_pct": round(self.game.percentage_infected() * 100, 2),
            "dead_pct": round(self.game.percentage_dead() * 100, 2),
            "countries_infected": self.game.infected_countries(),
            "total_countries": len(self.game.countries),
            "evolved_traits": sorted(self.game.disease.evolved),
            "available_traits": {
                tid: {
                    "name": t["name"],
                    "cost": t["cost"],
                    "tree": t["tree"],
                    "desc": t["desc"],
                }
                for tid, t in get_affordable_traits(
                    self.game.disease.evolved, self.game.dna
                ).items()
            },
        }

    def _reward(self) -> float:
        # Maximise deaths (2×) + currently infected, penalise cure progress
        return (
            self.game.percentage_infected()
            + self.game.percentage_dead() * 2.0
            - self.game.cure_progress * 0.5
        )
