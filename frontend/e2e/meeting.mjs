// The meeting page (spec 5.0 C3): notes that save themselves and survive a reload, show in the Встречи panel's
// Заметки tab; recap styles (the update button is off when nothing is new); transcript search with a hit counter.
// Runs once per interface language.
// Run: WORKBENCH_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 & node frontend/e2e/meeting.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Встречи", title: "Звонок с дилером", notesTab: "Заметки", edit: "Редактировать",
        bullets: "По пунктам", brief: "Кратко", update: "Обновить по новым репликам", saved: /Сохранено в/, of: "из",
        note: "Дубли заявок: VIN и телефон", summary: "Резюме" },
  en: { locale: "en-US", heading: "Meetings", title: "Dealer call", notesTab: "Notes", edit: "Edit",
        bullets: "Point by point", brief: "Brief", update: "Update with new lines", saved: /Saved at/, of: "of",
        note: "Duplicate requests: VIN and phone", summary: "Summary" },
};
const VTT = "WEBVTT\n\n" + [
  ["00:00:01.000", "00:00:04.000", "Анна", "Дилер заводит заявку вручную, и заявки дублируются"],
  ["00:00:05.000", "00:00:09.000", "Ирина", "Нужно проверять заявки по VIN и телефону"],
  ["00:00:10.000", "00:00:14.000", "Анна", "Ответ дилеру не позже чем через два часа"],
].map(([a, b, who, text]) => `${a} --> ${b}\n<v ${who}>${text}</v>\n`).join("\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const dir = mkdtempSync(join(tmpdir(), "wb-"));
  const vtt = join(dir, `${s.title}.vtt`);
  writeFileSync(vtt, VTT);

  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);

  await page.goto(base + "/#/meetings");
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  await page.locator("input[type=file]").setInputFiles(vtt);
  await page.waitForURL(/#\/(meeting|source)\//);
  await page.locator(".seg-row", { hasText: "по VIN и телефону" }).waitFor();
  const meetingUrl = page.url().replace(/\/summarize$/, "");
  step("an import opens the meeting page with its transcript");

  // Notes: type, wait for the autosave, reload.
  const editor = page.locator("textarea.notes-editor");
  await editor.click();
  await page.keyboard.type(s.note);
  await page.keyboard.press("Enter");
  await page.locator(".fmt button", { hasText: "☐" }).click();
  await page.keyboard.type("SLA 2");
  await page.locator(".notes-state", { hasText: s.saved }).waitFor({ timeout: 5000 });
  await page.goto(meetingUrl);
  await page.reload();
  await page.locator(".seg-row", { hasText: "по VIN и телефону" }).waitFor();
  const kept = await page.locator("textarea.notes-editor").inputValue();
  if (kept !== `${s.note}\n- [ ] SLA 2`) throw new Error("notes after reload: " + JSON.stringify(kept));
  step("notes save themselves and survive a reload; the format bar inserts Markdown");

  // The Встречи panel renders them, with a link back to the editor.
  await page.goto(base + "/#/meetings");
  await page.locator(".item", { hasText: s.title }).click();
  await page.locator(".mtabs").getByRole("tab", { name: s.notesTab, exact: true }).click();
  await page.locator(".panel .notes-view p", { hasText: s.note }).waitFor();
  await page.locator(".panel .notes-view li.task", { hasText: "SLA 2" }).waitFor();
  await page.locator(".panel").getByRole("button", { name: s.edit, exact: true }).click();
  await page.waitForURL(/#\/meeting\//);
  await page.locator("textarea.notes-editor").waitFor();
  step("the panel's Заметки tab shows the notes rendered and opens the editor");

  // Recap styles: switching to a style with no recap writes one (fake model), nothing new → no update.
  const recap = page.locator(".inspector .recap");
  await recap.getByRole("button", { name: s.bullets, exact: true }).click();
  await recap.locator(".md", { hasText: "recap bullets: 3 lines" }).waitFor();
  const update = recap.getByRole("button", { name: s.update });
  await update.waitFor();
  if (!(await update.isDisabled())) throw new Error("the update button must be off when nothing is new");
  await recap.getByRole("button", { name: s.brief, exact: true }).click();
  await recap.locator(".md", { hasText: "recap brief: 3 lines" }).waitFor();
  await recap.getByRole("button", { name: s.bullets, exact: true }).click();
  await recap.locator(".md", { hasText: "recap bullets: 3 lines" }).waitFor();
  const sent = await (await page.request.get(base + "/__fake/recaps")).json();
  const mine = sent.slice(-2);
  if (mine.length !== 2 || mine.some(r => r.incremental || r.lines !== 3)) throw new Error("recap prompts: " + JSON.stringify(sent));
  step("the style switch writes and shows each style; Обновить по новым репликам is off with nothing new");

  // The panel shows the same recap in the chosen style.
  await page.goto(base + "/#/meetings");
  await page.locator(".item", { hasText: s.title }).click();
  await page.locator(".mtabs").getByRole("tab", { name: s.summary, exact: true }).click();
  await page.locator(".panel .recap .md", { hasText: "recap bullets: 3 lines" }).waitFor();
  step("the panel's Резюме tab opens on the last chosen style");

  // Search: hits highlighted and counted; Enter / ⇧Enter step through them.
  await page.goto(meetingUrl.replace("#/source/", "#/meeting/"));
  const find = page.locator("#tr-find");
  await find.fill("заявк");
  await page.locator(".hits", { hasText: `1 ${s.of} 3` }).waitFor();
  const marks = await page.locator(".transcript mark.hit").count();
  if (marks !== 3) throw new Error("expected 3 highlighted hits, got " + marks);
  await find.press("Enter");
  await page.locator(".hits", { hasText: `2 ${s.of} 3` }).waitFor();
  await find.press("Shift+Enter");
  await find.press("Shift+Enter");
  await page.locator(".hits", { hasText: `3 ${s.of} 3` }).waitFor();
  await page.locator(".transcript mark.hit.cur").waitFor();
  step("transcript search highlights and counts; Enter / ⇧Enter step");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all meeting steps passed");
