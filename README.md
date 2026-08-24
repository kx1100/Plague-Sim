# Plague Sim

A Plague Inc.–style simulator packaged as an LLM benchmark environment for the
SWECC Mesocosm platform.

The agent plays the disease. It starts with one infected country and 15 DNA, and
each turn it may evolve one trait, devolve one it already owns, or pass. The
world fights back: countries grow aware and close borders, wealthy nations pour
money into research, and a completed cure ends the run. The goal is to infect
everyone before that happens.

The benchmark question is whether a model can hold a long-horizon plan under a
scarce budget — spread quietly first, resist the climates that hide the last
few percent of the population, and only then turn lethal.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # pytest only

.venv/Scripts/python.exe run.py                 # passive baseline, seeded in India
.venv/Scripts/python.exe run.py --help          # --seed-country, --max-days, --quiet
.venv/Scripts/python.exe -m pytest tests -q     # 158 tests
```

The simulation itself is pure stdlib — `requirements.txt` is deliberately empty
of runtime packages, because the Mesocosm platform installs it on `env submit`
and it should not pull in a test runner. Development dependencies live in
`requirements-dev.txt`.

`run.py` steps the environment with no actions at all, which is the floor any
real agent has to beat. It prints a progress table every 30 days plus the final
score block.

## The model

**The world.** 71 countries, 7,093,316,000 people, built by
[models/world_builder.py](models/world_builder.py) from
[data/countries.py](data/countries.py). Each country carries a population,
a climate (24 temperate, 20 arid, 14 humid, 13 cold), a wealth score, airport
and port counts, and a land-border list.

**Spread** ([simulation/spread.py](simulation/spread.py)) runs on four channels
each day: internal spread within an infected country, land borders, air routes
and sea routes. Climate gates the internal rate hard — cold countries run at
0.3× and arid at 0.5× base until the matching resistance trait is evolved, and
both need level 2 for the full multiplier. Awareness suppresses everything:
internal spread falls toward 35% of base as a country saturates its awareness,
airports close above 0.5 awareness and ports above 0.6.

**Deaths** ([simulation/deaths.py](simulation/deaths.py)) apply only if the
disease has lethality at all, scaled down by national wealth — at wealth 1.0,
healthcare cuts mortality by 70%.

**The cure** ([simulation/cure.py](simulation/cure.py)) accumulates from wealthy,
aware countries. Severity accelerates it sharply, drug resistance and genetic
hardening slow it, and any trait marked `special: "slows_cure"` in the trait data
slows it further. This is the central tension: symptoms are how you kill people
and also how you get caught.

**Traits** ([data/traits.py](data/traits.py)) — 60 of them across three trees,
697 DNA to evolve the lot, which no episode can afford:

| tree | count | what it buys |
|---|---|---|
| transmission | 17 | infectivity and spread routes (air, water, birds, insects, animals) |
| symptom | 32 | severity and lethality — and faster cure research |
| ability | 11 | drug/climate resistance, genetic hardening, cure reshuffles |

**DNA** ([simulation/dna.py](simulation/dna.py)) is the only currency, so its
scarcity *is* the difficulty. Every source is a ratchet on cumulative progress,
never a rate on the current population:

| source | pays for | max payouts | max DNA |
|---|---|---|---|
| country bubbles | each new country infected | 71 | ~213 |
| infection milestones | each 2% of the world reached | 50 | 100 |
| death milestones | each 0.5% of the world killed | 200 | 400 |

The bound comes from the size of the world, not from episode length. There is no
passive drip: waiting earns nothing directly, so income has to be earned by
spreading. `_MAX_DNA_PER_DAY = 8` is a backstop against a future source quietly
reintroducing runaway growth, not a balance lever.

## Playing it

Each step takes one action and advances one day:

| action | effect |
|---|---|
| `"Air1"` | evolve a trait from `observation.available_traits` |
| `"devolve:Air1"` | devolve a trait from `observation.devolve_options`, refunding a flat 2 DNA |
| `null` | pass, and let the day run |

An invalid action is rejected but the day still passes, so a bad output costs a
turn rather than stalling the episode. Devolving removes only that trait —
dependents stay evolved with an unmet prereq — and the three `GeneticReShuffle`
traits cannot be devolved at all: they roll the cure back once each, and letting
them be recycled for the 2 DNA refund was worth more than any legitimate
strategy in the game.

The observation is documented field by field in
[benchanything.json](benchanything.json) under
`binding_vow.observation_space.fields`, and a test asserts the two never drift
apart.

## Scoring and termination

`PlagueEnv.final_score()` returns the terminal block. The primary metric is
**`victory_progress`** = `(infected + dead) / population`, in `[0, 1]`. Winning
is reachable but rare, so agents are ranked by how close they got rather than by
a mostly-constant outcome. `extinction_progress` measures distance to the
premium `extinct` win, and `plague_score` is the Plague Inc. formula, kept for
continuity.

Five outcomes end an episode:

| outcome | meaning |
|---|---|
| `infected_all` | healthy population down to 0.1% of the world — **win** |
| `extinct` | the same, with 95%+ dead — **premium win** |
| `cured` | cure reached 1.0 — the disease lost |
| `died_out` | no infections left after day 30 |
| `timeout` | the 600-day cap ran out with none of the above |

`infected_all` triggers at 0.1% healthy rather than zero because internal spread
is exponential decay of the healthy population — it approaches zero and never
arrives, so requiring literally every human made the win unreachable by
construction rather than by difficulty.

## Running it as a benchmark environment

[adapter.py](adapter.py) wraps `PlagueEnv` in an HTTP server on port 8765, which
is what `mesocosm doctor --local` and `mesocosm run local` probe:

```bash
python adapter.py
curl localhost:8765/health
curl -X POST localhost:8765/reset -d '{"seed":"India"}'
curl -X POST localhost:8765/step  -d '{"action":"Air1"}'
```

Routes: `GET /health`, `GET /render`, `POST /reset`, `POST /step`, `POST /close`.
Seeds may be a country name, an integer (a country index), or null for a country
drawn at random.

**Episodes are reproducible.** Each one owns a `random.Random` seeded from
`rng_seed`, which defaults to `seed` — so the same seed always replays the same
world, and an episode is unaffected by whatever ran before it in the same
process. `/reset` echoes the seed it used, so an episode started without one can
still be replayed exactly. Pass `rng_seed` explicitly to run repeats on a single
country. This is what makes two agents' scores comparable: given the same seed
list, they face identical worlds.

The adapter also normalises natural-language output from weaker models: an
action of `"lets go with cold_resist"` resolves to `ColdResist1`, and to
`ColdResist2` once tier 1 is owned. Matching runs only against currently
affordable traits, so an already-evolved tier is skipped in favour of the next
one up. It matches trait IDs, ID stems and trait names of four characters or
more, so short IDs written with a space (`"Air 1"`) are not recovered.

### Running episodes

[tools/bench_local.py](tools/bench_local.py) drives the whole benchmark — reset,
prompt a model, step, repeat, then average the terminal fields named in
`benchanything.json`. It is the `mesocosm run local` loop with no dependency on
the Mesocosm CLI or platform, so it also works when they are unavailable:

```bash
python adapter.py                                       # terminal 1
python tools/bench_local.py --model ollama/llama3.2     # terminal 2
python tools/bench_local.py --model policy/expert       # no LLM: the baseline
python tools/bench_local.py --model anthropic/claude-opus-5 --probe
```

Backends are `ollama/*`, `anthropic/*`, `openai/*` (any `/v1/chat/completions`
endpoint, which is how Gemini is reached), and `policy/*` for the reference
policies from [tools/calibrate.py](tools/calibrate.py). A run against a cloud
model is ~600 calls per episode, so the spend guards — `--probe`, `--max-calls`,
`--max-cost`, `--skip-idle` — are on by default.

See [LOCAL_DEV.md](LOCAL_DEV.md) for the full flag table, the Ollama dev loop and
the Mesocosm submission commands.

### Recorded runs

Every run writes `runs/<date>-<model>/run.json` and appends `runs/index.json`.
Both are tracked in git, because a run made once and published has to be
readable cold: the record carries the seed list, every protocol setting, the
system prompt in full, the manifest hash, the git SHA, per-episode terminal
fields, action-health counts, token usage and wall time. `--no-save` turns it
off and `--runs-dir` moves it.

No credential ever reaches a record: it stores the *name* of the API-key
environment variable, never its value, and `--base-url` is scrubbed of userinfo,
query string and key-shaped path segments, since some providers carry the key in
the URL. `tests/test_no_secrets.py` scans the tracked tree so a paste accident
fails the suite instead of shipping.

## Watching a run back

[showcase/index.html](showcase/index.html) replays one episode day by day --
the chart, a 71-country map, the model's reasoning and the trait it bought each
turn. Open the file directly; there is no build step and nothing is fetched.

It uses a real exported run at `showcase/data/replay.json` when there is one and
otherwise falls back to a bundled sample of the reference expert policy, saying
so on screen. Either harness writes that file:

```bash
python tools/bench_local.py --model ollama/llama3.2 --episodes 1   --export showcase/data/replay.json          # local run
mesocosm run export RUN_ID -o showcase/data/replay.json    # platform run
```
See [showcase/README.md](showcase/README.md).

## Balance and calibration

An environment that ranks models on an artifact is worse than no environment, so
the balance is held in place by a harness rather than by judgement.

```bash
.venv/Scripts/python.exe tools/calibrate.py --seeds 10
.venv/Scripts/python.exe tools/calibrate.py --seeds 10 --verbose   # per-episode rows
```

[tools/calibrate.py](tools/calibrate.py) runs four reference policies — `pass`,
`random`, `greedy` (always buy the most lethal thing available, the classic
beginner error) and `expert` (climate resistance first, then cheap spread, then
lethality once saturated) — across N seed countries, and prints score, reach,
DNA budget, trait count and score composition, followed by nine acceptance
targets as PASS/FAIL:

- DNA stays bounded (≤450 for any policy)
- skilled play earns enough (≥150 for expert)
- no episode evolves the full tree
- expert clearly beats random (≥1.25×)
- expert gets measurably closer to victory (`victory_progress` gap ≥0.1)
- the DNA term stays under 25% of `plague_score`
- winning is reachable by skilled play
- careless play never wins
- expert is the top policy

All nine must pass after any balance change. `tests/test_balance.py` covers the
same ground fast enough for CI, and pins the expert wins to the `USA` and
`Russia` seeds specifically, so a tuning shift that loses them fails the suite
rather than silently making the environment unwinnable again.

Current results, 40 episodes (10 seeds × 4 policies):

| policy | wins | victory_progress | score | affected | dead | DNA earned |
|---|---|---|---|---|---|---|
| pass | 0/10 | 0.749 | 748.7 | 74.87% | 0.00% | 201 |
| random | 0/10 | 0.830 | 1074.2 | 82.96% | 24.44% | 256 |
| greedy | 0/10 | 0.768 | 1020.7 | 76.83% | 25.21% | 258 |
| expert | **2/10** | **0.999** | 1504.1 | 99.88% | 50.51% | 326 |

`pass` outscoring `greedy` is deliberate, not a bug: buying symptoms early is a
genuine blunder in Plague Inc., because severity spikes and the cure races
ahead. Careless action *should* underperform patience. What the benchmark needs
is that skilled play separates cleanly, and it does — on every axis, including
the only one that is binary.

### Tuned constants

Each of these was set against measured outcomes, and each carries its rationale
as a comment at the definition site:

| file | constant | value | why |
|---|---|---|---|
| [simulation/cure.py](simulation/cure.py) | `_CURE_CONTRIBUTION` | `0.000042` | **the difficulty dial** — see below |
| [simulation/cure.py](simulation/cure.py) | `_SEVERITY_CURE_SENSITIVITY` | `5.0` | makes severity management the core skill: flashy plagues get cured fast, quiet ones get a runway |
| [simulation/spread.py](simulation/spread.py) | `_AWARENESS_SPREAD_PENALTY` | `0.65` | at 0.8, late-game spread fell to 20% of base and no trait in the tree could answer it — a ceiling the agent cannot play against |
| [simulation/deaths.py](simulation/deaths.py) | `_BASE_DAILY_DEATH_RATE` | `0.03` | at 0.01 a fully evolved disease needed ~506 days to kill 95% of the world, so `extinct` was unreachable by arithmetic |
| [models/game_state.py](models/game_state.py) | `_SATURATION_THRESHOLD` | `0.001` | a win condition the exponential spread model can actually express |
| [simulation/dna.py](simulation/dna.py) | `_DEATH_BUBBLE_VALUE` | `1` | deaths became far more common at the higher death rate; holds the budget down |

**The difficulty dial.** Because the saturation threshold is binary, win rate is
a step function of cure speed:

| `_CURE_CONTRIBUTION` | expert wins | careless wins |
|---|---|---|
| 0.000045 | 0/10 | 0/30 |
| **0.000042 (current)** | **2/10** | **0/30** |
| 0.00004 | 9/10 | 0/30 |

If wins turn out too rare or too common against real models, this is the
constant to move — in small increments, re-running the harness each time.

## Repo layout

```
env.py                 PlagueEnv: reset/step/observation/final_score
adapter.py             HTTP wrapper (port 8765)
run.py                 passive baseline runner
benchanything.json     Mesocosm binding vow, observation and scoring spec
data/                  countries.py, traits.py (the 60-trait tree)
models/                Country, Disease, GameState, world_builder
simulation/            spread, deaths, cure, dna, actions
tools/calibrate.py     balance harness and acceptance targets
tools/bench_local.py   run the benchmark against a model, without Mesocosm
tools/run_store.py     run records: provenance, redaction, runs/index.json
runs/                  recorded runs, tracked and published
tests/                 158 tests: sim mechanics, env lifecycle, adapter, balance, harness
showcase/index.html    replay UI -- open it directly, no build step
tools/make_example_replay.py  regenerates the showcase's bundled sample
```
