// Meeting language (5.0.5): the record panel opens with the project's language (Russian on a new project) → pick
// Multilingual: the project keeps it and the row offers the multilingual model's download (the fake server has no
// model on disk) → start and stop: both requests carry the multilingual model, the meeting remembers it → the panel
// reopens on Multilingual → another project has its own value → the import menu shows the same row and the upload
// carries the model → Settings → Модели has a picker per language, and the panel follows it.
// Runs once per interface language, each on a project of its own.
// Run: FAKE_RECORDER=1 DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5321 &
//      node frontend/e2e/language.mjs http://127.0.0.1:5321
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Встречи", consent: "Да, записывать", stop: "Завершить и расшифровать", multi: "Multilingual",
        ru: "Русский", title: "Язык встречи", download: "Скачать", pickRu: "Модель для русского", pickMulti: "Модель для других языков" },
  en: { locale: "en-US", heading: "Meetings", consent: "Yes, record", stop: "Stop and transcribe", multi: "Multilingual",
        ru: "Russian", title: "Meeting language", download: "Download", pickRu: "Model for Russian", pickMulti: "Model for other languages" },
};
const MULTI = "multilingual_ctc";

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);
  const req = ctx.request;
  const json = async path => (await req.get(base + path)).json();
  const until = async (fn, what) => {
    for (let i = 0; i < 100; i++) { if (await fn()) return; await page.waitForTimeout(100); }
    throw new Error("timed out: " + what);
  };
  const project = async id => (await json("/api/projects")).projects.find(p => p.id === id);

  // Two projects of this run; the first is current.
  const a = await (await req.post(base + "/api/projects", { data: { name: `Мультиязычный ${lang}` } })).json();
  const b = await (await req.post(base + "/api/projects", { data: { name: `Русский ${lang}` } })).json();
  await req.post(`${base}/api/projects/${a.id}/current`);

  await page.goto(base + "/#/meetings");
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  const pop = page.locator(".rec-pop");
  const row = pop.locator(".ml");
  await page.locator(".rec-wrap .chev").click();
  await row.locator(`button[data-lang="ru"][aria-pressed="true"]`).waitFor();
  if (!(await row.textContent()).includes(s.title)) throw new Error("language row: " + await row.textContent());
  if (await pop.locator(".rp-model").count()) throw new Error("the model line is still there");
  step("the record panel opens on Russian for a new project");

  await row.getByRole("button", { name: s.multi, exact: true }).click();
  await pop.locator(`.ml[data-lang="multi"][data-model="${MULTI}"][data-installed="false"]`).waitFor();
  await pop.locator(".ml-download", { hasText: s.download }).waitFor();
  await until(async () => (await project(a.id)).asr_lang === "multi", "project a keeps Multilingual");
  step("Multilingual: the project keeps it, the missing model offers its download");

  const started = page.waitForRequest(r => r.url().endsWith("/desktop-record/start") && r.method() === "POST");
  await pop.locator(".rp-start").click();
  await page.getByRole("button", { name: s.consent }).click();
  const startBody = (await started).postDataJSON();
  if (startBody.model !== MULTI) throw new Error("start carried " + startBody.model);
  await page.waitForURL(/#\/meeting\/[0-9a-f-]+$/, { timeout: 5000 });
  const id = page.url().split("/").pop();
  await page.waitForTimeout(1500);                                   // some audio first
  const stopped = page.waitForRequest(r => r.url().endsWith("/desktop-record/stop"));
  await page.locator(".audio-pill").getByRole("button", { name: s.stop, exact: true }).click();
  const stopBody = (await stopped).postDataJSON();
  if (stopBody.model !== MULTI) throw new Error("stop carried " + stopBody.model);
  await until(async () => (await json(`/api/sources/${id}`)).asr_model === MULTI, "the meeting remembers its model");
  step("start and stop carry the multilingual model; the meeting remembers it");

  await page.goto(base + "/#/meetings");
  await page.locator(`#src-${id}`).click();
  await page.locator(".panel .ml-tag", { hasText: s.multi }).waitFor();
  await page.locator(".rec-wrap .chev").click();
  await row.locator(`button[data-lang="multi"][aria-pressed="true"]`).waitFor();
  step("the meeting shows Multilingual; the panel reopens on it");

  await req.post(`${base}/api/projects/${b.id}/current`);
  await page.reload();
  await page.locator(".rec-wrap .chev").click();
  await row.locator(`button[data-lang="ru"][aria-pressed="true"]`).waitFor();
  await req.post(`${base}/api/projects/${a.id}/current`);
  await page.reload();
  await page.locator(".rec-wrap .chev").click();
  await row.locator(`button[data-lang="multi"][aria-pressed="true"]`).waitFor();
  await page.keyboard.press("Escape");
  step("each project opens on its own language");

  // Import: the same row, preselected; the upload carries the model.
  await page.locator(".imp-wrap .ichev").click();
  const imp = page.locator(".imp-pop");
  await imp.locator(`.ml button[data-lang="multi"][aria-pressed="true"]`).waitFor();
  const chooser = page.waitForEvent("filechooser");
  await imp.locator(".rp-start").click();
  const uploaded = page.waitForRequest(r => new URL(r.url()).pathname === "/transcribe");
  const wav = Buffer.alloc(44 + 3200);
  wav.write("RIFF", 0); wav.writeUInt32LE(36 + 3200, 4); wav.write("WAVEfmt ", 8); wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(16000, 24); wav.writeUInt32LE(32000, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(3200, 40);
  await (await chooser).setFiles({ name: `Call ${lang}.wav`, mimeType: "audio/wav", buffer: wav });
  const res = await (await uploaded).response();       // a multipart body with a file is not readable here: ask the server
  const { source_id: imported } = await res.json();
  const src = await json(`/api/sources/${imported}`);
  if (src.asr_model !== MULTI) throw new Error("the import was transcribed with " + src.asr_model);
  step("the import menu has the same row; the upload carries the multilingual model");

  // Settings → Модели: a picker per language; the record panel follows the multilingual one.
  await page.goto(base + "/#/settings/models");
  await page.getByLabel(s.pickRu, { exact: true }).waitFor();
  const multiPick = page.getByLabel(s.pickMulti, { exact: true });
  if ((await multiPick.locator("option").count()) !== 2) throw new Error("the multilingual picker lists other models");
  await multiPick.selectOption("multilingual_large_ctc");
  await until(async () => (await json("/settings")).asr_langs.multi === "multilingual_large_ctc", "the multilingual choice is saved");
  await page.goto(base + "/#/meetings");
  await page.locator(".rec-wrap .chev").click();
  await pop.locator(`.ml[data-lang="multi"][data-model="multilingual_large_ctc"]`).waitFor();
  await req.post(base + "/settings", { data: { asr_model_multi: MULTI } });       // the next run starts as before
  step("Settings → Models: one picker per language; the record panel follows it");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log("language: all checks passed");
