"""
run.py — passive baseline run of the plague simulation.

Steps PlagueEnv with no actions (the agent never evolves anything), which gives
a floor to compare agent runs against. Uses the same scoring path as the
benchmark: PlagueEnv.final_score().
"""

import argparse

from env import PlagueEnv


def run_simulation(
    seed_country: str = "India",
    max_days: int = 600,
    verbose: bool = True,
) -> dict:
    env = PlagueEnv()
    env.reset(seed=seed_country)
    game = env.game

    if verbose:
        print("=== Plague Simulation (passive baseline) ===")
        print(f"Seed country : {seed_country}")
        print(f"World pop    : {game.total_population():,}")
        print(f"Countries    : {len(game.countries)}")
        print()
        print(
            f"{'Day':>5}  {'Infected':>9}  {'Dead':>9}  "
            f"{'Ctries':>6}  {'Cure':>6}  {'DNA':>7}"
        )
        print("-" * 58)

    for _ in range(max_days):
        _, _, done, _ = env.step(None)

        if verbose and game.day % 30 == 0:
            print(
                f"{game.day:>5}  "
                f"{game.percentage_infected() * 100:>8.2f}%  "
                f"{game.percentage_dead() * 100:>8.2f}%  "
                f"{game.infected_countries():>3}/{len(game.countries)}  "
                f"{game.cure_progress * 100:>5.1f}%  "
                f"{game.dna:>7}"
            )

        if done:
            break

    score = env.final_score()

    print()
    print("=== Final Score ===")
    print(f"Outcome      : {score['outcome'] or 'no terminal state (hit day cap)'}")
    print(f"Day          : {score['day']}")
    print(f"Infected     : {score['infected_pct']}%")
    print(f"Dead         : {score['dead_pct']}%")
    print(f"Affected     : {score['affected_pct']}%")
    print(f"Cure         : {score['cure_progress_pct']}%")
    print(f"Victory      : {score['victory_progress']:.1%} of the way to a win")
    print(f"Plague score : {score['plague_score']}")

    return score


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-country", default="India", help="Country to seed the outbreak in")
    parser.add_argument("--max-days", type=int, default=600, help="Episode length cap")
    parser.add_argument("--quiet", action="store_true", help="Suppress the per-30-day table (the final score still prints)")
    args = parser.parse_args()

    run_simulation(
        seed_country=args.seed_country,
        max_days=args.max_days,
        verbose=not args.quiet,
    )
