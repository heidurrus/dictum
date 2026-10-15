// Business analysis off per project (5.0.4): Settings → Project switch off → the rail has no Требования, Документы,
// Бэклог (Ещё has no Выгрузка), Встречи has no pipeline strip, requirement tab or extraction, the meeting page has no
// requirements panel, #/atoms and #/export land on Встречи, ⌘3 does nothing, the palette leaves them out; switched
// back on, everything is there again. Runs once per interface language.
// Run: DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 & node frontend/e2e/notes_mode.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", meeting: "Созвон про заявки", analysis: "Бизнес-анализ", autoExtract: "Сразу извлекать требования",
        hidden: ["Требования", "Документы", "Бэклог"], more: "Ещё", skills: "Скиллы", export: "Выгрузка",
        tab: "Требования", summary: "Резюме", extract: "Извлечь требования", search: "Экран, источник, документ, требование или команда" },
  en: { locale: "en-US", meeting: "Requests call", analysis: "Business analysis", autoExtract: "Extract requirements right away",
        hidden: ["Requirements", "Documents", "Backlog"], more: "More", skills: "Skills", export: "Export",
        tab: "Requirements", summary: "Summary", extract: "Extract requirements", search: "A screen, source, document, requirement or command" },
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  page.on("console", m => { if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(`${lang}: ${m.text()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);
  const json = async path => (await page.request.get(base + path)).json();
  async function until(fn, what) {
    for (let i = 0; i < 100; i++) { if (await fn()) return; await page.waitForTimeout(100); }
    throw new Error("timed out: " + what);
  }
  const hash = () => new URL(page.url()).hash;

  // A project of its own with one meeting.
  const made = await (await page.request.post(base + "/api/projects", { data: { name: `Заметки e2e ${lang}` } })).json();
  if (made.analysis !== true) throw new Error("a new project should start with business analysis on");
  await page.request.post(`${base}/api/projects/${made.id}/current`);
  const res = await page.request.post(base + "/transcribe", {
    multipart: { project_id: made.id, audio: { name: `${s.meeting}.vtt`, mimeType: "text/vtt",
                 buffer: Buffer.from("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nНужна выгрузка заявок в Excel\n") } },
  });
  if (!res.ok()) throw new Error("could not import the meeting: " + res.status());
  let meeting = null;
  await until(async () => (meeting = (await json(`/api/projects/${made.id}/sources`)).sources
    .find(x => x.title === s.meeting && x.status === "ready")), "meeting ready");

  const rail = page.locator("nav.rail");
  const railItem = name => rail.getByRole("button", { name, exact: true });
  async function expectRail(on) {
    for (const name of s.hidden) {
      if (on) await railItem(name).waitFor();
      else await railItem(name).waitFor({ state: "detached" });
    }
    await rail.getByRole("button", { name: s.more, exact: true }).click();
    const menu = page.locator(".more-menu");
    await menu.getByRole("menuitem", { name: s.skills }).waitFor();
    if (await menu.getByRole("menuitem", { name: s.export }).count() !== (on ? 1 : 0)) throw new Error(`Ещё: ${await menu.innerText()}`);
    await page.keyboard.press("Escape");
  }
  async function expectMeetings(on) {
    await page.goto(base + "/#/meetings");
    await page.locator(".item", { hasText: s.meeting }).click();
    const tabs = page.locator(".mtabs");
    await tabs.getByRole("tab", { name: s.summary }).waitFor();
    if (await tabs.getByRole("tab", { name: s.tab }).count() !== (on ? 1 : 0)) throw new Error("tabs: " + await tabs.innerText());
    if (on) await page.locator(".pipe").waitFor();
    else if (await page.locator(".pipe").count()) throw new Error("the pipeline strip should be gone");
    await page.locator(".panel-foot .btn.ghost.icon").click();      // ⋯: the extract item goes with it
    await page.locator(".menu").first().waitFor();
    if (await page.locator(".menu", { hasText: s.extract }).count() !== (on ? 1 : 0)) throw new Error("⋯ extract item");
    await page.keyboard.press("Escape");
  }
  async function expectPalette(on) {
    await page.keyboard.press("ControlOrMeta+k");
    const pal = page.locator(".palette");
    await pal.getByPlaceholder(s.search).waitFor();
    const text = await pal.locator(".palette-list").innerText();
    for (const name of [...s.hidden, s.export])
      if (text.includes(name) !== on) throw new Error(`palette (${on ? "on" : "off"}) and «${name}»: ${text}`);
    await page.keyboard.press("Escape");
    await pal.waitFor({ state: "detached" });
  }

  // On (the default): everything is there.
  await page.goto(base + "/#/meetings");
  await expectRail(true);
  step("on: the rail has the analysis screens");

  // Settings → Project → Бизнес-анализ off: the auto-extract and Jira quote rows and the Jira section go.
  await page.goto(base + "/#/settings/project");
  const sw = page.locator("#set-project input.analysis");
  await sw.waitFor();
  if (!await sw.isChecked()) throw new Error("the analysis switch should start on");
  await page.getByText(s.autoExtract).waitFor();
  await page.locator('.setnav .node[data-section="jira"]').waitFor();
  await sw.click();
  await until(async () => (await json(`/api/projects`)).projects.find(p => p.id === made.id)?.analysis === false, "analysis off");
  await page.getByText(s.autoExtract).waitFor({ state: "detached" });
  if (await page.locator('.setnav .node[data-section="jira"]').count()) throw new Error("the Jira section should be hidden");
  await page.goto(base + "/#/settings/privacy");
  await page.locator(".provider-row").first().waitFor();
  if (await page.locator(".provider-row", { hasText: "Jira" }).count()) throw new Error("the Jira line in Privacy should be hidden");
  step("Settings → Project: the switch goes off; auto-extract, Jira quotes, the Jira section and line are hidden");

  await expectRail(false);
  step("off: no Requirements, Documents, Backlog in the rail, no Export under More");

  await expectMeetings(false);
  step("off: Meetings has no pipeline strip, requirements tab or extract item");

  await page.goto(`${base}/#/meeting/${meeting.id}`);
  await page.locator(".notes-card").waitFor();
  await page.waitForTimeout(300);
  if (await page.locator(".live-req").count()) throw new Error("the requirements panel should be hidden");
  if (await page.getByRole("button", { name: s.extract, exact: true }).count()) throw new Error("the extract button should be hidden");
  step("off: the meeting page has no requirements panel and no extract button");

  for (const path of ["/atoms", "/document", "/backlog", "/export", `/atoms/source/${meeting.id}`]) {
    await page.goto(`${base}/#${path}`);
    await until(async () => hash() === "#/meetings", `${path} → #/meetings`);
  }
  step("off: #/atoms, #/document, #/backlog, #/export land on Meetings");

  await page.locator("body").click({ position: { x: 700, y: 10 } });
  await page.keyboard.press("ControlOrMeta+3");
  await page.waitForTimeout(300);
  if (hash() !== "#/meetings") throw new Error("⌘3 should do nothing: " + hash());
  await page.keyboard.press("ControlOrMeta+2");
  await until(async () => hash() === "#/library", "⌘2 → Library still works");
  step("off: ⌘3 does nothing, ⌘2 still opens Library");

  await page.goto(base + "/#/meetings");
  await page.locator(".item", { hasText: s.meeting }).waitFor();
  await expectPalette(false);
  step("off: the palette leaves the analysis screens out");

  // From an analysis screen of another project (on), the project picker to this one (off) lands on Встречи.
  const other = await (await page.request.post(base + "/api/projects", { data: { name: `Анализ e2e ${lang}` } })).json();
  await page.request.post(`${base}/api/projects/${other.id}/current`);
  await page.reload();                                   // the app reads the current project at start
  await railItem(s.hidden[0]).waitFor();
  await page.goto(base + "/#/atoms");
  await railItem(s.hidden[0]).waitFor();
  await page.waitForTimeout(300);
  if (hash() !== "#/atoms") throw new Error("#/atoms should open in a project with analysis on: " + hash());
  await page.locator(".project-chip").click();
  await page.locator(".proj-menu").getByRole("menuitem", { name: made.name }).click();
  await until(async () => hash() === "#/meetings", "picker → #/meetings");
  await railItem(s.hidden[0]).waitFor({ state: "detached" });
  step("the project picker from #/atoms to a project with analysis off lands on Meetings");

  // Back on: everything returns.
  await page.goto(base + "/#/settings/project");
  await page.locator("#set-project input.analysis:not(:checked)").click();
  await until(async () => (await json(`/api/projects`)).projects.find(p => p.id === made.id)?.analysis === true, "analysis on");
  await page.getByText(s.autoExtract).waitFor();
  await page.locator('.setnav .node[data-section="jira"]').waitFor();
  await expectRail(true);
  await expectMeetings(true);
  await page.goto(base + "/#/atoms");
  await page.waitForTimeout(500);
  if (hash() !== "#/atoms") throw new Error("#/atoms should stay when on: " + hash());
  await expectPalette(true);
  step("on again: settings rows, rail items, tab, strip, #/atoms and the palette are all back");

  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("errors:", errors); process.exit(1); }
console.log("notes mode: all steps passed");
