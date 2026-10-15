// Спросить (spec 5.0 C6): a material and a meeting, indexed by the fake index → ask → the answer streams in with two
// citation chips and the status line → a chip opens the material → ask for a client question → "Создано Q-n" and the
// Q atom is in Требования → the history lists both questions → delete one. Runs once per interface language.
// Run: DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 & node frontend/e2e/ask.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Спросить", placeholder: "Спросите о проекте…", ctx: "Только материалы «в контексте»",
        found: /Найдено в 2 материалах · claude-opus-5 · \d+,\d с/, searching: /Ищу…|Генерирую ответ…/, created: "Создано",
        history: "История", today: "Сегодня", del: "Удалить из истории", meetingChip: /^Встреча · 01:05$/,
        material: "SLA для дилеров", materialText: "Ответ дилеру по заявке даётся не позднее двух часов после создания заявки.",
        meeting: "Созвон с дилером", meetingLine: "Срок ответа дилеру по заявке два часа, так и договорились.",
        q1: "Какой срок ответа дилеру по заявке?", q2: "Сделай вопрос для клиента про срок ответа дилеру по заявке",
        answer: "Ответ дилеру даётся не позднее двух часов", statement: "Какой срок ответа дилеру считать целевым?" },
  en: { locale: "en-US", heading: "Ask", placeholder: "Ask about the project…", ctx: "Only materials “in context”",
        found: /Found in 2 sources · claude-opus-5 · \d+\.\d s/, searching: /Searching…|Writing the answer…/, created: "Created",
        history: "History", today: "Today", del: "Remove from history", meetingChip: /^Meeting · 01:05$/,
        material: "Dealer reply policy", materialText: "The dealer request reply is due no later than two hours after the request is created.",
        meeting: "Dealer call", meetingLine: "The dealer request reply is due in two hours, we agreed on that.",
        q1: "When is the dealer request reply due?", q2: "Make a question for the client about the dealer request reply",
        answer: "The dealer gets a reply within two hours", statement: "Which reply time to the dealer is the target?" },
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);
  const json = async (path, init) => (await page.request.fetch(base + path, init)).json();

  // A project of its own per language with one material and one meeting, indexed by the fake index.
  const made = await (await page.request.post(base + "/api/projects", { data: { name: `Спросить e2e ${lang}` } })).json();
  await page.request.post(`${base}/api/projects/${made.id}/current`);
  const added = await (await page.request.post(`${base}/api/projects/${made.id}/materials`,
    { data: { text: s.materialText, title: s.material } })).json();
  const materialId = added.materials[0].id;
  const res = await page.request.post(base + "/transcribe", {
    multipart: { project_id: made.id, audio: { name: `${s.meeting}.vtt`, mimeType: "text/vtt",
                 buffer: Buffer.from(`WEBVTT\n\n00:01:05.000 --> 00:01:09.000\n${s.meetingLine}\n`) } },
  });
  if (!res.ok()) throw new Error("could not import the meeting: " + res.status());
  for (let i = 0; ; i++) {                      // the meeting is ready, then one index pass covers everything
    const list = await json(`/api/projects/${made.id}/sources`);
    if (list.sources.some(x => x.title === s.meeting && x.status === "ready")) break;
    if (i > 100) throw new Error("the meeting did not get ready");
    await page.waitForTimeout(100);
  }
  const { job_id } = await (await page.request.post(`${base}/api/projects/${made.id}/index`, { data: {} })).json();
  for (let i = 0; job_id; i++) {
    const job = await json(`/job/${job_id}`);
    if (job.status === "done") break;
    if (job.status === "error" || i > 200) throw new Error("index job: " + JSON.stringify(job));
    await page.waitForTimeout(100);
  }

  await page.goto(base + "/#/ask");
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  const box = page.getByPlaceholder(s.placeholder);
  await box.waitFor();
  if (!(await box.evaluate(el => el === document.activeElement))) throw new Error("the composer should have the focus");
  const ctxSwitch = page.locator(".composer .switch");
  if (!(await ctxSwitch.isChecked())) throw new Error("the context switch should be on by default");
  await page.locator(".composer", { hasText: s.ctx }).waitFor();
  step("#/ask opens with the composer focused and the context switch on");

  await box.fill(s.q1);
  await box.press("Enter");
  await page.locator(".msg.me", { hasText: s.q1 }).waitFor();
  await page.locator(".msg.ai .st", { hasText: s.searching }).waitFor({ timeout: 5000 });
  const answer = page.locator(".msg.ai").last();
  await answer.locator(".st", { hasText: s.found }).waitFor({ timeout: 15000 });
  if (!(await answer.textContent()).includes(s.answer)) throw new Error("answer: " + await answer.textContent());
  const chips = answer.locator("button.cite");
  if (await chips.count() !== 2) throw new Error("chips: " + await chips.count());
  const texts = await chips.allTextContents();
  if (texts[0] !== s.material || !s.meetingChip.test(texts[1])) throw new Error("chip texts: " + JSON.stringify(texts));
  if (/\[(Источник|Source) \d+\]/.test(await answer.textContent())) throw new Error("a raw marker is shown");
  step("the answer streams in with the status line and two citation chips: the material and the meeting");

  await chips.first().click();
  await page.waitForURL(new RegExp(`#/library/${materialId}$`));
  await page.locator(".panel-head h2", { hasText: s.material }).waitFor();
  step("a chip opens the material");

  await page.goto(base + "/#/ask");
  await box.fill(s.q2);
  await box.press("Enter");
  const made2 = page.locator(".msg.ai .created", { hasText: s.created });
  await made2.waitFor({ timeout: 15000 });
  const label = (await made2.locator("button.cite").textContent()).trim();
  if (!/^Q-\d+$/.test(label)) throw new Error("created label: " + label);
  if ((await page.locator(".msg.ai").last().textContent()).includes("<intent>")) throw new Error("the intent is shown");
  const atoms = (await json(`/api/projects/${made.id}/atoms`)).atoms.filter(a => a.type === "question" && a.statement === s.statement);
  if (atoms.length !== 1 || atoms[0].evidence.length !== 2 || !atoms[0].evidence.some(e => e.source_id === materialId))
    throw new Error("Q atom: " + JSON.stringify(atoms));
  await made2.locator("button.cite").click();
  await page.waitForURL(new RegExp(`#/atoms/atom/${atoms[0].id}$`));
  await page.locator(`#atom-${atoms[0].id}`, { hasText: s.statement }).waitFor();
  step("asking for a client question creates a Q atom quoting both sources; it is in Требования");

  await page.goto(base + "/#/ask");
  const hist = page.locator(".hist");
  await hist.locator("h4", { hasText: s.history }).waitFor();
  await hist.locator(".day", { hasText: s.today }).waitFor();
  const rows = hist.locator(".h");
  await rows.nth(1).waitFor();
  const listed = await rows.allTextContents();
  if (listed.length !== 2 || !listed[0].includes(s.q2) || !listed[1].includes(s.q1)) throw new Error("history: " + JSON.stringify(listed));
  await rows.nth(1).locator(".hq").click();
  await page.locator(".msg.ai .st", { hasText: s.found }).waitFor();
  if (await page.locator(".msg.ai button.cite").count() !== 2) throw new Error("the re-shown answer lost its chips");
  step("the history lists both questions (Сегодня); clicking one shows its answer again");

  await rows.nth(1).hover();
  await rows.nth(1).getByRole("button", { name: s.del }).click();
  await page.waitForFunction(() => document.querySelectorAll(".hist .h").length === 1);
  const left = await json(`/api/projects/${made.id}/ask/history`);
  if (left.items.length !== 1 || left.items[0].question !== s.q2) throw new Error("history after delete: " + JSON.stringify(left.items));
  await page.reload();
  await rows.first().waitFor();
  if (await rows.count() !== 1) throw new Error("history after reload: " + await rows.count());
  step("× deletes a question from the history, and it stays deleted");

  await page.goto(base + "/#/library");
  await page.locator(".addrow").waitFor();
  await page.keyboard.press("ControlOrMeta+j");
  await page.waitForURL(/#\/ask$/);
  await page.waitForFunction(() => document.activeElement?.matches(".composer input"));
  step("⌘J opens Спросить with the cursor in the composer");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log("ask: all checks passed");
