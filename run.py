from models.game_state import GameState


def run_simulation(seed_country: str = "India", max_days: int = 600, verbose: bool = True):
    game = GameState()
    game.countries[seed_country].infected = 100

    if verbose:
        print("=== Plague Simulation ===")
        print(f"Seed country : {seed_country}")
        print(f"World pop    : {game.total_population():,}")
        print(f"Countries    : {len(game.countries)}")
        print()
        print(
            f"{'Day':>5}  {'Infected':>9}  {'Dead':>9}  "
            f"{'Ctries':>6}  {'Cure':>6}  {'DNA':>5}"
        )
        print("-" * 56)

    for _ in range(max_days):
        game.step()

        if verbose and game.day % 30 == 0:
            s = game.score()
            print(
                f"{s['day']:>5}  "
                f"{s['infected_pct']:>8.2f}%  "
                f"{s['dead_pct']:>8.2f}%  "
                f"{s['countries_infected']:>3}/{s['total_countries']}  "
                f"{s['cure_progress_pct']:>5.1f}%  "
                f"{game.dna:>5}"
            )

        if game.game_over:
            break

    if verbose:
        s = game.score()
        print()
        print("=== Final Score ===")
        print(f"Outcome   : {s['outcome']}")
        print(f"Day       : {s['day']}")
        print(f"Infected  : {s['infected_pct']}%")
        print(f"Dead      : {s['dead_pct']}%")
        print(f"Affected  : {s['affected_pct']}%")
        print(f"Cure      : {s['cure_progress_pct']}%")

    return game.score()


if __name__ == "__main__":
    run_simulation()
