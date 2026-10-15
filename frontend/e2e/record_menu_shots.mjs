// Screenshots of the record panel on Встречи (5.0.2) in ru and en, light, with the panel open, as the macOS
// desktop window sees it: run against e2e/fake_llm_server.py with FAKE_RECORDER=1 on a fresh data folder.
// The speech model is shown as installed (the fake server has none on disk) and system audio as allowed.
// Usage: node frontend/e2e/record_menu_shots.mjs http://127.0.0.1:5098 [out dir; default docs/design/5.0]
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] || "http://127.0.0.1:5098";
const out = process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), "../../docs/design/5.0");
mkdirSync(out, { recursive: true });

await fetch(base + "/api/permissions/request/system_audio", { method: "POST" });   // the fake marks it granted

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, locale] of [["ru", "ru-RU"], ["en", "en-US"]]) {
  const ctx = await browser.newContext({ locale, viewport: { width: 1280, height: 760 }, colorScheme: "light", deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  await page.route("**/api/asr/models*", async route => {
    const res = await route.fetch();
    const body = await res.json();
    body.models = body.models.map(m => (m.id === "v3_e2e_rnnt" ? { ...m, installed: true } : m));
    await route.fulfill({ response: res, json: body });
  });
  await page.goto(base + "/#/meetings");
  await page.locator(".rec-wrap .chev").click();
  await page.locator(".rec-pop .ml[data-installed='true']").waitFor();
  await page.locator(".rec-pop .rp-sys[data-sys='granted']").waitFor();
  await page.waitForTimeout(300);
  const file = join(out, `meetings-record-menu-${lang}.png`);
  await page.screenshot({ path: file });
  console.log("✓", file);
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
