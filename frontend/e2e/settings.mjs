// Settings as sections (spec 5.0 C9): open each section → "Требования на лету" off and on, round-tripping through
// /settings → the consent reminder off and on → rebind ⌥Space to ⌥D and back (a conflict is refused) → the stats row counts a recap that ran → the
// storage card shows the data folder. Runs once per interface language.
// Run: WORKBENCH_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 & node frontend/e2e/settings.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", title: "Настройки", meeting: "Созвон про заявки",
        sections: ["Проект", "Модели", "Приватность", "Хранилище", "Запись", "Jira", "Горячие клавиши", "Интерфейс", "Система"],
        reqs: "Требования на лету", whisper: "Шепнуть", change: "Изменить", conflict: /уже назначено: Записать встречу/,
        week: "Неделя", month: "Месяц", storage: "Папка данных" },
  en: { locale: "en-US", title: "Settings", meeting: "Requests call",
        sections: ["Project", "Models", "Privacy", "Storage", "Recording", "Jira", "Shortcuts", "Interface", "System"],
        reqs: "Requirements on the fly", whisper: "Whisper", change: "Change", conflict: /already used by: Record a meeting/,
        week: "Week", month: "Month", storage: "Data folder" },
};
const IDS = ["project", "models", "privacy", "storage", "record", "jira", "keys", "interface", "system"];

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  page.on("console", m => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(`${lang}: ${m.text()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);
  const json = async path => (await page.request.get(base + path)).json();
  const settings = () => json("/settings");
  async function until(fn, what) {
    for (let i = 0; i < 100; i++) { if (await fn()) return; await page.waitForTimeout(100); }
    throw new Error("timed out: " + what);
  }

  // A project of its own with one meeting.
  const made = await (await page.request.post(base + "/api/projects", { data: { name: `Настройки e2e ${lang}` } })).json();
  await page.request.post(`${base}/api/projects/${made.id}/current`);
  const res = await page.request.post(base + "/transcribe", {
    multipart: { project_id: made.id, audio: { name: `${s.meeting}.vtt`, mimeType: "text/vtt",
                 buffer: Buffer.from("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nНужна выгрузка заявок в Excel\n") } },
  });
  if (!res.ok()) throw new Error("could not import the meeting: " + res.status());
  let meeting = null;
  await until(async () => (meeting = (await json(`/api/projects/${made.id}/sources`)).sources
    .find(x => x.title === s.meeting && x.status === "ready")), "meeting ready");

  // Each section: #/settings opens the first; the left column opens the others at #/settings/<section>.
  await page.goto(base + "/#/settings");
  await page.getByRole("heading", { name: s.title, exact: true }).waitFor();
  await page.locator('.setcards[data-section="project"]').waitFor();
  const nav = page.locator(".setnav");
  if (await nav.locator(".node").count() !== IDS.length) throw new Error("sections: " + await nav.innerText());
  for (const [i, id] of IDS.entries()) {
    await nav.getByRole("button", { name: s.sections[i], exact: true }).click();
    await page.locator(`.setcards[data-section="${id}"] .sec-title`, { hasText: s.sections[i] }).waitFor();
    if (!page.url().endsWith("#/settings/" + id)) throw new Error("route: " + page.url());
  }
  step("every section opens at #/settings/<section>");

  // Запись → "Требования на лету" off, then on; each change is in /settings and survives a reload.
  await page.goto(base + "/#/settings/record");
  const reqs = page.getByRole("checkbox", { name: s.reqs, exact: true });
  await reqs.waitFor();
  if (!await reqs.isChecked()) throw new Error("live requirements should start on");
  await reqs.click();
  await until(async () => (await settings()).live_requirements === false, "live_requirements off");
  await page.reload();
  await reqs.waitFor();
  if (await reqs.isChecked()) throw new Error("the switch did not stay off after a reload");
  await reqs.click();
  await until(async () => (await settings()).live_requirements === true, "live_requirements on");
  step("Требования на лету round-trips off and on");

  // Приватность → "Напоминать о согласии на запись" off survives a reload, then back on.
  await page.goto(base + "/#/settings/privacy");
  const consent = page.locator('.setcards[data-section="privacy"] input.consent-reminder');
  await consent.waitFor();
  await until(async () => await consent.isEnabled(), "consent switch enabled");
  if (!await consent.isChecked()) throw new Error("the consent reminder should start on");
  await consent.click();
  await until(async () => (await settings()).consent_reminder === false, "consent_reminder off");
  await page.reload();
  await consent.waitFor();
  await until(async () => await consent.isEnabled(), "consent switch enabled after reload");
  if (await consent.isChecked()) throw new Error("the consent reminder did not stay off after a reload");
  await consent.click();
  await until(async () => (await settings()).consent_reminder === true, "consent_reminder on");
  step("consent reminder round-trips off and on");

  // Горячие клавиши → ⌥Space to ⌥D (double-click the row, press the keys), a conflict is refused, then back.
  await nav.getByRole("button", { name: s.sections[6], exact: true }).click();
  const row = page.locator('.hk[data-action="whisper"]');
  await row.locator(".combo", { hasText: "⌥Space" }).waitFor();
  await row.dblclick();
  await row.locator(".rec-kbd").waitFor();
  await page.keyboard.press("Alt+KeyD");
  await row.locator(".combo", { hasText: "⌥D" }).waitFor();
  await until(async () => (await settings()).hotkeys.whisper === "alt+d", "whisper on alt+d");
  await row.getByRole("button", { name: s.change, exact: true }).click();
  await page.keyboard.press("Meta+KeyR");                    // ⌘R records a meeting: refused
  await row.locator(".msg.bad", { hasText: s.conflict }).waitFor();
  if ((await settings()).hotkeys.whisper !== "alt+d") throw new Error("a conflicting binding was saved");
  await row.getByRole("button", { name: s.change, exact: true }).click();
  await page.keyboard.press("Alt+Space");
  await row.locator(".combo", { hasText: "⌥Space" }).waitFor();
  await until(async () => (await settings()).hotkeys.whisper === "alt+space", "whisper back on alt+space");
  step("⌥Space → ⌥D → ⌥Space, ⌘R refused as taken");

  // Модели → the stats row counts the recap that runs now.
  await page.goto(base + "/#/settings/models");
  const cloud = page.locator('.tile[data-stat="cloud"] b');
  await cloud.waitFor();
  const before = await json("/api/stats?period=7d");
  const { job_id } = await (await page.request.post(`${base}/api/sources/${meeting.id}/recap`, { data: { style: "brief" } })).json();
  await until(async () => (await json(`/job/${job_id}`)).status === "done", "recap job");
  const after = await json("/api/stats?period=7d");
  if (after.cloud_calls !== before.cloud_calls + 1 || after.tokens_cloud <= before.tokens_cloud || after.meetings < 1)
    throw new Error("stats: " + JSON.stringify({ before, after }));
  const period = page.getByRole("group", { name: lang === "ru" ? "Период" : "Period" });
  await period.getByRole("button", { name: s.month, exact: true }).click();
  await period.getByRole("button", { name: s.week, exact: true }).click();
  await cloud.filter({ hasText: String(after.cloud_calls) }).waitFor();
  const meetings = await page.locator('.tile[data-stat="meetings"] b').innerText();
  if (Number(meetings) < 1) throw new Error("meetings tile: " + meetings);
  step(`stats row shows the recap (${after.cloud_calls} cloud calls, ${meetings} meetings)`);

  // Хранилище → the data folder path, counts and size.
  await page.goto(base + "/#/settings/storage");
  const storage = await json("/api/storage");
  await page.locator(".storage-card .path", { hasText: storage.path }).waitFor();
  await page.locator(".storage-card .counts", { hasText: /\d/ }).waitFor();
  await page.getByText(s.storage, { exact: true }).first().waitFor();
  step("storage card shows " + storage.path);

  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all settings steps passed");
