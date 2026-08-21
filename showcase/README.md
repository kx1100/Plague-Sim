# Showcase — replay UI

A single-page replay of one Plague Sim episode: scrub through the run day by
day and watch what the agent saw, what it said, and what the world did about it.

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

The page prefers a real exported run at `showcase/data/replay.json`:

```bash
mesocosm run export RUN_ID -o showcase/data/replay.json
```

That path is gitignored. When it is missing — or when the page is opened from
`file://`, where browsers block reading a local JSON file — it falls back to a
bundled sample episode and says so in a banner at the top.

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

All three come from one command, so they cannot drift apart:

```bash
python tools/make_example_replay.py
```

Re-run it after any change to the world, the trait tree, or the environment's
`info` payload. They are `.js` rather than `.json` because a `<script src>` is
readable from `file://` and a `fetch` is not.

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
```
