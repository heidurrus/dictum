// Встречи (spec 5.0 C2): list, search, rename in the panel, open the meeting. Runs once per interface language.
// Run: DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 & node frontend/e2e/meetings.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Встречи", search: "Искать по названию и тексту встреч", open: "Открыть встречу",
        a: "Созвон с логистикой", b: "Планёрка", word: "ксилофон", renamed: "Созвон о складе" },
  en: { locale: "en-US", heading: "Meetings", search: "Search meeting titles and text", open: "Open meeting",
        a: "Logistics call", b: "Standup", word: "xylophone", renamed: "Warehouse call" },
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const dir = mkdtempSync(join(tmpdir(), "dictum-"));
  const a = join(dir, `${s.a}.txt`), b = join(dir, `${s.b}.txt`);
  writeFileSync(a, `Склад принимает заказы до полудня. Пароль дня: ${s.word}.\n`);
  writeFileSync(b, "Обсудили отпуск и дежурства.\n");

  // A fresh browser profile: no stored language, so the interface follows the locale.
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400 && !/\/summarize$/.test(new URL(r.url()).pathname)) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);

  await page.goto(base + "/");
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  if (!page.url().includes("#/meetings")) throw new Error("home should be #/meetings: " + page.url());
  step("the empty address opens Встречи, in the OS language");

  await page.locator("input[type=file]").setInputFiles([a, b]);
  const rowA = page.locator(".item", { hasText: s.a }), rowB = page.locator(".item", { hasText: s.b });
  await rowA.waitFor(); await rowB.waitFor();
  step("imported text files appear as rows");

  await page.getByPlaceholder(s.search).fill(s.word);
  await rowB.waitFor({ state: "detached" });
  await rowA.waitFor();
  step("search by a word from the text finds the meeting");

  await rowA.click();
  const title = page.locator(".panel-head h2");
  await title.filter({ hasText: s.a }).waitFor();
  await title.click();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.type(s.renamed);
  await page.keyboard.press("Enter");
  await page.locator(".item", { hasText: s.renamed }).waitFor();
  await page.getByPlaceholder(s.search).fill("");
  await page.locator(".item", { hasText: s.renamed }).waitFor();
  if (await page.locator(".item", { hasText: s.a }).count()) throw new Error("the old title is still in the list");
  step("rename in the panel updates the row");

  await page.locator(".item", { hasText: s.renamed }).click();
  await page.getByRole("button", { name: s.open }).click();
  await page.waitForURL(/#\/meeting\//);
  await page.locator(".screen-title", { hasText: s.renamed }).waitFor();
  step("Открыть встречу opens the meeting page with the new title");

  // Back home, double-click opens it too.
  await page.goto(base + "/#/meetings");
  await page.locator(".item", { hasText: s.renamed }).dblclick();
  await page.waitForURL(/#\/meeting\//);
  step("double-click opens the meeting");

  // The record panel (5.0.2): microphone, one line each for system audio and the model, who-said-what, Start.
  // No model list and no CPU/GPU here (those are in Settings → Модели); Escape and an outside click close it.
  await page.goto(base + "/#/meetings");
  const chev = page.locator(".rec-wrap .chev");
  const pop = page.locator(".rec-pop");
  await chev.click();
  await pop.locator("#rec-mic").waitFor();
  await pop.locator(".rp-model[data-installed]:not([data-installed=''])").waitFor();
  await pop.locator(".rp-sys").waitFor();
  await pop.locator(".rp-start").waitFor();
  if (await pop.locator("details, .seg, .models").count()) throw new Error("the record panel still has the model list or CPU/GPU");
  if (await pop.evaluate(el => getComputedStyle(el).textAlign) !== "left") throw new Error("the record panel is not left-aligned");
  await pop.locator("#rec-mic").focus();
  await page.keyboard.press("Escape");
  await pop.waitFor({ state: "detached" });
  await chev.click();
  await pop.waitFor();
  await page.mouse.click(5, 450);
  await pop.waitFor({ state: "detached" });
  await chev.click();
  await pop.locator(".rp-model .linkish").click();
  await page.waitForURL(/#\/settings\/models/);
  step("record panel: calm summary, Escape and outside click close it, Change goes to Settings → Models");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all meetings steps passed");
