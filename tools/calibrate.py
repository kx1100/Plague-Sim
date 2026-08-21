"""
calibrate.py — balance harness for the plague benchmark.

Runs a set of reference policies across several seeds and reports the metrics
that decide whether the environment is measuring skill or measuring noise:

  * DNA budget      — total DNA granted per episode. Must stay scarce all game.
  * Traits evolved  — how much of the 697-DNA tree the agent could afford.
  * Score spread    — a good env separates expert play from careless play.
  * Score mix       — how much of plague_score comes from leftover DNA rather
                      than from actually infecting and killing people.

Usage:
    python tools/calibrate.py
    python tools/calibrate.py --seeds 8 --verbose
"""

import argparse
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.traits import TRAITS                    # noqa: E402
from env import PlagueEnv                         # noqa: E402

# Seeds chosen to span climate, wealth, and connectivity.
DEFAULT_SEEDS = [
    "India", "China", "USA", "Brazil", "Egypt",
    "Russia", "Australia", "Madagascar", "Germany", "Indonesia",
]

_NON_SYMPTOM = [tid for tid, t in TRAITS.items() if t["tree"] != "symptom"]


# ── Reference policies ────────────────────────────────────────────────────────

def policy_pass(obs):
    """Do nothing. The floor any real agent must beat."""
    return None


def policy_random(obs):
    """Pick any affordable trait at random. Careless but active."""
    affordable = list(obs["available_traits"])
    return random.choice(affordable) if affordable else None


def policy_greedy(obs):
    """Always buy the most lethal thing available. The classic beginner error."""
    affordable = obs["available_traits"]
    if not affordable:
        return None
    return max(
        affordable,
        key=lambda t: TRAITS[t]["effects"].get("lethality", 0) * 3
        + TRAITS[t]["effects"].get("infectivity", 0),
    )


def policy_expert(obs):
    """
    Spread cheaply and quietly, then turn lethal once the world is saturated.

    The two things that separate this from policy_greedy: it buys only cheap
    transmission early (the expensive tier-2s are not worth the DNA when the
    budget is ~200 for a 697-DNA tree), and it holds a reserve so it can still
    afford lethality after the spread phase.
    """
    affordable = obs["available_traits"]
    if not affordable:
        return None

    spreading = obs["infected_pct"] < 60

    if spreading:
        # Cheap non-symptom traits only, so the back half of the budget survives.
        cheap = [
            t for t in affordable
            if t in _NON_SYMPTOM and TRAITS[t]["cost"] <= 12
        ]
        if cheap:
            return min(cheap, key=lambda t: TRAITS[t]["cost"])
        # Cheap infectivity symptoms are fine too, they barely raise severity.
        quiet_symptoms = [
            t for t in affordable
            if TRAITS[t]["effects"].get("infectivity", 0) > 0
            and TRAITS[t]["effects"].get("severity", 0) <= 0.02
            and TRAITS[t]["cost"] <= 8
        ]
        if quiet_symptoms:
            return max(
                quiet_symptoms,
                key=lambda t: TRAITS[t]["effects"]["infectivity"] / TRAITS[t]["cost"],
            )
        return None

    # Saturated: buy the most lethality per DNA point available.
    lethal = [t for t in affordable if TRAITS[t]["effects"].get("lethality", 0) > 0]
    if lethal:
        return max(lethal, key=lambda t: TRAITS[t]["effects"]["lethality"] / TRAITS[t]["cost"])
    # Nothing lethal yet -- open the cheapest path toward it.
    return min(affordable, key=lambda t: TRAITS[t]["cost"])


POLICIES = {
    "pass": policy_pass,
    "random": policy_random,
    "greedy": policy_greedy,
    "expert": policy_expert,
}


# ── Episode runner ────────────────────────────────────────────────────────────

