from dataclasses import dataclass, field


@dataclass
class Disease:
    infectivity: float = 1.0
    severity: float = 0.0
    lethality: float = 0.0

    air_transmission: int = 0
    water_transmission: int = 0
    bird_transmission: int = 0

    cold_resist: int = 0
    heat_resist: int = 0

    drug_resist: int = 0
    genetic_hardening: int = 0

    evolved: set[str] = field(default_factory=set)

    def evolve(self, trait_id: str, trait_data: dict):
        """
        Apply a trait's effects to this disease.
        """

        self.evolved.add(trait_id)

        for stat, delta in trait_data["effects"].items():

            current = getattr(self, stat, 0)

            setattr(
                self,
                stat,
                current + delta
            )