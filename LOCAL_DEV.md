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

A tripped guard stops the run and still reports the episodes that finished.

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
