from data.traits import TRAITS

_DEVOLVE_REFUND = 2  # flat DNA returned per devolve


def evolve_trait(game, trait_id: str) -> bool:
    """
    Spend DNA to evolve a trait. Returns True on success.
    Prereqs must be met, trait must not already be evolved, DNA must be sufficient.
    Reshuffle traits immediately roll back cure progress.
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

    special = trait.get("special", "")
    if special == "reshuffle_25":
        game.cure_progress = max(0.0, game.cure_progress - 0.25)
    elif special == "reshuffle_40":
        game.cure_progress = max(0.0, game.cure_progress - 0.40)
    elif special == "reshuffle_60":
        game.cure_progress = max(0.0, game.cure_progress - 0.60)

    return True


def devolve_trait(game, trait_id: str) -> int:
    """
    Devolve a single trait. Returns _DEVOLVE_REFUND (2 DNA) on success, 0 if not evolved.
    Subsequent traits that required this trait as a prereq are NOT removed — they remain
    evolved but their prereq is no longer met. Reshuffle cure rollbacks are NOT reversed.
    """
    if trait_id not in TRAITS or trait_id not in game.disease.evolved:
        return 0

    trait = TRAITS[trait_id]
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
