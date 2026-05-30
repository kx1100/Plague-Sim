import random


def climate_multiplier(climate: str, disease) -> float:
    if climate == "cold":
        return 0.3 + 0.35 * min(disease.cold_resist, 2)
    if climate == "arid":
        return 0.5 + 0.25 * min(disease.heat_resist, 2)
    if climate == "humid":
        return 1.1 + 0.10 * min(disease.water_transmission, 2)
    return 1.0  # temperate


def spread_inside_country(country, disease) -> None:
    if country.infected == 0 or country.healthy <= 0:
        return

    mult = climate_multiplier(country.climate, disease)
    awareness_penalty = country.awareness * 0.8
    effective_rate = disease.infectivity * mult * 0.05 * (1.0 - awareness_penalty)

    new_infected = int(country.healthy * effective_rate * country.infection_ratio)
    new_infected = max(0, min(new_infected, country.healthy))
    country.infected += new_infected


def spread_land_borders(countries: dict, disease) -> None:
    seeds: dict[str, int] = {}

    for name, src in countries.items():
        if src.infected == 0 or src.infection_ratio < 0.0001:
            continue

        bird_bypass = disease.bird_transmission * 0.15
        src_open = max(0.0, 1.0 - src.awareness * 0.9)
        src_eff = min(1.0, src_open + bird_bypass)

        for neighbor_name in src.borders:
            if neighbor_name not in countries:
                continue
            dest = countries[neighbor_name]
            if dest.healthy <= 0:
                continue

            dest_open = max(0.0, 1.0 - dest.awareness * 0.9)
            dest_eff = min(1.0, dest_open + bird_bypass)

            seed = int(src.infected * 0.001 * src_eff * dest_eff)
            if seed > 0:
                seeds[neighbor_name] = seeds.get(neighbor_name, 0) + seed

    for name, count in seeds.items():
        dest = countries[name]
        dest.infected += min(count, dest.healthy)


def spread_air_routes(countries: dict, disease) -> None:
    airport_list = [c for c in countries.values() if c.airports > 0]
    sources = [c for c in airport_list if c.infected > 0 and c.infection_ratio >= 0.001]

    bird_bypass = disease.bird_transmission * 0.2

    for src in sources:
        closure = max(0.0, src.awareness - 0.5) * 2.0
        src_eff = min(1.0, max(0.0, 1.0 - closure) + bird_bypass)

        base_seed = int(
            src.infected * 0.00001 * src.airports
            * src_eff * (1 + disease.air_transmission)
        )
        if base_seed <= 0:
            continue

        for _ in range(src.airports):
            dest = random.choice(airport_list)
            if dest is src or dest.healthy <= 0:
                continue
            dest_closure = max(0.0, dest.awareness - 0.5) * 2.0
            dest_eff = min(1.0, max(0.0, 1.0 - dest_closure) + bird_bypass)
            seed = max(1, int(base_seed * dest_eff))
            dest.infected += min(seed, dest.healthy)


def spread_sea_routes(countries: dict, disease) -> None:
    port_list = [c for c in countries.values() if c.ports > 0]
    sources = [c for c in port_list if c.infected > 0 and c.infection_ratio >= 0.001]

    water_boost = 1.0 + disease.water_transmission * 0.3

    for src in sources:
        closure = max(0.0, src.awareness - 0.6) * 2.5
        src_eff = max(0.0, 1.0 - closure)

        base_seed = int(
            src.infected * 0.000008 * src.ports * src_eff * water_boost
        )
        if base_seed <= 0:
            continue

        for _ in range(src.ports):
            dest = random.choice(port_list)
            if dest is src or dest.healthy <= 0:
                continue
            dest_closure = max(0.0, dest.awareness - 0.6) * 2.5
            dest_eff = max(0.0, 1.0 - dest_closure)
            seed = max(1, int(base_seed * dest_eff))
            dest.infected += min(seed, dest.healthy)
