// Материалы (spec 5.0 C5, first half): paste text, label it, filter by the label, the in-context checkbox, the
// keyword search across a material and a meeting line, delete and undo. Runs once per interface language.
// Run: WORKBENCH_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 & node frontend/e2e/library.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Материалы", paste: "Вставить текст", titlePh: "Название (необязательно)", bodyPh: "Текст",
        add: "Добавить", newLabel: "Создать метку", labelPh: "Название", createAssign: "Создать и назначить",
        search: "Искать в материалах и встречах", more: "Ещё", del: "Удалить", undo: "Вернуть",
        meetings: "Встречи", materials: "Материалы",
        a: "Регламент приёма заявок", b: "Заметки с воркшопа", meeting: "Созвон с дилером",
        word: "ксилофон", label: "регламент" },
  en: { locale: "en-US", heading: "Library", paste: "Paste text", titlePh: "Title (optional)", bodyPh: "Text",
        add: "Add", newLabel: "New label", labelPh: "Name", createAssign: "Create and assign",
        search: "Search materials and meetings", more: "More", del: "Delete", undo: "Undo",
        meetings: "Meetings", materials: "Materials",
        a: "Request handling policy", b: "Workshop notes", meeting: "Dealer call",
        word: "xylophone", label: "policy" },
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);

  // A meeting whose line holds the word the search must find next to the material.
  const res = await page.request.post(base + "/transcribe", {
    multipart: { audio: { name: `${s.meeting}.txt`, mimeType: "text/plain", buffer: Buffer.from(`Дилер спросил про ${s.word} в карточке.\n`) } },
  });
  if (!res.ok()) throw new Error("could not import the meeting: " + res.status());

  await page.goto(base + "/#/library");
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  step("#/library opens Материалы in the OS language");

  for (const [title, body] of [[s.b, "Обсудили отпуска и дежурства."], [s.a, `Заявка принимается за день. Код: ${s.word}.`]]) {
    await page.locator(".addrow").getByRole("button", { name: s.paste }).click();
    await page.getByPlaceholder(s.titlePh).fill(title);
    await page.getByPlaceholder(s.bodyPh).fill(body);
    await page.locator(".sheet").getByRole("button", { name: s.add, exact: true }).click();
    await page.locator("tr.item", { hasText: title }).waitFor();
  }
  const rowA = page.locator("tr.item", { hasText: s.a }), rowB = page.locator("tr.item", { hasText: s.b });
  step("pasted text appears in the list");

  await rowA.click();
  await page.locator(".panel-head h2", { hasText: s.a }).waitFor();
  await page.getByRole("button", { name: s.newLabel }).click();
  await page.getByPlaceholder(s.labelPh, { exact: true }).fill(s.label);
  await page.getByRole("button", { name: s.createAssign }).click();
  await rowA.locator(".ltag", { hasText: s.label }).waitFor();
  if (await rowB.locator(".ltag").count()) throw new Error("the label landed on the other material");
  step("a new label is created and shows on the selected row");

  await page.locator(`.tree button.lbl[data-label="${s.label}"]`).click();
  await rowB.waitFor({ state: "detached" });
  await rowA.waitFor();
  await page.locator(`.tree button.lbl[data-label="${s.label}"]`).click();
  await rowB.waitFor();
  step("the label filters the list, and a second click clears the filter");

  const box = rowA.locator("input[type=checkbox]");
  if (!(await box.isChecked())) throw new Error("a new material should be in context");
  await box.click();
  const pid = (await (await page.request.get(base + "/api/projects")).json()).current_project_id;
  let off = false;
  for (let i = 0; i < 20 && !off; i++) {
    const list = (await (await page.request.get(`${base}/api/projects/${pid}/materials`)).json()).materials;
    off = list.find(m => m.title === s.a)?.in_context === false;
    if (!off) await page.waitForTimeout(100);
  }
  if (!off) throw new Error("in_context was not saved");
  if (await page.locator(".panel .crow input.switch").isChecked()) throw new Error("the panel switch did not follow");
  step("the Контекст checkbox switches the material out of the AI context");

  await page.getByPlaceholder(s.search).fill(s.word);
  const hits = page.locator(".hits");
  await hits.locator(".hsec", { hasText: s.materials }).waitFor();
  await hits.locator(".hsec", { hasText: s.meetings }).waitFor();
  await hits.locator(".hit", { hasText: s.a }).waitFor();
  await hits.locator(".hit", { hasText: s.meeting }).waitFor();
  await hits.locator(".hit mark").first().waitFor();
  step("search finds the material and the meeting line, grouped, with the word marked");
  await hits.locator(".hit", { hasText: s.meeting }).click();
  await page.waitForURL(/#\/meeting\/[^/]+\/seg\/0/);
  step("a meeting hit opens the meeting at its line");

  await page.goto(base + "/#/library");
  await rowA.click();
  await page.locator(".panel-foot").getByRole("button", { name: s.more }).click();
  await page.getByRole("menuitem", { name: s.del }).click();
  await rowA.waitFor({ state: "detached" });
  await page.locator(".toast button", { hasText: s.undo }).click();
  await rowA.waitFor();
  step("delete removes the material and undo brings it back");

  // Встречи never lists materials.
  await page.goto(base + "/#/meetings");
  await page.locator(".item", { hasText: s.meeting }).waitFor();
  if (await page.locator(".item", { hasText: s.a }).count()) throw new Error("a material is listed among the meetings");
  step("Встречи does not show materials");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all library steps passed");
