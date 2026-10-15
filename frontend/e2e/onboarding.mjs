// First run (spec 5.0 C8): a fresh install opens on the onboarding → welcome → permissions (the fake answers granted
// after a request; a reload resumes on the same step) → models (the fake completes a download in 2 s) → download
// ("В фоне" in one language, waiting for "Готово" in the other) → discovery lists the two files of the fake's temp folder →
// import them → done → "Показать подсказки" → five tips over #t-rec, #t-whisper, #t-list, #t-library, #t-ask → the shell
// on Встречи with the imported meeting → a reload does not show the onboarding again. The tips come back from Help; Esc
// closes them. Runs once per interface language (the fake server resets the first-run state in between).
// Run: ONBOARDING=1 DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py 5312 &
//      node frontend/e2e/onboarding.mjs http://127.0.0.1:5312
import { chromium } from "playwright-core";
import { writeFileSync } from "node:fs";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const L = {
  ru: { locale: "ru-RU", welcome: "Добро пожаловать в Dictum", start: "Начать", perms: "Разрешения", allowAll: "Разрешить всё",
        granted: "Разрешено", notGranted: "Не разрешено", next: "Далее", models: "Модели", machine: /(ГБ памяти)|(Отметили то)/,
        download: "Загрузить", running: "Готовим Dictum…", done: "Готово", background: "В фоне", checked: "Проверка моделей пройдена",
        materials: "Материалы", add2: "Добавить 2 и продолжить", allSet: "Всё готово", tips: "Показать подсказки",
        tipTitles: ["Записать встречу", "Шепнуть", "Встречи", "Материалы", "Спросить"], of: n => `${n} из 5`, nextTip: "Дальше",
        lastTip: "Готово", meetings: "Встречи", help: "Справка и команды", helpTips: "Подсказки",
        files: null, meeting: "Звонок с дилером", material: "Регламент обработки заявок" },
  en: { locale: "en-US", welcome: "Welcome to Dictum", start: "Start", perms: "Permissions", allowAll: "Allow all",
        granted: "Allowed", notGranted: "Not allowed", next: "Next", models: "Models", machine: /(GB of memory)|(We picked)/,
        download: "Download", running: "Getting Dictum ready…", done: "Done", background: "In the background", checked: "Models verified",
        materials: "Materials", add2: "Add 2 and continue", allSet: "All set", tips: "Show tips",
        tipTitles: ["Record a meeting", "Whisper", "Meetings", "Materials", "Ask"], of: n => `${n} of 5`, nextTip: "Next",
        lastTip: "Done", meetings: "Meetings", help: "Help and commands", helpTips: "Tips",
        files: ["Dealer call.wav", "Request handling policy.md"], meeting: "Dealer call", material: "Request handling policy" },
};

// One second of 16 kHz mono silence: the fake transcription never reads it, the import only needs an audio file.
function wav() {
  const data = Buffer.alloc(32000), h = Buffer.alloc(44);
  h.write("RIFF", 0); h.writeUInt32LE(36 + data.length, 4); h.write("WAVEfmt ", 8); h.writeUInt32LE(16, 16); h.writeUInt16LE(1, 20);
  h.writeUInt16LE(1, 22); h.writeUInt32LE(16000, 24); h.writeUInt32LE(32000, 28); h.writeUInt16LE(2, 32); h.writeUInt16LE(16, 34);
  h.write("data", 36); h.writeUInt32LE(data.length, 40);
  return Buffer.concat([h, data]);
}

