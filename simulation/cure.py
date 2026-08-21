# Per-country research contribution, scaled by wealth and awareness.
#
# This is the clock the disease races, and it is the main difficulty dial.
# Tuned against win rate: at 0.000045 nothing ever wins, at 0.00004 the expert
# reference policy wins 9/10 which makes winning routine. At 0.000042 it wins
# 2/10 while careless play never wins -- a real achievement with headroom left
# for a smarter agent.
_CURE_CONTRIBUTION = 0.000042

# How sharply symptom severity accelerates research.
#
# This is what makes severity management the core skill: a flashy plague is
# cured fast, a quiet one is given time. At the original 2.0 the penalty was too
# soft to punish careless symptom buying, and separating good play from bad
# meant making the world easier for everyone. At 5.0 careless play stalls near
# 25% infected while patient play reaches saturation.
_SEVERITY_CURE_SENSITIVITY = 5.0


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
        c.wealth * c.awareness * _CURE_CONTRIBUTION
        for c in game.countries.values()
        if c.awareness > 0
    )

    severity_boost = 1.0 + game.disease.severity * _SEVERITY_CURE_SENSITIVITY
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
