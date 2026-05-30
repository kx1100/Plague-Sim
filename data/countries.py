"""
World data for Plague Inc simulation.
~55 regions matching the real game's geography, populations, and connectivity.
Climate types: 'arid', 'cold', 'humid', 'temperate'
Wealth 0-1: affects healthcare quality, cure research contribution, and detection speed.
"""

# Each entry: name, population, climate, wealth (0-1), airports (0-3), ports (0-3), land_borders
# Land borders are defined once here; simulation computes bidirectional graph automatically.
COUNTRIES_RAW = [
    # ── NORTH AMERICA ──────────────────────────────────────────────────────────
    ("Greenland",           56_000,         "cold",       0.65, 1, 1, ["Canada"]),
    ("Canada",              38_000_000,     "cold",       0.90, 3, 2, ["USA"]),
    ("USA",                 330_000_000,    "temperate",  0.95, 3, 3, ["Canada", "Mexico"]),
    ("Mexico",              128_000_000,    "arid",       0.50, 2, 2, ["USA", "Central America"]),
    ("Central America",     50_000_000,     "humid",      0.30, 1, 2, ["Mexico", "Colombia"]),
    ("Caribbean",           45_000_000,     "humid",      0.40, 1, 2, []),

    # ── SOUTH AMERICA ───────────────────────────────────────────────────────────
    ("Colombia",            50_000_000,     "humid",      0.40, 1, 2, ["Central America", "Venezuela", "Brazil", "Peru"]),
    ("Venezuela",           28_000_000,     "humid",      0.35, 1, 2, ["Colombia", "Brazil"]),
    ("Brazil",              213_000_000,    "humid",      0.45, 2, 3, ["Venezuela", "Colombia", "Peru", "Bolivia", "Argentina"]),
    ("Peru",                33_000_000,     "arid",       0.35, 1, 1, ["Colombia", "Brazil", "Bolivia", "Chile"]),
    ("Bolivia",             11_700_000,     "arid",       0.30, 1, 0, ["Peru", "Brazil", "Argentina", "Chile"]),
    ("Argentina",           45_000_000,     "temperate",  0.45, 2, 2, ["Bolivia", "Brazil", "Chile"]),
    ("Chile",               19_000_000,     "arid",       0.50, 1, 2, ["Peru", "Bolivia", "Argentina"]),

    # ── EUROPE ──────────────────────────────────────────────────────────────────
    ("Iceland",             360_000,        "cold",       0.90, 1, 1, []),
    ("UK",                  67_000_000,     "temperate",  0.90, 2, 2, []),
    ("Ireland",             5_000_000,      "temperate",  0.85, 1, 1, []),
    ("Norway",              5_400_000,      "cold",       0.95, 1, 2, ["Sweden", "Finland", "Russia"]),
    ("Sweden",              10_000_000,     "cold",       0.90, 1, 2, ["Norway", "Finland", "Denmark"]),
    ("Finland",             5_500_000,      "cold",       0.85, 1, 1, ["Norway", "Sweden", "Russia"]),
    ("Denmark",             5_800_000,      "cold",       0.90, 1, 2, ["Germany", "Sweden"]),
    ("Germany",             83_000_000,     "temperate",  0.90, 2, 1, ["Denmark", "Netherlands", "Belgium", "France", "Switzerland", "Austria", "Czech Republic", "Poland"]),
    ("Netherlands",         17_000_000,     "temperate",  0.90, 2, 2, ["Germany", "Belgium"]),
    ("Belgium",             11_000_000,     "temperate",  0.85, 1, 1, ["Netherlands", "Germany", "France"]),
    ("France",              67_000_000,     "temperate",  0.85, 2, 2, ["Belgium", "Germany", "Switzerland", "Italy", "Spain"]),
    ("Spain",               47_000_000,     "arid",       0.75, 2, 2, ["France", "Portugal"]),
    ("Portugal",            10_000_000,     "temperate",  0.70, 1, 2, ["Spain"]),
    ("Italy",               60_000_000,     "temperate",  0.80, 2, 2, ["France", "Switzerland", "Austria", "Balkans"]),
    ("Switzerland",         8_500_000,      "cold",       0.95, 1, 0, ["France", "Germany", "Italy", "Austria"]),
    ("Austria",             9_000_000,      "temperate",  0.85, 1, 0, ["Germany", "Switzerland", "Italy", "Czech Republic", "Hungary", "Balkans"]),
    ("Czech Republic",      10_700_000,     "temperate",  0.75, 1, 0, ["Germany", "Austria", "Poland", "Slovakia"]),
    ("Slovakia",            5_500_000,      "temperate",  0.65, 1, 0, ["Czech Republic", "Poland", "Hungary", "Austria", "Ukraine"]),
    ("Poland",              38_000_000,     "cold",       0.70, 1, 1, ["Germany", "Czech Republic", "Slovakia", "Ukraine", "Belarus", "Baltic States", "Russia"]),
    ("Baltic States",       6_000_000,      "cold",       0.70, 1, 2, ["Poland", "Belarus", "Finland", "Russia"]),
    ("Hungary",             10_000_000,     "temperate",  0.65, 1, 0, ["Austria", "Slovakia", "Ukraine", "Romania", "Balkans"]),
    ("Romania",             19_000_000,     "temperate",  0.55, 1, 1, ["Hungary", "Ukraine", "Moldova", "Bulgaria", "Balkans"]),
    ("Moldova",             4_000_000,      "temperate",  0.30, 1, 0, ["Ukraine", "Romania"]),
    ("Bulgaria",            7_000_000,      "temperate",  0.55, 1, 1, ["Romania", "Balkans", "Greece", "Turkey"]),
    ("Balkans",             20_000_000,     "temperate",  0.50, 1, 1, ["Italy", "Austria", "Hungary", "Romania", "Bulgaria", "Greece", "Turkey"]),
    ("Greece",              11_000_000,     "temperate",  0.65, 1, 2, ["Balkans", "Bulgaria", "Turkey"]),
    ("Ukraine",             44_000_000,     "temperate",  0.40, 1, 1, ["Poland", "Slovakia", "Hungary", "Romania", "Moldova", "Belarus", "Russia"]),
    ("Belarus",             9_500_000,      "cold",       0.45, 1, 0, ["Poland", "Baltic States", "Ukraine", "Russia"]),
    ("Russia",              145_000_000,    "cold",       0.55, 3, 2, ["Norway", "Finland", "Baltic States", "Belarus", "Ukraine", "Kazakhstan", "China", "Mongolia"]),

    # ── AFRICA ──────────────────────────────────────────────────────────────────
    ("Morocco",             37_000_000,     "arid",       0.40, 1, 2, ["Algeria", "W. Africa"]),
    ("Algeria",             44_000_000,     "arid",       0.40, 1, 1, ["Morocco", "Libya", "W. Africa"]),
    ("Libya",               7_000_000,      "arid",       0.35, 1, 1, ["Algeria", "Egypt", "W. Africa"]),
    ("Egypt",               100_000_000,    "arid",       0.45, 1, 2, ["Libya", "Sudan", "Middle East"]),
    ("Sudan",               45_000_000,     "arid",       0.20, 1, 1, ["Egypt", "C. Africa", "E. Africa", "Middle East"]),
    ("W. Africa",           400_000_000,    "humid",      0.20, 1, 2, ["Morocco", "Algeria", "Libya", "C. Africa"]),
    ("C. Africa",           130_000_000,    "humid",      0.15, 1, 0, ["W. Africa", "E. Africa", "Sudan"]),
    ("E. Africa",           250_000_000,    "humid",      0.25, 1, 2, ["C. Africa", "Sudan", "S. Africa"]),
    ("S. Africa",           60_000_000,     "arid",       0.50, 1, 2, ["E. Africa"]),
    ("Madagascar",          27_000_000,     "humid",      0.20, 1, 1, []),

    # ── MIDDLE EAST ─────────────────────────────────────────────────────────────
    ("Turkey",              84_000_000,     "arid",       0.60, 2, 2, ["Balkans", "Bulgaria", "Greece", "Caucasus", "Middle East"]),
    ("Caucasus",            15_000_000,     "temperate",  0.40, 1, 1, ["Turkey", "Russia", "Middle East", "C. Asia"]),
    ("Middle East",         80_000_000,     "arid",       0.60, 2, 2, ["Egypt", "Turkey", "Caucasus", "Iran", "Saudi Arabia", "Sudan"]),
    ("Saudi Arabia",        35_000_000,     "arid",       0.75, 2, 2, ["Middle East", "Yemen"]),
    ("Yemen",               30_000_000,     "arid",       0.20, 1, 1, ["Saudi Arabia"]),
    ("Iran",                84_000_000,     "arid",       0.45, 1, 1, ["Turkey", "Caucasus", "Middle East", "Pakistan", "C. Asia"]),
    ("C. Asia",             100_000_000,    "arid",       0.25, 1, 0, ["Russia", "China", "Iran", "Pakistan", "Caucasus", "Kazakhstan"]),
    ("Kazakhstan",          19_000_000,     "arid",       0.45, 1, 0, ["Russia", "China", "C. Asia"]),

    # ── ASIA ────────────────────────────────────────────────────────────────────
    ("Pakistan",            220_000_000,    "arid",       0.30, 1, 1, ["Iran", "India", "C. Asia", "China"]),
    ("India",               1_380_000_000,  "humid",      0.35, 3, 3, ["Pakistan", "China", "SE Asia"]),
    ("China",               1_400_000_000,  "humid",      0.45, 3, 3, ["Russia", "Kazakhstan", "C. Asia", "Pakistan", "India", "SE Asia", "South Korea", "Mongolia"]),
    ("Mongolia",            3_300_000,      "cold",       0.30, 1, 0, ["Russia", "China"]),
    ("South Korea",         52_000_000,     "temperate",  0.80, 2, 2, ["China"]),
    ("Japan",               126_000_000,    "temperate",  0.90, 3, 2, []),
    ("SE Asia",             220_000_000,    "humid",      0.35, 2, 3, ["China", "India"]),
    ("Philippines",         110_000_000,    "humid",      0.30, 2, 2, []),
    ("Indonesia",           273_000_000,    "humid",      0.35, 2, 3, []),
    ("Australia",           25_000_000,     "arid",       0.90, 3, 3, []),
    ("New Zealand",         5_000_000,      "temperate",  0.85, 2, 1, []),
]