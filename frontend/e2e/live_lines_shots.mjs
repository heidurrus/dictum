// Screenshots of the meeting page right after Stop (5.0.5) in ru and en, light: the live lines stay, lighter, under
// "the full transcript is being made" until the final transcript replaces them. Run against e2e/fake_llm_server.py
// with FAKE_RECORDER=1 on a fresh data folder (its fake live pass adds four lines; the full pass takes ~6 s).
// Usage: node frontend/e2e/live_lines_shots.mjs http://127.0.0.1:5098 [out dir; default docs/design/5.0]
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] || "http://127.0.0.1:5098";
const out = process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), "../../docs/design/5.0");
mkdirSync(out, { recursive: true });

const L = {
  ru: { locale: "ru-RU", record: "Записать встречу", consent: "Да, записывать", stop: "Завершить и расшифровать" },
  en: { locale: "en-US", record: "Record a meeting", consent: "Yes, record", stop: "Stop and transcribe" },
};
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1280, height: 760 }, colorScheme: "light", deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  await page.goto(base + "/#/meetings");
  await page.locator("button.rmain", { hasText: s.record }).click();
  await page.getByRole("button", { name: s.consent }).click();
  await page.waitForURL(/#\/meeting\/[0-9a-f-]+$/, { timeout: 5000 });
  await page.locator(".live-row.provisional").nth(3).waitFor({ timeout: 10000 });
  await page.locator(".audio-pill").getByRole("button", { name: s.stop, exact: true }).click();
  await page.locator(".rough-lines .live-row.provisional").nth(3).waitFor({ timeout: 8000 });
  await page.waitForTimeout(200);
  const file = join(out, `live-lines-stay-${lang}.png`);
  await page.screenshot({ path: file });
  console.log("✓", file);
  await page.locator(".seg-row:not(.live-row)").first().waitFor({ timeout: 20000 });   // let the job finish
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
