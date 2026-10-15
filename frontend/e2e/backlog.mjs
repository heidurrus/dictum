// Decomposition screen against e2e/fake_llm_server.py (default http://127.0.0.1:5098).
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
const page = await browser.newPage({ locale: "ru-RU", viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${r.status()} ${r.url()}`);
});
const step = (name) => console.log("✓", name);
const sub = page.locator(".screen-sub");

await page.goto(base + "/#/backlog");
await page.getByText("Сначала нужен документ").waitFor();
step("backlog explains the document comes first");

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
await page.getByRole("button", { name: /К бэклогу/ }).click();
await page.getByText("Можно собирать бэклог из документа v1").waitFor();
step("document → decomposition");

await page.getByRole("button", { name: "Собрать бэклог" }).click();
await sub.filter({ hasText: "2 истории · 1 эпик" }).waitFor({ timeout: 15000 });
await page.locator(".epic .t", { hasText: "Работа оператора" }).waitFor();
await page.locator(".inspector").getByText("Цель: Быстрее обслуживать звонки").waitFor();
await page.locator(".tree .node.story").first().locator(".t").click();        // details of a story are in the inspector
await page.locator(".inspector .acs b", { hasText: "Дано" }).first().waitFor();
await page.locator(".inspector .refs .link", { hasText: /§3\.1 · FR-\d/ }).first().waitFor();
const firstSub = page.locator(".tree .node.sub").first();
if (await firstSub.locator(".inc").isChecked()) throw new Error("generated sub-tasks must start unticked");
await firstSub.getByText("сгенерировано").waitFor();
const nfr = page.locator(".tree .node.nfr").first();
if (await nfr.locator(".inc").isChecked()) throw new Error("NFR items must start unticked");
if (shots) await page.screenshot({ path: join(shots, "backlog.png"), fullPage: true });
step("epics, stories with criteria and FRD links; sub-tasks and NFR unticked");

// Untick the epic → its stories go too.
await page.locator(".tree .node.epic > .row-line .inc").uncheck();
await page.locator(".screen-head").getByRole("button", { name: /В Jira · 0/ }).waitFor();   // sub-tasks and NFRs start unticked anyway
await page.locator(".tree .node.epic > .row-line .inc").check();
step("unticking an epic unticks its stories");

// Edit a story: text + a new criterion; it gets pinned.
await page.locator(".tree .node.story").first().locator(".t").click();
const story = page.locator(".inspector");
await story.getByRole("button", { name: "Править" }).click();
await story.locator("textarea").fill("Как старший смены, я хочу видеть историю заказов, чтобы разбирать жалобы");
await story.getByRole("button", { name: "Добавить критерий" }).click();
await story.locator(".ac-edit").last().locator("input").nth(2).fill("история показана за 12 месяцев");
await story.getByRole("button", { name: "Сохранить" }).click();
await story.getByText("изменено").first().waitFor();
await story.getByText("история показана за 12 месяцев").waitFor();
step("edit a story and add a criterion (pinned)");

await page.getByRole("button", { name: "Проверить по INVEST" }).click();
await page.locator(".invest", { hasText: "INVEST · S" }).waitFor({ timeout: 15000 });
await page.locator(".invest").getByRole("button", { name: "Применить" }).click();
await page.getByText("Текст истории обновлён").waitFor();
step("INVEST check with a suggested fix applied");

await nfr.locator(".t").click();
await page.locator(".inspector").getByRole("button", { name: /В критерии/ }).first().click();
await page.getByText(/Перенесено в критерии/).waitFor();
if (await page.locator(".tree .node.nfr").count() !== 0) throw new Error("the NFR should be moved into the story");
step("NFR moved into a story's criteria");

await page.locator(".screen-head").getByRole("button", { name: "Пересобрать" }).click();
await page.getByText(/Собрано \d+ истори/).waitFor({ timeout: 15000 });
await page.locator(".tree .node.story").first().locator(".t").click();
await page.locator(".inspector").getByText("история показана за 12 месяцев").waitFor();
step("rebuild keeps the edited story");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all backlog steps passed");
