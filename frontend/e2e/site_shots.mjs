// Screenshots for the site (getdictum.app): nine screens of one realistic English project, light and dark, 1440×900 @2x,
// against e2e/fake_llm_server.py on a fresh data folder. The fake server is switched to its site mode first
// (POST /__fake/site): realistic English recaps, answers, requirements, document and backlog.
// Run: DICTUM_DATA_DIR=$(mktemp -d) FAKE_RECORDER=1 .venv/bin/python frontend/e2e/fake_llm_server.py 5098 &
//      cd frontend && node e2e/site_shots.mjs http://127.0.0.1:5098 [out dir, or OUT=…; default site/img]
import { chromium } from "playwright-core";
import { mkdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] || "http://127.0.0.1:5098";
const out = process.env.OUT || process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), "../../site/img");
const SCALE = Number(process.env.SCALE || 2);
mkdirSync(out, { recursive: true });
const step = name => console.log("✓", name);

// ── Seed content ────────────────────────────────────────────────────────────────────────────────────────────────
const vtt = cues => "WEBVTT\n\n" + cues.map(([who, text], i) => {
  const t = s => `00:${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}.000`;
  const at = 4 + i * 17;
  return `${t(at)} --> ${t(at + 14)}\n<v ${who}>${text}</v>\n`;
}).join("\n");

const DISCOVERY = "Discovery call · Contact-centre CRM";
const DISCOVERY_VTT = vtt([
  ["Mark", "Thanks for making the time, Anna. Let's start with what an operator sees when a call comes in."],
  ["Anna", "Today they wait for the CRM to load, sometimes ten seconds. The client card must open within two seconds of an incoming call."],
  ["Mark", "So it opens on ring, before the operator picks up?"],
  ["Anna", "Yes. The CRM should look the caller up in the PBX by phone number while it is still ringing."],
  ["Anna", "And if the number is unknown, open the search with the number already filled in."],
  ["Mark", "What should the card show first?"],
  ["Anna", "Open orders, the last three calls, and any complaint that is still open. That's what they ask about."],
  ["Mark", "And supervisors, how do they follow live calls today?"],
  ["Anna", "They walk over and stand behind people. We want them to listen in silently on any live call, no beep for the customer or the operator."],
  ["Anna", "Every listen-in is logged: who, when, which call. Compliance will ask for it."],
  ["Mark", "Who may listen in, team leads or only the quality team?"],
  ["Anna", "Good question, I'll check with Olga. Oh, and call recordings are kept for ninety days, then deleted automatically."],
  ["Mark", "Last one from me: does the PBX vendor have an API for the lookup, or do we poll the call log?"],
  ["Anna", "No idea, honestly. Ask Daniel at the vendor, I'll send you his address."],
]);
const FOLLOWUP = "Follow-up with the PBX vendor";
const FOLLOWUP_VTT = vtt([
  ["Mark", "Daniel, thanks for joining. The main question is the caller lookup when the phone rings."],
  ["Daniel", "We send a webhook on ring with the caller's number, usually within a hundred milliseconds."],
  ["Mark", "Can the CRM answer that webhook with the client's name for the operator's phone display?"],
  ["Daniel", "Yes, if you reply within 300 milliseconds the name shows on the handset."],
  ["Daniel", "One thing: silent listen-in is only on the Enterprise tier, so check the client's licence."],
  ["Mark", "Good. I'll send you the list of fields we need for the lookup by Friday."],
]);
const NOTES = "Anna: head of the contact centre, 40 operators in two shifts\n- [ ] Ask Daniel (PBX vendor) about the lookup API\n- [ ] Check with Olga who may listen in";
const MATERIALS = [
  { title: "CRM spec v0.3 — client card", label: "CRM", text:
    "Client card. When a call comes in, the PBX passes the caller's phone number to the CRM on ring. The CRM looks the " +
    "client up by phone number and opens the client card within two seconds of the incoming call. The card shows open " +
    "orders, the last three calls and open complaints. If the phone number is unknown, the operator gets client search " +
    "with the number filled in.\n\nResponse time. The client card is on screen within two seconds of the incoming call, " +
    "measured at the 95th percentile over a working day. The lookup starts while the phone is still ringing.\n\n" +
    "Out of scope for v1: outbound campaigns, the dialler, chat." },
  { title: "Email thread: listen-in and recordings", label: "compliance", text:
    "From: Anna Lindqvist\nTo: Mark Ellis\nSubject: Re: listen-in and recordings\n\nMark, compliance confirmed: " +
    "supervisors may listen in silently on live calls, but every listen-in must be logged with the supervisor, the time " +
    "and the call. Call recordings are kept for ninety days and then deleted. Operators are told about monitoring in " +
    "their contract, not by a beep on the call.\n\nAnna\n\n> Anna, could you check with compliance whether silent " +
    "listen-in is allowed and how long we keep call recordings?\n> Mark" },
  { title: "PBX API note", label: "telephony", text:
    "PBX API, vendor docs v4. Ring webhook: the PBX sends a POST to the CRM with the caller's phone number, the call ID " +
    "and the line, on ring, within 100 ms. If the CRM answers within 300 ms with a display name, the name shows on the " +
    "operator's handset. The client lookup by phone number is the CRM's job; the PBX does not store clients.\n\n" +
    "Silent listen-in: POST /calls/{id}/monitor with mode=silent. Enterprise tier only." },
];
const QUESTION = "What did the client say about response time?";

