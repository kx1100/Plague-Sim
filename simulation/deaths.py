# Daily mortality among the infected, before healthcare is applied.
#
# Tuned so the 32 lethality traits actually matter: at 0.01 a fully evolved
# disease needed ~506 days to kill 95% of a saturated world, which is longer
# than the 600-day episode allows, so the `extinct` win was unreachable by
# arithmetic rather than by difficulty.
_BASE_DAILY_DEATH_RATE = 0.03

# Wealth stands in for healthcare quality. At wealth 1.0 mortality is cut 70%.
_HEALTHCARE_SCALING = 0.7


def process_deaths(country, disease) -> None:
    if country.infected == 0 or disease.lethality <= 0:
        return

    healthcare_factor = 1.0 - country.wealth * _HEALTHCARE_SCALING
    daily_death_rate = disease.lethality * healthcare_factor * _BASE_DAILY_DEATH_RATE

    deaths = int(country.infected * daily_death_rate)
    deaths = min(deaths, country.infected)
    if deaths <= 0:
        return

    country.dead += deaths
    country.infected -= deaths
