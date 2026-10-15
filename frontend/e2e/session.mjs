// Live session (spec 5.0 C4.1, C4.3): record from Встречи → the meeting page opens at once with the audio pill →
// provisional lines appear → with `live_questions` on, the question card answers the question heard from a material
// "в контексте" and "Добавить в заметки" puts it into the notes → pause shows the paused state → resume → stop →
// the live lines stay with "the full transcript is being made" until the final transcript replaces them,
// "Требования из встречи" is shown and the meeting is processed.
// Runs once per interface language.
// Run: FAKE_RECORDER=1 DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 &
//      node frontend/e2e/session.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Встречи", record: "Записать встречу", consent: "Да, записывать", recording: "Идёт запись",
        pause: "Пауза", resume: "Продолжить", stop: "Завершить и расшифровать", listening: "Слушаю…",
        paused: "На паузе — звук не пишется", title: /^Встреча /, ready: "Разобран", kept: "Полная расшифровка готовится",
        reqs: "Требования из встречи",
        qTitle: "В разговоре прозвучал вопрос", qAdd: "Добавить в заметки", qNote: "- Вопрос: ", qAnswer: "Статус утверждает руководитель" },
  en: { locale: "en-US", heading: "Meetings", record: "Record a meeting", consent: "Yes, record", recording: "Recording",
        pause: "Pause", resume: "Resume", stop: "Stop and transcribe", listening: "Listening…",
        paused: "Paused: no audio is being recorded", title: /^Meeting /, ready: "Processed", kept: "The full transcript is being made",
        reqs: "Requirements from the meeting",
        qTitle: "A question came up in the call", qAdd: "Add to notes", qNote: "- Question: ", qAnswer: "Статус утверждает руководитель" },
};
const QUESTION = "А кто утверждает изменение статуса заявки дилера?";
const LIVE = ["Давайте начнём с заявок дилеров", "Заявки дублируются почти каждый день", "Проверяем дубли по VIN и телефону", QUESTION];
const MATERIAL = { title: "Регламент v2", text: "Изменение статуса заявки дилера утверждает руководитель отдела или его заместитель." };
const FINAL = "Нужна выгрузка отчёта в Excel";

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];

