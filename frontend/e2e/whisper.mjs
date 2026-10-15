// Шепнуть (spec 5.0 C7): ⌥Space from another screen opens #/whisper and starts listening → the scripted words appear →
// the capture stops by itself → the result card shows what was said and two items (a reminder for tomorrow 10:00 and a
// task) → save → both are in the inbox under Сегодня → tick the task → "Сделать вопросом" on the reminder (no project:
// the chooser) → the Q atom is in Требования → delete with undo. A meeting can't start while a whisper records.
// Runs once per interface language.
// Run: FAKE_RECORDER=1 DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 &
//      node frontend/e2e/whisper.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", heading: "Шепнуть", meetings: "Встречи", listening: "Слушаю…", firstWords: "Напомни завтра",
        said: "Напомни завтра в десять позвонить Ирине насчёт истории заявки и ещё надо отправить Олегу регламент",
        saidHead: /^Вы сказали · 0:\d\d · GigaAM, локально/, reminder: "Позвонить Ирине насчёт истории заявки",
        task: "Отправить Олегу регламент", kindRemind: "Напоминание", due: "завтра, 10:00", more: "Ещё одно в этой же фразе",
        save: "Сохранить 2", today: "Сегодня", saved: "Сохранено: 2 записи · уведомление завтра, 10:00",
        open: n => new RegExp(`^${n} открыт(ая|ых)$`), toQuestion: "Сделать вопросом", made: /^Создан вопрос Q-\d+ в проекте «/,
        openQ: "Открыть", del: "Удалить", deleted: "Удалено из ящика", undo: "Вернуть", notify: "Напоминания приходят, пока Dictum открыт." },
  en: { locale: "en-US", heading: "Whisper", meetings: "Meetings", listening: "Listening…", firstWords: "Remind me tomorrow",
        said: "Remind me tomorrow at ten to call Irina about the request history and also send Oleg the policy",
        saidHead: /^You said · 0:\d\d · GigaAM, on this computer/, reminder: "Call Irina about the request history",
        task: "Send Oleg the policy", kindRemind: "Reminder", due: "tomorrow, 10:00", more: "One more in the same phrase",
        save: "Save 2", today: "Today", saved: "Saved: 2 items · notification tomorrow, 10:00",
        open: n => new RegExp(`^${n} open$`), toQuestion: "Make a question", made: /^Question Q-\d+ created in “/,
        openQ: "Open", del: "Delete", deleted: "Removed from the inbox", undo: "Undo", notify: "Reminders arrive while Dictum is open." },
};

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  // the one expected refusal: a meeting while the whisper records
  page.on("response", r => { if (r.status() >= 400 && !/desktop-record\/start$/.test(new URL(r.url()).pathname)) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);
  const json = async path => (await page.request.get(base + path)).json();

  const project = `Шепнуть e2e ${lang}`;
  const made = await (await page.request.post(base + "/api/projects", { data: { name: project } })).json();
  await page.request.post(`${base}/api/projects/${made.id}/current`);

  await page.goto(base + "/#/meetings");
  await page.getByRole("heading", { name: s.meetings, exact: true }).waitFor();
  await page.locator("body").click({ position: { x: 700, y: 5 } });
  await page.keyboard.press("Alt+Space");
  await page.waitForURL(/#\/whisper$/);
  await page.getByRole("heading", { name: s.heading, exact: true }).waitFor();
  await page.locator(".wbtn.live").waitFor();
  await page.locator(".wcap h2", { hasText: s.listening }).waitFor();
  await page.locator(".wcap", { hasText: s.notify }).waitFor();
  step("⌥Space from Встречи opens Шепнуть and starts listening");

  const busy = await page.request.post(base + "/desktop-record/start", { data: {} });
  if (busy.status() !== 409) throw new Error("a meeting started while a whisper records: " + busy.status());
  step("a meeting can't start while a whisper records (409)");

  await page.locator("#wlive", { hasText: s.firstWords }).waitFor({ timeout: 5000 });
  step("the words appear as they are spoken");

  const said = page.locator(".wres .said");
  await said.waitFor({ timeout: 15000 });
  const head = (await said.locator("small").textContent()).trim();
  if (!s.saidHead.test(head)) throw new Error("said: " + head);
  if (!(await said.textContent()).includes(s.said)) throw new Error("transcript: " + await said.textContent());
  const card = page.locator(".wparsed");
  if ((await card.locator("input.title").inputValue()) !== s.reminder) throw new Error("title: " + await card.locator("input.title").inputValue());
  await card.locator('button.chip[aria-pressed="true"]', { hasText: s.kindRemind }).waitFor();
  await card.locator(".due-tag", { hasText: s.due }).waitFor();
  await card.locator(".meta.more", { hasText: s.more }).filter({ hasText: s.task }).waitFor();
  step("it stops by itself; the result card shows what was said, the reminder for tomorrow 10:00 and the task");

  await card.getByRole("button", { name: s.save }).click();
  await page.locator(".toast", { hasText: s.saved }).waitFor();
  const inbox = page.locator(".winbox");
  const todayRows = inbox.locator(".wsec", { hasText: s.today });
  await todayRows.waitFor();
  const reminderRow = inbox.locator(".witem", { hasText: s.reminder });
  const taskRow = inbox.locator(".witem", { hasText: s.task });
  await reminderRow.waitFor();
  await taskRow.waitFor();
  await page.locator(".wbtn:not(.live)").waitFor();
  step("Сохранить 2: both items are in the inbox under Сегодня, the capture is idle again");

  await taskRow.locator("input.cb").check();
  await page.locator(".witem.done", { hasText: s.task }).waitFor();
  const open = (await json("/api/whispers")).open;
  await inbox.locator(".open-n").filter({ hasText: s.open(open) }).waitFor();
  const taskApi = (await json("/api/whispers?q=" + encodeURIComponent(s.task))).items.find(w => w.title === s.task);
  if (!taskApi?.done) throw new Error("the task is not done: " + JSON.stringify(taskApi));
  step("ticking the task strikes it through and the open count follows");

  await reminderRow.locator("button.to-q").click();
  await page.locator(".menu .menu-item", { hasText: project }).click();
  const toast = page.locator(".toast", { hasText: s.made });
  await toast.waitFor();
  const atoms = (await json(`/api/projects/${made.id}/atoms`)).atoms.filter(a => a.type === "question");
  if (atoms.length !== 1 || atoms[0].statement !== s.reminder + "?" || atoms[0].evidence[0].quote !== s.said)
    throw new Error("Q atom: " + JSON.stringify(atoms));
  await toast.getByRole("button", { name: s.openQ }).click();
  await page.waitForURL(new RegExp(`#/atoms/atom/${atoms[0].id}$`));
  await page.locator(`#atom-${atoms[0].id}`, { hasText: s.reminder }).waitFor();
  const sources = (await json(`/api/projects/${made.id}/sources`)).sources;
  if (sources.length) throw new Error("the Шепнуть source shows among the meetings: " + JSON.stringify(sources));
  step("Сделать вопросом (project chooser) creates a Q atom quoting the transcript; it is in Требования");

  await page.goto(base + "/#/whisper");
  await taskRow.waitFor();
  await taskRow.hover();
  await taskRow.getByRole("button", { name: s.del }).click();
  await taskRow.waitFor({ state: "detached" });
  await page.locator(".toast", { hasText: s.deleted }).getByRole("button", { name: s.undo }).click();
  await inbox.locator(".witem", { hasText: s.task }).waitFor();
  step("delete removes the item, Вернуть brings it back");
  await ctx.close();
}
await browser.close();
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log("whisper: all checks passed");
