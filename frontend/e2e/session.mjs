// Live session (spec 5.0 C4.1, C4.2): record from Встречи → the meeting page opens at once with the audio pill →
// provisional lines appear → a requirement found on the fly appears with the "1 новое" tag → accept it with its
// checkbox → pause shows the paused state → resume → stop → the final transcript replaces the provisional lines,
// the meeting is processed and the accepted requirement is listed under "Требования из встречи".
// Runs once per interface language.
// Run: FAKE_RECORDER=1 WORKBENCH_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 &
//      node frontend/e2e/session.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Встречи", record: "Записать встречу", consent: "Да, записывать", recording: "Идёт запись",
        pause: "Пауза", resume: "Продолжить", stop: "Завершить и расшифровать", listening: "Слушаю…",
        paused: "На паузе — звук не пишется", title: /^Встреча /, ready: "Разобран",
        liveReqs: "Требования на лету", newOne: "1 новое", reqs: "Требования из встречи" },
  en: { locale: "en-US", heading: "Meetings", record: "Record a meeting", consent: "Yes, record", recording: "Recording",
        pause: "Pause", resume: "Resume", stop: "Stop and transcribe", listening: "Listening…",
        paused: "Paused: no audio is being recorded", title: /^Meeting /, ready: "Processed",
        liveReqs: "Requirements on the fly", newOne: "1 new", reqs: "Requirements from the meeting" },
};
const LIVE = ["Давайте начнём с заявок дилеров", "Заявки дублируются почти каждый день", "Проверяем дубли по VIN и телефону"];
const FINAL = "Нужна выгрузка отчёта в Excel";
const LIVE_REQ = "Проверять дубли заявок по VIN и телефону";

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
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
  if (await page.locator(".live-row").count() !== 3) throw new Error("live rows: " + await page.locator(".live-row").count());
  step("three provisional lines appear while recording, ending with Слушаю…");

  const block = page.locator(".live-atoms");
  await block.locator("h2", { hasText: s.liveReqs }).waitFor();
  const req = block.locator(".req", { hasText: LIVE_REQ });
  await req.waitFor({ timeout: 10000 });
  const tag = block.locator(".new-tag");
  await tag.waitFor();
  if ((await tag.textContent()).trim() !== s.newOne) throw new Error("new tag: " + await tag.textContent());
  if (!(await req.textContent()).includes("«дубли по VIN и телефону»")) throw new Error("live req: " + await req.textContent());
  step("a requirement found on the fly appears under the notes with the new tag");

  await req.getByRole("checkbox").check();
  await tag.waitFor({ state: "detached" });
  for (let i = 0; i < 50; i++) {
    const a = (await json(`/api/sources/${id}/live`)).atoms.find(x => x.statement === LIVE_REQ);
    if (a?.status === "accepted" && a.live) break;
    if (i === 49) throw new Error("live atom not accepted: " + JSON.stringify(a));
    await page.waitForTimeout(100);
  }
  if (!(await req.getByRole("checkbox").isChecked())) throw new Error("the checkbox did not stay checked");
  step("its checkbox accepts it; looking at the block clears the tag");

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
  await page.locator(".seg-row", { hasText: FINAL }).first().waitFor({ timeout: 20000 });
  if (await page.locator(".live-row").count()) throw new Error("provisional lines are still shown");
  const done = await json(`/api/sources/${id}`);
  if (done.status !== "ready" || done.segments.some(x => x.provisional) || done.segments.some(x => LIVE.includes(x.text)))
    throw new Error("final source: " + JSON.stringify({ status: done.status, segments: done.segments }));
  if (!done.audio_files.some(f => f.id === "mic") || !done.audio_files.some(f => f.id === "sys") || done.audio_file !== "mixed.wav")
    throw new Error("audio files: " + JSON.stringify(done.audio_files));
  step("stop: the final transcript replaces the provisional lines; mic, sys and mixed audio are kept");

  await page.locator(".live-req h2", { hasText: s.reqs }).waitFor();
  await page.locator(".live-req .req", { hasText: LIVE_REQ }).locator(".status.ok").waitFor({ timeout: 10000 });
  const kept = (await json(`/api/projects/${src.project_id}/atoms?source_id=${id}`)).atoms.find(x => x.statement === LIVE_REQ);
  if (!kept || kept.status !== "accepted" || !kept.live || !kept.stale_evidence) throw new Error("kept live atom: " + JSON.stringify(kept));
  step("after stop the accepted requirement is listed under Требования из встречи (its quote marked stale)");

  await page.goto(base + "/#/meetings");
  await page.locator(`#src-${id} .right .tag`, { hasText: s.ready }).waitFor({ timeout: 10000 });
  step("the meeting is listed as processed");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log("session: all checks passed");
