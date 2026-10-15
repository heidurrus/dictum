// Screenshots of the screens restyled in 4.9.14 (Требования, Документы, Бэклог, Выгрузка, Скиллы) in ru and en,
// light and dark, at 1440 and 390 px, against e2e/fake_llm_server.py on a fresh data folder.
// Usage: node frontend/e2e/restyle_shots.mjs http://127.0.0.1:5098 [out dir, or OUT=…; default docs/design/5.0]
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] || "http://127.0.0.1:5098";
const out = process.env.OUT || process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), "../../docs/design/5.0");
mkdirSync(out, { recursive: true });
const dir = mkdtempSync(join(tmpdir(), "wb-"));
const call1 = join(dir, "Созвон по карточке.vtt");
writeFileSync(call1, "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Карточка открывается не дольше двух секунд</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>Оператор видит историю заказов</v>\n\n" +
  "00:00:09.000 --> 00:00:12.000\n<v SPEAKER_00>Оператор ищет клиента по номеру</v>\n");
const call2 = join(dir, "Встреча по заявкам.vtt");
writeFileSync(call2, "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Система проверяет VIN и телефон на дубли</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>История изменений заявки: кто, когда, что</v>\n\n" +
  "00:00:09.000 --> 00:00:12.000\n<v SPEAKER_00>Кто утверждает смену статуса заявки?</v>\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
const step = (name) => console.log("✓", name);

// Seed: one meeting reviewed into a document and a backlog, a second one extracted after them (pending, the
// document stale by one accepted requirement).
{
  const ctx = await browser.newContext({ locale: "ru-RU", viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(e.message));
  const sub = page.locator(".screen-sub");
  async function importAndExtract(path, n) {
    await page.goto(base + "/#/sources");
    await page.locator("input[type=file]").first().setInputFiles(path);
    await page.locator(".seg-row").first().waitFor();
    await page.getByRole("button", { name: "Извлечь требования" }).click();
    await page.getByRole("button", { name: `Требования из источника · ${n}` }).waitFor({ timeout: 15000 });
  }
  await importAndExtract(call1, 3);
  await page.goto(base + "/#/atoms");
  await sub.filter({ hasText: "на проверку" }).waitFor();
  await page.locator(".check-all input").check();
  await page.locator(".bulkbar").getByRole("button", { name: /конфликтные/ }).click();
  await page.getByText("Все требования разобраны").waitFor();
  await page.goto(base + "/#/document");
  await page.locator(".screen-head").getByRole("button", { name: "Собрать документ" }).click();
  await sub.filter({ hasText: "версия 1" }).waitFor({ timeout: 15000 });
  await page.goto(base + "/#/backlog");
  await page.locator(".screen-head").getByRole("button", { name: "Собрать бэклог" }).click();
  await page.locator(".tree .node.story").first().waitFor({ timeout: 15000 });
  await importAndExtract(call2, 3);
  await page.goto(base + "/#/atoms");
  await page.locator(".atom").first().waitFor();
  await page.locator(".scope .seg-m").getByRole("button", { name: /^На проверку/ }).click();
  await page.locator(".atom .type").first().click();
  await page.keyboard.press("a");
  await sub.filter({ hasText: "принято 4" }).waitFor();
  await ctx.close();
  step("seeded: 6 requirements, a document v1 now stale, a backlog");
}

const SCREENS = [["requirements", "#/atoms", ".atom"], ["documents", "#/document", ".paper"], ["backlog", "#/backlog", ".tree .node"],
                 ["export", "#/export", ".dest"], ["skills", "#/skills", ".list .item"]];
for (const [lang, locale] of [["ru", "ru-RU"], ["en", "en-US"]])
  for (const scheme of ["light", "dark"])
    for (const [w, h] of [[1440, 900], [390, 844]]) {
      const ctx = await browser.newContext({ locale, colorScheme: scheme, viewport: { width: w, height: h }, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      page.on("pageerror", e => errors.push(e.message));
      for (const [name, hash, ready] of SCREENS) {
        await page.goto(`${base}/${hash}`);
        await page.locator(ready).first().waitFor({ timeout: 15000 });
        if (name === "skills") await page.locator(".list .item", { hasText: /извлечение требований|requirement extraction/i }).first().click();   // a skill open in the editor
        await page.waitForTimeout(500);
        await page.screenshot({ path: join(out, `${name}-${lang}-${scheme}-${w}.png`) });
      }
      await ctx.close();
      step(`${lang} ${scheme} ${w}`);
    }

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("screenshots in", out);
