// End-to-end check of the FRD screen against e2e/fake_llm_server.py (default http://127.0.0.1:5098).
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const shots = process.env.SHOTS || "";
const dir = mkdtempSync(join(tmpdir(), "wb-"));
const vttPath = join(dir, "Созвон по карточке.vtt");
writeFileSync(vttPath, "WEBVTT\n\n" +
  "00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Карточка открывается не дольше двух секунд</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>Хватит и пяти секунд</v>\n\n" +
  "00:00:09.000 --> 00:00:12.000\n<v SPEAKER_00>Оператор видит историю заказов</v>\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ locale: "ru-RU", viewport: { width: 1280, height: 900 }, acceptDownloads: true });
const errors = [];
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${r.status()} ${r.url()}`);
});
const step = (name) => console.log("✓", name);
const shot = async (name) => { if (shots) await page.screenshot({ path: join(shots, name), fullPage: true }); };

await page.goto(base + "/#/document");
await page.getByText("Пока нечего собирать").waitFor();
step("document screen explains what's needed first");

// Source → atoms → accept all.
await page.goto(base + "/#/sources");
await page.locator('input[type=file]').setInputFiles(vttPath);
await page.getByText("Оператор видит историю заказов").waitFor();
await page.getByRole("button", { name: "Извлечь требования" }).click();
await page.getByRole("button", { name: "Требования из источника · 3" }).waitFor({ timeout: 15000 });
await page.goto(base + "/#/atoms");
await page.locator(".screen-sub", { hasText: "на ревью" }).waitFor();
for (let i = 0; i < 3; i++) await page.keyboard.press("a");
await page.getByText("Все требования разобраны").waitFor();
await page.locator(".screen-head").getByRole("button", { name: "Собрать документ" }).click();
await page.getByText("Можно собирать: 3 принятых требования").waitFor();
step("atoms accepted, the document offers to build");

await page.locator(".screen-head").getByRole("button", { name: "Собрать документ" }).click();
await page.locator(".screen-sub", { hasText: "версия 1 · 3 требования" }).waitFor({ timeout: 15000 });
await page.locator(".sec h3", { hasText: "3.1 Карточка клиента" }).waitFor();
await page.locator('#blk-FR-1 .src[aria-label="из требования, 1 источник"]').waitFor();
await page.getByText(/конфликт.* не разрешён/).waitFor();
await shot("document.png");
step("version 1 built: sections, IDs, sources, conflict warning");

// Edit the atom behind FR-1 into something vague → stale → rebuild → quality finding.
const fr1 = page.locator("#blk-FR-1");
await fr1.hover();
await fr1.getByRole("button", { name: "Править требование" }).click();
await fr1.locator("textarea").fill("Интерфейс карточки должен быть удобным");
await fr1.getByRole("button", { name: "Сохранить" }).click();
await page.getByText("После сборки изменилось 1 требование").waitFor();
await page.getByText("разделы 3.1 устарели").waitFor();
step("editing an atom marks its section stale");

await page.locator(".row-note").getByRole("button", { name: "Обновить изменённое" }).click();
await page.locator(".screen-sub", { hasText: "версия 2" }).waitFor({ timeout: 15000 });
const finding = page.locator(".finding", { hasText: "FR-1" });
await finding.getByText("размыто").waitFor();
step("rebuild (changed only) and the quality check flags the vague word");

await finding.getByRole("button", { name: "Починить" }).click();
await finding.locator("textarea").waitFor();
await finding.getByRole("button", { name: "Принять в требование" }).click();
await page.getByText("Требование обновлено. Обновите документ").waitFor();
step("fix proposal applied to the atom");

await page.locator(".inspector").getByRole("tab", { name: /^Изменения/ }).click();
await page.locator(".inspector").getByRole("button", { name: "Сравнить с v1" }).click();
await page.locator(".change", { hasText: "FR-1" }).getByText("изменено").waitFor();
await page.locator(".inspector").getByRole("button", { name: "Скрыть сравнение" }).click();
step("diff with the previous version");

await page.locator("#sec-purpose").getByRole("button", { name: "Свой текст" }).click();
await page.locator("#sec-purpose textarea").fill("Согласовано с заказчиком 12.03.");
await page.locator("#sec-purpose").getByRole("button", { name: "Сохранить" }).click();
await page.locator("#sec-purpose .blk.free", { hasText: "Согласовано с заказчиком 12.03." }).waitFor();
step("pinned free text");

await page.getByRole("button", { name: "Другие форматы" }).click();
await page.getByRole("menuitem", { name: "Word — ГОСТ" }).click();
const [download] = await Promise.all([page.waitForEvent("download"),
  page.getByRole("button", { name: "Экспорт в Word" }).click()]);
const saved = join(dir, download.suggestedFilename());
await download.saveAs(saved);
if (!saved.endsWith("v2.docx") || statSync(saved).size < 10000) throw new Error("bad export " + saved);
step("DOCX export (GOST)");

// Output language: switching the project to English asks for a full rebuild.
await page.locator(".rail").getByRole("button", { name: "Настройки" }).click();
await page.locator(".out-lang").getByRole("button", { name: "English" }).click();
await page.goto(base + "/#/document");
await page.waitForTimeout(1500); await shot("lang.png");
await page.getByText("Документ собран на русском, а язык проекта — на английском").waitFor();
step("output language setting and the rebuild hint");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all document steps passed");