// ── Seed through the API ────────────────────────────────────────────────────────────────────────────────────────
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
const seedCtx = await browser.newContext({ locale: "en-US", viewport: { width: 1440, height: 900 } });
const req = seedCtx.request;
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
await json("PATCH", `/api/projects/${pid}`, { name: "Contact-centre CRM", auto_extract: false, language: "en" });

async function importMeeting(title, text) {
  const r = await req.post(base + "/transcribe", {
    multipart: { project_id: pid, audio: { name: `${title}.vtt`, mimeType: "text/vtt", buffer: Buffer.from(text) } } });
  if (!r.ok()) throw new Error("import: " + r.status());
  return until(async () => (await json("GET", `/api/projects/${pid}/sources`)).sources
    .find(s => s.title === title && s.status === "ready"), "meeting " + title);
}
const extract = async id => job((await json("POST", `/api/sources/${id}/atoms/extract`, {})).job_id);

const followup = await importMeeting(FOLLOWUP, FOLLOWUP_VTT);
const discovery = await importMeeting(DISCOVERY, DISCOVERY_VTT);
await json("PUT", `/api/sources/${discovery.id}/notes`, { text: NOTES });
for (const s of [followup, discovery]) {
  await job((await json("POST", `/api/sources/${s.id}/recap`, { style: "brief" })).job_id);
  await json("PATCH", `/api/sources/${s.id}`, { recap_style: "brief" });
}
step("two meetings with a brief recap, notes on the discovery call");

// Requirements: the vendor follow-up extracted and left for review (listed first), the discovery call reviewed (all
// but one question accepted), a document and a backlog built from it.
await extract(followup.id);
const pending = new Set((await json("GET", `/api/projects/${pid}/atoms`)).atoms.map(a => a.id));
await extract(discovery.id);
let atoms = (await json("GET", `/api/projects/${pid}/atoms`)).atoms;
await json("POST", `/api/projects/${pid}/atoms/bulk`, { items: atoms.filter(a => !pending.has(a.id) && !/poll the call log/.test(a.statement))
  .map(a => ({ id: a.id, status: "accepted" })) });
await job((await json("POST", `/api/projects/${pid}/document/build`, { mode: "full" })).job_id);
await job((await json("POST", `/api/projects/${pid}/backlog/build`, {})).job_id);
atoms = (await json("GET", `/api/projects/${pid}/atoms`)).atoms;
step(`requirements: ${atoms.length} (${atoms.filter(a => a.status === "accepted").length} accepted), a document, a backlog`);

const mats = {};
for (const m of MATERIALS) {
  const added = await json("POST", `/api/projects/${pid}/materials`, { text: m.text, title: m.title });
  mats[m.title] = added.materials[0].id;
  await job(added.index_job);
}
await job((await json("POST", `/api/projects/${pid}/index`, {})).job_id);
for (const m of MATERIALS) await json("POST", `/api/projects/${pid}/labels`, { name: m.label, seed_material_id: mats[m.title] });
for (const m of (await json("GET", `/api/projects/${pid}/materials`)).materials)     // keep only the confident auto labels
  for (const l of m.labels) if (l.assigned_by === "auto" && l.score < 0.6) await json("DELETE", `/api/materials/${m.id}/labels/${l.id}`);
await job((await json("POST", `/api/projects/${pid}/ask`, { question: QUESTION, context_only: false })).job_id);
step("three materials indexed, three labels, the question asked");

const friday = new Date();
friday.setDate(friday.getDate() + ((5 - friday.getDay() + 7) % 7 || 7));
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
for (const [transcript, item] of [
  ["An idea: show an open complaint as a red banner at the top of the client card",
   { kind: "idea", title: "Open complaint as a banner on the client card", text: "show an open complaint as a red banner at the top of the client card" }],
  ["Task: draft the listen-in NFR before the review",
   { kind: "task", title: "Draft the listen-in NFR", text: "draft the listen-in NFR before the review" }],
  ["Remind me on Friday at ten to send Anna the PBX question",
   { kind: "remind", title: "Send Anna the PBX question", text: "on Friday at ten send Anna the PBX question", due: `${iso(friday)}T10:00` }],
]) await json("POST", "/api/whispers", { transcript, items: [{ ...item, project_id: pid }] });
step("three whispers");
await seedCtx.close();

