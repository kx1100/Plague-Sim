"""
make_example_replay.py — build the showcase's offline sample replay.

The showcase has to run with no network and no completed Mesocosm run, so it
ships a real episode captured here. This writes two artefacts from one pass so
they cannot drift apart:

  showcase/replay.example.js    one episode in the Mesocosm run-export shape,
                                assigned to a global rather than served as JSON:
                                Chrome blocks fetch() of a local file from a
                                file:// page, but not <script src>
  showcase/world.js             the country roster and its region grouping
  showcase/traits.js            id -> [name, cost, tree] for all 60 traits

Only the .js is written. An identical .json alongside it would be a second copy
of the same 660 KB for no reader -- the shape is the export shape either way,
and `python -m json.tool` will pretty-print the global's payload if anyone wants
to read it by eye.

The roster matters because `info["world"]` is a bare list in country-name-sorted
order -- the names are not repeated per step -- and because the regions do not
exist in the environment at all: they are parsed out of the section comments in
data/countries.py, which is the only place the world is grouped geographically.

The episode is the reference expert policy from tools/calibrate.py, NOT a model,
so its `reasoning` is derived from the policy's own rule and the document is
marked `generated_by` accordingly. The showcase says so on screen whenever it is
running on this file rather than a real exported run.

Usage:
    python tools/make_example_replay.py
    python tools/make_example_replay.py --seed-country India --rng-seed 7
"""

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data.traits import TRAITS                     # noqa: E402
from env import PlagueEnv                          # noqa: E402
from models.game_state import GameState            # noqa: E402
from tools.calibrate import policy_expert          # noqa: E402

SHOWCASE = ROOT / "showcase"

# Only the fields the showcase actually reads are kept per turn. A full
# observation carries `available_traits` (up to 60 entries of name/cost/tree)
# every step, which would multiply the file size for data no replay UI shows.
_OBS_KEYS = (
    "day", "dna", "dna_earned", "cure_progress", "infected_pct", "dead_pct",
    "victory_progress", "countries_infected",
)

# `evolved_traits` is carried on the after-board only. It is the one field that
# grows without bound (42 ids by the endgame), and repeating it on the
# pre-action board as well added ~350 KB for a list the showcase reads once.
_AFTER_KEYS = _OBS_KEYS + ("evolved_traits",)


def region_map() -> dict[str, str]:
    """country -> region, read from the section comments in data/countries.py."""
    region, out = None, {}
    for line in (ROOT / "data" / "countries.py").read_text(encoding="utf-8").splitlines():
        header = re.match(r"\s*#\s*[─\-]+\s*([A-Z][A-Z /&\-]+?)\s*[─\-]+\s*$", line)
        if header:
            region = header.group(1).strip()
            continue
        entry = re.match(r'\s*\("([^"]+)",', line)
        if entry and region:
            out[entry.group(1)] = region
    return out


def explain(action: str | None, obs: dict) -> str:
    """
    Stand-in for model reasoning, derived from what the expert policy actually
    weighed. Never presented as a model's words -- see `generated_by`.
    """
    if action is None:
        return (
            f"Nothing affordable at {obs['dna']} DNA. Holding, and letting the "
            f"outbreak earn the next bubble."
        )
    trait = TRAITS[action]
    cure = obs["cure_progress"] * 100
    if trait["tree"] == "ability" and "Resist" in action:
        return (
            f"{trait['name']} first. Cold and arid regions cap out well below "
            f"full spread without it, and they hold enough of the world that "
            f"the last few percent are unreachable otherwise."
        )
    if trait["tree"] == "transmission":
        return (
            f"{trait['name']} at {trait['cost']} DNA — cheap reach while the "
            f"cure is only at {cure:.1f}%. Spreading is what pays for "
            f"everything later."
        )
    if obs["infected_pct"] < 50:
        return (
            f"{trait['name']} is cheap enough at {trait['cost']} to take now "
            f"without moving severity much. The cure is at {cure:.1f}% and I do "
            f"not want to draw attention yet."
        )
    return (
        f"Reach is at {obs['infected_pct']:.1f}% and the cure at {cure:.1f}%. "
        f"Time to convert reach into deaths — {trait['name']} is the best "
        f"severity per DNA I can afford at {trait['cost']}."
    )


