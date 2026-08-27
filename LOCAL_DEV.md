# Local development (Ollama)

Iterate on `env.py` and `benchanything.json` on your machine before `mesocosm env submit`. No API keys — only [Ollama](https://ollama.com).

## One-time setup

1. Install the CLI: `pip install swecc-mesocosm`
   This covers `mesocosm run local`, `bench_common` for `adapter.py`, and the HTTP stack (`fastapi`, `uvicorn`). You do **not** need `pip install -r requirements.txt` for the default scaffold — that file is only for extra packages your env imports (see comments in `requirements.txt`). The platform installs it when you `env submit`.
2. Install Ollama and pull a model:
   ```bash
   ollama pull llama3.2
   ```
3. Ensure Ollama is running (`ollama serve` — the desktop app usually does this).

## Dev loop

```bash
export MESOCOSM_LOCAL=1   # optional: bench-api :8010, adapter :8765 defaults
mesocosm doctor --local   # verify adapter (8765) before run local
```

**Terminal 1 — env server**

```bash
python adapter.py
# → http://localhost:8765/health
```

**Terminal 2 — bench episodes**

```bash
mesocosm run local
# same as: mesocosm run local --model ollama/llama3.2
```

Uses `benchanything.json` for the binding vow and scoring. Does **not** register the domain or create platform runs.

## Flags

| Flag | Default | Purpose |
|------|---------|---------|
| `--model` | `ollama/llama3.2` | Must be `ollama/<name>` matching a pulled model |
| `--episodes` | `5` | Number of episodes |
| `--env-url` | `http://localhost:8765` | Adapter URL if you changed the port |
| `--manifest` | `benchanything.json` | Alternate manifest path |
| `--system-prompt` | — | Extra instruction for the agent |

## Without the Mesocosm CLI

[tools/bench_local.py](tools/bench_local.py) is the same loop as `mesocosm run
local` — reset, prompt, step, repeat, average the terminal fields named in
`benchanything.json` — with no dependency on the CLI or the platform. Use it
when Mesocosm is unavailable, or to bench a cloud model without a platform run.

```bash
python adapter.py                                    # terminal 1
python tools/bench_local.py                          # terminal 2, ollama/llama3.2
```

It talks to the adapter over HTTP rather than importing `PlagueEnv`, so the
natural-language action matching in `adapter.py` is exercised exactly as it is
for a hosted agent.

| Backend | Example | Needs |
|---|---|---|
| Ollama | `--model ollama/llama3.2` | Ollama running; no key |
| Reference policy | `--model policy/expert` | nothing — no model is called |
| Claude | `--model anthropic/claude-opus-5` | `pip install anthropic`, `ANTHROPIC_API_KEY` |
| OpenAI-compatible | `--model openai/gpt-5` | `--base-url`, `--api-key-env` |

`policy/pass|random|greedy|expert` runs the reference policies from
[tools/calibrate.py](tools/calibrate.py) through the full HTTP path. They cost
nothing and are the baseline a model has to beat — `expert` should reproduce
what `tools/calibrate.py` reports for the same seeds, which is also how you tell
the harness itself is sound.

Gemini goes through the OpenAI backend on Google's compatibility layer:

```bash
python tools/bench_local.py --model openai/gemini-3.1-flash-lite   --base-url https://generativelanguage.googleapis.com/v1beta/openai   --api-key-env GEMINI_API_KEY
```

### Not spending a fortune by accident

An episode is up to 600 days and the faithful loop is one call per day, so a
five-episode run against a cloud model is ~3000 calls. The guards are on by
default:

| Flag | Default | Purpose |
|------|---------|---------|
| `--probe` | off | One call on a fresh board, prompt and reply printed, then exit. Check the plumbing before committing to a run. |
| `--max-calls` | `episodes x max-steps` | Hard ceiling on model calls for the run. |
| `--max-cost` | `5.00` on paid backends | Hard ceiling on estimated USD. `0` disables. Anthropic list prices are built in; use `--price-in`/`--price-out` for anything else. |
| `--skip-idle` | off | No model call on days where nothing is affordable, where the only moves are `null` or a devolve. Cuts most of an episode's calls. |
| `--retries` | 2 | Retries per *transient* failure. A 4xx that is not a rate limit is fatal at once, so a bad key costs one call. |
| `--rpm` | off | Pace calls to N requests per minute. |
| `--tpm` | off | Pace calls to N tokens per minute. |

A tripped guard stops the run and still reports the episodes that finished.

### Free tiers: pacing, not spending, is the constraint

On a free key, exceeding the rate does not cost more — it fails the run. The
harness calls sequentially, so left alone it issues requests as fast as the
endpoint answers, twenty to forty a minute. Against a cap of eight that dies in
the second minute, mid-episode, having already spent the quota it needed.

`--rpm` and `--tpm` pace the calls ahead of time, as sliding sixty-second
windows. **Set both**: a request cap and a token cap bind at different points,
and on some tiers it is tokens that run out first. Gemma's free tier allows 30
requests a minute but only 16K tokens, and one turn of this benchmark costs
about 1.8K — so it is really a nine-calls-a-minute key, and `--rpm` alone would
sail past the limit it was set to respect.

```bash
--rpm 28 --tpm 15000 --retries 3      # a 30 rpm / 16K tpm free tier, with headroom
```

Leave headroom under the published numbers; the provider's window and yours do
not start at the same instant.

Requests-per-**day** is the limit to check before choosing a model at all. A
ten-episode sweep is ~400–500 calls (measured: 498 for `gemma3:4b`, 391 for
`llama3.2`), so a 20 RPD model cannot finish a single episode, however patient
the pacing. The run prints how much of its wall time went to waiting, which is
what distinguishes a slow model from a throttled one:

```
paced    : 2891s of 4102s spent waiting on the 28 rpm + 15000 tpm limit
```

Both caps come back as HTTP 429 and the harness tells them apart. A per-minute
limit is retried on a backoff that climbs towards the width of the window
(20s, 40s, 60s) rather than the seconds a dropped connection deserves. A
per-day limit **stops the run**, keeping the episodes that finished — waiting
cannot clear it, so sleeping out the retries first would only lose time.

Pacing is not recorded in the run's `protocol` block, and deliberately so: it
changes when the model is asked, never what it is asked, so a paced run stays
directly comparable to an unpaced one.

### Reading the output

Every run reports what the model's turns actually did, as counts and as a share
of what it attempted:

```
actions  : 118 accepted, 3 rejected — 2% of attempted (3 illegal moves, 0 unreadable), 6 passed, 771 auto-passed
```

The share is the number that matters, because `103 illegal` reads very
differently beside 393 accepted than beside 3900. A rejected move is one the
environment threw away, so a model rejecting a fifth of its actions only played
four turns in five — the rest of its score is the simulation running unattended.

Illegal moves and unreadable replies are counted separately on purpose. An
**illegal** move is the model naming a trait it cannot currently afford or
reach: that is bad play, and it is a result, so it never raises a warning.
An **unreadable** reply is one the parser could not turn into a trait ID at
all, which implicates the harness rather than the model — above 10% the run
says so. Empty replies are called out separately again, because that is what a
truncated reasoning model looks like from here.

The metrics below the actions line each carry their spread:

```
  victory_progress      0.8646  sd 0.0441   95% CI [0.8331, 0.8962] <- primary
```

Ten seeds is a small sample, so the interval is wide, and it is the only honest
way to compare two models: **overlapping intervals mean the run did not tell
them apart**, however far apart the means look. The interval uses Student's t
rather than the normal 1.96 — at ten seeds that is a 15% difference, which is
exactly the margin that turns a tie into an apparent ranking. All of this is
stored in `run.json` as well (`sd`, `sem`, `ci95`, and `action_health.rates`),
so a published record can be read correctly without recomputing anything.

**Thinking models need room.** `qwen3` and friends put their reasoning in a
separate field, and Ollama's token budget covers reasoning *and* the answer — so
`--max-tokens 1024` can be spent entirely on thinking, leaving no action at all.
The harness stops with an actionable error rather than scoring the silence.
Use `--max-tokens 4096`, or `--ollama-think off` to turn thinking off entirely.

**Reproducibility.** An episode's world comes from `--rng-seed`, defaulting to
the seed itself, so the same seed list replays identically for every model —
which is what makes two models' scores comparable. Pass `--rng-seed` explicitly
to run repeats on one seed country.

Other flags worth knowing: `--effort` and `--thinking` for the Anthropic
backend (Claude models reject `--temperature`; pass `--effort none --thinking
off` for models older than the Opus 5 family), `--history N` for how many recent
turns the model sees, and `--export PATH` to write the run in the same shape
`mesocosm run export` produces — which is what [showcase/index.html](showcase/index.html)
reads, so the replay UI works without a platform run too:

```bash
python tools/bench_local.py --model ollama/llama3.2 --episodes 1   --export showcase/data/replay.json
```

## Ship to Mesocosm

When local runs look good:

```bash
mesocosm auth login
mesocosm env submit --name "My env" --github-url https://github.com/you/your-repo
# submit clones the repo and registers a draft domain from benchanything.json — no separate register step
mesocosm env list   # note domain_id when status is ready
mesocosm run create --domain DOMAIN_ID --vow-version 1.0.0 --model gemini/gemini-3.1-flash-lite ...
```

Platform runs use cloud models on SWECC infrastructure; local Ollama is only for your machine.

**Non-interactive auth:** `mesocosm auth login` prompts for credentials. In CI, set `SWECC_BENCH_TOKEN` or use `mesocosm auth guest`.

**Legacy:** repos that use `domain.py` with `DOMAIN_CONFIG` (not created by `mesocosm init`) can still run `mesocosm register path/to/domain.py [--auto-id] [--publish]` to POST the domain manually.
