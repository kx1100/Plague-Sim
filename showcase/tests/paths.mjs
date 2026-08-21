// Two paths the sample run does not cover:
//   1. file:// — the browser blocks fetch of a local JSON, so it must not be called
//   2. a real exported run at data/replay.json — must be used instead of the sample
import { JSDOM, VirtualConsole } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const DIR = fileURLToPath(new URL("..", import.meta.url));
const html = readFileSync(`${DIR}/index.html`, "utf8");

function boot({ url, fetchImpl, onFetch }) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push(String(e.message)));
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url,
    virtualConsole: vc,
    beforeParse(window) {
      for (const f of ["traits.js", "world.js", "replay.example.js"]) {
        window.eval(readFileSync(`${DIR}/${f}`, "utf8"));
      }
      window.fetch = (...a) => { onFetch && onFetch(...a); return fetchImpl(...a); };
    },
  });
  return { dom, errors, $: (id) => dom.window.document.getElementById(id) };
}

const out = [];
const check = (label, ok, detail) =>
  out.push(`  [${ok ? "PASS" : "FAIL"}] ${label}${detail ? " — " + detail : ""}`);

// ── 1. file:// ────────────────────────────────────────────────────────────
let fetched = false;
{
  const { dom, errors, $ } = boot({
    url: "file:///C:/Users/katie/Personal%20Projects/Plague%20Sim/showcase/index.html",
    onFetch: () => { fetched = true; },
    fetchImpl: () => Promise.reject(new Error("file:// fetch is blocked by the browser")),
  });
  await new Promise((r) => setTimeout(r, 250));
  console.log("── opened straight from disk (file://) ─────────────────");
  check("never calls fetch", !fetched);
  check("renders the bundled sample", $("v-day").textContent === "1", "day " + $("v-day").textContent);
  check("names the run", $("model").textContent === "reference expert policy", $("model").textContent);
  check("sample notice shown", !$("notice").hidden);
  check("map painted", dom.window.document.querySelectorAll(".country").length === 71);
  check("no errors", errors.length === 0, errors.join("; "));
  console.log(out.join("\n"));
  out.length = 0;
  dom.window.close();
}

// ── 2. a real exported run ────────────────────────────────────────────────
{
  // Shaped like bench_common/export/replay.py output for a model run.
  const realRun = {
    schema_version: "1",
    domain_id: "some-uuid",
    domain_name: "Plague Sim",
    visibility: "gallery_public",
    run: { config: { model: "gemini/gemini-3.1-flash-lite" } },
    episodes: [{ id: "episode-uuid", seed: 42, terminal_info: { outcome: "timeout" } }],
    replay: {
      "episode-uuid": [
        {
          step: 1,
          model: "gemini/gemini-3.1-flash-lite",
          observation: { day: 0, dna: 15, cure_progress: 0, infected_pct: 0, dead_pct: 0, countries_infected: 1, evolved_traits: [] },
          board_after: { day: 1, dna: 6, cure_progress: 0, infected_pct: 0.01, dead_pct: 0, victory_progress: 0.0001, countries_infected: 3, evolved_traits: ["Air1"] },
          reasoning: "Airborne first: it is the cheapest way to leave the seed country.",
          action: "Air1",
          reward: 0.01,
          terminated: false,
          info: { day: 1, dna: 6, cure_progress: 0, outcome: null, action_accepted: true, world: Array.from({ length: 71 }, () => [0.5, 0]) },
        },
        {
          step: 2,
          observation: { day: 1, dna: 6, cure_progress: 0, infected_pct: 0.01, dead_pct: 0, countries_infected: 3, evolved_traits: ["Air1"] },
          board_after: { day: 2, dna: 8, cure_progress: 0.01, infected_pct: 0.05, dead_pct: 0, victory_progress: 0.0005, countries_infected: 5, evolved_traits: ["Air1"] },
          reasoning: "Nothing worth buying at 6 DNA. Waiting.",
          action: null,
          reward: 0.02,
          terminated: true,
          info: { day: 2, dna: 8, cure_progress: 0.01, outcome: "timeout", action_accepted: null, world: Array.from({ length: 71 }, () => [1.5, 0.2]) },
          episode_end: { steps: 2, status: "completed", terminal_info: { outcome: "timeout", days_to_infect_50pct: null } },
        },
      ],
    },
  };

  const { dom, errors, $ } = boot({
    url: "https://mesocosm.test/showcase/index.html",
    fetchImpl: () => Promise.resolve({ ok: true, json: () => Promise.resolve(realRun) }),
  });
  await new Promise((r) => setTimeout(r, 250));
  console.log("\n── a real exported run at data/replay.json ─────────────");
  check("uses the real run, not the sample", $("model").textContent === "gemini/gemini-3.1-flash-lite", $("model").textContent);
  check("sample notice hidden", $("notice").hidden);
  check("seed from episodes[]", /seed 42 · 2 turns/.test($("runmeta").textContent), $("runmeta").textContent);
  check("outcome from terminal_info", $("outcome").textContent === "timeout", $("outcome").textContent);
  check("reads board_after", $("v-day").textContent === "1", "day " + $("v-day").textContent);
  check("model reasoning shown", /Airborne first/.test($("reasoning").textContent), $("reasoning").textContent.slice(0, 40));
  check("action + cost", $("action-name").textContent === "Air1" && $("action-cost").textContent === "9",
    $("action-name").textContent + " / " + $("action-cost").textContent);
  check("one action tick", dom.window.document.querySelectorAll(".tick").length === 1);

  const scrub = $("scrub");
  scrub.value = "1";
  scrub.dispatchEvent(new dom.window.Event("input"));
  check("pass turn renders", $("action-name").textContent === "pass", $("action-name").textContent);
  check("history holds only the real buy", dom.window.document.querySelectorAll(".buy").length === 1,
    dom.window.document.querySelectorAll(".buy").length + " rows");
  check("no errors", errors.length === 0, errors.join("; "));
  console.log(out.join("\n"));
  dom.window.close();
}
