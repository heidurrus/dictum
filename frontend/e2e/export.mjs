// Jira export against e2e/fake_llm_server.py, which uses a fake sign-in and an in-memory Jira (project SBX).
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const shots = process.env.SHOTS || "";
const dir = mkdtempSync(join(tmpdir(), "dictum-"));
const vttPath = join(dir, "Созвон.vtt");
writeFileSync(vttPath, "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Карточка открывается не дольше двух секунд</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>Оператор видит историю заказов</v>\n\n" +
  "00:00:09.000 --> 00:00:12.000\n<v SPEAKER_00>Оператор ищет клиента по номеру</v>\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ locale: "ru-RU", viewport: { width: 1280, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${r.status()} ${r.url()}`);
});
const step = (name) => console.log("✓", name);
const sub = page.locator(".screen-sub");

// Source → atoms → document → backlog.
await page.goto(base + "/#/sources");
await page.locator('input[type=file]').setInputFiles(vttPath);
await page.locator(".seg-row").first().waitFor();
await page.getByRole("button", { name: "Извлечь требования" }).click();
await page.getByRole("button", { name: "Требования из источника · 3" }).waitFor({ timeout: 15000 });
await page.goto(base + "/#/atoms");
await sub.filter({ hasText: "на проверку" }).waitFor();
await page.locator(".check-all input").check();
await page.locator(".bulkbar").getByRole("button", { name: /конфликтные/ }).click();   // all, conflicts included
await page.getByText("Все требования разобраны").waitFor();
await page.goto(base + "/#/document");
await page.locator(".screen-head").getByRole("button", { name: "Собрать документ" }).click();
await sub.filter({ hasText: "версия 1" }).waitFor({ timeout: 15000 });
await page.goto(base + "/#/backlog");
await page.locator(".screen-head").getByRole("button", { name: "Собрать бэклог" }).click();
await sub.filter({ hasText: "2 истории" }).waitFor({ timeout: 15000 });
await page.locator(".screen-head").getByRole("button", { name: /В Jira/ }).click();
step("backlog → export screen");

// Connect: the sign-in opens in a browser tab, the app notices.
const [popup] = await Promise.all([context.waitForEvent("page"), page.getByRole("button", { name: "Подключить Jira" }).click()]);
await popup.getByText("Jira подключена").waitFor();
await popup.close();
await page.getByText("подключено", { exact: true }).waitFor({ timeout: 10000 });
await page.getByText("Доступ к сайтам: sandbox.atlassian.net").waitFor();
step("connect Jira (sign-in in the browser); connected sites are shown");

// Target: site, project; issue types mapped by meaning.
await page.locator("#jr-project").selectOption("SBX");
for (const [i, name] of [[0, "Эпик"], [1, "История"], [2, "Задача"], [3, "Подзадача"]])
  if (await page.locator(".types select").nth(i).inputValue() !== name) throw new Error("type mapping " + name);
await page.getByRole("button", { name: "Сохранить" }).click();
await sub.filter({ hasText: "SBX · Sandbox" }).waitFor();
step("choose project; types mapped automatically");

// Preview: read only.
// The read-only preview runs by itself once the target is set.
await page.locator(".counts").getByText("создать: 3").waitFor({ timeout: 15000 });
await page.locator(".counts").getByText("пропустить: 5").waitFor();
if (shots) await page.screenshot({ path: join(shots, "export.png"), fullPage: true });
step("preview: create 3, skip 5 (sub-tasks and NFR unticked)");

// Push, with the explicit confirmation naming the project.
await page.locator(".screen-head").getByRole("button", { name: "Выгрузить 3 задачи" }).click();
await page.getByText("Создать или обновить 3 задачи в проекте SBX (sandbox.atlassian.net)?").waitFor();
await page.getByRole("button", { name: "Да, выгрузить в SBX" }).click();
await page.getByText("Готово: 3 задачи").waitFor({ timeout: 15000 });
await page.locator(".result a", { hasText: "SBX-1" }).waitFor();
step("push with confirmation: 3 issues created with links");

await page.locator(".screen-head").getByRole("button", { name: /Обновить|Показать предпросмотр/ }).click();
await page.locator(".counts").getByText("без изменений: 3").waitFor({ timeout: 15000 });
step("a second preview: everything unchanged, nothing to push");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all export steps passed");
