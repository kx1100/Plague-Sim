from data.countries import COUNTRIES_RAW
from models.country import Country


def build_world():
    countries = {}

    for row in COUNTRIES_RAW:
        country = Country(
            name=row[0],
            population=row[1],
            climate=row[2],
            wealth=row[3],
            airports=row[4],
            ports=row[5],
            borders=list(row[6]),
        )
        countries[country.name] = country

    # The raw data defines borders one-directionally; make them bidirectional.
    for name, country in countries.items():
        for neighbor in country.borders:
            if neighbor in countries and name not in countries[neighbor].borders:
                countries[neighbor].borders.append(name)

    return countries
