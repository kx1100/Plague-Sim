from dataclasses import dataclass


@dataclass
class Country:
    name: str
    population: int
    climate: str
    wealth: float

    airports: int
    ports: int

    borders: list[str]

    infected: int = 0
    dead: int = 0

    awareness: float = 0.0

    @property
    def healthy(self) -> int:
        return self.population - self.infected - self.dead

    @property
    def infection_ratio(self) -> float:
        living = self.population - self.dead
        if living <= 0:
            return 0.0
        return self.infected / living

    @property
    def death_ratio(self) -> float:
        if self.population == 0:
            return 0.0
        return self.dead / self.population