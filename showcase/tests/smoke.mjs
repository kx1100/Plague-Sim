// Load showcase/index.html in jsdom with the real generated data, drive the
// transport, and report anything that errors or renders wrong.
import { JSDOM, VirtualConsole } from "jsdom";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const DIR = fileURLToPath(new URL("..", import.meta.url));
const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + (e.stack || e.message)));
vc.on("error", (...a) => errors.push("console.error: " + a.join(" ")));
vc.on("warn", (...a) => errors.push("console.warn: " + a.join(" ")));

const html = readFileSync(`${DIR}/index.html`, "utf8");

const dom = new JSDOM(html, {
  runScripts: "dangerously",
  url: "https://example.test/showcase/index.html",
  virtualConsole: vc,
  resources: undefined,
  beforeParse(window) {
    // Local <script src> is not fetched by jsdom without a resource loader, so
    // the generated globals are injected exactly as the browser would have.
    for (const f of ["traits.js", "world.js", "replay.example.js"]) {
      window.eval(readFileSync(`${DIR}/${f}`, "utf8"));
    }
    // No real run bundled: make fetch fail the way a 404 would.
    window.fetch = () => Promise.resolve({ ok: false, json: () => Promise.resolve(null) });
    window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
  },
});

const { window } = dom;
const $ = (id) => window.document.getElementById(id);
const text = (id) => ($(id) ? $(id).textContent.trim() : "<<missing #" + id + ">>");

await new Promise((r) => setTimeout(r, 300));

const results = [];
const check = (label, ok, detail) => {
  results.push(`  [${ok ? "PASS" : "FAIL"}] ${label}${detail ? " — " + detail : ""}`);
  return ok;
};

console.log("── boot ────────────────────────────────────────────────");
check("model named", text("model") === "reference expert policy", text("model"));
check("run meta", /seed USA · 400 turns/.test(text("runmeta")), text("runmeta"));
check("outcome badge", text("outcome") === "infected_all", text("outcome"));
check("sample notice shown", !$("notice").hidden);
check("map built", window.document.querySelectorAll(".country").length === 71,
  window.document.querySelectorAll(".country").length + " tiles");
check("regions labelled", window.document.querySelectorAll(".region").length === 6,
  [...window.document.querySelectorAll(".region-label")].map((n) => n.textContent).join(" | "));
check("chart drawn", ($("p-inf").getAttribute("points") || "").split(" ").length === 400);
check("action ticks", window.document.querySelectorAll(".tick").length === 41,
  window.document.querySelectorAll(".tick").length + " ticks");

console.log(results.join("\n"));
results.length = 0;

console.log("\n── frame 0 ─────────────────────────────────────────────");
check("day", text("v-day") === "1", text("v-day"));
check("no purchases yet shown as such", /Nothing evolved/.test(text("buys")) || text("trait-count") === "1 / 60",
  text("trait-count") + " · " + text("buys").slice(0, 40));
console.log(results.join("\n"));
results.length = 0;

// Drive the scrubber to the hero frame used in the design.
const scrub = $("scrub");
scrub.value = "325";
scrub.dispatchEvent(new window.Event("input"));

console.log("\n── frame 326 (design hero) ─────────────────────────────");
console.log("   day", text("v-day"), "| inf", text("v-inf"), "| dead", text("v-dead"), "| cure", text("v-cure"));
console.log("   action:", text("action-name"), "| cost", text("action-cost"), "|", text("dna-left"));
console.log("   traits:", text("trait-count"), "| countries:", text("v-countries"));
console.log("   trees:", [...window.document.querySelectorAll(".tree")].map((n) => n.textContent.replace(/\s+/g, " ").trim()).join(" | "));
console.log("   counter:", text("counter"));
console.log("   reasoning:", text("reasoning").slice(0, 90) + "…");
check("action is the expected trait", text("action-name") === "InternalHaemorrhaging", text("action-name"));
check("cost from the trait table", text("action-cost") === "12", text("action-cost"));
check("trait count", text("trait-count") === "38 / 60", text("trait-count"));
const treeText = [...window.document.querySelectorAll(".tree")].map((n) => n.textContent.replace(/\s+/g, " ").trim()).join(", ");
check("tree split", /symptom ?24\/32/.test(treeText.replace(/\s+/g, " ")), treeText);
check("history newest first", window.document.querySelector(".buy .buy-name").textContent === "Internal Haemorrhaging",
  window.document.querySelector(".buy .buy-name").textContent);
check("history is complete", window.document.querySelectorAll(".buy").length === 38,
  window.document.querySelectorAll(".buy").length + " rows");

// Map colouring: Australia must be visibly behind at this frame.
const tiles = [...window.document.querySelectorAll(".country")];
const aus = tiles.find((t) => t.title === "Australia");
const usa = tiles.find((t) => t.title === "USA");
check("Australia outlined as lagging", /solid/.test(aus.style.outline), aus.style.outline || "(none)");
check("USA not outlined", !/solid/.test(usa.style.outline || ""), usa.style.outline || "(none)");
check("tiles are tinted", /oklch/.test(usa.style.background), usa.style.background);
console.log("   Australia:", aus.style.background, "| USA:", usa.style.background);
console.log(results.join("\n"));
results.length = 0;

console.log("\n── transport ───────────────────────────────────────────");
$("next").dispatchEvent(new window.Event("click"));
check("next advances", text("v-day") === "327", "day " + text("v-day"));
$("prev").dispatchEvent(new window.Event("click"));
check("prev rewinds", text("v-day") === "326", "day " + text("v-day"));

scrub.value = "399";
scrub.dispatchEvent(new window.Event("input"));
check("last frame", text("v-day") === "400", "day " + text("v-day"));
console.log("   final: inf", text("v-inf"), "dead", text("v-dead"), "cure", text("v-cure"), "|", text("counter"));

$("next").dispatchEvent(new window.Event("click"));
check("cannot run past the end", text("v-day") === "400", "day " + text("v-day"));

scrub.value = "0";
scrub.dispatchEvent(new window.Event("input"));
check("scrubs back to the start", text("v-day") === "1", "day " + text("v-day"));

// Play, then confirm it advances and stops cleanly.
$("play").dispatchEvent(new window.Event("click"));
await new Promise((r) => setTimeout(r, 260));
const advanced = Number(text("v-day")) > 1;
$("play").dispatchEvent(new window.Event("click"));
check("play advances frames", advanced, "reached day " + text("v-day"));
console.log(results.join("\n"));

console.log("\n── console ─────────────────────────────────────────────");
console.log(errors.length ? errors.join("\n") : "  no errors or warnings");
dom.window.close();
