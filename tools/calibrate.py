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
_CLIMATE_RESIST = ["ColdResist1", "ColdResist2", "HeatResist1", "HeatResist2"]
_WINS = ("extinct", "infected_all")


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
    Climate resistance first, then cheap spread, then lethality once saturated.

    Climate resistance leads because arid and cold regions cap out at 0.5x and
    0.3x spread without it, and they hold enough of the world population that
    the last few percent are unreachable otherwise -- which is precisely the gap
    that separates a win from a 99.9% loss.
    """
    affordable = obs["available_traits"]
    if not affordable:
        return None

    climate = [t for t in affordable if t in _CLIMATE_RESIST]
    if climate:
        return min(climate, key=lambda t: TRAITS[t]["cost"])

    if obs["infected_pct"] < 60:
        cheap = [
            t for t in affordable
            if t in _NON_SYMPTOM and TRAITS[t]["cost"] <= 12
        ]
        if cheap:
            return min(cheap, key=lambda t: TRAITS[t]["cost"])
        # Cheap infectivity symptoms are fine, they barely raise severity.
        quiet = [
            t for t in affordable
            if TRAITS[t]["effects"].get("infectivity", 0) > 0
            and TRAITS[t]["effects"].get("severity", 0) <= 0.02
            and TRAITS[t]["cost"] <= 8
        ]
        if quiet:
            return max(
                quiet,
                key=lambda t: TRAITS[t]["effects"]["infectivity"] / TRAITS[t]["cost"],
            )
        return None

    lethal = [t for t in affordable if TRAITS[t]["effects"].get("lethality", 0) > 0]
    if lethal:
        return max(lethal, key=lambda t: TRAITS[t]["effects"]["lethality"] / TRAITS[t]["cost"])
    return min(affordable, key=lambda t: TRAITS[t]["cost"])


POLICIES = {
    "pass": policy_pass,
    "random": policy_random,
    "greedy": policy_greedy,
    "expert": policy_expert,
}


# ── Episode runner ────────────────────────────────────────────────────────────

def run_episode(policy, seed_country: str, rng_seed: int) -> dict:
    # Two generators, deliberately. The env derives its world from the country
    # name alone -- exactly what tools/bench_local.py does -- so "seed USA"
    # means one specific world everywhere in the project, and a policy run here
    # is directly comparable to the same policy run through the HTTP harness.
    # Passing `rng_seed` to the env instead would silently give the two tools
    # different worlds for the same country, which is how the expert policy
    # came to win 2/10 here and 4/10 there.
    #
    # `rng_seed` still seeds the module generator, which is now only
    # policy_random's own choices.
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
        "won": score["outcome"] in _WINS,
        "victory_progress": score["victory_progress"],
        "extinction_progress": score["extinction_progress"],
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
        f"{'policy':<8} {'wins':>6} {'victory':>8} {'score':>9} {'affected':>9} "
        f"{'dead':>7} {'traits':>7} {'DNA earned':>11} {'DNA term':>9}"
    )
    print(header)
    print("-" * len(header))
    for name, rows in results.items():
        wins = sum(1 for r in rows if r["won"])
        print(
            f"{name:<8} {wins:>3}/{len(rows):<2} {_mean(rows,'victory_progress'):>8.3f} "
            f"{_mean(rows,'score'):>9.1f} {_mean(rows,'affected'):>8.2f}% "
            f"{_mean(rows,'dead'):>6.2f}% {_mean(rows,'traits'):>6.1f} "
            f"{_mean(rows,'dna_earned'):>11.0f} {_mean(rows,'dna_term_pct'):>8.1f}%"
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
        "DNA stays bounded (<=450 any policy)", max(budgets) <= 450,
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
    # A score ratio was the right discriminator when nothing could win and the
    # spread was the only axis. Now that winning is reachable, win rate carries
    # that signal and the scores necessarily compress -- slowing the cure enough
    # for skilled play to finish also gives careless play more room. So this
    # checks a clear margin, and the win-rate targets below do the real work.
    expert_vp = _mean(results["expert"], "victory_progress")
    random_vp = _mean(results["random"], "victory_progress")
    ok &= check(
        "expert clearly beats random", expert >= 1.25 * random_,
        f"expert {expert:.1f} vs random {random_:.1f} ({expert / random_:.2f}x)"
        if random_ else f"expert {expert:.1f} vs random 0",
    )
    ok &= check(
        "expert gets measurably closer to victory", expert_vp - random_vp >= 0.1,
        f"victory_progress {expert_vp:.3f} vs {random_vp:.3f}",
    )
    ok &= check(
        "DNA term under 25% of score",
        all(r["dna_term_pct"] < 25 for r in all_rows),
        f"max {max(r['dna_term_pct'] for r in all_rows):.1f}%",
    )
    ok &= check(
        "winning is reachable by skilled play",
        any(r["won"] for r in results["expert"]),
        f"expert won {sum(1 for r in results['expert'] if r['won'])}/{len(results['expert'])}",
    )
    ok &= check(
        "careless play never wins",
        not any(r["won"] for r in results["random"] + results["greedy"] + results["pass"]),
        f"random+greedy+pass won "
        f"{sum(1 for r in results['random'] + results['greedy'] + results['pass'] if r['won'])}",
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
