"""
Trait definitions for Plague Inc Bacteria simulation.
Faithful to the real game's Bacteria plague type on Normal difficulty.

Each trait has:
  cost      - DNA points to evolve
  prereqs   - list of trait IDs that must be evolved first
  tree      - 'transmission' | 'symptom' | 'ability'
  effects   - dict of stat deltas applied to Disease when evolved
  special   - optional key for non-numeric effects
  desc      - short description shown to player
"""

TRAITS = {
    # ══════════════════════════════════════════════════════════════════
    # TRANSMISSION TREE
    # ══════════════════════════════════════════════════════════════════

    "Water1": {
        "name": "Water 1",
        "tree": "transmission",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.08, "water_transmission": 1},
        "desc": "Pathogen survives longer in water. Bonus spread in humid regions and via sea routes.",
    },
    "Water2": {
        "name": "Water 2",
        "tree": "transmission",
        "cost": 3,
        "prereqs": ["Water1"],
        "effects": {"infectivity": +0.10, "water_transmission": 1},
        "desc": "Enhanced water survival. Major boost to humid-climate and sea-route spread.",
    },
    "Air1": {
        "name": "Air 1",
        "tree": "transmission",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.08, "air_transmission": 1},
        "desc": "Pathogen becomes airborne. Moderate spread boost in all climates.",
    },
    "Air2": {
        "name": "Air 2",
        "tree": "transmission",
        "cost": 3,
        "prereqs": ["Air1"],
        "effects": {"infectivity": +0.10, "air_transmission": 1},
        "desc": "Improved aerosolization. Significant spread boost, especially via airports.",
    },
    "ExtremeBioaerosol": {
        "name": "Extreme Bioaerosol",
        "tree": "transmission",
        "cost": 5,
        "prereqs": ["Air2", "Water2"],
        "effects": {"infectivity": +0.25},
        "desc": "Ultimate transmission upgrade. Massively boosts spread in all environments.",
    },
    "Blood1": {
        "name": "Blood 1",
        "tree": "transmission",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.06},
        "desc": "Blood-borne transmission. Spreads through medical settings and contact.",
    },
    "Blood2": {
        "name": "Blood 2",
        "tree": "transmission",
        "cost": 3,
        "prereqs": ["Blood1"],
        "effects": {"infectivity": +0.08},
        "desc": "Enhanced blood-borne transmission. Exploits healthcare infrastructure.",
    },
    "Rodents": {
        "name": "Rodents",
        "tree": "transmission",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.06},
        "special": "rural_boost",
        "desc": "Spread via rodents. Bonus in rural and low-wealth regions.",
    },
    "Livestock": {
        "name": "Livestock",
        "tree": "transmission",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.05},
        "special": "rural_boost",
        "desc": "Spread via farm animals. Bonus in agricultural regions.",
    },
    "Bird1": {
        "name": "Bird 1",
        "tree": "transmission",
        "cost": 3,
        "prereqs": [],
        "effects": {"infectivity": +0.08, "bird_transmission": 1},
        "desc": "Avian vector. Partially bypasses closed borders; bonus spread via airports.",
    },
    "Bird2": {
        "name": "Bird 2",
        "tree": "transmission",
        "cost": 4,
        "prereqs": ["Bird1"],
        "effects": {"infectivity": +0.10, "bird_transmission": 1},
        "desc": "Enhanced avian vector. Substantially bypasses travel restrictions.",
    },
    "Insect1": {
        "name": "Insect 1",
        "tree": "transmission",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.05},
        "special": "humid_boost",
        "desc": "Insect vector. Strong bonus spread in humid and hot regions.",
    },
    "Insect2": {
        "name": "Insect 2",
        "tree": "transmission",
        "cost": 3,
        "prereqs": ["Insect1"],
        "effects": {"infectivity": +0.08},
        "special": "humid_boost",
        "desc": "Enhanced insect vector. Dominant spread pathway in tropical regions.",
    },
    "ExtremeZoonosis": {
        "name": "Extreme Zoonosis",
        "tree": "transmission",
        "cost": 5,
        "prereqs": ["Livestock", "Rodents", "Bird2"],
        "effects": {"infectivity": +0.20},
        "desc": "Ultimate animal vector. Massive spread boost, ignores most border controls.",
    },
    "BacterialResilience1": {
        "name": "Bacterial Resilience 1",
        "tree": "transmission",
        "cost": 1,
        "prereqs": [],
        "effects": {"infectivity": +0.02},
        "desc": "Minor structural improvement. Small infectivity boost.",
    },
    "BacterialResilience2": {
        "name": "Bacterial Resilience 2",
        "tree": "transmission",
        "cost": 1,
        "prereqs": ["BacterialResilience1"],
        "effects": {"infectivity": +0.02},
        "desc": "Continued structural hardening.",
    },
    "BacterialResilience3": {
        "name": "Bacterial Resilience 3",
        "tree": "transmission",
        "cost": 2,
        "prereqs": ["BacterialResilience2"],
        "effects": {"infectivity": +0.03},
        "desc": "Advanced resilience. Moderate infectivity boost.",
    },
    "BacterialResilience4": {
        "name": "Bacterial Resilience 4",
        "tree": "transmission",
        "cost": 2,
        "prereqs": ["BacterialResilience3"],
        "effects": {"infectivity": +0.03},
        "desc": "Near-optimal bacterial structure.",
    },
    "BacterialResilience5": {
        "name": "Bacterial Resilience 5",
        "tree": "transmission",
        "cost": 3,
        "prereqs": ["BacterialResilience4"],
        "effects": {"infectivity": +0.04},
        "desc": "Peak bacterial evolution. Significant infectivity boost.",
    },

    # ══════════════════════════════════════════════════════════════════
    # SYMPTOM TREE  (most raise severity, which accelerates cure research)
    # ══════════════════════════════════════════════════════════════════

    "Coughing": {
        "name": "Coughing",
        "tree": "symptom",
        "cost": 1,
        "prereqs": [],
        "effects": {"infectivity": +0.01, "severity": +0.05},
        "desc": "Persistent cough. Minor air-spread boost, slightly visible to authorities.",
    },
    "Sneezing": {
        "name": "Sneezing",
        "tree": "symptom",
        "cost": 1,
        "prereqs": ["Coughing"],
        "effects": {"infectivity": +0.01, "severity": +0.04},
        "desc": "Sneezing spreads the pathogen. Slightly increases detection risk.",
    },
    "Pneumonia": {
        "name": "Pneumonia",
        "tree": "symptom",
        "cost": 2,
        "prereqs": ["Sneezing"],
        "effects": {"lethality": +0.03, "severity": +0.08},
        "desc": "Lung inflammation. Notable mortality increase, high visibility.",
    },
    "Nausea": {
        "name": "Nausea",
        "tree": "symptom",
        "cost": 1,
        "prereqs": [],
        "effects": {"severity": +0.04},
        "desc": "Debilitating nausea. No spread boost, but raises severity.",
    },
    "Vomiting": {
        "name": "Vomiting",
        "tree": "symptom",
        "cost": 1,
        "prereqs": ["Nausea"],
        "effects": {"infectivity": +0.01, "severity": +0.05},
        "desc": "Vomiting spreads pathogen via fecal-oral route.",
    },
    "Diarrhea": {
        "name": "Diarrhea",
        "tree": "symptom",
        "cost": 1,
        "prereqs": ["Vomiting"],
        "effects": {"infectivity": +0.01, "severity": +0.04},
        "desc": "Diarrhea greatly enhances water-route transmission.",
    },
    "Dysentery": {
        "name": "Dysentery",
        "tree": "symptom",
        "cost": 2,
        "prereqs": ["Diarrhea"],
        "effects": {"lethality": +0.03, "severity": +0.06},
        "desc": "Severe gut infection. Meaningful lethality, especially in low-wealth regions.",
    },
    "Rash": {
        "name": "Rash",
        "tree": "symptom",
        "cost": 1,
        "prereqs": [],
        "effects": {"severity": +0.05},
        "desc": "Visible skin rash. Raises public awareness, no direct mortality.",
    },
    "SkinLesions": {
        "name": "Skin Lesions",
        "tree": "symptom",
        "cost": 2,
        "prereqs": ["Rash"],
        "effects": {"lethality": +0.03, "severity": +0.08},
        "desc": "Necrotic skin lesions. High visibility, moderate lethality.",
    },
    "Necrosis": {
        "name": "Necrosis",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["SkinLesions"],
        "effects": {"lethality": +0.08, "severity": +0.10},
        "desc": "Tissue death. High lethality and visibility — will trigger rapid cure research.",
    },
    "Fever": {
        "name": "Fever",
        "tree": "symptom",
        "cost": 1,
        "prereqs": [],
        "effects": {"severity": +0.04},
        "desc": "Fever detectable by thermal scanners. Raises airport/port detection.",
    },
    "Sweating": {
        "name": "Sweating",
        "tree": "symptom",
        "cost": 1,
        "prereqs": ["Fever"],
        "effects": {"infectivity": +0.01, "severity": +0.03},
        "desc": "Profuse sweating spreads pathogen through skin contact.",
    },
    "ImmunesSuppression": {
        "name": "Immune Suppression",
        "tree": "symptom",
        "cost": 2,
        "prereqs": ["Sweating"],
        "effects": {"lethality": +0.05, "severity": +0.05},
        "desc": "Weakens host immune system. Increases lethality significantly.",
    },
    "Cysts": {
        "name": "Cysts",
        "tree": "symptom",
        "cost": 1,
        "prereqs": [],
        "effects": {"severity": +0.02},
        "desc": "Internal cysts. Minor severity increase, hard to detect early.",
    },
    "Tumours": {
        "name": "Tumours",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["Cysts", "Rash"],
        "effects": {"lethality": +0.07, "severity": +0.10},
        "desc": "Rapid tumour growth. High lethality once tumours are detected.",
    },
    "SystemicInfection": {
        "name": "Systemic Infection",
        "tree": "symptom",
        "cost": 4,
        "prereqs": ["Tumours"],
        "effects": {"lethality": +0.10, "severity": +0.12},
        "desc": "Full systemic invasion. Organ failure cascade begins.",
    },
    "Anaemia": {
        "name": "Anaemia",
        "tree": "symptom",
        "cost": 2,
        "prereqs": [],
        "effects": {"lethality": +0.03},
        "desc": "Blood cell destruction. Moderate lethality increase.",
    },
    "Haemophilia": {
        "name": "Haemophilia",
        "tree": "symptom",
        "cost": 2,
        "prereqs": ["Anaemia"],
        "effects": {"lethality": +0.05},
        "desc": "Prevents blood clotting. Significant lethality.",
    },
    "HaemorrhagicShock": {
        "name": "Haemorrhagic Shock",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["Haemophilia"],
        "effects": {"lethality": +0.12, "severity": +0.10},
        "desc": "Catastrophic blood loss. Very high lethality and visibility. Use carefully.",
    },
    "Paralysis": {
        "name": "Paralysis",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["ImmunesSuppression", "Anaemia"],
        "effects": {"lethality": +0.06},
        "desc": "Nervous system damage causes paralysis. Moderate lethality.",
    },
    "Insanity": {
        "name": "Insanity",
        "tree": "symptom",
        "cost": 3,
        "prereqs": [],
        "effects": {"severity": +0.05},
        "special": "slows_cure",
        "desc": "Mass insanity disrupts cure research. Globally slows cure by 10%.",
    },
    "Coma": {
        "name": "Coma",
        "tree": "symptom",
        "cost": 4,
        "prereqs": ["Paralysis", "Insanity"],
        "effects": {"lethality": +0.10},
        "desc": "Coma precedes death. High lethality, lower severity than visible symptoms.",
    },
    "InternalHaemorrhaging": {
        "name": "Internal Haemorrhaging",
        "tree": "symptom",
        "cost": 4,
        "prereqs": [],
        "effects": {"lethality": +0.15, "severity": +0.12},
        "desc": "Massive internal bleeding. Very high lethality. Triggers emergency cure effort.",
    },
    "TotalOrganFailure": {
        "name": "Total Organ Failure",
        "tree": "symptom",
        "cost": 5,
        "prereqs": ["Pneumonia", "Paralysis"],
        "effects": {"lethality": +0.20, "severity": +0.15},
        "desc": "Complete systemic shutdown. Highest lethality in the tree. Endgame trait.",
    },

    # ══════════════════════════════════════════════════════════════════
    # ABILITY TREE
    # ══════════════════════════════════════════════════════════════════

    "DrugResistance1": {
        "name": "Drug Resistance 1",
        "tree": "ability",
        "cost": 3,
        "prereqs": [],
        "effects": {"drug_resist": 1},
        "desc": "Resists antibiotics. Each aware country contributes 15% less to cure research.",
    },
    "DrugResistance2": {
        "name": "Drug Resistance 2",
        "tree": "ability",
        "cost": 4,
        "prereqs": ["DrugResistance1"],
        "effects": {"drug_resist": 1},
        "desc": "Full antibiotic resistance. Cure research reduced 30% from drug treatments.",
    },
    "ColdResist1": {
        "name": "Cold Resist 1",
        "tree": "ability",
        "cost": 2,
        "prereqs": [],
        "effects": {"cold_resist": 1},
        "desc": "Survives cold temperatures. Spread in cold climates significantly improved.",
    },
    "ColdResist2": {
        "name": "Cold Resist 2",
        "tree": "ability",
        "cost": 3,
        "prereqs": ["ColdResist1"],
        "effects": {"cold_resist": 1},
        "desc": "Thrives in cold. Normal spread rates in Arctic/cold regions.",
    },
    "HeatResist1": {
        "name": "Heat Resist 1",
        "tree": "ability",
        "cost": 2,
        "prereqs": [],
        "effects": {"heat_resist": 1},
        "desc": "Survives high temperatures. Spread in arid/hot climates improved.",
    },
    "HeatResist2": {
        "name": "Heat Resist 2",
        "tree": "ability",
        "cost": 3,
        "prereqs": ["HeatResist1"],
        "effects": {"heat_resist": 1},
        "desc": "Optimal heat adaptation. Normal spread rates in arid regions.",
    },
    "GeneticHardening1": {
        "name": "Genetic Hardening 1",
        "tree": "ability",
        "cost": 2,
        "prereqs": [],
        "effects": {"genetic_hardening": 1},
        "desc": "Genome stabilizes. Global cure research slowed by 15%.",
    },
    "GeneticHardening2": {
        "name": "Genetic Hardening 2",
        "tree": "ability",
        "cost": 3,
        "prereqs": ["GeneticHardening1"],
        "effects": {"genetic_hardening": 1},
        "desc": "Near-impenetrable genetic structure. Cure research slowed 30% total.",
    },
    "GeneticReShuffle1": {
        "name": "Genetic ReShuffle 1",
        "tree": "ability",
        "cost": 4,
        "prereqs": ["GeneticHardening1"],
        "effects": {},
        "special": "reshuffle_25",
        "desc": "ONE-TIME USE. Resets cure progress by 25%. Use when cure is > 30%.",
    },
    "GeneticReShuffle2": {
        "name": "Genetic ReShuffle 2",
        "tree": "ability",
        "cost": 5,
        "prereqs": ["GeneticReShuffle1"],
        "effects": {},
        "special": "reshuffle_40",
        "desc": "ONE-TIME USE. Resets cure progress by 40%. Use when cure is > 50%.",
    },
    "GeneticReShuffle3": {
        "name": "Genetic ReShuffle 3",
        "tree": "ability",
        "cost": 6,
        "prereqs": ["GeneticReShuffle2"],
        "effects": {},
        "special": "reshuffle_60",
        "desc": "ONE-TIME USE. Resets cure progress by 60%. Emergency use only.",
    },
}


def get_available_traits(evolved: set, dna: int) -> dict:
    """Return traits the player can currently evolve (prereqs met, not yet evolved, can afford)."""
    available = {}
    for tid, trait in TRAITS.items():
        if tid in evolved:
            continue
        if not all(p in evolved for p in trait["prereqs"]):
            continue
        available[tid] = trait
    return available


def get_affordable_traits(evolved: set, dna: int) -> dict:
    """Return traits that are available AND affordable."""
    available = get_available_traits(evolved, dna)
    return {tid: t for tid, t in available.items() if t["cost"] <= dna}