const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
let first = true;
for (const [lang, s] of Object.entries(L)) {
  const ctx = await browser.newContext({ locale: s.locale, viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on("pageerror", e => errors.push(`${lang}: ${e.message}`));
  page.on("response", r => { if (r.status() >= 400) errors.push(`${lang}: ${r.status()} ${r.url()}`); });
  const step = name => console.log(`✓ [${lang}]`, name);
  const json = async path => (await page.request.get(base + path)).json();
  const h1 = text => page.getByRole("heading", { level: 1, name: text, exact: true });
  const onbStep = async n => { await page.locator(`.onb[data-step="${n}"]`).waitFor(); };

  if (!first) {
    // A fresh install again, with two new files in the discovery folder (the first run imported the other two).
    await page.request.post(base + "/__fake/reset-onboarding");
    const { root } = await json("/__fake/discover-root");
    writeFileSync(join(root, s.files[0]), wav());
    writeFileSync(join(root, s.files[1]), `# ${s.material}\n\nThe dealer gets a reply within two hours.\n`);
  }
  if ((await json("/api/onboarding")).done) throw new Error("the onboarding is already done on a fresh install");

  // 1. Welcome
  await page.goto(base + "/");
  await h1(s.welcome).waitFor();
  if (await page.locator(".rail").count()) throw new Error("the shell shows during the onboarding");
  if ((await page.locator(".panel-art").count()) !== 3) throw new Error("the welcome step needs three illustrated panels");
  if ((await page.locator(".steps i.on").count()) !== 1) throw new Error("progress: step 1 of 6");
  step("a fresh install opens on the welcome step");
  await page.getByRole("button", { name: s.start }).click();

  // 2. Permissions: three rows, not allowed until requested; a reload resumes here.
  await h1(s.perms).waitFor();
  await page.locator(".perm .tag", { hasText: s.notGranted }).nth(2).waitFor();
  await page.reload();
  await h1(s.perms).waitFor();
  step("permissions: three rows; a reload resumes on the same step");
  await page.getByRole("button", { name: s.allowAll, exact: true }).click();
  for (const which of ["microphone", "system_audio", "notifications"])
    await page.locator(`.perm[data-perm="${which}"] .tag`, { hasText: new RegExp(`^${s.granted}$`) }).waitFor();
  if (await page.getByRole("button", { name: s.allowAll, exact: true }).count()) throw new Error("Разрешить всё stays after all are allowed");
  step("Разрешить всё asks for each in turn and every row reads Разрешено");
  await page.locator(".onb-bot").getByRole("button", { name: s.next }).click();

  // 3. Models: speech, language model (with the machine line), index model, Claude.
  await h1(s.models).waitFor();
  await page.locator(".lead", { hasText: s.machine }).waitFor();
  await page.locator(".model.on", { hasText: "GigaAM" }).waitFor();
  await page.locator(".model", { hasText: "Claude" }).click();
  await page.locator(".key input[type=password]").waitFor();
  const llm = await json("/api/local-llm");
  await page.locator(".model", { hasText: llm.models.find(m => m.recommended).label }).click();
  if (await page.locator(".key input").count()) throw new Error("the key field stays without Claude chosen");
  step("models: speech, language and index cards; Claude reveals the key field");
  await page.locator(".onb-bot").getByRole("button", { name: s.download }).click();

  // 4. Download: three in a row (speech, index, language model).
  await h1(s.running).waitFor();
  if ((await page.locator(".dl-row").count()) !== 3) throw new Error("expected three downloads");
  if (first) {
    await page.getByRole("button", { name: s.background }).click();
    step("download: three progress bars; В фоне goes on while they run");
  } else {
    await h1(s.done).waitFor({ timeout: 20000 });
    await page.getByText(s.checked).waitFor();
    step("download: three progress bars, then Готово with a check");
    await page.locator(".onb-bot").getByRole("button", { name: s.next }).click();
  }

  // 5. Materials: the two files of the fake's folder; import both.
  await h1(s.materials).waitFor();
  await page.locator(".disc", { hasText: s.meeting }).waitFor();
  if ((await page.locator(".disc").count()) !== 2) throw new Error("discovery must list exactly the two new files");
  for (const row of await page.locator(".disc input[type=checkbox]").all()) await row.check();
  await page.getByRole("button", { name: s.add2 }).click();
  step("materials: two candidates listed and imported");

  // 6. Done: six cards, then the tips.
  await h1(s.allSet).waitFor();
  if ((await page.locator(".done-card").count()) !== 6) throw new Error("the done step needs six cards");
  if ((await json("/api/onboarding")).step !== 6) throw new Error("the step was not saved");
  await page.getByRole("button", { name: s.tips }).click();

  // Tutorial: five tips over their targets, in order.
  const targets = ["t-rec", "t-whisper", "t-list", "t-library", "t-ask"];
  for (let i = 0; i < 5; i++) {
    const tip = page.locator(".tut .tip");
    await tip.locator("h4", { hasText: s.tipTitles[i] }).waitFor();
    await tip.getByText(s.of(i + 1), { exact: true }).waitFor();
    if ((await tip.getAttribute("data-target")) !== targets[i]) throw new Error(`tip ${i + 1} points at the wrong place`);
    if (!(await page.locator("#" + targets[i]).count())) throw new Error(`#${targets[i]} is missing in the shell`);
    if (!(await page.locator(".tut .spot").count())) throw new Error(`tip ${i + 1} has no spotlight`);
    await tip.getByRole("button", { name: i < 4 ? s.nextTip : s.lastTip, exact: true }).click();
  }
  await page.locator(".tut").waitFor({ state: "detached" });
  step("tutorial: five tips over #t-rec, #t-whisper, #t-list, #t-library, #t-ask");

  await page.getByRole("heading", { name: s.meetings, exact: true }).waitFor();
  await page.locator(".item", { hasText: s.meeting }).first().waitFor();
  const pid = (await json("/api/projects")).current_project_id;
  const mats = (await json(`/api/projects/${pid}/materials`)).materials;
  if (!mats.some(m => m.title.includes(s.material))) throw new Error("the document did not land in Материалы");
  step("the shell opens on Встречи with the imported meeting; the document is a material");

  await page.reload();
  await page.getByRole("heading", { name: s.meetings, exact: true }).waitFor();
  if (await page.locator(".onb").count()) throw new Error("the onboarding came back after a reload");
  if (!(await json("/api/onboarding")).done) throw new Error("the onboarding is not marked done");
  step("a reload opens the shell, not the onboarding");

  // Help → Подсказки brings the tips back; Esc closes them.
  await page.getByRole("button", { name: s.help }).click();
  await page.getByRole("menuitem", { name: s.helpTips }).click();
  await page.locator(".tut .tip h4", { hasText: s.tipTitles[0] }).waitFor();
  await page.keyboard.press("Escape");
  await page.locator(".tut").waitFor({ state: "detached" });
  step("Help → Подсказки shows the tips again; Esc closes them");

  await ctx.close();
  first = false;
}
await browser.close();
if (errors.length) {
  console.error("errors:\n" + errors.join("\n"));
  process.exit(1);
}
console.log("onboarding e2e passed");
