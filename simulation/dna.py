"""
DNA economy.

DNA is the only currency in the game, so its scarcity *is* the difficulty. Every
source here must be bounded over a full episode, or the agent ends up able to
afford the entire 697-DNA trait tree and stops making choices.

Budget: bounded at 450 DNA for any policy across a 600-day episode, against a
tree that costs 697 to evolve fully, with at least 150 available to skilled play.
Income is play-dependent by design -- spreading is what pays -- so the invariant
is a ceiling plus a floor, not one flat band. Measured max is 340 (see
`tools/calibrate.py`); the agent affords roughly a third to a half of the tree,
and has to earn the back half by spreading rather than by waiting.

Every source is a *ratchet on cumulative progress*, never a rate on the current
population. A per-tick award scales with the infected headcount and runs away
once billions are infected -- which is exactly how this economy broke before.
"""

# Per newly infected country, scaled up once severity is high (a flashy plague
# generates more "bubbles"). 71 countries -> ~140-210 DNA over a full sweep.
_COUNTRY_BUBBLE_BASE = 2

# Infection milestones pay out as the disease works through the world population.
# This is what bootstraps the mid-game: spreading earns the DNA that pays for
# lethality, so the agent has to succeed at transmission before it can kill.
_INFECTION_MILESTONE_FRACTION = 0.02   # one milestone per 2% of the world reached
_INFECTION_BUBBLE_VALUE = 2            # -> at most 100 DNA

# Death milestones are awarded on CUMULATIVE deaths, not per-tick deaths.
_DEATH_MILESTONE_FRACTION = 0.005      # one milestone per 0.5% of the world dead
_DEATH_BUBBLE_VALUE = 1                # -> at most 200 DNA, and only for a total kill

# Backstop. Bounds any single day regardless of how many events land at once, so
# a future source cannot quietly reintroduce runaway growth.
_MAX_DNA_PER_DAY = 8


def generate_dna(
    game,
    newly_infected_countries: int = 0,
    deaths_this_tick: int = 0,
) -> None:
    """
    Award DNA for this tick:
      - Each newly infected country pays a bubble worth 2-3 DNA.
      - Each 2% of the world reached pays 1 DNA, once.
      - Each 0.5% of the world killed pays 1 DNA, once.
      - Nothing accrues passively; sitting still earns nothing.
    The daily total is capped at _MAX_DNA_PER_DAY.
    """
    severity = min(1.0, game.disease.severity)
    country_bubble = _COUNTRY_BUBBLE_BASE + round(severity)

    earned = newly_infected_countries * country_bubble
    earned += _milestone_dna(game)

    granted = min(earned, _MAX_DNA_PER_DAY)
    game.dna += granted
    game.dna_earned += granted   # lifetime total, for calibration and tests


def _milestone_dna(game) -> int:
    """DNA for cumulative infection and death milestones crossed since last tick."""
    total_pop = game.total_population()
    if total_pop <= 0:
        return 0

    # Ever-infected ratchets upward: the dead still count as ground taken.
    ever_infected = game.total_infected() + game.total_dead()

    return (
        _crossed(
            game, "infection_milestones_awarded",
            ever_infected, total_pop,
            _INFECTION_MILESTONE_FRACTION, _INFECTION_BUBBLE_VALUE,
        )
        + _crossed(
            game, "death_milestones_awarded",
            game.total_dead(), total_pop,
            _DEATH_MILESTONE_FRACTION, _DEATH_BUBBLE_VALUE,
        )
    )


def _crossed(game, counter: str, amount: int, total: int, fraction: float, value: int) -> int:
    """Pay for each new milestone of fraction * total that amount has passed."""
    milestone = max(1, int(total * fraction))
    reached = amount // milestone
    newly_reached = reached - getattr(game, counter)
    if newly_reached <= 0:
        return 0

    setattr(game, counter, reached)
    return newly_reached * value
