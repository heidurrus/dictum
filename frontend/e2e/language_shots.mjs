// Screenshots of the meeting language (5.0.5) in ru and en, light: the record panel on Встречи with Multilingual picked,
// and Settings → Модели with a picker per language. Run against e2e/fake_llm_server.py with FAKE_RECORDER=1 on a fresh
// data folder. Both models are shown as installed (the fake server has none on disk) and system audio as allowed.
// Usage: node frontend/e2e/language_shots.mjs http://127.0.0.1:5098 [out dir; default docs/design/5.0]
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const base = process.argv[2] || "http://127.0.0.1:5098";
const out = process.argv[3] || join(dirname(fileURLToPath(import.meta.url)), "../../docs/design/5.0");
mkdirSync(out, { recursive: true });

await fetch(base + "/api/permissions/request/system_audio", { method: "POST" });   // the fake marks it granted
const { current_project_id: pid } = await (await fetch(base + "/api/projects")).json();
await fetch(`${base}/api/projects/${pid}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify({ asr_lang: "multi" }) });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, locale] of [["ru", "ru-RU"], ["en", "en-US"]]) {
  const ctx = await browser.newContext({ locale, viewport: { width: 1280, height: 760 }, colorScheme: "light", deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  await page.route("**/api/asr/models*", async route => {
    const res = await route.fetch();
    const body = await res.json();
    body.models = body.models.map(m => (["v3_e2e_rnnt", "multilingual_ctc"].includes(m.id) ? { ...m, installed: true } : m));
    await route.fulfill({ response: res, json: body });
  });
  await page.goto(base + "/#/meetings");
  await page.locator(".rec-wrap .chev").click();
  await page.locator(".rec-pop .ml[data-lang='multi'][data-installed='true']").waitFor();
  await page.locator(".rec-pop .rp-sys[data-sys='granted']").waitFor();
  await page.waitForTimeout(300);
  let file = join(out, `record-language-${lang}.png`);
  await page.screenshot({ path: file });
  console.log("✓", file);

  await page.goto(base + "/#/settings/models");
  const card = page.locator("#set-asr");
  await card.locator(".asr-langs select").first().waitFor();
  await card.evaluate(el => el.scrollIntoView({ block: "start" }));
  await page.waitForTimeout(400);
  file = join(out, `models-two-languages-${lang}.png`);
  await page.screenshot({ path: file });
  console.log("✓", file);
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