def run_episode(policy, seed_country: str, rng_seed: int) -> dict:
    random.seed(rng_seed)
    env = PlagueEnv()
    env.reset(seed_country)

    done = False
    while not done and env.game.day < 600:
        obs = env.observation()
        _, _, done, _ = env.step(policy(obs))

    game = env.game
    score = env.final_score()

    # Split plague_score into its parts to see what is actually driving it.
    total = game.total_population()
    spent = sum(TRAITS[t]["cost"] for t in game.disease.evolved)
    dna_term = 10 * (
        (game.disease.severity * (game.dna * 2 + spent) * 4)
        / (max(1.0, min(100.0, game.cure_progress * 100)) * max(1, game.day))
    )

    return {
        "score": score["plague_score"],
        "affected": score["affected_pct"],
        "dead": score["dead_pct"],
        "day": score["day"],
        "outcome": score["outcome"],
        "traits": len(game.disease.evolved),
        "dna_earned": game.dna_earned,
        "dna_left": game.dna,
        "dna_term_pct": 100 * dna_term / score["plague_score"] if score["plague_score"] else 0.0,
    }


def _mean(rows, key):
    return statistics.mean(r[key] for r in rows)


# ── Acceptance targets ────────────────────────────────────────────────────────

def check(label: str, ok: bool, detail: str) -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}: {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=5, help="How many seed countries to run")
    parser.add_argument("--verbose", action="store_true", help="Show every episode")
    args = parser.parse_args()

    seeds = DEFAULT_SEEDS[: args.seeds]
    print(f"Calibrating over {len(seeds)} seeds: {', '.join(seeds)}\n")

    results = {}
    for name, policy in POLICIES.items():
        rows = [run_episode(policy, s, i) for i, s in enumerate(seeds)]
        results[name] = rows
        if args.verbose:
            for seed, row in zip(seeds, rows):
                print(
                    f"    {name:7} {seed:12} score={row['score']:>8.1f} "
                    f"affected={row['affected']:>6.2f} dead={row['dead']:>6.2f} "
                    f"traits={row['traits']:>2} outcome={row['outcome']}"
                )

    header = (
        f"{'policy':<8} {'score':>9} {'affected':>9} {'dead':>7} "
        f"{'traits':>7} {'DNA earned':>11} {'DNA left':>9} {'DNA term':>9}"
    )
    print(header)
    print("-" * len(header))
    for name, rows in results.items():
        print(
            f"{name:<8} {_mean(rows,'score'):>9.1f} {_mean(rows,'affected'):>8.2f}% "
            f"{_mean(rows,'dead'):>6.2f}% {_mean(rows,'traits'):>6.1f} "
            f"{_mean(rows,'dna_earned'):>11.0f} {_mean(rows,'dna_left'):>9.1f} "
            f"{_mean(rows,'dna_term_pct'):>8.1f}%"
        )

    print("\nAcceptance targets:")
    all_rows = [r for rows in results.values() for r in rows]
    budgets = [r["dna_earned"] for r in all_rows]
    expert, random_ = _mean(results["expert"], "score"), _mean(results["random"], "score")

    # DNA earned is play-dependent by design -- spreading is what pays -- so the
    # invariant is an upper bound on every policy plus a floor on skilled play,
    # not one flat band across policies that are supposed to differ.
    expert_budgets = [r["dna_earned"] for r in results["expert"]]

    ok = True
    ok &= check(
        "DNA stays bounded (<=300 any policy)", max(budgets) <= 300,
        f"max {max(budgets)} across {len(budgets)} episodes",
    )
    ok &= check(
        "skilled play earns enough (>=150)", min(expert_budgets) >= 150,
        f"expert range {min(expert_budgets)}-{max(expert_budgets)}",
    )
    ok &= check(
        "no episode evolves the full tree", all(r["traits"] < len(TRAITS) for r in all_rows),
        f"max {max(r['traits'] for r in all_rows)}/{len(TRAITS)} traits",
    )
    ok &= check(
        "expert beats random by >=2x", expert >= 2 * random_,
        f"expert {expert:.1f} vs random {random_:.1f} ({expert / random_:.2f}x)"
        if random_ else f"expert {expert:.1f} vs random 0",
    )
    ok &= check(
        "DNA term under 25% of score",
        all(r["dna_term_pct"] < 25 for r in all_rows),
        f"max {max(r['dna_term_pct'] for r in all_rows):.1f}%",
    )
    ok &= check(
        "expert is the top policy",
        expert == max(_mean(rows, "score") for rows in results.values()),
        f"expert {expert:.1f}",
    )

    print("\n" + ("All targets met." if ok else "Targets NOT met -- retune."))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