def build(seed_country: str, rng_seed: int) -> dict:
    random.seed(rng_seed)
    env = PlagueEnv()
    obs = env.reset(seed_country)

    turns, done, step = [], False, 0
    while not done:
        step += 1
        before = obs
        action = policy_expert(obs)
        reasoning = explain(action, before)
        obs, reward, done, info = env.step(action)
        # `observation` is the board the agent acted on; `board_after` is the
        # same board once the day has run. The real exporter emits all three
        # keys (bench_common/export/replay.py), and the showcase reads
        # board_after so the stats and the map describe the same moment.
        turns.append({
            "step": step,
            "observation": {k: before[k] for k in _OBS_KEYS},
            "board_before": {k: before[k] for k in _OBS_KEYS},
            "board_after": {k: obs[k] for k in _AFTER_KEYS},
            "reasoning": reasoning,
            "action": action,
            "reward": round(reward, 6),
            "terminated": done,
            "info": {
                "day": info["day"],
                "dna": info["dna"],
                "cure_progress": info["cure_progress"],
                "outcome": info["outcome"],
                "action_accepted": info["action_accepted"],
                "world": info["world"],
            },
        })

    score = env.final_score()
    turns[-1]["episode_end"] = {
        "total_reward": None,
        "steps": step,
        "status": "completed",
        "terminal_info": score,
    }
    return {
        "schema_version": "1",
        "domain_id": "plague-sim-local-sample",
        "domain_name": "Plague Sim",
        "binding_vow_version": "1.0.0",
        "visibility": "sample",
        "generated_by": (
            "tools/make_example_replay.py — the reference expert policy from "
            "tools/calibrate.py, not a language model. The `reasoning` field is "
            "derived from the policy's own rule."
        ),
        "seed": seed_country,
        "rng_seed": rng_seed,
        "replay": {f"sample-{seed_country.lower()}": turns},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-country", default="USA")
    parser.add_argument("--rng-seed", type=int, default=7)
    args = parser.parse_args()

    doc = build(args.seed_country, args.rng_seed)
    episode = next(iter(doc["replay"].values()))
    terminal = episode[-1]["episode_end"]["terminal_info"]

    (SHOWCASE / "replay.example.js").write_text(
        "// Generated by tools/make_example_replay.py — do not edit.\n"
        "// One episode in the Mesocosm run-export shape. Assigned to a global\n"
        "// so the page works from file://, where Chrome blocks fetch() of a\n"
        "// local file but not <script src>.\n"
        "window.PLAGUE_SAMPLE_REPLAY = " + json.dumps(doc, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    regions = region_map()
    names = sorted(GameState().countries)
    missing = [n for n in names if n not in regions]
    if missing:
        raise SystemExit(f"no region for: {missing}")
    (SHOWCASE / "world.js").write_text(
        "// Generated by tools/make_example_replay.py — do not edit.\n"
        "// Country roster in the same country-name-sorted order as info.world,\n"
        "// with regions parsed from the section comments in data/countries.py.\n"
        "window.PLAGUE_WORLD = "
        + json.dumps([[n, regions[n]] for n in names], separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    # Without this the showcase would have to guess a trait's cost from the DNA
    # balance between turns -- which is wrong, because income lands in the same
    # step -- and guess its tree from the id.
    (SHOWCASE / "traits.js").write_text(
        "// Generated by tools/make_example_replay.py — do not edit.\n"
        "// id -> [display name, DNA cost, tree]. The replay names trait ids\n"
        "// only, so cost and tree are not otherwise recoverable from it.\n"
        "window.PLAGUE_TRAITS = "
        + json.dumps(
            {tid: [t["name"], t["cost"], t["tree"]] for tid, t in TRAITS.items()},
            separators=(",", ":"),
        )
        + ";\n",
        encoding="utf-8",
    )

    size = (SHOWCASE / "replay.example.js").stat().st_size
    print(f"seed {args.seed_country} (rng {args.rng_seed}) — {len(episode)} turns, "
          f"outcome {terminal['outcome']}, victory {terminal['victory_progress']}")
    print(f"wrote showcase/replay.example.js ({size // 1024} KB), world.js, traits.js")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
