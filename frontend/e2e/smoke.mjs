// End-to-end smoke test of the new UI against a running app (default http://127.0.0.1:5097).
// Uses the installed Google Chrome, headless. Run: node e2e/smoke.mjs [baseUrl]
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5097";
const vttPath = join(mkdtempSync(join(tmpdir(), "wb-")), "Встреча с заказчиком.vtt");
writeFileSync(vttPath, "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Нужна карточка клиента до ответа</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>Не дольше двух секунд</v>\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ locale: "ru-RU", viewport: { width: 1280, height: 900 } });
const errors = [];
const EXPECTED_HTTP_ERRORS = [/\/summarize$/];   // no API key in the test profile → 400 by design
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !EXPECTED_HTTP_ERRORS.some(re => re.test(new URL(r.url()).pathname)))
    errors.push(`${r.status()} ${r.url()}`);
});
page.on("console", m => {
  // HTTP failures are tracked precisely above; anything else logged as an error fails the run.
  if (m.type() === "error" && !m.text().startsWith("Failed to load resource")) errors.push(m.text());
});
const step = (name) => console.log("✓", name);

await page.goto(base + "/#/sources");                 // the 4.x address opens Встречи
await page.getByRole("heading", { name: "Встречи", exact: true }).waitFor();
step("meetings screen loads");

// Import a transcript: button says "import and summarize", then we land on the transcript.
await page.locator('input[type=file]').setInputFiles(vttPath);
await page.getByText("Нужна карточка клиента до ответа").waitFor();
if (!page.url().includes("/source/")) throw new Error("did not open the transcript: " + page.url());
step("transcript import opens the transcript");
// No API key in the test profile: the summary must fail with a clear, actionable message.
await page.getByText(/API key|ключ/i).first().waitFor({ timeout: 10000 });
step("summary without a key explains what to do");

// Rename a speaker: the chip in the transcript follows.
await page.getByRole("tab", { name: /^Участники/ }).click();
const nameInput = page.locator(".speaker input").first();
await nameInput.fill("Иван Петров");
await nameInput.press("Enter");
await page.locator(".seg-row .spk", { hasText: "Иван Петров" }).first().waitFor();
step("speaker rename shows in the transcript");

// Back to the list, the import is there; delete it and undo.
await page.locator(".screen-head").getByRole("button", { name: "Назад: Встречи", exact: true }).click();
const row = page.locator(".item", { hasText: "Встреча с заказчиком" });
await row.waitFor();
await row.click();
await row.getByText("Разобран").waitFor();
await page.locator(".panel-foot").getByRole("button", { name: "Ещё" }).click();
await page.getByRole("menuitem", { name: "Удалить" }).click();
await page.getByRole("status").getByText("удалён").waitFor();
await page.getByRole("button", { name: "Вернуть" }).click();
await row.waitFor();
step("delete + undo restores the source");

// Import an email: it opens as a letter with sender details and paragraphs.
const emlPath = join(mkdtempSync(join(tmpdir(), "wb-")), "letter.eml");
writeFileSync(emlPath, "From: Ivan Petrov <ivan@client.ru>\nTo: Anna <anna@us.example>\nSubject: Card requirements\n" +
  "Content-Type: text/plain; charset=utf-8\n\nКарточка клиента должна открываться до ответа.\n\nСпасибо, Иван\n");
await page.locator('input[type=file]').setInputFiles(emlPath);            // already on Встречи
await page.getByText("Карточка клиента должна открываться до ответа.").waitFor();
await page.getByText("От: Ivan Petrov").waitFor();
await page.locator(".block-title", { hasText: "Письмо" }).waitFor();
if (await page.locator(".seg-meta").count()) throw new Error("an email must render as paragraphs, not timed segments");
step("email import opens as a letter with sender and paragraphs");
await page.locator(".screen-head").getByRole("button", { name: "Назад: Встречи", exact: true }).click();

// Create a project and switch to it: the list is empty there.
await page.locator(".proj").click();
await page.getByPlaceholder("Название проекта").fill("E2E проект " + Date.now());
await page.getByRole("button", { name: "Создать" }).click();
await page.getByText("С чего начать").waitFor();
step("new project is created and empty");

// Status chip: "Готово" when idle, the job while a transcription runs (the fake server takes ~3 s), then "Готово" again.
const chip = page.locator(".topbar .status-chip");
await chip.filter({ hasText: "Готово" }).waitFor();
const wavPath = join(mkdtempSync(join(tmpdir(), "wb-")), "Созвон.wav");
const samples = 16000, wav = Buffer.alloc(44 + samples * 2);
wav.write("RIFF", 0); wav.writeUInt32LE(36 + samples * 2, 4); wav.write("WAVEfmt ", 8); wav.writeUInt32LE(16, 16);
wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22); wav.writeUInt32LE(16000, 24); wav.writeUInt32LE(32000, 28);
wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(samples * 2, 40);
writeFileSync(wavPath, wav);
await page.locator('input[type=file]').setInputFiles(wavPath);
await chip.filter({ hasText: /задач/ }).waitFor({ timeout: 10000 });
await chip.filter({ hasText: "Готово" }).waitFor({ timeout: 30000 });
step("status chip shows the transcription job, then Готово");

// Language switch.
await page.locator(".rail").getByRole("button", { name: "Настройки" }).click();
await page.getByRole("group", { name: "Язык интерфейса" }).getByRole("button", { name: "English" }).click();
await page.getByRole("heading", { name: "Settings" }).waitFor();
await page.getByRole("group", { name: "Interface language" }).getByRole("button", { name: "Русский" }).click();
step("language switches RU ↔ EN");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all smoke steps passed");