// ── Screens ─────────────────────────────────────────────────────────────────────────────────────────────────────
const SCREENS = [
  ["meetings", "#/meetings", async page => {
    await page.locator(".item", { hasText: FOLLOWUP }).waitFor();
    await page.locator(".item", { hasText: DISCOVERY }).click();
    await page.locator(".panel-head h2", { hasText: DISCOVERY }).waitFor();
    const tab = page.locator(".mtabs").getByRole("tab", { name: "Summary", exact: true });
    await tab.click();
    await page.locator(".panel .recap .md", { hasText: "two seconds" }).waitFor();
  }],
  ["meeting", `#/meeting/${discovery.id}`, async page => {
    await page.locator(".seg-row", { hasText: "two seconds" }).first().waitFor();
    await page.locator(".inspector .recap .md", { hasText: "two seconds" }).waitFor();
  }],
  ["library", "#/library", async page => {
    await page.getByRole("button", { name: "Graph", exact: true }).click();
    const node = page.locator(".graph g.gnode", { hasText: MATERIALS[0].title.slice(0, 20) });
    await node.waitFor();
    await node.click();
    await page.locator(".panel-head h2", { hasText: MATERIALS[0].title }).waitFor();
    await page.locator(".panel .links.related .r").first().waitFor();
  }],
  ["ask", "#/ask", async page => {
    const box = page.getByPlaceholder("Ask about the project…");
    await box.waitFor();
    await page.locator(".hist .h .hq", { hasText: QUESTION }).first().click();       // asked while seeding
    await page.locator(".msg.ai .st", { hasText: /Found in/ }).waitFor({ timeout: 20000 });
    await page.locator(".msg.ai button.cite").first().waitFor();
    await box.fill("");
    await box.blur();
    await page.waitForTimeout(2500);                   // the re-shown answer's highlight fades
  }],
  ["whisper", "#/whisper", async page => {
    await page.locator(".winbox .witem", { hasText: "Send Anna the PBX question" }).waitFor();
    await page.locator(".winbox .witem").nth(2).waitFor();
  }],
  ["requirements", "#/atoms", async page => {
    await page.locator(".atom").first().waitFor();
    const notNow = page.getByRole("button", { name: "Not now", exact: true });
    if (await notNow.count()) { await notNow.click(); await notNow.waitFor({ state: "detached" }); }
    await page.locator(".scope .seg-m").getByRole("button", { name: /^All/ }).click();
    await page.locator(".atom", { hasText: "ring webhook with the caller" }).first().click();
  }],
  ["documents", "#/document", async page => { await page.locator(".paper").waitFor(); }],
  ["backlog", "#/backlog", async page => {
    await page.locator(".tree .node.story").first().click();
    await page.locator(".inspector, aside").filter({ hasText: "Open the client card on ring" }).first().waitFor();
  }],
  ["settings", "#/settings/models", async page => { await page.locator('.setcards[data-section="models"]').waitFor(); }],
];
const only = process.env.ONLY ? process.env.ONLY.split(",") : null;

for (const scheme of ["light", "dark"]) {
  const ctx = await browser.newContext({ locale: "en-US", colorScheme: scheme, viewport: { width: 1440, height: 900 },
                                         deviceScaleFactor: SCALE });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(e.message));
  page.on("response", r => { if (r.status() >= 400) errors.push(`${r.status()} ${r.url()}`); });
  for (const [name, hash, ready] of SCREENS) {
    if (only && !only.includes(name)) continue;
    await page.goto(`${base}/${hash}`);
    await page.locator(".screen-title").first().waitFor();
    await ready(page);
    await page.waitForLoadState("networkidle");
    await page.locator(".status-chip.idle").waitFor({ timeout: 20000 });      // no job running in the top bar
    await page.locator(".toast").first().waitFor({ state: "detached", timeout: 15000 }).catch(() => {});
    await page.mouse.move(1439, 899);
    await page.evaluate(() => { window.scrollTo(0, 0); for (const el of document.querySelectorAll("*")) if (el.scrollTop) el.scrollTop = 0; });
    await page.waitForTimeout(600);
    const busy = await page.locator(".toast, .spinner, [aria-busy=true]").count();
    if (busy) console.warn(`  ${name}-${scheme}: ${busy} toast/spinner element(s) on screen`);
    const file = join(out, `${name}-${scheme}.png`);
    await page.screenshot({ path: file });
    step(`${name}-${scheme} (${Math.round(statSync(file).size / 1024)} KB)`);
  }
  await ctx.close();
}

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("screenshots in", out);
