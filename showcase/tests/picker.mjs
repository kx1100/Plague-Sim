// The published-sweep path: the model picker, switching between exhibition
// episodes, and the results table. The other two suites cover the page with no
// sweep bundled, which is still a supported state -- this one loads
// showcase/replays/, so it needs `python tools/publish_showcase.py` to have run.
import { JSDOM, VirtualConsole } from "jsdom";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const DIR = fileURLToPath(new URL("..", import.meta.url));
const REPLAYS = `${DIR}/replays`;

if (!existsSync(`${REPLAYS}/index.js`)) {
  console.log("── model picker ────────────────────────────────────────");
  console.log("  [SKIP] no published sweep — run python tools/publish_showcase.py");
  process.exit(0);
}

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e.stack || e.message)));
vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));
vc.on("warn", (...a) => errors.push("console.warn: " + a.join(" ")));

const html = readFileSync(`${DIR}/index.html`, "utf8");
const dom = new JSDOM(html, {
  runScripts: "dangerously",
  url: "file:///C:/Users/katie/Personal%20Projects/Plague%20Sim/showcase/index.html",
  virtualConsole: vc,
  beforeParse(window) {
    // jsdom fetches no local <script src>, so the globals a browser would have
    // are injected. Two of the four published replays are loaded on purpose:
    // the rest exercise the lazy path.
    for (const f of ["traits.js", "world.js", "replay.example.js"]) {
      window.eval(readFileSync(`${DIR}/${f}`, "utf8"));
    }
    window.eval(readFileSync(`${REPLAYS}/index.js`, "utf8"));
    for (const f of ["policy-pass.js", "policy-expert.js"]) {
      window.eval(readFileSync(`${REPLAYS}/${f}`, "utf8"));
    }
    window.fetch = () => Promise.reject(new Error("file:// fetch is blocked"));
    window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
  },
});

const { window } = dom;
const doc = window.document;
const $ = (id) => doc.getElementById(id);
const text = (id) => ($(id) ? $(id).textContent.trim() : "<<missing #" + id + ">>");
const chips = () => [...doc.querySelectorAll(".chip")];
const chipFor = (label) => chips().find((c) => c.textContent.indexOf(label) === 0);
const click = (node) => node.dispatchEvent(new window.Event("click", { bubbles: true }));

const out = [];
const check = (label, ok, detail) =>
  out.push(`  [${ok ? "PASS" : "FAIL"}] ${label}${detail ? " — " + detail : ""}`);

await new Promise((r) => setTimeout(r, 300));

const RUNS = window.PLAGUE_RUNS;

console.log("── model picker ────────────────────────────────────────");
check("picker shown", !$("runs").hidden);
check("one chip per recorded run", chips().length === RUNS.runs.length,
  chips().length + " chips for " + RUNS.runs.length + " runs");
const playable = RUNS.runs.filter((r) => r.replay).length;
check("runs without an exhibition are disabled, not hidden",
  chips().filter((c) => c.disabled).length === RUNS.runs.length - playable,
  chips().filter((c) => c.disabled).length + " disabled");
check("a disabled chip says why", /no exhibition episode/.test(
  chips().find((c) => c.disabled).title || ""),
  (chips().find((c) => c.disabled).title || "").slice(0, 60));

console.log("\n── first playable run is selected ──────────────────────");
check("a run is playing", Number(text("v-day")) === 1, "day " + text("v-day"));
check("chip is pressed", chips().some((c) => c.getAttribute("aria-pressed") === "true"));
const pressed = () => chips().find((c) => c.getAttribute("aria-pressed") === "true");
check("named by its label, not by the export's own model id",
  text("model") === pressed().firstChild.textContent, text("model"));
check("run meta says exhibition", /seed India · \d+ turns · exhibition/.test(text("runmeta")),
  text("runmeta"));
check("notice separates exhibition from the sweep",
  !$("notice").hidden && /not.*one of the ten scored seeds/i.test(text("notice")),
  text("notice").slice(0, 80));

console.log("\n── switching model ─────────────────────────────────────");
const before = doc.querySelectorAll(".tick").length;
click(chipFor("policy/expert"));
await new Promise((r) => setTimeout(r, 60));
check("switches to the clicked run", text("model") === "policy/expert", text("model"));
check("only one chip stays pressed",
  chips().filter((c) => c.getAttribute("aria-pressed") === "true").length === 1);
check("starts at the beginning again", text("v-day") === "1", "day " + text("v-day"));
const after = doc.querySelectorAll(".tick").length;
check("action ticks are replaced, not accumulated", after > 0 && after !== before + before,
  before + " ticks then " + after);
check("purchase history re-rendered for the new run",
  doc.querySelectorAll(".buy").length + doc.querySelectorAll(".buys-empty").length > 0);

console.log("\n── a replay that is not loaded yet ─────────────────────");
const lazy = RUNS.runs.find((r) => r.replay && !window.PLAGUE_REPLAYS[r.replay]);
click(chipFor(lazy.label));
await new Promise((r) => setTimeout(r, 60));
const injected = [...doc.querySelectorAll("script[src]")].map((s) => s.getAttribute("src"));
check("is fetched by injecting its script, not by fetch()",
  injected.indexOf("replays/" + lazy.replay_file) !== -1, injected.join(", "));

console.log("\n── results ─────────────────────────────────────────────");
check("results button offered", !$("results-open").hidden);
click($("results-open"));
check("results open", !$("results").hidden);
const rows = [...doc.querySelectorAll("#results-body tbody tr")];
check("a row per run", rows.length === RUNS.runs.length, rows.length + " rows");

const cells = (label) => {
  const row = rows.find((r) => r.cells[0].textContent === label);
  return row ? [...row.cells].map((c) => c.textContent.trim()) : null;
};
const hosted = cells(RUNS.runs.find((r) => r.backend === "openai").label);
console.log("   hosted row:", hosted.join(" | "));
check("hosted model beats the baseline on the paired test",
  hosted[4].indexOf("+") === 0 && hosted[7] === "▲", hosted[4] + " " + hosted[7]);
check("its unpaired interval is shown too", /\[/.test(hosted[3]), hosted[3]);

const local = cells("gemma3:4b (ollama)");
console.log("   local row:", local.join(" | "));
check("a local model that was never separated reads as such", local[7] === "≈", local[7]);

const baselineRow = rows.find((r) => r.className.indexOf("is-baseline") !== -1);
check("the baseline is marked", baselineRow && baselineRow.cells[0].textContent === RUNS.baseline.label,
  baselineRow ? baselineRow.cells[0].textContent : "(none)");
check("the retired run is named, not hidden",
  /2026-09-01/.test(text("results-body")) && /evidence/.test(text("results-body")));
check("both readings are explained",
  /paired/.test(text("results-body")) && /bootstrap/.test(text("results-body")));

click($("results-close"));
check("results close", $("results").hidden);
console.log(out.join("\n"));

console.log("\n── console ─────────────────────────────────────────────");
console.log(errors.length ? errors.join("\n") : "  no errors or warnings");
dom.window.close();
