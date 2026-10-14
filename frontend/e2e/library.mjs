// Материалы (spec 5.0 C5): paste text, the graph (default view) with the fake index, a label created from a selected
// material that assigns itself by meaning, "Похожие материалы", an auto label removed and never put back, filter by
// the label, the in-context checkbox, the keyword search across a material and a meeting line, delete and undo.
// Runs once per interface language.
// Run: WORKBENCH_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 & node frontend/e2e/library.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Материалы", paste: "Вставить текст", titlePh: "Название (необязательно)", bodyPh: "Текст",
        add: "Добавить", newLabel: "Создать метку", labelPh: "Название", createAssign: "Создать и назначить",
        search: "Искать в материалах и встречах", more: "Ещё", del: "Удалить", undo: "Вернуть",
        meetings: "Встречи", materials: "Материалы", graph: "Граф", list: "Список", assigned: /назначена: (\d+)/,
        removeLabel: name => `Снять метку «${name}»`,
        a: "Регламент приёма заявок", b: "Заметки с воркшопа", c: "Сроки проверки заявок", meeting: "Созвон с дилером",
        word: "ксилофон", label: "регламент" },
  en: { locale: "en-US", heading: "Library", paste: "Paste text", titlePh: "Title (optional)", bodyPh: "Text",
        add: "Add", newLabel: "New label", labelPh: "Name", createAssign: "Create and assign",
        search: "Search materials and meetings", more: "More", del: "Delete", undo: "Undo",
        meetings: "Meetings", materials: "Materials", graph: "Graph", list: "List", assigned: /assigned: (\d+)/,
        removeLabel: name => `Remove the label “${name}”`,
        a: "Request handling policy", b: "Workshop notes", c: "Request review deadlines", meeting: "Dealer call",
        word: "xylophone", label: "policy" },
};
// The fake index embeds a hashed bag of words: A and C share most words, B shares none.
const TEXT = {
  a: word => `Заявка дилера принимается за день, проверка заявки дилера по регламенту приёма. Код: ${word}.`,
  b: () => "Обсудили отпуска и дежурства.",
  c: () => "Проверка заявки дилера по регламенту приёма занимает день.",
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);

  // A project of its own per language, so the graph holds exactly this run's materials.
  const made = await (await page.request.post(base + "/api/projects", { data: { name: `Материалы e2e ${lang}` } })).json();
  await page.request.post(`${base}/api/projects/${made.id}/current`);
  // A meeting whose line holds the word the search must find next to the material.
  const res = await page.request.post(base + "/transcribe", {
    multipart: { audio: { name: `${s.meeting}.txt`, mimeType: "text/plain", buffer: Buffer.from(`Дилер спросил про ${s.word} в карточке.\n`) } },
  });
  if (!res.ok()) throw new Error("could not import the meeting: " + res.status());

  await page.goto(base + "/#/library");
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  step("#/library opens Материалы in the OS language");

  const node = title => page.locator(".graph g.gnode", { hasText: title.slice(0, 20) });
  for (const k of ["b", "a", "c"]) {
    await page.locator(".addrow").getByRole("button", { name: s.paste }).click();
    await page.getByPlaceholder(s.titlePh).fill(s[k]);
    await page.getByPlaceholder(s.bodyPh).fill(TEXT[k](s.word));
    await page.locator(".sheet").getByRole("button", { name: s.add, exact: true }).click();
    await node(s[k]).waitFor();
  }
  if (!(await page.getByRole("button", { name: s.graph, exact: true }).getAttribute("aria-pressed") === "true"))
    throw new Error("the graph is not the default view");
  await page.locator(".graph line.edge").first().waitFor();
  if (await page.locator(".graph g.gnode").count() !== 3) throw new Error("the graph should show three nodes");
  step("the graph is the default view and shows three pasted texts with an edge between the similar two");

  await node(s.a).click();
  await page.locator(".panel-head h2", { hasText: s.a }).waitFor();
  await page.locator(".graph line.edge.hot").first().waitFor();
  await page.locator(".panel .links.related .r", { hasText: s.c }).waitFor();
  if (!/\d+%/.test(await page.locator(".panel .links.related .r", { hasText: s.c }).innerText()))
    throw new Error("a similar material shows no percentage");
  step("clicking a node selects the material, highlights its edges and lists similar materials with a percentage");

  await page.getByRole("button", { name: s.newLabel }).click();
  await page.getByPlaceholder(s.labelPh, { exact: true }).fill(s.label);
  await page.getByRole("button", { name: s.createAssign }).click();
  const toast = page.locator(".toast", { hasText: s.assigned });
  await toast.waitFor();
  const n = Number((await toast.innerText()).match(s.assigned)[1]);
  if (n < 1) throw new Error("the toast counts no materials");
  await page.locator(`.panel .ltag[data-label="${s.label}"]`).waitFor();
  step(`the label lands on the seed and the toast counts ${n} material(s) by meaning`);

  await page.getByRole("button", { name: s.list, exact: true }).click();
  const rowA = page.locator("tr.item", { hasText: s.a }), rowB = page.locator("tr.item", { hasText: s.b });
  const rowC = page.locator("tr.item", { hasText: s.c });
  await rowA.locator(".ltag", { hasText: s.label }).waitFor();
  await rowC.locator(".ltag", { hasText: s.label }).waitFor();
  if (await rowB.locator(".ltag").count()) throw new Error("the label landed on the unrelated material");
  step("the label is on the similar material too, not on the unrelated one");

  await rowC.click();
  await page.locator(".panel-head h2", { hasText: s.c }).waitFor();
  await page.locator(`.panel .ltag[data-label="${s.label}"] .auto`).waitFor();
  await page.getByRole("button", { name: s.removeLabel(s.label) }).click();
  await rowC.locator(".ltag").waitFor({ state: "detached" });
  step("an auto label shows its marker and can be taken off");

  const pid = (await (await page.request.get(base + "/api/projects")).json()).current_project_id;
  const labels = (await (await page.request.get(`${base}/api/projects/${pid}/labels`)).json()).labels;
  const del = await page.request.delete(`${base}/api/labels/${labels.find(l => l.name === s.label).id}`);
  if (!del.ok()) throw new Error("could not delete the label");
  await page.reload();
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  await rowA.click();
  await page.locator(".panel-head h2", { hasText: s.a }).waitFor();
  await page.getByRole("button", { name: s.newLabel }).click();
  await page.getByPlaceholder(s.labelPh, { exact: true }).fill(s.label);
  await page.getByRole("button", { name: s.createAssign }).click();
  await rowA.locator(".ltag", { hasText: s.label }).waitFor();
  await page.waitForTimeout(300);
  if (await rowC.locator(".ltag").count()) throw new Error("the recreated label came back on the material it was taken off");
  step("a label recreated with the same name does not return where it was removed");

  await page.locator(`.tree button.lbl[data-label="${s.label}"]`).click();
  await rowB.waitFor({ state: "detached" });
  await rowA.waitFor();
  await page.locator(`.tree button.lbl[data-label="${s.label}"]`).click();
  await rowB.waitFor();
  step("the label filters the list, and a second click clears the filter");

  const box = rowA.locator("input[type=checkbox]");
  if (!(await box.isChecked())) throw new Error("a new material should be in context");
  await box.click();
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