// The question card (C4.3) is off by default: turn it on through /settings, and give the current project a material
// "в контексте" that answers the scripted question, indexed by the fake index.
{
  const ctx = await browser.newContext();
  const req = ctx.request;
  const on = await (await req.post(base + "/settings", { data: { live_questions: true } })).json();
  if (on.live_questions !== true) throw new Error("live_questions did not turn on: " + JSON.stringify(on));
  const { current_project_id: pid } = await (await req.get(base + "/api/projects")).json();
  await req.post(`${base}/api/projects/${pid}/materials`, { data: MATERIAL });
  const { job_id } = await (await req.post(`${base}/api/projects/${pid}/index`, { data: {} })).json();
  for (let i = 0; job_id; i++) {
    const job = await (await req.get(`${base}/job/${job_id}`)).json();
    if (job.status === "done") break;
    if (job.status === "error" || i > 200) throw new Error("index job: " + JSON.stringify(job));
    await new Promise(r => setTimeout(r, 100));
  }
  await ctx.close();
}
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);
  const json = path => page.evaluate(p => fetch(p).then(r => r.json()), path);

  await page.goto(base + "/#/meetings");
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  await page.locator("button.rmain", { hasText: s.record }).click();
  const consent = page.getByRole("button", { name: s.consent });
  await consent.click();                     // a fresh browser session asks about consent first
  await page.waitForURL(/#\/meeting\/[0-9a-f-]+$/, { timeout: 5000 });
  const id = page.url().split("/").pop();
  const pill = page.locator(".audio-pill");
  await pill.waitFor();
  if (!(await pill.textContent()).includes(s.recording)) throw new Error("pill: " + await pill.textContent());
  const title = await page.locator("h1.mt-title").textContent();
  if (!s.title.test(title)) throw new Error("title: " + title);
  if (await page.locator(".hud").count()) throw new Error("the HUD should give way to the pill on the meeting page");
  const src = await json(`/api/sources/${id}`);
  if (src.status !== "recording") throw new Error("source status: " + src.status);
  step("recording starts from Встречи and lands on the meeting page with the pill; the meeting exists already");

  await page.locator(".listening.on", { hasText: s.listening }).waitFor();
  for (const text of LIVE) await page.locator(".live-row.provisional", { hasText: text }).waitFor({ timeout: 8000 });
  if (await page.locator(".live-row").count() !== 4) throw new Error("live rows: " + await page.locator(".live-row").count());
  step("four provisional lines appear while recording, ending with Слушаю…");

  const card = page.locator(".q-card", { hasText: s.qTitle });
  await card.waitFor({ timeout: 10000 });
  const cardText = await card.textContent();
  if (!cardText.includes(QUESTION) || !cardText.includes(s.qAnswer) || !cardText.includes(MATERIAL.title))
    throw new Error("question card: " + cardText);
  await card.getByRole("button", { name: s.qAdd }).click();
  await card.waitFor({ state: "detached" });
  const line = `${s.qNote}${QUESTION}`;
  await page.waitForFunction(l => document.querySelector("textarea.notes-editor")?.value.includes(l), line);
  const withNote = await json(`/api/sources/${id}`);
  if (!(withNote.notes || "").includes(line) || !(withNote.notes || "").includes(`(${MATERIAL.title})`))
    throw new Error("notes: " + withNote.notes);
  await page.waitForTimeout(2500);                       // two more polls: the dismissed card does not come back
  if (await page.locator(".q-card").count()) throw new Error("the question card came back");
  step("the question card answers the question from the material; Добавить в заметки puts the line into the notes");

  if (await page.locator(".live-req").count()) throw new Error("no requirements block while recording");
  if ("atoms" in await json(`/api/sources/${id}/live`)) throw new Error("the live poll should not carry requirements");
  step("no requirements are extracted while recording");

  await pill.getByRole("button", { name: s.pause, exact: true }).click();
  await page.locator(".audio-pill.paused").waitFor();
  await page.locator(".listening.paused", { hasText: s.paused }).waitFor();
  const st = await json("/desktop-record/status");
  if (!st.paused || st.pauses.length !== 1 || st.source_id !== id) throw new Error("status while paused: " + JSON.stringify(st));
  step("pause shows the paused state; the recorder reports the paused span");

  await pill.getByRole("button", { name: s.resume, exact: true }).click();
  await page.locator(".audio-pill:not(.paused)").waitFor();
  await page.locator(".listening.on").waitFor();
  const st2 = await json("/desktop-record/status");
  if (st2.paused || st2.pauses[0][1] == null) throw new Error("status after resume: " + JSON.stringify(st2));
  step("resume continues the recording");

  await pill.getByRole("button", { name: s.stop, exact: true }).click();
  await page.locator(".rough-note", { hasText: s.kept }).waitFor({ timeout: 8000 });
  for (const text of LIVE) await page.locator(".rough-lines .live-row.provisional", { hasText: text }).waitFor({ timeout: 1000 });
  const processing = await json(`/api/sources/${id}`);
  if (processing.status !== "processing" || processing.segments.length !== 4 || !processing.segments.every(x => x.provisional))
    throw new Error("processing source: " + JSON.stringify({ status: processing.status, segments: processing.segments }));
  step("after stop the live lines stay, lighter, under “the full transcript is being made”");

  await page.locator(".seg-row", { hasText: FINAL }).first().waitFor({ timeout: 20000 });
  if (await page.locator(".live-row").count()) throw new Error("provisional lines are still shown");
  const done = await json(`/api/sources/${id}`);
  if (done.status !== "ready" || done.segments.some(x => x.provisional) || done.segments.some(x => LIVE.includes(x.text)))
    throw new Error("final source: " + JSON.stringify({ status: done.status, segments: done.segments }));
  if (!done.audio_files.some(f => f.id === "mic") || !done.audio_files.some(f => f.id === "sys") || done.audio_file !== "mixed.wav")
    throw new Error("audio files: " + JSON.stringify(done.audio_files));
  step("stop: the final transcript replaces the provisional lines; mic, sys and mixed audio are kept");

  await page.locator(".live-req h2", { hasText: s.reqs }).waitFor();
  step("after stop the meeting's requirements block is shown");

  await page.goto(base + "/#/meetings");
  await page.locator(`#src-${id} .right .tag`, { hasText: s.ready }).waitFor({ timeout: 10000 });
  step("the meeting is listed as processed");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log("session: all checks passed");
