from data.traits import TRAITS


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
