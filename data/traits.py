"""
Trait definitions for Plague Inc Bacteria simulation
Costs and effects are faithful to the real game's Bacteria plague type on Normal difficulty.

Each trait has:
  cost      - DNA points to evolve
  prereqs   - list of trait IDs that must be evolved first
  tree      - 'transmission' | 'symptom' | 'ability'
  effects   - dict of stat deltas applied to Disease when evolved
  special   - optional key for non-numeric effects
  desc      - short description shown to agent
"""

TRAITS = {
    # ══════════════════════════════════════════════════════════════════
    # TRANSMISSION TREE
    # ══════════════════════════════════════════════════════════════════

    "Water1": {
        "name": "Water 1",
        "tree": "transmission",
        "cost": 9,
        "prereqs": [],
        "effects": {"infectivity": +0.08, "water_transmission": 1},
        "desc": "Pathogen survives in water. Spread bonus in humid regions and via sea routes.",
    },
    "Water2": {
        "name": "Water 2",
        "tree": "transmission",
        "cost": 15,
        "prereqs": ["Water1"],
        "effects": {"infectivity": +0.10, "water_transmission": 1},
        "desc": "Enhanced water survival. Major boost to humid-climate and sea-route spread.",
    },
    "Air1": {
        "name": "Air 1",
        "tree": "transmission",
        "cost": 9,
        "prereqs": [],
        "effects": {"infectivity": +0.08, "air_transmission": 1},
        "desc": "Pathogen becomes airborne. Spread bonus in all climates, especially via airports.",
    },
    "Air2": {
        "name": "Air 2",
        "tree": "transmission",
        "cost": 14,
        "prereqs": ["Air1"],
        "effects": {"infectivity": +0.10, "air_transmission": 1},
        "desc": "Improved aerosolization. Significant spread boost via airports and arid climates.",
    },
    "ExtremeBioaerosol": {
        "name": "Extreme Bioaerosol",
        "tree": "transmission",
        "cost": 16,
        "prereqs": ["Air2", "Water2"],
        "effects": {"infectivity": +0.25},
        "desc": "Bypasses air/water filters. Massive spread in humid and arid climates and via all transit.",
    },
    "Blood1": {
        "name": "Blood 1",
        "tree": "transmission",
        "cost": 8,
        "prereqs": [],
        "effects": {"infectivity": +0.06},
        "desc": "Blood-borne transmission. Spreads through medical contact and bodily fluids.",
    },
    "Blood2": {
        "name": "Blood 2",
        "tree": "transmission",
        "cost": 13,
        "prereqs": ["Blood1"],
        "effects": {"infectivity": +0.08},
        "desc": "Enhanced blood-borne spread. Exploits healthcare infrastructure, especially in poor regions.",
    },
    "Rodent1": {
        "name": "Rodent 1",
        "tree": "transmission",
        "cost": 10,
        "prereqs": [],
        "effects": {"infectivity": +0.06},
        "special": "rural_boost",
        "desc": "Common fleas infected. Spread bonus in urban and high-density regions.",
    },
    "Rodent2": {
        "name": "Rodent 2",
        "tree": "transmission",
        "cost": 16,
        "prereqs": ["Rodent1"],
        "effects": {"infectivity": +0.08},
        "special": "rural_boost",
        "desc": "Rodents directly infected. Greater spread in urban regions.",
    },
    "Livestock1": {
        "name": "Livestock 1",
        "tree": "transmission",
        "cost": 7,
        "prereqs": [],
        "effects": {"infectivity": +0.05},
        "special": "rural_boost",
        "desc": "Farm animals carry the disease. Spread bonus in rural regions.",
    },
    "Livestock2": {
        "name": "Livestock 2",
        "tree": "transmission",
        "cost": 12,
        "prereqs": ["Livestock1"],
        "effects": {"infectivity": +0.07},
        "special": "rural_boost",
        "desc": "Wildlife infected. Greater spread across rural and agricultural regions.",
    },
    "Bird1": {
        "name": "Bird 1",
        "tree": "transmission",
        "cost": 12,
        "prereqs": [],
        "effects": {"infectivity": +0.08, "bird_transmission": 1},
        "desc": "Avian vector. Partially bypasses closed borders; bonus spread via airports.",
    },
    "Bird2": {
        "name": "Bird 2",
        "tree": "transmission",
        "cost": 18,
        "prereqs": ["Bird1"],
        "effects": {"infectivity": +0.10, "bird_transmission": 1},
        "desc": "Infected birds attack other species. Substantially bypasses border and travel restrictions.",
    },
    "Insect1": {
        "name": "Insect 1",
        "tree": "transmission",
        "cost": 9,
        "prereqs": [],
        "effects": {"infectivity": +0.05},
        "special": "humid_boost",
        "desc": "Insect vector. Strong spread bonus in humid and hot regions.",
    },
    "Insect2": {
        "name": "Insect 2",
        "tree": "transmission",
        "cost": 20,
        "prereqs": ["Insect1"],
        "effects": {"infectivity": +0.08},
        "special": "humid_boost",
        "desc": "Enhanced insect vector. Dominant spread pathway in tropical regions.",
    },
    "ExtremeZoonosis": {
        "name": "Extreme Zoonosis",
        "tree": "transmission",
        "cost": 22,
        "prereqs": ["Livestock2", "Rodent2", "Bird2"],
        "effects": {"infectivity": +0.20},
        "desc": "Crosses multiple species barriers. Massive spread, ignores most border controls.",
    },
    "ExtremeHematophagy": {
        "name": "Extreme Hematophagy",
        "tree": "transmission",
        "cost": 24,
        "prereqs": ["Insect2", "Blood2"],
        "effects": {"infectivity": +0.15},
        "desc": "Uses host lymphocytes to replicate. Extreme infectivity, especially in poor regions.",
    },

    # ══════════════════════════════════════════════════════════════════
    # SYMPTOM TREE
    # Chain: Nausea → Vomiting → Diarrhea → Dysentery
    #        Coughing → Sneezing → Pneumonia → PulmonaryFibrosis → PulmonaryOedema
    #          Pneumonia + Paralysis → TotalOrganFailure
    #        Rash → SkinLesions → Necrosis
    #        Insomnia → Paranoia → Insanity → Coma (+ Paralysis)
    #        Cysts → Abscesses
    #          Cysts + Rash → Tumours → SystemicInfection
    #        Fever → Sweating → Inflammation → Seizures
    #          Fever → HyperSensitivity
    #          Sweating + Cysts → ImmunesSuppression
    #        Anaemia → Haemophilia → InternalHaemorrhaging → HaemorrhagicShock
    #        ImmunesSuppression + Anaemia → Paralysis
    # ══════════════════════════════════════════════════════════════════

    "Nausea": {
        "name": "Nausea",
        "tree": "symptom",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.01, "severity": +0.01},
        "desc": "Stomach discomfort. Slight spread chance via close contact.",
    },
    "Vomiting": {
        "name": "Vomiting",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["Nausea"],
        "effects": {"infectivity": +0.03, "severity": +0.01},
        "desc": "Projectile vomiting spreads infected material. Modest infectivity boost.",
    },
    "Diarrhea": {
        "name": "Diarrhoea",
        "tree": "symptom",
        "cost": 6,
        "prereqs": ["Vomiting"],
        "effects": {"infectivity": +0.06, "severity": +0.04, "lethality": +0.01},
        "desc": "Digestive tract infection. Water-route spread bonus; dehydration deaths, especially in poor countries.",
    },
    "Dysentery": {
        "name": "Dysentery",
        "tree": "symptom",
        "cost": 19,
        "prereqs": ["Diarrhea"],
        "effects": {"infectivity": +0.08, "severity": +0.15, "lethality": +0.08},
        "desc": "Total digestive breakdown. Infected sewage, starvation, and mass death.",
    },
    "Coughing": {
        "name": "Coughing",
        "tree": "symptom",
        "cost": 4,
        "prereqs": [],
        "effects": {"infectivity": +0.03, "severity": +0.01},
        "desc": "Spreads pathogen into surroundings. Bonus in dense urban areas.",
    },
    "Sneezing": {
        "name": "Sneezing",
        "tree": "symptom",
        "cost": 5,
        "prereqs": ["Coughing"],
        "effects": {"infectivity": +0.05, "severity": +0.01},
        "desc": "Fluid discharge greatly increases infection rates.",
    },
    "Pneumonia": {
        "name": "Pneumonia",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["Sneezing"],
        "effects": {"infectivity": +0.03, "severity": +0.02},
        "desc": "Lung inflammation. Visible symptom; cold climates especially vulnerable.",
    },
    "PulmonaryFibrosis": {
        "name": "Pulmonary Fibrosis",
        "tree": "symptom",
        "cost": 6,
        "prereqs": ["Pneumonia"],
        "effects": {"infectivity": +0.03, "severity": +0.03, "lethality": +0.02},
        "desc": "Lung scarring causes extreme coughing. Fatal in humid climates with exertion.",
    },
    "PulmonaryOedema": {
        "name": "Pulmonary Oedema",
        "tree": "symptom",
        "cost": 7,
        "prereqs": ["PulmonaryFibrosis"],
        "effects": {"infectivity": +0.05, "severity": +0.04, "lethality": +0.02},
        "desc": "Fluid build-up releases pathogen into air. Heart failure and respiratory collapse.",
    },
    "Rash": {
        "name": "Rash",
        "tree": "symptom",
        "cost": 3,
        "prereqs": [],
        "effects": {"infectivity": +0.02, "severity": +0.01},
        "desc": "Visible skin rash. Slightly raises public awareness.",
    },
    "SkinLesions": {
        "name": "Skin Lesions",
        "tree": "symptom",
        "cost": 8,
        "prereqs": ["Rash"],
        "effects": {"infectivity": +0.11, "severity": +0.04},
        "desc": "Open wounds massively increase infectivity. Highly visible.",
    },
    "Necrosis": {
        "name": "Necrosis",
        "tree": "symptom",
        "cost": 27,
        "prereqs": ["SkinLesions"],
        "effects": {"infectivity": +0.10, "severity": +0.20, "lethality": +0.13},
        "desc": "Tissue death and gangrene. Decomposed bodies remain infectious. Extreme visibility.",
    },
    "Insomnia": {
        "name": "Insomnia",
        "tree": "symptom",
        "cost": 2,
        "prereqs": [],
        "effects": {"severity": +0.03},
        "desc": "Inability to sleep makes people irritable and unproductive.",
    },
    "Paranoia": {
        "name": "Paranoia",
        "tree": "symptom",
        "cost": 4,
        "prereqs": ["Insomnia"],
        "effects": {"severity": +0.04},
        "desc": "Irrational delusions cause victims to distrust authorities and refuse treatment.",
    },
    "Insanity": {
        "name": "Insanity",
        "tree": "symptom",
        "cost": 18,
        "prereqs": ["Paranoia"],
        "effects": {"infectivity": +0.06, "severity": +0.15},
        "special": "slows_cure",
        "desc": "Frontal-cortex damage causes mass behavioural collapse. Significantly harder to cure globally.",
    },
    "Coma": {
        "name": "Coma",
        "tree": "symptom",
        "cost": 21,
        "prereqs": ["Insanity", "Paralysis"],
        "effects": {"severity": +0.15, "lethality": +0.02},
        "desc": "Neuropathic brain-stem shutdown causes loss of consciousness. Often fatal. Hard to cure.",
    },
    "Cysts": {
        "name": "Cysts",
        "tree": "symptom",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.02, "severity": +0.02},
        "desc": "Painful lumps containing pathogen. Bursting spreads disease.",
    },
    "Abscesses": {
        "name": "Abscesses",
        "tree": "symptom",
        "cost": 2,
        "prereqs": ["Cysts"],
        "effects": {"infectivity": +0.04, "severity": +0.04},
        "desc": "Pockets of infected flesh burst and spread pathogen. Acts as breeding ground.",
    },
    "Tumours": {
        "name": "Tumours",
        "tree": "symptom",
        "cost": 11,
        "prereqs": ["Cysts", "Rash"],
        "effects": {"infectivity": +0.02, "lethality": +0.04},
        "desc": "Uncontrolled tumour growth disrupts cell pathways. High lethality, low visibility.",
    },
    "SystemicInfection": {
        "name": "Systemic Infection",
        "tree": "symptom",
        "cost": 17,
        "prereqs": ["Tumours"],
        "effects": {"infectivity": +0.06, "severity": +0.07, "lethality": +0.06},
        "desc": "Body-wide organ invasion. Fast, fatal spread through multiple tissue types.",
    },
    "Fever": {
        "name": "Fever",
        "tree": "symptom",
        "cost": 9,
        "prereqs": [],
        "effects": {"infectivity": +0.04, "severity": +0.03, "lethality": +0.03},
        "desc": "High temperature detected by airport scanners. Highly contagious and potentially fatal.",
    },
    "Sweating": {
        "name": "Sweating",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["Fever"],
        "effects": {"infectivity": +0.02, "severity": +0.01},
        "desc": "Infected fluid lost through sweating. More dangerous in cold countries.",
    },
    "HyperSensitivity": {
        "name": "Hyper Sensitivity",
        "tree": "symptom",
        "cost": 2,
        "prereqs": ["Fever"],
        "effects": {"infectivity": +0.01, "severity": +0.02},
        "desc": "Allergic reactions distract the immune system. Wealthy regions particularly vulnerable.",
    },
    "Inflammation": {
        "name": "Inflammation",
        "tree": "symptom",
        "cost": 5,
        "prereqs": ["Sweating"],
        "effects": {"infectivity": +0.02, "severity": +0.02, "lethality": +0.02},
        "desc": "Swelling obstructs breathing and bodily processes. Can be fatal.",
    },
    "Seizures": {
        "name": "Seizures",
        "tree": "symptom",
        "cost": 4,
        "prereqs": ["Inflammation"],
        "effects": {"infectivity": +0.01, "severity": +0.07, "lethality": +0.03},
        "desc": "Random blackouts reduce patient's ability to function. Occasionally fatal.",
    },
    "ImmunesSuppression": {
        "name": "Immune Suppression",
        "tree": "symptom",
        "cost": 12,
        "prereqs": ["Sweating", "Cysts"],
        "effects": {"infectivity": +0.02, "severity": +0.06, "lethality": +0.04},
        "desc": "Lymphocytes hijacked. Immune system collapses. Significantly increases replication freedom.",
    },
    "Anaemia": {
        "name": "Anaemia",
        "tree": "symptom",
        "cost": 2,
        "prereqs": [],
        "effects": {"infectivity": +0.01, "severity": +0.01},
        "desc": "Red blood cell destruction causes organ hypoxia.",
    },
    "Haemophilia": {
        "name": "Haemophilia",
        "tree": "symptom",
        "cost": 3,
        "prereqs": ["Anaemia"],
        "effects": {"infectivity": +0.04, "severity": +0.03},
        "desc": "Blood refuses to clot. Significant infectivity from uncontrolled bleeding.",
    },
    "InternalHaemorrhaging": {
        "name": "Internal Haemorrhaging",
        "tree": "symptom",
        "cost": 12,
        "prereqs": ["Haemophilia"],
        "effects": {"severity": +0.09, "lethality": +0.07},
        "desc": "Arterial membranes break down. Rapid internal bleeding and death.",
    },
    "HaemorrhagicShock": {
        "name": "Haemorrhagic Shock",
        "tree": "symptom",
        "cost": 23,
        "prereqs": ["InternalHaemorrhaging"],
        "effects": {"severity": +0.15, "lethality": +0.15},
        "desc": "Catastrophic blood loss causes oxygen deprivation, unconsciousness, and death.",
    },
    "Paralysis": {
        "name": "Paralysis",
        "tree": "symptom",
        "cost": 10,
        "prereqs": ["ImmunesSuppression", "Anaemia"],
        "effects": {"infectivity": +0.01, "severity": +0.05, "lethality": +0.01},
        "desc": "Motor neurons destroyed. Patients paralysed and extremely hard to cure.",
    },
    "TotalOrganFailure": {
        "name": "Total Organ Failure",
        "tree": "symptom",
        "cost": 28,
        "prereqs": ["Pneumonia", "Paralysis"],
        "effects": {"severity": +0.20, "lethality": +0.25},
        "desc": "Catastrophic cell death across all tissue types. Rapid, universal organ shutdown.",
    },

    # ══════════════════════════════════════════════════════════════════
    # ABILITY TREE
    # ══════════════════════════════════════════════════════════════════

    "DrugResistance1": {
        "name": "Drug Resistance 1",
        "tree": "ability",
        "cost": 11,
        "prereqs": [],
        "effects": {"drug_resist": 1},
        "desc": "Resists class 1-2 antibiotics. Cure research slowed 15%. More effective in wealthy countries.",
    },
    "DrugResistance2": {
        "name": "Drug Resistance 2",
        "tree": "ability",
        "cost": 25,
        "prereqs": ["DrugResistance1"],
        "effects": {"drug_resist": 1},
        "desc": "Full antibiotic resistance. Cure research slowed 30% total.",
    },
    "ColdResist1": {
        "name": "Cold Resistance 1",
        "tree": "ability",
        "cost": 7,
        "prereqs": [],
        "effects": {"cold_resist": 1},
        "desc": "Survives cold temperatures. Spread in cold climates significantly improved.",
    },
    "ColdResist2": {
        "name": "Cold Resistance 2",
        "tree": "ability",
        "cost": 12,
        "prereqs": ["ColdResist1"],
        "effects": {"cold_resist": 1},
        "desc": "Thrives in cold. Normal spread rates in Arctic and northern regions.",
    },
    "HeatResist1": {
        "name": "Heat Resistance 1",
        "tree": "ability",
        "cost": 11,
        "prereqs": [],
        "effects": {"heat_resist": 1},
        "desc": "Survives high temperatures. Spread in arid and hot climates improved.",
    },
    "HeatResist2": {
        "name": "Heat Resistance 2",
        "tree": "ability",
        "cost": 22,
        "prereqs": ["HeatResist1"],
        "effects": {"heat_resist": 1},
        "desc": "Optimal heat adaptation. Normal spread rates in arid regions.",
    },
    "GeneticHardening1": {
        "name": "Genetic Hardening 1",
        "tree": "ability",
        "cost": 7,
        "prereqs": [],
        "effects": {"genetic_hardening": 1},
        "desc": "Genome stabilizes. Cure research globally slowed by 15%.",
    },
    "GeneticHardening2": {
        "name": "Genetic Hardening 2",
        "tree": "ability",
        "cost": 22,
        "prereqs": ["GeneticHardening1"],
        "effects": {"genetic_hardening": 1},
        "desc": "Pathogen resists lab analysis. Cure research slowed 30% total.",
    },
    "GeneticReShuffle1": {
        "name": "Genetic ReShuffle 1",
        "tree": "ability",
        "cost": 17,
        "prereqs": ["GeneticHardening1"],
        "effects": {},
        "special": "reshuffle_25",
        "desc": "ONE-TIME USE. Resets cure progress by 25%. Use when cure is > 30%.",
    },
    "GeneticReShuffle2": {
        "name": "Genetic ReShuffle 2",
        "tree": "ability",
        "cost": 21,
        "prereqs": ["GeneticReShuffle1"],
        "effects": {},
        "special": "reshuffle_40",
        "desc": "ONE-TIME USE. Resets cure progress by 40%. Use when cure is > 50%.",
    },
    "GeneticReShuffle3": {
        "name": "Genetic ReShuffle 3",
        "tree": "ability",
        "cost": 25,
        "prereqs": ["GeneticReShuffle2"],
        "effects": {},
        "special": "reshuffle_60",
        "desc": "ONE-TIME USE. Resets cure progress by 60%. Emergency use only.",
    },
}


def get_available_traits(evolved: set, dna: int) -> dict:
    """Return traits the player can currently evolve (prereqs met, not yet evolved)."""
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
ailable = {}
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
    return {tid: t for tid, t in available.items() if t["cost"] <= dna}lable = {}
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