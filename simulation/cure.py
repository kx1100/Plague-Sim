def update_awareness(game) -> None:
    """
    Countries become aware based on visible infection.
    High severity makes the disease more visible; more infected = faster awareness rise.
    """
    for country in game.countries.values():
        if country.infected == 0:
            continue
        base = 0.001
        scale = country.infection_ratio * (0.5 + game.disease.severity * 3.0)
        gain = min(0.03, base + scale)
        country.awareness = min(1.0, country.awareness + gain)


def update_cure(game) -> None:
    """
    Cure progress accumulates from wealthy, aware countries.
    High severity accelerates research; drug resistance and genetic hardening slow it.
    """
    if game.cure_progress >= 1.0:
        return

    total_contrib = sum(
        c.wealth * c.awareness * 0.0001
        for c in game.countries.values()
        if c.awareness > 0
    )

    severity_boost = 1.0 + game.disease.severity * 2.0
    drug_penalty = max(0.1, 1.0 - game.disease.drug_resist * 0.15)
    hardening_penalty = max(0.1, 1.0 - game.disease.genetic_hardening * 0.15)
    insanity_penalty = 0.9 if "Insanity" in game.disease.evolved else 1.0

    daily = (
        total_contrib
        * severity_boost
        * drug_penalty
        * hardening_penalty
        * insanity_penalty
    )

    game.cure_progress = min(1.0, game.cure_progress + daily)
