# Showcase — replay UI

A single-page replay of Plague Sim episodes: pick a model, scrub through its run
day by day, and watch what the agent saw, what it said, and what the world did
about it. **RESULTS** opens the recorded sweep's scores and paired comparison.

```
open showcase/index.html
```

No build step, no server, no network. Open the file directly.

## What it shows

- **Stat tiles** — day, infected %, dead %, cure %, with population counts.
- **The race** — infected, dead and cure plotted across the whole episode, with
  a playhead. Click anywhere on the chart to jump there.
- **The world** — 71 countries as tiles, grouped into six regions. Brightness is
  how much of a country is affected; hue turns from amber to crimson as more of
  the affected die; a blue outline marks a country still under 70% affected.
- **Reasoning** — the model's own text for that turn.
- **Action** — the trait it evolved, its tree and DNA cost, or `pass`.
- **Purchase history** — every trait bought so far, newest first, scrollable
  back to day 1.

Transport: `←` `→` step a turn, `space` plays and pauses, `Home` / `End` jump to
the ends, and the scrubber has a tick for every action taken.

## Where the data comes from

Three sources, in this order:

1. **A local export at `showcase/data/replay.json`**, fetched when the page is
   served over http. That path is gitignored — it is the scratch slot for
   whatever you just ran.
2. **The published sweep in [`replays/`](replays/)**, which is what a visitor
   sees. `replays/index.js` carries every recorded run's score, spread, action
   health and paired comparison; `replays/<model>.js` is one watchable episode,
   loaded only when its chip is clicked. Both are generated:

   ```bash
   python tools/publish_showcase.py
   ```
3. **The bundled sample**, when neither exists. The page says so in a banner.

### Exhibition episodes are not the scored sweep

The scored runs in [`runs/`](../runs/) store summaries, not turns — so no
episode from the sweep can be replayed, and one played again is a *different*
episode. Every published replay is therefore an **exhibition**: the same
featured seed for every model, exported with `--no-save` so it never enters
`runs/index.json`, labelled on screen, and never folded into a score.

```bash
python tools/bench_local.py --model policy/expert --seeds India --skip-idle     --temperature 0 --no-save --export showcase/data/exhibition-policy-expert.json
python tools/publish_showcase.py
```

A model with no exhibition episode still appears in the picker, greyed out, and
in the results table: its absence is a fact about what has been published, not
about the model.

**The sample is not a model.** It is the reference expert policy from
[`tools/calibrate.py`](../tools/calibrate.py) playing seed `USA` to an
`infected_all` win in 400 days, and its `reasoning` text is derived from the
policy's own rule rather than written by any model. It exists so the UI has
something real to render before a benchmarked run exists.

## Generated files — do not edit

| file | what it is |
|---|---|
| `replay.example.js` | the sample episode, in the Mesocosm run-export shape |
| `world.js` | the 71-country roster and its regions |
| `traits.js` | trait id → name, DNA cost, tree |
| `replays/index.js` | every recorded run: score, spread, action health, paired comparison |
| `replays/<model>.js` | one exhibition episode, trimmed to what the page draws |

The first three come from one command, so they cannot drift apart:

```bash
python tools/make_example_replay.py     # sample, world, traits
python tools/publish_showcase.py        # replays/
```

Re-run the first after any change to the world, the trait tree, or the
environment's `info` payload. They are `.js` rather than `.json` because a
`<script src>` is readable from `file://` and a `fetch` is not.

A published replay keeps `info.world` on every fifth day (the page holds the
last frame it saw, so this is invisible) and drops `board_before` and
`observation`, which duplicate what the UI reads from `board_after`. That is
~55% off an episode, with nothing lost on screen.

The map is driven by `info["world"]` — per-country `[infected_pct, dead_pct]` in
country-name-sorted order, which [`env.py`](../env.py) attaches to every step.
It rides in `info` rather than in the observation on purpose: the benchmark
harness builds the model's prompt from the observation alone, but exports `info`
into every replay turn, so the map costs the agent nothing.

## Design

The layout was drafted on a design canvas before it was built; the two
directions that were not taken are kept on its second page. The working
`.dc.html` sources are in [`design/`](design/).

## Checking it

`design/` and the two jsdom scripts in `tests/` are development aids, not part
of the page. The tests drive the real `index.html` — booting it, scrubbing it,
and asserting what it renders — for both data paths:

```bash
npm install jsdom
node showcase/tests/smoke.mjs    # the bundled sample, end to end
node showcase/tests/paths.mjs    # file:// and a real exported run
node showcase/tests/picker.mjs   # the published sweep: picker, switching, results
```

`picker.mjs` skips itself when `replays/index.js` has not been generated.
