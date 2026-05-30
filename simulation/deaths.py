def process_deaths(country, disease) -> None:
    if country.infected == 0 or disease.lethality <= 0:
        return

    # Wealth represents healthcare quality; high wealth = lower mortality
    healthcare_factor = 1.0 - country.wealth * 0.7
    daily_death_rate = disease.lethality * healthcare_factor * 0.01

    deaths = int(country.infected * daily_death_rate)
    deaths = min(deaths, country.infected)
    if deaths <= 0:
        return

    country.dead += deaths
    country.infected -= deaths
