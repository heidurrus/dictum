// End-to-end check of the Skills screen against e2e/fake_llm_server.py (default http://127.0.0.1:5098).
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const shots = process.env.SHOTS || "";
const dir = mkdtempSync(join(tmpdir(), "wb-"));
const vttPath = join(dir, "Созвон.vtt");
writeFileSync(vttPath, "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Карточка открывается не дольше двух секунд</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>Оператор видит историю заказов</v>\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
page.on("dialog", d => d.accept());
const errors = [];
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${r.status()} ${r.url()}`);
});
const step = (name) => console.log("✓", name);
const shot = async (name) => { if (shots) await page.screenshot({ path: join(shots, name), fullPage: true }); };
const list = page.locator(".list");

// A source with accepted atoms, so "try" has something to work with.
await page.goto(base + "/#/sources");
await page.locator('input[type=file]').setInputFiles(vttPath);
await page.getByText("Оператор видит историю заказов").waitFor();
await page.getByRole("button", { name: "Извлечь требования" }).click();
await page.getByRole("button", { name: "Требования из источника · 2" }).waitFor({ timeout: 15000 });
await page.goto(base + "/#/atoms");
await page.locator(".screen-sub", { hasText: "на ревью" }).waitFor();
for (let i = 0; i < 2; i++) await page.keyboard.press("a");
await page.getByText("Все требования разобраны").waitFor();

await page.locator(".rail").getByRole("button", { name: "Ещё" }).click();          // Skills sit under "Ещё" in the rail
await page.locator(".rail").getByRole("menuitem", { name: "Скиллы" }).click();
await list.getByText("Типы документов").waitFor();
await list.getByRole("button", { name: /SRS — спецификация требований/ }).click();
await page.locator(".e-title h2", { hasText: "SRS" }).waitFor();
await page.getByText("Встроенный скилл нельзя менять").waitFor();
step("skills listed by stage; built-in is read-only");

await page.locator(".screen-head").getByRole("button", { name: "Сделать копию" }).click();
await page.getByText("Копия создана").waitFor();
await page.locator(".title-input").fill("SRS для банка");
await page.locator("#sk-instr").fill("Пиши сухо и коротко. Язык: {language}.");
await page.getByRole("tab", { name: /Разделы/ }).click();
await page.getByRole("button", { name: "Раздел, который напишет ИИ" }).click();
const last = page.locator(".sec-row").last();
await last.getByPlaceholder("Название (рус.)").fill("Глоссарий");
await last.getByPlaceholder("Что ИИ должен написать в этом разделе").fill("Термины и определения из требований.");
await page.getByText("Есть несохранённые изменения").waitFor();
await page.keyboard.press(process.platform === "darwin" ? "Meta+s" : "Control+s");
await page.getByText("Сохранено (версия 2)").waitFor();
await list.getByRole("button", { name: /SRS для банка/ }).waitFor();
step("copy, edit instructions and sections, save with ⌘S");

await page.getByRole("tab", { name: "Использование" }).click();
await page.getByRole("button", { name: "Создать документ этого типа" }).waitFor();
step("a document type is used by creating a document of that type");

await page.getByRole("tab", { name: /История/ }).click();
await page.locator(".history").getByRole("button", { name: "Показать" }).first().click();
await page.locator(".h-text").getByText("You are a senior business analyst").waitFor();
step("history shows the previous version");

await page.getByRole("tab", { name: "Попробовать" }).click();
await page.getByRole("button", { name: "Запустить" }).click();
await page.locator(".result h4", { hasText: "Глоссарий" }).waitFor({ timeout: 15000 });
await shot("skills.png");
step("try the draft on the project: preview includes the new section");

const [zip] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Экспорт .zip" }).click()]);
const zipPath = join(dir, zip.suggestedFilename());
await zip.saveAs(zipPath);
await page.locator(".screen-head input[type=file]").setInputFiles(zipPath);
await page.getByText(/Скилл «SRS для банка» импортирован/).waitFor();
if (!page.url().endsWith("-2")) throw new Error("imported skill not opened: " + page.url());
step("export .zip and import it back");

// Quality: your own rule.
await list.getByRole("button", { name: /Проверка качества/ }).click();
await page.locator(".e-title h2", { hasText: "Проверка качества" }).waitFor();
await page.locator(".screen-head").getByRole("button", { name: "Сделать копию" }).click();
await page.getByText("Копия создана").waitFor();
await page.locator(".title-input").waitFor();                  // the editable copy is open
await page.getByRole("tab", { name: "Правила" }).click();
await page.getByRole("button", { name: "Добавить правило" }).click();
await page.locator(".rule").last().getByPlaceholder("Название").fill("Нет роли");
await page.locator(".rule").last().getByPlaceholder("Что проверять").fill("Требование не называет роль пользователя.");
await page.getByRole("button", { name: /^Сохранить/ }).click();
await page.getByText("Сохранено (версия 2)").waitFor();
step("quality skill with a custom rule");

// Word template: copy the GOST look, get the .docx, upload it back.
await list.getByRole("button", { name: /Word — ГОСТ/ }).click();
await page.locator(".e-title h2", { hasText: "Word — ГОСТ" }).waitFor();
await page.locator(".screen-head").getByRole("button", { name: "Сделать копию" }).click();
await page.getByText("Копия создана").waitFor();
try { await page.getByText("{{section:functional}}").waitFor({ timeout: 8000 }); }
catch (e) { await page.screenshot({ path: join(shots || dir, "skills-fail.png"), fullPage: true }); console.log(page.url()); throw e; }
const [tpl] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Скачать шаблон" }).click()]);
const tplPath = join(dir, "template.docx");
await tpl.saveAs(tplPath);
await page.locator(".editor input[type=file]").setInputFiles(tplPath);
await page.getByText("Шаблон обновлён").waitFor();
step("export skill: download and upload the Word template");

await list.getByRole("button", { name: /SRS для банка/ }).first().click();
await page.waitForFunction(() => document.querySelector(".title-input")?.value === "SRS для банка");
await page.getByRole("tab", { name: "Использование" }).click();
await page.getByRole("button", { name: "Создать документ этого типа" }).click();
await page.waitForURL(/#\/document\/[0-9a-f-]{36}$/);
await page.locator(".doc-tabs [role=tab]").nth(1).waitFor();                // the new document next to the first one
await page.locator(".screen-title", { hasText: "SRS для банка" }).waitFor();
await page.locator(".screen-head").getByRole("button", { name: "Собрать документ" }).click();
await page.locator(".screen-sub", { hasText: "версия 1" }).waitFor({ timeout: 15000 });
await page.locator(".sec h2", { hasText: "Глоссарий" }).waitFor();
await page.getByRole("button", { name: "Другие форматы" }).click();
await page.getByRole("menuitem", { name: "Word — ГОСТ (копия)" }).click();
const [doc] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Экспорт в Word" }).click()]);
if (!doc.suggestedFilename().endsWith(".docx")) throw new Error("no docx");
step("document uses the default FRD skill and exports with the custom template");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all skills steps passed");
