def generate_dna(
    game,
    newly_infected_countries: int = 0,
    deaths_this_tick: int = 0,
) -> None:
    """
    DNA is earned from events, scaled by severity (mimicking Plague Inc. bubble system):
      - Each newly infected country triggers a bubble worth 1-5 DNA.
      - Every 10,000 deaths this tick triggers a death bubble worth 1-5 DNA.
      - Passive: tiny background drip from large infected populations.
    """
    severity = game.disease.severity
    bubble_value = max(1, round(1 + severity * 4))  # 1 at sev=0, 5 at sev=1

    game.dna += newly_infected_countries * bubble_value
    game.dna += (deaths_this_tick // 10_000) * bubble_value
    game.dna += max(0, round(game.total_infected() * 0.0000001))
