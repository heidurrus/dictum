// End-to-end check of requirement atoms against e2e/fake_llm_server.py (default http://127.0.0.1:5098).
// Run: DICTUM_DATA_DIR=$(mktemp -d) python frontend/e2e/fake_llm_server.py & node e2e/atoms.mjs
import { chromium } from "playwright-core";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:5098";
const shots = process.env.SHOTS || "";
const vttPath = join(mkdtempSync(join(tmpdir(), "dictum-")), "Созвон по карточке.vtt");
writeFileSync(vttPath, "WEBVTT\n\n" +
  "00:00:01.000 --> 00:00:04.000\n<v SPEAKER_00>Карточка открывается не дольше двух секунд</v>\n\n" +
  "00:00:05.000 --> 00:00:08.000\n<v SPEAKER_01>Хватит и пяти секунд</v>\n\n" +
  "00:00:09.000 --> 00:00:12.000\n<v SPEAKER_00>Оператор видит историю заказов</v>\n\n" +
  "00:00:13.000 --> 00:00:16.000\n<v SPEAKER_01>А кто переносит старые обращения?</v>\n");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ locale: "ru-RU", viewport: { width: 1280, height: 900 } });
const errors = [];
const EXPECTED_HTTP_ERRORS = [/\/summarize$/];
page.on("pageerror", e => errors.push(e.message));
page.on("response", r => {
  if (r.status() >= 400 && !EXPECTED_HTTP_ERRORS.some(re => re.test(new URL(r.url()).pathname)))
    errors.push(`${r.status()} ${r.url()}`);
});
const step = (name) => console.log("✓", name);
const shot = async (name) => { if (shots) await page.screenshot({ path: join(shots, name), fullPage: true }); };

await page.goto(base + "/#/atoms");
await page.getByText("Требований пока нет").waitFor();
step("atoms screen has an empty state");

await page.goto(base + "/#/sources");
await page.locator('input[type=file]').setInputFiles(vttPath);
await page.getByText("Оператор видит историю заказов").waitFor();
await page.getByRole("button", { name: "Извлечь требования" }).click();
await page.getByRole("button", { name: "Требования из источника · 4" }).waitFor({ timeout: 15000 });
step("extraction from the transcript screen");

await page.getByRole("button", { name: "Требования из источника · 4" }).click();
const srcFilter = page.locator(".scope").getByRole("button", { name: "Источник", exact: true });
await srcFilter.waitFor();
if (!(await srcFilter.textContent()).includes("Созвон по карточке")) throw new Error("the source filter should be set");
await srcFilter.click();
await page.getByRole("menuitem", { name: "Все источники" }).click();
await page.getByText("4 всего · 4 на проверку · принято 0").waitFor();
await page.locator(".scope").getByRole("button", { name: /^В конфликте/ }).click();          // conflicts are a filter chip; the card is in the inspector
await page.locator(".conflict", { hasText: "Разные требования к сроку" }).waitFor();
await page.locator(".scope .seg-m").getByRole("button", { name: /^На проверку/ }).click();
await shot("atoms.png");
step("atoms listed with counts and a conflict");

// Keyboard review: accept the selected (first) atom, reject the next.
await page.keyboard.press("a");
await page.getByText("4 всего · 3 на проверку · принято 1").waitFor();
await page.keyboard.press("x");
await page.getByText("4 всего · 2 на проверку · принято 1").waitFor();
await page.getByRole("status").getByRole("button", { name: "Отменить" }).click();
await page.getByText("4 всего · 3 на проверку · принято 1").waitFor();
step("keyboard accept / reject / undo");

// Edit a statement: the original wording stays visible.
await page.keyboard.press("e");
const area = page.locator(".inspector textarea");
await area.fill("Карточка клиента открывается за 3 секунды");
await area.press("Enter");
await page.getByText("Исходная формулировка:").first().waitFor();
step("edit keeps the original wording");

// Resolve the conflict by turning it into a question for the client.
await page.locator(".scope").getByRole("button", { name: /^В конфликте/ }).click();
await page.locator(".conflict").getByRole("button", { name: "Спросить заказчика" }).click();
await page.getByText("ждёт ответа заказчика").first().waitFor();
await page.locator(".scope .seg-m").getByRole("button", { name: /^Все/ }).click();
await page.locator(".scope .types").getByRole("button", { name: "Q", exact: true }).click();     // the type chips of the scope row
await page.locator(".atom", { hasText: "Уточнить у заказчика" }).waitFor();
step("conflict becomes a question");

// A quote opens the source at that line.
await page.locator(".scope .types").getByRole("button", { name: /^Q/ }).click();
await page.locator(".atom", { hasText: "Хватит и пяти секунд" }).first().locator(".type").click();
await page.locator(".inspector .evidence-head").first().click();
await page.locator(".seg-row.flash", { hasText: "Хватит и пяти секунд" }).waitFor();
step("evidence quote jumps to the transcript line");

await page.goto(base + "/#/atoms");
await page.locator(".screen-sub", { hasText: "на проверку" }).waitFor();
for (let i = 0; i < 6; i++) await page.keyboard.press("a");
try { await page.getByText("Все требования разобраны").waitFor({ timeout: 8000 }); }
catch (err) { await page.screenshot({ path: join(shots || tmpdir(), "atoms-fail.png"), fullPage: true }); throw err; }
await shot("atoms-done.png");
step("all reviewed state");

await browser.close();
if (errors.length) { console.error("page errors:", errors); process.exit(1); }
console.log("all atom steps passed");
