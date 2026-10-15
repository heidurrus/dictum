// Bulk review of atoms against e2e/fake_llm_server.py (default http://127.0.0.1:5098).
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const shots = process.env.SHOTS || "";
const dir = mkdtempSync(join(tmpdir(), "dictum-"));
const vtt = (name, lines) => {
  const path = join(dir, name);
  writeFileSync(path, "WEBVTT\n\n" + lines.map((l, i) =>
    `00:00:0${i * 2 + 1}.000 --> 00:00:0${i * 2 + 2}.000\n<v SPEAKER_0${i % 2}>${l}</v>\n`).join("\n"));
  return path;
};
const call = vtt("Созвон.vtt", ["Карточка открывается за две секунды", "Хватит и пяти секунд",
  "Оператор видит историю заказов", "Номер карты скрыт"]);
const mail = vtt("Письмо.vtt", ["Нужна выгрузка в Excel", "Нужен экспорт в PDF"]);

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ locale: "ru-RU", viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${r.status()} ${r.url()}`);
});
const step = (name) => console.log("✓", name);
const sub = page.locator(".screen-sub");
const selected = page.locator(".bulkbar b");

async function importAndExtract(path, n) {
  await page.goto(base + "/#/sources");
  await page.locator('input[type=file]').setInputFiles(path);
  await page.locator(".seg-row").first().waitFor();
  await page.getByRole("button", { name: "Извлечь требования" }).click();
  await page.getByRole("button", { name: new RegExp(`Требования из источника · ${n}`) }).waitFor({ timeout: 15000 });
}
await importAndExtract(call, 4);
await importAndExtract(mail, 2);
await page.goto(base + "/#/atoms");
await sub.filter({ hasText: "6 на проверку" }).waitFor();

// Select everything shown and accept in one go; undo brings it all back.
await page.locator(".check-all input").check();
await selected.filter({ hasText: "Выбрано: 6" }).waitFor();
await page.locator(".bulkbar").getByText(/в конфликтах: \d/).waitFor();
// The main button leaves atoms in a conflict for review; this one takes them too.
await page.locator(".bulkbar").getByRole("button", { name: /конфликтные/ }).click();
await sub.filter({ hasText: "6 всего · 0 на проверку · принято 6" }).waitFor();
if (await page.locator(".bulkbar").count()) throw new Error("selection should clear after a bulk action");
await page.getByRole("status").getByRole("button", { name: "Отменить" }).click();
await sub.filter({ hasText: "6 на проверку" }).waitFor();
step("select all → accept 6 at once → undo");

// Shift-click range, then change type in bulk.
const checks = page.locator(".atom .row-check");
await checks.nth(0).click();
await checks.nth(2).click({ modifiers: ["Shift"] });
await selected.filter({ hasText: "Выбрано: 3" }).waitFor();
await page.locator(".bulkbar").getByRole("button", { name: "Сменить тип…" }).click();
await page.locator(".bulkbar").getByRole("menuitem", { name: "Вопрос" }).click();
await page.getByText("Изменено 3 требования").waitFor();
await page.locator(".scope .types").getByRole("button", { name: "Q", exact: true }).click();     // the type chips of the scope row
await page.locator(".scope .types button", { hasText: /Q\s*·\s*3/ }).waitFor();
await page.locator(".scope .types").getByRole("button", { name: /^Q/ }).click();
step("shift-click range → change type for 3");

// Keyboard: space toggles, Esc clears, ⌘A selects all.
await page.locator(".atom .type").first().click();
await page.keyboard.press(" ");
await selected.filter({ hasText: "Выбрано: 1" }).waitFor();
await page.keyboard.press("Escape");
await page.locator(".bulkbar").waitFor({ state: "detached" });
await page.keyboard.press(process.platform === "darwin" ? "Meta+a" : "Control+a");
await selected.filter({ hasText: "Выбрано: 6" }).waitFor();
await page.keyboard.press("Escape");
step("keyboard: space, Esc, ⌘A");

// One source only: pick it, select all, reject.
await page.locator(".scope").getByRole("button", { name: "Источник", exact: true }).click();
await page.getByRole("menuitem", { name: /^Письмо/ }).click();
await page.waitForFunction(() => document.querySelectorAll(".atom").length === 2, null, { timeout: 5000 })
  .catch(() => { throw new Error("source filter should show 2 atoms"); });
await page.locator(".check-all input").check();
await page.locator(".bulkbar").getByRole("button", { name: "Отклонить" }).click();
await sub.filter({ hasText: "6 всего · 4 на проверку · принято 0" }).waitFor();
if (shots) await page.screenshot({ path: join(shots, "bulk.png"), fullPage: true });
step("source filter → reject everything from one source");

// Delete: one atom by its button, then the rest by selection; undo brings them back.
await page.locator(".scope").getByRole("button", { name: "Источник", exact: true }).click();
await page.getByRole("menuitem", { name: "Все источники" }).click();
await page.locator(".scope .seg-m").getByRole("button", { name: /^Все/ }).click();
await sub.filter({ hasText: "6 всего · 4 на проверку · принято 0" }).waitFor();
await page.locator(".atom .type").first().click();
await page.locator(".inspector").getByRole("button", { name: "Удалить требование" }).click();
await page.getByRole("status").getByText("Удалено 1 требование").waitFor();
await sub.filter({ hasText: "5 всего" }).waitFor();
await page.getByRole("status").getByRole("button", { name: "Отменить" }).click();
await sub.filter({ hasText: "6 всего" }).waitFor();
await page.locator(".check-all input").check();
await page.keyboard.press("Delete");
await page.getByRole("status").getByText("Удалено 6 требований").waitFor();
await page.getByText("Требований пока нет").waitFor();
await page.getByRole("status").getByRole("button", { name: "Отменить" }).click();
await sub.filter({ hasText: "6 всего" }).waitFor();
step("delete one, delete all selected with the Delete key, undo");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all bulk steps passed");
