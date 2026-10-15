// Screenshots of a project with business analysis off (5.0.4): Встречи and Settings → Project, ru and en, light,
// 1440×900, against e2e/fake_llm_server.py on a fresh data folder in its site mode (realistic English content).
// Usage: node frontend/e2e/notes_mode_shots.mjs http://127.0.0.1:5098 [out dir, or OUT=…; default docs/design/5.0]
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] || "http://127.0.0.1:5098";
const out = process.env.OUT || process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), "../../docs/design/5.0");
mkdirSync(out, { recursive: true });

const vtt = cues => "WEBVTT\n\n" + cues.map(([who, text], i) => {
  const t = s => `00:${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}.000`;
  const at = 4 + i * 17;
  return `${t(at)} --> ${t(at + 14)}\n<v ${who}>${text}</v>\n`;
}).join("\n");
const MEETINGS = [
  ["Weekly sync · design team", vtt([
    ["Lena", "Quick round: the onboarding screens are in review, two comments left from Max."],
    ["Max", "Both are about the empty state copy, I'll send the final text today."],
    ["Lena", "Good. Next week we start on the settings page, I'd like a draft by Wednesday."],
    ["Tom", "I'm off on Friday, so let's review the draft on Thursday morning."],
  ])],
  ["1:1 with Tom", vtt([
    ["Lena", "How is the new icon set going?"],
    ["Tom", "Forty of sixty icons done. The rest are the editor tools, I need the final list from Max."],
    ["Lena", "Let's agree you ship the first forty to the repo this week so others can use them."],
  ])],
  ["Discovery call · Contact-centre CRM", vtt([
    ["Mark", "Thanks for making the time, Anna. Let's start with what an operator sees when a call comes in."],
    ["Anna", "Today they wait for the CRM to load, sometimes ten seconds. The client card must open within two seconds of an incoming call."],
    ["Mark", "So it opens on ring, before the operator picks up?"],
    ["Anna", "Yes. The CRM should look the caller up in the PBX by phone number while it is still ringing."],
    ["Anna", "Open orders, the last three calls, and any complaint that is still open. That's what they ask about."],
    ["Anna", "Good question, I'll check with Olga. Oh, and call recordings are kept for ninety days, then deleted automatically."],
  ])],
];
const NOTES = "Anna: head of the contact centre, 40 operators in two shifts\n- [ ] Send Anna the call summary\n- [ ] Book the follow-up with the PBX vendor";

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
const seed = await browser.newContext({ locale: "en-US" });
const req = seed.request;
const json = async (method, path, data) => {
  const r = await req.fetch(base + path, { method, ...(data !== undefined ? { data } : {}) });
  if (!r.ok()) throw new Error(`${method} ${path}: ${r.status()} ${await r.text()}`);
  return r.json();
};
async function until(fn, what, tries = 300) {
  for (let i = 0; i < tries; i++) { const v = await fn(); if (v) return v; await new Promise(r => setTimeout(r, 100)); }
  throw new Error("timed out: " + what);
}
const job = async id => id && until(async () => {
  const j = await json("GET", `/job/${id}`);
  if (j.status === "error") throw new Error("job failed: " + JSON.stringify(j));
  return j.status === "done" && j;
}, "job " + id);

await json("POST", "/__fake/site", { on: true });
const pid = (await json("GET", "/api/projects")).current_project_id;
await json("PATCH", `/api/projects/${pid}`, { name: "Team meetings", analysis: false, language: "en" });
let last = null;
for (const [title, text] of MEETINGS) {
  const r = await req.post(base + "/transcribe", {
    multipart: { project_id: pid, audio: { name: `${title}.vtt`, mimeType: "text/vtt", buffer: Buffer.from(text) } } });
  if (!r.ok()) throw new Error("import: " + r.status());
  last = await until(async () => (await json("GET", `/api/projects/${pid}/sources`)).sources
    .find(s => s.title === title && s.status === "ready"), "meeting " + title);
  await job((await json("POST", `/api/sources/${last.id}/recap`, { style: "brief" })).job_id);
}
await json("PUT", `/api/sources/${last.id}/notes`, { text: NOTES });
await seed.close();
console.log("✓ seeded: three meetings with recaps, business analysis off");

for (const [lang, locale] of [["ru", "ru-RU"], ["en", "en-US"]]) {
  const ctx = await browser.newContext({ locale, viewport: { width: 1440, height: 900 }, colorScheme: "light", deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  await page.goto(base + "/#/meetings");
  await page.locator(".item", { hasText: "Discovery call" }).click();
  await page.locator(".panel-body").waitFor();
  await page.waitForTimeout(800);
  await page.screenshot({ path: join(out, `notes-mode-meetings-${lang}.png`) });
  await page.goto(base + "/#/settings/project");
  await page.locator("#set-project input.analysis:not(:checked)").waitFor();
  await page.waitForTimeout(400);
  await page.screenshot({ path: join(out, `notes-mode-settings-${lang}.png`) });
  console.log(`✓ ${lang}`);
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("screenshots in", out);
