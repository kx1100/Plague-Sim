from data.traits import TRAITS

_DEVOLVE_REFUND = 2  # flat DNA returned per devolve

# Cure rollback granted the first time each ReShuffle trait is evolved.
_RESHUFFLE_ROLLBACK = {
    "reshuffle_25": 0.25,
    "reshuffle_40": 0.40,
    "reshuffle_60": 0.60,
}

# Specials that fire once per game. Traits carrying one cannot be devolved,
# because devolve/re-evolve would otherwise re-trigger the effect.
_ONE_TIME_SPECIALS = frozenset(_RESHUFFLE_ROLLBACK)


def evolve_trait(game, trait_id: str) -> bool:
    """
    Spend DNA to evolve a trait. Returns True on success.
    Prereqs must be met, trait must not already be evolved, DNA must be sufficient.
    ReShuffle traits roll the cure back the first time they are evolved, once each.
    """
    if trait_id not in TRAITS:
        return False

    trait = TRAITS[trait_id]

    if trait_id in game.disease.evolved:
        return False

    if not all(p in game.disease.evolved for p in trait["prereqs"]):
        return False

    if game.dna < trait["cost"]:
        return False

    game.dna -= trait["cost"]
    game.disease.evolve(trait_id, trait)

    rollback = _RESHUFFLE_ROLLBACK.get(trait.get("special", ""))
    if rollback is not None and trait_id not in game.disease.used_specials:
        game.cure_progress = max(0.0, game.cure_progress - rollback)
        game.disease.used_specials.add(trait_id)

    return True


def devolve_trait(game, trait_id: str) -> int:
    """
    Devolve a single trait. Returns _DEVOLVE_REFUND (2 DNA) on success, 0 if the
    trait is not evolved or is a one-time-use special.

    Subsequent traits that required this trait as a prereq are NOT removed -- they
    remain evolved but their prereq is no longer met.
    """
    if trait_id not in TRAITS or trait_id not in game.disease.evolved:
        return 0

    trait = TRAITS[trait_id]

    # One-time-use traits are locked in. Allowing a devolve here would let the
    # agent recycle the cure rollback for the 2 DNA refund, over and over.
    if trait.get("special") in _ONE_TIME_SPECIALS:
        return 0

    for stat, delta in trait["effects"].items():
        current = getattr(game.disease, stat, 0)
        new_val = current - delta
        if isinstance(delta, int):
            new_val = max(0, int(new_val))
        else:
            new_val = round(new_val, 6)
        setattr(game.disease, stat, new_val)

    game.disease.evolved.discard(trait_id)
    game.dna += _DEVOLVE_REFUND
    return _DEVOLVE_REFUND
