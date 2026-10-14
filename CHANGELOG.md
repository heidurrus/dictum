# Changelog

## 4.9.13 (2026-10-15): Settings

- **Settings as sections.** A left column Проект · Модели · Приватность · Хранилище · Запись · Jira · Горячие клавиши · Интерфейс · Система, cards per section, one section at a time at `#/settings/<section>`; `#/settings` opens the first (Проект, or Модели without a project). Every 4.x control is still there, moved into its section: project name, output language, extract at once, what goes to Jira, project file export and now import, archive; provider, Claude key and model, Ollama model, built-in model, speech models, device, speakers, HF token; theme and language; runtime checks and version.
- **Модели.** Language-model cards with «нужно n ГБ памяти», «не хватает памяти» and the speed tag exactly as `/api/local-llm` reports them, download with progress, delete, «Выбрать»; «Claude (облако)» as a card with the key field below; the index model card (download, delete, «используют Материалы и «Спросить»»); the speech cards (installed, size, active, recommended; the rest behind «Показать все модели»); the machine line «На этом Mac 16 ГБ памяти и чип M1 Pro». **Stats row**: «За неделю на этом компьютере обработано n токенов · n встреч · n отправлено в облако» with tiles for local tokens, meetings, minutes transcribed, passages indexed and cloud requests, and a Неделя / Месяц / Всё время switch.
- **Usage counters.** A `usage` row (schema v9, additive) for every built-in model call (prompt and completion tokens from llama-server's `usage`, or its `timings`; the streamed calls ask for `stream_options.include_usage`), every Ollama call (its eval counts), every Claude call (input including cached prompt, output; kind `llm_cloud`), every embedding batch (texts) and every transcription pass (seconds of audio: files, both channels, live windows, whispers). Counting never breaks the call it counts.
- **Приватность.** «Только локально» for the project, the consent reminder, and one line per engine saying what leaves the computer (GigaAM, built-in model, index, Ollama, Claude, Jira).
- **Хранилище.** The data folder, projects / meetings / materials / whispers and the size on disk, «Показать», and «Сменить папку…» (a native folder picker in the app, a path field in the browser): the whole folder moves as a job with the 4.x migration's logic (rename; across volumes copy, verify file count and bytes, then remove the original), refused while a meeting or a whisper records or a model downloads, and when the target is the same folder, inside it, not empty or not writable. A pointer file `data-location.json` in the default folder makes the next start use the new place (a folder that is not there, such as an unplugged drive, falls back to the default). Then «Перезапустите Dictum». With `DICTUM_DATA_DIR` set the folder cannot be moved. «Хранить аудио рядом с транскриптом» is shown on and locked: audio is never deleted.
- **Запись.** Microphone, «Живой транскрипт», «Требования на лету», «Отвечать на вопросы из разговора», «Останавливать при тишине» with minutes (off = 0), the default recap style (a meeting without its own choice opens with it) and the recap detail Обычное / Сжатое (`notes_style`; concise adds a brevity rule to the recap prompt).
- **Горячие клавиши.** Every action of the `hotkeys` map as a row with its keys and status (from any app / in the Dictum window / taken / invalid); double-click or «Изменить», then press the new combination (Esc cancels); a combination another action has, or one macOS keeps (⌘Space, ⌘Tab, ⌘Q, ⌘H, ⌘M), is refused with a message, here and on the server; «Сбросить» per row; the «Строка меню» switch (`menubar`). Combos are stored in one spelling (`cmd+ctrl+alt+shift+key`).
- **Jira.** The connection status and the project's export target, with a button to the connection card on Выгрузка.
- API: `GET /api/stats?period=7d|30d|all` → `{tokens_local, tokens_cloud, cloud_calls, meetings, seconds_transcribed, embeddings}`; `GET /api/storage` → `{path, counts: {projects, meetings, materials, whispers}, bytes, default, movable, moved_to}`; `POST /api/data-dir/move {path}` → `{job_id}` (400 / 409 with `code`: `same`, `inside`, `not_empty`, `not_writable`, `override`, `recording`, `downloading`, `moving`); `/settings` round-trips `embed_model`, `recap_style`, `notes_style` and `tuning` too. Settings gain `recap_style` ("brief") and `notes_style` ("standard"). The desktop bridge gains `choose_folder()`.
- e2e: `frontend/e2e/settings.mjs` (ru-RU, en-US); `smoke.mjs` opens Интерфейс before switching the language.

## 4.9.12 (2026-10-15): First run and tutorial

- **First run.** A fresh install opens on six full-screen steps instead of the shell, with six progress bars on top; each step is saved, so a restart resumes where you stopped, and «Назад» goes back where it is safe. 1. **Добро пожаловать**: the local-only promise, three illustrated panels (Записывайте встречи / Проверяйте требования / Собирайте документы, drawn in CSS), the terms line, «Начать». 2. **Разрешения**: Микрофон, Системный звук, Уведомления with their real state (Разрешено / Не разрешено), per-row «Разрешить» and «Системные настройки», «Разрешить всё» (one after another), «Позже». 3. **Модели**: the GigaAM cards, the language-model cards with the machine line («На этом Mac 16 ГБ памяти и чип M1 Pro»), the index model, and «Claude (облако)», which reveals the API-key field; the recommended ones are preselected. «Загрузить» downloads speech, index and language model in that order through the usual routes. 4. **Загрузка**: a progress bar per model; «В фоне» goes on while they run (the status chip shows them), «Готово» with a check when all are in. 5. **Материалы**: candidate files from Загрузки, Документы and Рабочий стол (audio and video, .docx .pdf .md .txt .rtf .html .eml; newest 50; hidden files, files over 2 GB and files already imported into any project are left out), «Выбрать папку» for a typed path, «Ничего не добавлять», «Добавить n и продолжить»: audio becomes meetings (transcribed once the speech model is in place), the rest materials. The files are copied; the originals stay. 6. **Всё готово**: six cards, «Показать подсказки» or «Пропустить».
- **Tips.** A spotlight over the record button, Шепнуть, the meetings list, Материалы and Спросить with a card (n из 5, Закрыть, Дальше / Готово); Esc closes it and it follows window resizes. The help button now opens a menu: Команды и поиск (⌘K), Подсказки, Первый запуск заново (`#/onboarding`); the last two are in the command palette too.
- **How permissions are read on macOS**: the microphone from AVFoundation's authorization status (no prompt); system audio only on macOS 14.2+, `undetermined` until a tap has worked once (the «Разрешить» dry run opens the tap for about a second and drops the audio, nothing is written; refused while a recording runs), notifications `undetermined` until the first notification went out («Dictum готов»). Windows: the microphone is granted when an input device enumerates, the rest is `unsupported`.
- A transcription queued while a speech model downloads now waits in its slot («Ждём, пока загрузится модель распознавания…») instead of fetching the model itself.
- The first-run card of an empty Встречи (name, AI check, first source) stays for projects created later, in the 5.0 look.
- API: `GET /api/onboarding` → `{done, step}`, `POST /api/onboarding {done}` or `{step}` (`onboarding:v5` in `setup-state.json`); `GET /api/permissions` → `{microphone, system_audio, notifications}` each `granted | denied | undetermined | unsupported`, `POST /api/permissions/request/<which>`, `POST /api/permissions/open-settings/<which>`; `GET /api/discover[?folder=]` → `{candidates: [{path, name, kind: audio|document, size, modified, folder}], roots}` (`DICTUM_DISCOVER_ROOTS` replaces the folders), `POST /api/discover/import {paths, project_id, options?}` → `{meetings: [{source_id, job_id}], materials, failed, index_job}`; `/api/local-llm` gains `machine: {ram, chip, os}`.
- e2e: `fake_llm_server.py` marks the first run done before serving unless started with `ONBOARDING=1`, which `frontend/e2e/onboarding.mjs` uses.

## 4.9.11 (2026-10-15): Menu-bar item and global ⌥ Space

- **Global ⌥Space (macOS).** Шепнуть now starts from any app, also when the Dictum window is behind others or minimised: the window comes forward on #/whisper and starts listening; a second press stops it. The record hot key works the same way when it is not a plain ⌘ + key (⌘R stays a window-level key, so other apps keep their own ⌘R). The keys are registered with Carbon's `RegisterEventHotKey`, which needs no Accessibility permission and is allowed in the App Store sandbox; changing the `hotkeys` setting re-registers them at once. When another app or the system holds the combination, it is logged, and the Шепнуть screen says «⌥Space занято другой программой» instead of «Из любого окна: ⌥Space».
- **Menu-bar item (macOS).** The Dictum glyph (a template image, tinted for light and dark menu bars) with Шепнуть ⌥Space, Записать встречу ⌘R, Показать Dictum and Выйти (the same path as closing the window; a recording's audio is kept). While a meeting or a whisper records, the items read «Остановить запись» / «Остановить» and a red dot shows next to the glyph. The titles follow the interface language. Setting `menubar` (on by default; through `/settings`, no UI yet) removes the item at runtime.
- Windows and browser mode are unchanged: the window-level keys only.
- API: `POST /api/ui-lang {lang}` (sent by the page on boot and on a language switch), `GET /api/hotkeys/status` → `{available, whisper, record}` with `ok` | `taken` | `window` | `invalid` | `off`, `GET /api/i18n/menu?lang=` → `{lang, strings}` (the `menu.*` keys, exported by the build into `static/app/menu.json`). Settings gain `menubar`. The page receives the hot keys as a `dictum:hotkey` event.

## 4.9.10 (2026-10-15): Шепнуть

- **Шепнуть** (`#/whisper`) replaces the placeholder: press the big button (or ⌥Space anywhere in the Dictum window), say what needs doing, and it lands in a personal inbox as a task, note, reminder or idea. While you speak the words appear under «Слушаю…»; a second press, two seconds of silence once speech was heard, or 90 seconds stop it. The result card shows «Вы сказали · 0:07 · GigaAM, локально» with the transcript, then the parsed item: type chips Задача / Заметка / Напоминание / Идея, an editable title, the due tag (click to change it; × removes it), the project tag with «проект угадан по словам «заявки» и «Ирина»» (a menu changes it), and «Ещё одно в этой же фразе» for the other items of the same phrase. «Сохранить n» saves them all, «Переговорить» listens again, «Отменить» drops the result; nothing is saved before that. No consent sheet (it is your own voice); the microphone permission is the same as for meetings, and so is the device.
- **The inbox** is personal: it ignores the current project and never reaches a project's requirements, documents, backlog, Jira, search or export. Filters Все · Открытые · Задачи · Заметки · Напоминания, search over titles, text and transcripts, «n открытых», groups Сегодня / Вчера / Раньше; tasks and reminders have a checkbox (done = struck through, the due time turns green); × deletes with «Вернуть».
- **«Сделать вопросом»** turns an item into a client question on demand: a Q requirement (pending, in Требования) in the item's project (or the one you pick when it has none), whose evidence quotes the transcript from the project's hidden «Шепнуть» source (kind `note`, never listed among the meetings). The item shows «Вопрос создан».
- **Reminders**: while the app runs, a check every 30 seconds shows a system notification («Dictum» and the item's title) for every reminder or task whose time has come, once. The screen says reminders arrive only while Dictum is open.
- **How it understands.** The microphone is recorded by the meeting recorder (one channel) into `<data>/whispers/<id>/mic.wav`; the live words come from the meeting's live transcriber with a 2-second window, the auto-stop from its silence watch (2 s, the -50 dBFS floor). After the stop GigaAM transcribes the file (`transcribe_longform` with an HF token, else the short-form pass cut at pauses) and one structured call to the configured model (a «Только локально» current project stays local) returns `{items: [{kind, title, text, due, project_hint}]}`. The prompt is the new built-in skill **Шепнуть** (`skills/whisper`, editable like the others); the app adds the JSON contract, `now` with the timezone and weekday, the interface language, the project names and the date rules. The same rules also run in code and win when they find a date: «завтра в десять» = tomorrow 10:00, «до вечера» = today 18:00, «в понедельник» = next Monday 09:00, «через час» = now + 1 h, the English ones likewise. The project is matched by name (word stems) or by a label of the current project. Without a ready model the transcript is kept as one note and the card says the AI is not set up. A whisper can't start while a meeting records, nor a meeting while a whisper records (409). The audio is never deleted, also not with the item.
- API: `POST /api/whispers/record/start {mic_device, model, device}`, `GET /api/whispers/live` → `{recording, text, elapsed, stopped_by}`, `POST /api/whispers/record/stop` → `{transcript, items, duration, audio_file}` (not saved), `POST /api/whispers {items, transcript, audio_file}`, `GET /api/whispers?filter=all|open|task|note|remind|idea&q=` → `{items, open}`, `PATCH /api/whispers/<id>` (kind, title, text, due_at, done, project_id), `DELETE /api/whispers/<id>` and `POST …/restore`, `POST /api/whispers/<id>/to-question {project_id?}`. Schema v9 part 7: `whispers` (with `atom_id`); source kind `note`.

## 4.9.9 (2026-10-15): Спросить, and answers to questions heard in a call

- **Спросить** (`#/ask`) replaces the placeholder: ask a question about the project and get an answer from its meetings, requirements and materials. Each answer has a status line («Найдено в 2 материалах · модель · 2,1 с»; «Ищу…» / «Генерирую ответ…» while it runs, the text streaming in) and its sources as chips right where the model cited them: the material's title, «Встреча · 04:05» for a meeting line, the requirement's id. A chip opens the material in Материалы, the meeting at that line, or the requirement. The composer has «Только материалы «в контексте»» (on by default, remembered; meetings and requirements are always searched) and says where the question goes: «Без интернета, ничего не отправляется наружу» for the local model, «Вопрос и найденные фрагменты отправляются в Claude» otherwise. ⌘J (the hotkeys map's `ask`) opens it with the cursor in the composer. A project with nothing to search shows an empty state.
- **«Сделай из этого вопрос для клиента»**: when you ask for a client question, the answer also creates a Q requirement (pending, in Требования) whose evidence quotes the sources it rests on, and says «Создано Q-9» with a link.
- **History** in the right column, grouped Сегодня / Вчера / Раньше: a click shows the answer again with its chips, × removes it. It is kept in the project (and in project exports).
- **How it answers.** The question is embedded by the local index and compared with the chunks of the project's materials (only those «в контексте» with the switch on), the meeting windows and the accepted and pending requirements; the best `tuning.retrieve_k` (12) become numbered sources, and up to four keyword (FTS5) hits add exact terms the vectors missed. Without the index model only the keyword search runs and the status line says so. The prompt is the new built-in skill **Спросить** (`skills/ask`, editable and replaceable per project like the recap skills); the app adds the fixed part: a `[Источник N]` / `[Source N]` marker after every claim, «Не нашёл в материалах проекта.» when nothing fits, and the `create_question` intent. The model is the project's provider: a «Только локально» project uses the local model only, and without a ready provider the same setup error as for summaries comes back.
- **Answers to questions heard in a call** (setting `live_questions`, off by default; through `/settings`, no UI yet). While a meeting is recorded, every live window the new lines are checked: a line that ends with «?» or starts with кто / что / как / когда / где / почему / сколько / какой / какая / какие (who, what, how, when, where, why, which) and has at least six words. When a material «в контексте» is close enough (cosine above 0.5), the model answers in two sentences with one source, and the dark card «В разговоре прозвучал вопрос» appears bottom-left on the meeting page with «Добавить в заметки» (appends «- Вопрос: … — ответ: … (источник)» to the notes) and «Скрыть». One card at a time, the newest wins, gone after 60 seconds. It runs in its own thread, skips a turn while busy, logs its errors and never touches the audio or the recording.
- API: `POST /api/projects/<id>/ask {question, context_only}` → `{job}`, the job's result `{answer, citations: [{n, entity: material|segment|atom, entity_id, locator, title, start?}], created: {atom_id, label, statement} | null, sources_used, elapsed, indexed, model, id}`, partial text in the job while it runs as for `/summarize`; `GET /api/projects/<id>/ask/history?limit=50` → `{items, searchable, indexed}`; `DELETE /api/ask/<id>`; `GET /api/sources/<id>/live` adds `question: {id, text, answer, citation} | null`; `POST /api/sources/<id>/live/question/dismiss {id}`. Settings gain `live_questions`. Schema v9 part 6: `ask_history`.

## 4.9.8 (2026-10-15): Index, graph, labels that assign themselves

- **A local index.** Materials, meeting lines and requirements are embedded on this computer by a small multilingual model, Qwen3-Embedding-0.6B (GGUF Q8_0, 639 MB, pinned to a Hugging Face revision and SHA-256 like the chat models). It downloads through the same installer (`/api/local-llm` lists it under `embed_models`; `POST /api/local-llm/download {model: "qwen3-embedding-0.6b"}`) and runs in a second llama-server (`--embedding --pooling last`) on its own private port, started on demand and stopped after 15 idle minutes, so it never evicts the chat model. Materials are cut into ~800-character chunks between sentences, meetings into ~600-character windows of lines, accepted and pending requirements by their statement; what is already embedded with the same text is skipped. Nothing leaves the machine.
- **Indexing is a job** («Индексирую» in the status chip, with progress), one at a time and at most one waiting per project. It runs after a material is added, after a meeting's transcript is saved and after requirements are added; «Переиндексировать» in the material's Ещё menu re-embeds that one from scratch.
- **Граф**, now the default view of Материалы (the last view is remembered): materials as nodes coloured by their first label, a line between materials that are similar in meaning (best pair of chunks above `tuning.graph_edge`, 0.30; at most 5 per material), the selected material and its lines highlighted, a click selects, + / − / centre, the legend of the labels shown. Over 200 materials it shows the 200 best connected and says so.
- **«Похожие материалы»** in the panel: the five closest materials with their similarity in percent (the same number as the graph's line). **«Где используется»**: the requirements whose evidence quotes the material and the documents whose latest version cites them, each a link.
- **Labels that assign themselves.** «Создать и назначить» puts the label on the selected material and on every material whose best chunk is within `tuning.label_assign` (0.45) of it; without a selected material, on the five closest to the label's name (above 0.35). The toast counts them: «Метка «дилеры» назначена: 5 материалов по смыслу». Automatic labels show «авто» with the similarity in a tooltip. A new material gets every label whose centroid (the mean of its members, refreshed on every change) is close enough. Taking an automatic label off leaves a tombstone, so it is never put back, even when the label is deleted and created again with the same name; labels put on by hand are never changed by automatic runs.
- **Without the model** import, labels by hand and keyword search work as before; the graph, «Похожие материалы» and the create-label hint offer «Скачайте модель индекса» with a download button.
- API: `GET /api/materials/<id>/related` → `{related: [{id, title, ext, kind, score}], available, model, size}`; `GET /api/projects/<id>/materials/graph` → `{nodes: [{id, title, ext, kind, label, color}], edges: [{a, b, w}], truncated, available}`; `GET /api/materials/<id>/used-in` → `{atoms, documents}`; `POST /api/projects/<id>/index {material_id?}` → `{job_id}`; `POST /api/projects/<id>/labels` adds `auto: [{id, score}]` and `index`; material imports return `index_job`. Settings gain `embed_model` and `tuning` (`label_assign`, `graph_edge`, `retrieve_k`; settings.json only). Schema v9 part 5: `material_chunks`, `source_embeddings` (float32 little-endian), `labels.deleted_at`; project exports leave vectors out.

## 4.9.7 (2026-10-15): Материалы

- **Материалы** (`#/library`, `#/library/<id>`) replaces the placeholder: documents, links and pasted text of the project. The left column filters by kind (Все материалы · Файлы · Ссылки · Заметки) and by label, with counts; the middle card shows the materials as a list (Имя with a type badge · Метки · Изменён · Размер · Контекст) or as tiles; the right panel shows the selected material: type, size, date, the first 1,200 characters of its text, its labels, «Включать в контекст ИИ», and Открыть (the library's copy of the file in its app on the desktop, the text in a sheet otherwise), Показать в Finder, Ещё → Извлечь требования / Удалить (with undo). The graph view, «Похожие материалы» and «Где используется» say «в следующем обновлении».
- **Adding**: «Добавить» (and the same four buttons above the list): Файлы (.docx, .pdf, .md, .txt, .rtf, .html, .eml, read with the extractors text sources already use), Ссылка (fetched once, 10 s timeout, the page's readable text kept; «Загрузить заново» in Ещё), Вставить текст, Импорт папки (a path; hidden files skipped, at most 200 files, as a job with progress). Dropping files or a link anywhere on the window adds them while Материалы is open. Files are copied to `<data>/library/<project>/materials/<id>.<ext>`; the original is never touched. In a «Только локально» project a link is saved with the error «offline» and never fetched.
- **A material is a source** of kind `material` (its paragraphs are segments without timestamps), so extraction, evidence and the audit log work on it unchanged. Встречи and the project status never count materials; a requirement's evidence from a material, and `#/source/<id>` of a material, open it in Материалы.
- **Labels**, by hand for now: «Создать метку» names a label, gives it the next colour of the palette and puts it on the selected material; «+ метка» in the panel adds an existing one, × on a chip takes it off. A click on a label in the left column filters the list. Assigning labels by meaning comes with the index in the next update; the store already keeps a removed automatic label as a tombstone so it is never put back.
- **Keyword search** across the project: the field in the header finds meeting lines, meeting notes, materials and requirements (every word, as a prefix, any case or script) and groups the hits under it, with the matching words marked; a hit opens the meeting at the line, the material or the requirement.
- API: `GET/POST /api/projects/<id>/materials` (`?kind=&label=&q=`; multipart `files`, or `{url}`, `{text, title}`, `{folder}` → job); `GET/PATCH/DELETE /api/materials/<id>` (`?full=1` for the whole text; PATCH `title`, `in_context`; DELETE is undone by `POST /api/sources/<id>/restore` or `/api/materials/<id>/restore`); `POST /api/materials/<id>/resync`, `/open`; `GET /api/projects/<id>/search?q=&limit=` → `{hits: [{entity: segment|note|material|atom, id, title, snippet, …}]}`; `GET/POST /api/projects/<id>/labels` (`{name, seed_material_id?}` → `{label, assigned}`), `DELETE /api/labels/<id>`, `POST/DELETE /api/materials/<id>/labels/<label_id>`. `/api/projects/<id>/sources` leaves materials out. Schema v9 part 4: `materials`, `labels`, `material_labels` and the FTS5 table `search`, filled once from existing meetings, notes and requirements on the first start; project export and import carry materials and labels.

## 4.9.6 (2026-10-15): Requirements while recording, auto-stop on silence

- **Requirements on the fly.** While a meeting is recorded, «Требования на лету» under the notes lists the requirements found in what was just said: type, statement, speaker · time · quote, and a checkbox that accepts the requirement at once (through the atom's own endpoint). The «1 новое» / «6 новых» tag counts what came in since you last looked at the block; it clears when the block scrolls into view or is clicked. «Все →» opens the meeting's requirements. After stop the block becomes «Требования из встречи», as before.
- **How it works.** Every 90 seconds (`live_window_atoms`), when at least 4 new lines reached the live transcript, those lines go through the normal extractor with the project's skills, with the 10 lines before them as context only; what it finds is saved as pending requirements marked `live`, with quotes checked against the lines they came from, and compared with the project's requirements by the usual duplicate check. It runs only when the project's AI is set up and `live_requirements` is on (the default). It runs in its own thread, never waits for or blocks the live transcript, skips a turn while the previous pass is still running, and logs its errors; it never touches the audio or the recording.
- **After stop** the final extraction runs over the whole transcript as before. Requirements found live are kept even when the final pass does not find them again (they are yours; a re-extraction keeps them too); their quotes are looked up again by text in the final transcript and point at the final lines, and a requirement whose quote is gone is marked «цитаты нет в итоговом транскрипте» (`stale_evidence`). A requirement the final pass finds again is folded into the live one by the usual duplicate check, so you never see it twice.
- **Auto-stop on silence.** After `silence_stop_minutes` (default 10; 0 turns it off) without speech on either channel, paused time not counted, the recording stops through exactly the same path as the Stop button (the meeting is finalised and transcribed, every WAV kept), and a system notification says «Запись остановлена: тишина 10 минут» / «Recording stopped after 10 minutes of silence» in the interface language. The HUD says «Остановлено: тишина» with «Открыть встречу», the meeting page says it while the meeting is processed, and after two silent minutes the audio pill counts down: «Тишина 2:00 · остановка через 8:00». The silence watch reads the channel files read-only, like the live transcript.
- API: `GET /api/sources/<id>/live?atoms_after=<ts>` adds `atoms: [{id, type, statement, status, quote, segment_idx, start, speaker, live, stale_evidence, created_at, new}]` (newest first), `silence`, `silence_stop` and `stopped: {reason, minutes, job_id}`; `GET /desktop-record/status` adds `stopped`; `POST /desktop-record/start` accepts `lang`. Settings `live_requirements`, `live_window_atoms` and `silence_stop_minutes` round-trip through `/settings` (no UI yet). Schema v9 part 3: `atoms.live`, `atoms.stale_evidence`.

## 4.9.5 (2026-10-15): Live transcript while recording

- **A meeting from the first second.** «Записать встречу» creates the meeting at once («Встреча 15.10.2026, 11:30», in the interface language) and opens its page; in Встречи the row says «Идёт запись» with a red dot. The microphone and system audio are written straight into the meeting's folder, so nothing is moved when the recording ends. Stop finalises the same meeting (mixed.wav for playback, as before) and starts the full transcription on it.
- **The transcript while you talk.** Every 15 seconds the new audio of each channel is read from mic.wav and sys.wav (read-only, by byte offset; the files are never locked, moved or rewritten), cut at the last pause, recognised with the GigaAM model you transcribe with (batch size 1, GPU memory released after each pass) and added to the page as provisional lines (lighter text) with Микрофон / Собеседники and times from the start of the recording. The page polls every 2 seconds, follows the newest line while you are at the bottom, and ends with «Слушаю…». After stop the full transcription replaces every provisional line.
- **When the machine cannot keep up**, the window doubles (up to a minute); if it still cannot, live mode turns off and the page says «Транскрипт появится после остановки». Any error in the live pass does the same; the recording itself is never affected. Without an installed speech model, or with the `live_transcription` setting off, live mode is off from the start.
- **Pause and resume**, in the meeting page's audio pill (Идёт запись · pause · stop, with level bars and the timer) and in the recording HUD elsewhere. While paused the recorder keeps writing silence, so times stay continuous; the paused spans are reported and skipped by the live pass; the page says «На паузе — звук не пишется».
- **A crash or quit mid-recording** leaves mic.wav and sys.wav untouched; at the next start the meeting becomes «Без расшифровки» with «Расшифровать».
- API: `POST /desktop-record/start {title, model, device, …}` → `{source_id, live}`; `POST /desktop-record/pause` and `/resume`; `GET /desktop-record/status` adds `source_id`, `paused`, `pauses`, `live`; `POST /desktop-record/stop {model, device, …}` finalises the meeting and returns the job in `X-Job-Id`; `GET /api/sources/<id>/live?after=<idx>` → `{segments, recording, paused, elapsed, live: on|off|catching_up, listening}`. Schema v9 part 2: `segments.provisional`.

## 4.9.4 (2026-10-15): Meeting page with notes and recap styles

- **The meeting page** (`#/meeting/<id>`; `#/source/<id>`, `…/seg/<idx>` and `…/summarize` still open it) is a header card (back to Встречи, the title renamed in place, date · kind · model, «Ещё» with the save-audio items) and two cards. **Транскрипт**: Микрофон / Собеседники chips for two-channel recordings (the speakers' names otherwise; renaming stays in Участники), a search that highlights hits and counts them («2 из 5»; Enter / ⇧Enter step through), Все реплики / С требованиями, lines with time · speaker · text, the quoted spans and requirement chips; a click on the time plays from there, double-click corrects the line, the player stays at the bottom.
- **Заметки**: Markdown notes per meeting with a format bar (B, I, H, •, 1., ☐, ⌘B / ⌘I), saved by themselves a second after you stop typing («Сохранено в 14:02»), with a preview. Under them, «Требования из встречи»: the meeting's requirements with their type, statement and quote. The Встречи panel's Заметки tab shows the notes rendered, with «Редактировать».
- **Recap styles**: Кратко / По пунктам / Действия, in the meeting's inspector and in the panel's Резюме tab. Each style is a built-in skill (Скиллы → Резюме: кратко / по пунктам / действия), editable like any other. «Обновить по новым репликам» sends the previous recap and only the lines said since, and asks the model to update it; it is enabled only when there are such lines. «Пересобрать» sends everything. A style with no recap yet gets one when you switch to it; the chosen style is remembered per meeting.
- API: `PUT /api/sources/<id>/notes {text}` and `POST /api/sources/<id>/notes/append {line}` → `{saved_at, text}` (both in the audit log; autosaves within a minute share one entry); `POST /api/sources/<id>/recap {style, incremental}` → a summarize job; `GET /api/sources/<id>` returns `notes`, `recap_style` and `summaries` by style with `through_idx`, plus the old `summary` field for the current style. `/summarize` keeps working and writes the Кратко recap.
- Schema v9: `sources.notes`, `sources.recap_style`, `summaries.style` (existing summaries become Кратко), `summaries.through_idx`; one summary row per style. Project export and import carry them; 4.9.3 project files still import.

## 4.9.3 (2026-10-15): Встречи

- **Встречи is the home page.** It replaces the Sources and Overview screens; the old `#/sources` and `#/overview` addresses open it. The header says «<project> · n встреч · n требований», with «Импорт» (⌘O, or drop files anywhere on the window) and «Записать встречу» (the microphone and recognition options are behind the arrow next to it; the consent question and the stop button live here).
- **The pipeline strip**: Встречи · Требования · ТЗ vN · Бэклог · Jira, each with its ring and its state in words (the same wording the overview had); a click opens that screen, and the chip the next step points at is outlined.
- **The meeting list**: search over titles and the text of every meeting (a word that only appears in the transcript finds it), sort Новые / Старые / А–Я, rows with an icon by kind, date, duration, people, a Запись / Импорт / Текст tag, the state (Разобран, Распознаю · n%, Без расшифровки, Ошибка with the reason on hover) and the requirement count. Double-click or Enter opens the meeting.
- **The details panel**: the title is renamed in place (click it, Enter saves); tabs Резюме (the summary, its [mm:ss] references open the meeting at that line, «Сделать сводку» / «Обновить»), Транскрипт (read-only, with the quoted spans, requirement chips and a search that highlights and counts hits), Заметки (next update) and Требования. «Открыть встречу», «Требования · n» and «Ещё»: save audio, extract requirements, rename, delete with undo. Narrow windows hide the panel.
- `GET /api/projects/<id>/sources` takes `q` (case-insensitive in any script) and `sort` (`new`, `old`, `az`), and every row carries `people`, `atoms` and `tags`.
- On first start the interface language follows the system (Russian for ru-*, English otherwise); the choice in Settings wins afterwards.

## 4.9.2 (2026-10-14): Status chip and hotkeys

- **A status chip in the top bar says what the machine is doing.** While a call is recorded: «Идёт запись · 12:04» with a red dot, and a click opens Встречи, where the recording controls are. While something runs: the first job with its progress ring («Распознаю · 42% · 1 задача», «Извлекаю требования… · 2 задачи», model downloads with their size). Otherwise «Готово». A click lists every job with its progress and running time; model downloads can be cancelled from there. It checks every 2 seconds while something runs and every 15 seconds otherwise.
- **`GET /api/jobs`** lists running and queued jobs (transcription, summary, requirement extraction, document, backlog, Jira, skill tries), the speech-model and built-in AI model downloads, and the recorder state. Every job now carries a kind and a label.
- **Shortcuts come from one map in the settings** (`hotkeys`): ⌘R record (app window only; in a browser ⌘R still reloads), ⌘K commands, ⌘⇧L theme, ⌘J Спросить, ⌥Space Шепнуть, ⌘1…⌘8 the rail sections. There is no screen to change them yet; the tooltips and the command palette show the keys from the map.
- At phone width the Sources screen no longer shows a second round record button under its header. The transcript title no longer repeats the «Источники ›» crumb; the back link above the title does that.
- The e2e stand-in server stubs torch and speech recognition itself, so it runs from the project's `.venv` without the ML stack.

## 4.9.1 (2026-10-14): New shell

- **A navigation rail replaces the sidebar.** On the left: the Dictum mark, the record button (⌘R in the app window), then Встречи, Материалы, Требования, Документы, Бэклог, Спросить, Шепнуть and Настройки at the bottom; ⌘1…⌘8 follow that order. Скиллы and Выгрузка are under «Ещё» and in the ⌘K palette. Требования shows how many requirements wait for review, Документы gets a dot when a document is out of date. Материалы, Спросить and Шепнуть say what is coming; they arrive in the next updates. Встречи still opens the Sources screen for now.
- **A top bar and a page header.** The project chip at the top switches projects, creates or opens one, lists the archive and shows whether the project is local only (⌘⇧P). The theme toggle (⌘⇧L) and help (the command palette) sit on the right. Every screen has a large title with its status line and actions, and its content sits in a rounded card.
- **A tonal theme, light and dark.** Softer surfaces, rounder corners and new colours from the 5.0 design, on every screen. Dark follows the system, or the choice in Settings.
- **Inter.** The interface uses Inter (variable, Cyrillic included), bundled with the app; nothing loads from the network.
- Phone-width windows (≤ 760 px) get a bottom bar with five sections, and the record button moves into the page header.

## 4.9.0 (2026-10-14): Dictum

- **The app is now called Dictum.** It was Requirements Workbench up to 4.2. The Mac app is `Dictum.app` (bundle id `com.heidurrus.dictum`), the downloads are `Dictum-<version>-macos-arm64.dmg` and `Dictum-<version>-Setup.exe`. This is the first pre-release of 5.0.
- **Your data moves by itself.** On the first start the `RequirementsWorkbench` data folder (`~/Library/Application Support` on macOS, `%LOCALAPPDATA%` on Windows) is renamed to `Dictum`, before anything can record, so projects, recordings, settings, the runtime and the downloaded models are all kept and nothing downloads again. A `migrated-from.txt` inside notes where it came from. If a 4.x copy is still running, or the folder cannot be moved, the app keeps using the old folder and tries again on the next start. If both folders exist, neither is touched.
- Because the bundle id changed, macOS asks again for microphone and system audio access on the first recording. On Windows the old Start menu and desktop shortcuts are replaced.
- Project exports are written as `dictum-project`; files exported by 4.x still import. `DICTUM_DATA_DIR` overrides the data folder (`WORKBENCH_DATA_DIR` still works).

## 4.2.2 (2026-10-14): Icon, final colours

- The icon is blue with white bars, and the three text lines are the same length.

## 4.2.1 (2026-10-14): App icon

- The Mac app has an icon: three bars of sound that become three lines of text (`docs/design/icon/`). The app was shipping with the generic macOS icon.

## 4.2.0 (2026-10-14): Bigger built-in models

- **Three more models in Settings → AI**: Qwen3.6 35B-A3B (a mixture-of-experts model, about 3B parameters active per token, so it runs fast and is the recommended choice on a 32 GB Mac), Qwen3.8 27B (the strongest answers of the list, a dense model and several times slower), and Qwen3.5 9B (a step up from the 4B on 16 GB machines). Files are pinned to a revision and verified by checksum like the others. The 35B and 27B need 32 GB of memory; on a 16 GB Mac they are listed as "not enough memory" and Gemma 4 12B stays the recommendation.

## 4.1.1 (2026-10-09): Save a source's audio

- **Save audio…** on the Source screen's "Ещё" menu and in the Sources list inspector. A recording offers both sides mixed, your microphone and the other side as separate files; an import offers the file you dropped in, under its original name. Works for recordings that are not transcribed yet.

## 4.1.0 (2026-10-07): Speech models in Settings, and long recordings no longer eat the Mac's memory

- **Settings → Запись и распознавание lists every GigaAM model**: what is on disk (with its size), what is not, which one is recommended and which cover languages other than Russian. Download with a progress bar and cancel; delete to free disk space. Downloads are verified by checksum before they replace anything, so a cut-off download no longer leaves a damaged model and "model checksum failed" at the next transcription.
- **Long recordings on the Apple GPU** used to grow the app to 19 GB on a 16 GB Mac, because PyTorch keeps every GPU block it has allocated and the chunks came in a thousand different lengths. The app now releases the GPU cache after every batch and groups chunks by length. The same applies to transcription with speaker separation.
- The "is this file long?" check reads the WAV header instead of loading the whole recording onto the GPU first.
- Progress during a long transcription now shows the segment count ("Transcribing segments… 120/365").

## 4.0.6 (2026-10-07): Progress for a transcription started from the Source screen

- "Распознать" on the Source screen started the job without the progress card in the sidebar or the percentage on the screen. It now goes through the same tracker as the Sources screen.

## 4.0.5 (2026-10-07): Speaker separation on the Apple GPU, and re-runs

- **Transcription with speaker separation failed on the GPU** after the first channel with "Inference tensors cannot be saved for backward". The second channel's model run had autograd on; it now runs in inference mode like every other transcription.
- **Pressing Transcribe again replaces a request that is still waiting** instead of queueing behind it. A transcription that is already running cannot be stopped; the app says so, and quitting the app stops it.
- Failed jobs write their full traceback to `logs/jobs.log` in the app's data folder.

## 4.0.4 (2026-10-06): A transcription cut off by a restart no longer looks like it is still running

- Jobs do not survive quitting the app. A source that was being transcribed at that moment stayed marked "in progress" forever, with no way to start it again. On start the app now puts such a source back to "not transcribed" (or "failed" if its audio was never saved), so the Transcribe button is there.

## 4.0.3 (2026-10-06): Long recordings failed with "torchcodec is not available"

- Recordings and audio files longer than about 25 seconds are split by voice activity detection before transcription. GigaAM handed the audio *file* to pyannote for that, and since torchaudio 2.9 that needs torchcodec, which fails without FFmpeg's shared libraries. The app now decodes the audio with its own ffmpeg and hands pyannote the waveform, as it already did for speaker separation.

## 4.0.2 (2026-09-30): Source screen opened empty

- **Source:** when a requirement had two quotes on the same transcript line, the screen failed to render and showed neither the transcript nor the summary. A line now lists each requirement once, and the page no longer depends on the IDs being unique.

## 4.0.1 (2026-09-30): Filter counts match the list

- **Requirements:** the counts on "На ревью / Принятые / Отклонённые / Конфликты / Все" and in the type menu ignored the source filter and the search, so a tab could say 77 and show nothing. Each count is now the number of rows that choice shows.
- When nothing matches, the empty state names the filters that are on (source, type, search, status) and one button clears them all.

## 4.0.0 (2026-09-29): New interface

The whole interface is rebuilt from a new design (`docs/design/redesign.md`, prototype in `docs/design/prototype/`). The pipeline, the data and the API are the same.

- **Panes instead of one scrolling page.** Every screen is a toolbar plus panes that scroll on their own: content, an inspector for the selected item and, on wide windows (workspace from 1800 px), a context pane with the source. Pane widths are proportions of the window, so a large monitor shows more information, not more empty space.
- **Sidebar shows the state of the pipeline in words**: "75 на ревью", "устарел", "11 историй", "5 из 14", each with a stage ring. Recent sources and all documents are one click away. Running jobs show in a card at the bottom.
- **New Overview screen**: the one next step, the pipeline, what waits for the client, requirements by type, what changed since last time.
- **Select, then act.** Row actions are no longer bare icons: the inspector has labelled buttons with their keys printed on them (Принять A, Отклонить X, Править E).
- **Requirements** (were "Атомы"): conflicts are a filter and a card in the inspector; editing happens in the inspector; the type is a dot and a code (FR-12, BR-3).
- **Sources**: a table with a preview; the whole window takes dropped files and imports them at once; recording continues while you work on other screens, with a pill on every screen.
- **Source**: transcript, summary and the source's requirements side by side; quotes are marked in the text; search; a player bar with speed.
- **Documents**: contents and versions on the left, the page in the middle, Качество / Изменения / Сведения on the right; `[` and `]` walk the findings.
- **Backlog** (was "Декомпозиция"): one line per item; the story, its criteria and INVEST findings are in the inspector.
- **Export**: one place for Jira, Word, the traceability table and the letter to the client.
- **⌘K** finds any screen, source, document, requirement or command.
- **Shortcuts work on the Russian keyboard layout.**
- "Атом" is now "требование" everywhere in the interface.
- Small API addition: `GET /api/projects/<id>/atoms` returns `rid`, the ID a requirement already has in documents.

## 3.3.3 (2026-09-29): Wide windows

- **Source screen:** the summary panel was fixed at 340–500 px, and the transcript was capped at 72 characters per line inside a card that stretched across the window, which left a large empty area. From 1400 px up, the two panels now split the width about 55/45, and the transcript runs up to 100 characters per line.
- **Atoms screen:** from 1800 px up, the inspector grows with the window instead of staying at 380–460 px.

## 3.3.2 (2026-09-29): Skill download button

- The skill header's download control was a bare icon next to the "Make a copy" button, with no label. It is now a labelled "Export .zip" button, and its tooltip says what the file contains.

## 3.3.1 (2026-09-29): Re-type old atoms

- **"Уточнить типы" / "Refine types" on the Atoms screen.** Atoms extracted before 3.3 could only be functional, NFR or question, so every ID came out as FR, NFR or Q. The button re-reads accepted and pending atoms and moves the ones that fit to business (BR), risk (RSK) or as-is (AS). Wording is not changed, and one Undo reverts the whole pass. When a project has no atoms of the new types, a banner suggests the button.
- Documents still titled "FRD — …" from before 3.2 are renamed "SRS — …".

## 3.3.0 (2026-09-29): Each document takes its own requirements

- **Requirements go to the document that needs them.** Atoms have three more types, and extraction finds them:
  - **бизнес** (business requirement, BR-n)
  - **риск** (risk, RSK-n)
  - **как есть** (a fact or problem of today's process, AS-n)

  Each document type declares which atom types it holds and which it only reads for context:

  | Document | Holds | Reads for context |
  |---|---|---|
  | SRS | FR, NFR, questions | BR |
  | BRD | BR, NFR (constraints), questions | FR, risks |
  | Vision & Scope | BR, FR, NFR, questions | risks |
  | Risk register | risks: one table row per risk, nothing invented; questions | requirements |
  | As-Is / To-Be | AS facts, questions | FR/NFR/BR, cited in the To-Be |

  A change to a BR marks only the BRD out of date, not the SRS. The document's tab shows what it takes and reads.
- **"В декомпозицию"** (into the backlog): a per-document switch; the type sets the default (SRS and GOST yes, the others no). The backlog is built from all documents marked this way and says which ones. Jira descriptions and the traceability matrix name each requirement's own document. Business requirements from a BRD marked for decomposition become stories too.
- **Delete any document** with the × on its tab or from the "…" menu; a project keeps at least one.
- The empty state of a document counts only the atoms it can use and says which types are missing.

## 3.2.0 (2026-09-29): Document types, skills in your language, wide screens

- **Several documents per project, of real BA types.** "FRD" is gone as a concept. The **Документы** (documents) screen has one tab per document and **＋ Документ** to add one of these types:
  - **BRD** — business requirements: business context, goals and success metrics, stakeholders (a table), scope, business requirements, constraints.
  - **SRS** — functional and non-functional requirements. This is the old FRD; existing projects keep their document.
  - **Vision & Scope** — background, vision statement, objectives, stakeholders, major features, a scope-of-releases table.
  - **Реестр и матрица рисков** (risk register and matrix) — a risk table with R-n IDs (probability, impact, response, owner, related requirements) and a probability × impact matrix built from it.
  - **Текущее и целевое состояние** (As-Is / To-Be) — today's process, pain points (a table), the future process with requirement IDs, a gap analysis table, the transition.
  - **ТЗ по ГОСТ 34** (technical specification, GOST 34 style).

  Each document has its own versions, sign-off, quality check and export (Word and Markdown include the tables). Narrative documents also use the source summaries. A document's type can be changed, and your own types are skills you copy and edit.
- **Tables in documents.** A document type's section can be a table (`format: table`, `columns: …`), with automatic row IDs and a heat map.
- **Skills in the interface language.** Built-in skills have Russian and English titles and descriptions; you see the ones matching the app language. Editing a two-language skill changes the language you're working in.
- **Clearer "where it's used".** A skill says whether this project uses it (chosen for the project, or the default) and what the other projects use. The buttons are "Использовать в этом проекте" (use in this project), "Вернуть общий выбор" (back to the default) and "Сделать по умолчанию" (make it the default). Document types instead offer "Создать документ этого типа" (create a document of this type).
- **Big and wide screens.**
  - Content grows with the window.
  - On very large displays the whole UI scales up.
  - Atoms get an inspector pane: the selected atom's quote in context from the transcript, its facts, actions and history.
  - Transcript and Document use the width.
- The backlog, Jira and the traceability matrix read the requirements from the document that has them: the first one, or else the newest SRS or BRD.

## 3.1.0 (2026-09-29): After the product review

Acts on the whole product review in `docs/product/pm-review.md`. Item-by-item status and the decisions taken on its open questions are in `docs/product/implementation.md`.

- **Jira stays in sync after changes.**
  - Rebuilding the backlog keeps each story's link to its Jira issue, so pushing again updates the issues instead of duplicating them.
  - Issues whose requirement disappeared are listed as orphans. The app never deletes anything in Jira.
  - A change to an atom now shows downstream: the document, the backlog and the Jira step turn amber, and the Jira ✓ only means Jira matches.
  - A new per-project setting, **Что уходит в Jira** (what goes to Jira), controls quotes. "Local only" projects send references, not the client's words.
- **Conflicts and questions.**
  - "Все атомы разобраны" (all atoms reviewed) says when a conflict is still open.
  - Bulk **Принять** (accept) leaves atoms in a conflict for review.
  - Accepting a question no longer closes its conflict. Questions go open → asked → answered, and the answer can settle the conflict.
- **Для заказчика** (for the client), a new tab on Atoms: open questions, action items from the calls (no longer thrown away) and **Письмо заказчику** (email to the client).
- **Review at scale:**
  - search and grouping, with filters remembered per project
  - reject reasons ("вне рамок" / out of scope feeds FRD section 5)
  - MoSCoW priority on keys 1–4, pushed to Jira as a label
  - **＋ Атом** for your own requirements
  - a history per atom
- **The app learns from review:** repeated rejects and rewrites become a suggested rule for the project's extraction skill. **Уточнить…** (refine) gives a one-off instruction to an extraction, a document build or a backlog build.
- **Capture:**
  - a setup checklist
  - **Дальше: …** (what's next) and "since last time" on Sources
  - multi-file import
  - a consent reminder before recording
  - requirements extracted automatically after a recording is transcribed, with an ETA and a notification
  - progress text in the interface language
- **Transcript:** lines that became atoms are highlighted. A line can be corrected: the original is kept, and quotes that no longer match are flagged. **Скопировать как письмо** copies the summary as a recap email.
- **Document:**
  - clearer **Обновить изменённое** (update what changed) and **Пересобрать весь документ…** (asks first)
  - **Исправить всё и обновить** (fix all and update)
  - version sign-off (Черновик / На согласовании / Согласовано), with change requests against the approved version
  - Jira keys on requirements
  - export to Markdown and a traceability matrix (XLSX)
  - loading the client's reviewed .docx back as a source
- **Projects:** save a whole project as one file and open it on another computer. The default project is now "Мой проект".
- **Other:**
  - "Транскрипт" is no longer a pipeline step (⌘1–⌘5).
  - Undo lasts at least 10 s, and ⌘Z undoes the last action.
  - Settings offers a way back to where you came from.

## 3.0.0 (2026-09-28): New design

A redesign of every screen, following `docs/design/`. All features and shortcuts stay where
they were.

- **Look:**
  - System fonts, a quieter neutral palette and higher text contrast (WCAG AA throughout).
  - A proper **dark theme**. The primary button is now readable in dark mode.
  - **Theme** switch in Settings, or **⌘⇧L**.
- **Sidebar:**
  - Step icons and **badges**: atoms to review, document version (amber when out of date),
    items marked for Jira, a check after a push.
  - Collapses to an icon rail on narrow windows. **⌘\** toggles it, **⌘1–⌘6** jump to a step,
    **⌘,** opens Settings.
- **Toolbar:** every screen has one sticky toolbar with the title, its state and the next step.
- **Atoms:**
  - Conflicts are a one-line summary that expands in place.
  - Status filter is a segmented control; type filters are chips.
  - The focused atom (accent bar) looks different from ticked atoms (tint).
  - Row actions appear on hover.
  - The bulk bar floats at the bottom and never covers the last row.
- **Document:**
  - Reads like paper. Requirement IDs hang in the margin, and sources are chips that open
    the transcript.
  - Quality findings sit next to the text.
  - Contents and versions are in a sticky side column.
- **Decomposition:** a tree with Jira-style type glyphs, collapsible epics and stories,
  acceptance criteria as a Given / When / Then table, and INVEST findings inline.
- **Выгрузка:**
  - A three-step header.
  - The preview is a table with a sticky push bar.
  - Pushing asks for confirmation in a dialog that lists the site, project and counts.
    **⌘↵** opens it and **Esc** cancels.
- **Skills:** the editor has tabs (Инструкции · Разделы/Правила/Шаблон · Попробовать ·
  Контракт · История), with a floating save bar.
- **Settings:** a grouped form, one setting per row.
- **Fixes:**
  - Toasts belong to the screen that raised them, stack (at most two) and move above the
    bulk bar.
  - AI setup errors (missing or rejected Anthropic key, model not downloaded…) now show in
    the interface language with an **Открыть настройки** button. The summary error is shown
    in place.

## 2.9.4 (2026-09-28): Delete atoms

- **Atoms can now be deleted**, not just rejected:
  - the trash button on an atom
  - **Удалить** in the bulk bar for everything ticked
  - the **Delete** / **Backspace** key

  Deleted atoms leave the list, the counters and the next document build. Open conflicts
  they were part of close. **Отменить** brings everything back, conflicts included, and every
  deletion is recorded in the audit log.
- Keyboard shortcuts on the Atoms screen keep working right after you tick a checkbox.

## 2.9.3 (2026-09-28): Jira sign-in asks which account

- **Подключить Jira** now opens the Atlassian sign-in in a **private browser window**
  (Chrome, Edge, Brave, Chromium or Firefox). A normal window silently reused whatever
  Atlassian account the browser was already logged into, e.g. a work account, and
  Atlassian's sign-in gives apps no way to ask for an account choice. In a private window you
  log in with the account you want. **в обычном окне** is still there if you prefer.
- The Выгрузка screen warns when the connected account can't see the site the project is set
  to push to.

## 2.9.2 (2026-09-28): Jira without the Keychain

- Connecting Jira no longer involves the macOS Keychain, which kept asking for access. You
  sign in in the browser as before, and the app keeps the sign-in in a private file in its own
  data folder (readable only by your user account, like the Anthropic key). **Отключить**
  removes it.
- Old Keychain entries named "RequirementsWorkbench.atlassian" are no longer used. You can
  delete them in Keychain Access, or just leave them.

## 2.9.1 (2026-09-28): Output language, Jira sign-in fix

- **Язык результатов per project** (Settings → Проект): Как в источниках / Русский / English.
  The AI writes summaries, requirements, the FRD, stories and criteria, and the labels in Jira
  descriptions in that language, translating from Russian or English sources. Quotes stay in
  the original language, because they're evidence. Switching the language rebuilds the whole
  document, and the Document screen tells you when it's in the other language.
- Fixed: connecting Jira failed with "403 … Error 1010". Atlassian's Cloudflare blocked
  Python's default user agent; the app now identifies itself. Found and fixed during a live
  push to a sandbox project.
- The Выгрузка screen shows which Atlassian sites the connection can access, so signing in
  with the wrong account (e.g. a work login remembered by the browser) is obvious.

## 2.9.0 (2026-09-28): Increment 4b, Jira export

- **A new Выгрузка screen (step 6).** It sends the ticked backlog to Jira Cloud through the
  Atlassian Remote MCP server.
  - **Подключить Jira** opens the Atlassian sign-in in your browser. The app registers
    itself; there are no keys to copy.
  - Sign-in tokens are kept in the macOS Keychain / Windows Credential Manager and refreshed
    automatically. **Отключить** removes them.
- **Choose the site and project** per workbench project. Issue types are mapped by what they
  are (epic level, sub-task flag), so localised types such as Эпик / История / Задача /
  Подзадача work. You can change the mapping.
- **A dry-run preview** with Создать · Обновить · Без изменений · Пропустить. It only reads
  Jira; nothing changes there until you press **Выгрузить N задач** and confirm the target
  project by name.
- **The push** creates epics first, then stories inside their epics, then sub-tasks under
  their stories. Each description carries the story, the acceptance criteria, the FRD reference
  (version · section · FR-n) and a verbatim source quote with date and time.
- **Safe to repeat:**
  - Every issue gets a `rw-…` label, so a retry after a failure finds issues already created
    instead of duplicating them.
  - Pushing again only updates what changed.
  - Issues edited in Jira since the last push are flagged and need an explicit tick to
    overwrite.
  - Failed rows are listed with the reason and can be retried.
- Only the fields the workbench owns are written: summary, description, labels, parent.

## 2.8.0 (2026-09-28): Increment 4a, decomposition

- **A new Декомпозиция screen (step 5).** **Собрать бэклог** turns the latest FRD into:
  - epics, each with the business goal it serves
  - user stories: "Как <роль>, я хочу …, чтобы …"
  - acceptance criteria in Дано / Когда / Тогда form, including negative cases
  - optional technical sub-tasks

  Every story links to its FRD section and requirement (FRD 3.1 · FR-2). Every functional
  requirement is covered; any the AI misses get a story of their own.
- **Tickboxes decide what goes to Jira.** Unticking an epic unticks its stories. AI-generated
  sub-tasks and non-functional requirements start unticked. An NFR can be moved into a
  story's criteria with one click.
- **Проверить по INVEST.** Each story is checked (Independent, Negotiable, Valuable,
  Estimable, Small, Testable), and problems come with a suggested fix you can apply.
- **Edit everything:** titles, story text, goals and criteria (add or remove), plus adding,
  reordering and deleting (with undo) epics, stories and sub-tasks. Edited items are pinned,
  so **Пересобрать** never overwrites them.
- When the document gets a newer version, the backlog tells you and offers to rebuild.
- Two new editable skills: **Декомпозиция на истории** and **Проверка INVEST**.
- The Document screen has a **К декомпозиции** link.

## 2.7.2 (2026-09-28): Action items are no longer requirements

- Extraction now tells **requirements** (what the system must do) apart from **action items**
  ("отправлю письмо", "Иван пришлёт выгрузку", "созвонимся в четверг") and other non-requirements
  (process, complaints without a stated need). Those are set aside instead of becoming
  functional requirements. The result shows how many action items were skipped.
- It still keeps real requirements that mention email when the *system* does it ("система
  отправляет клиенту письмо-подтверждение").
- Works with your own extraction skills too: the app's format contract now includes the two
  new labels. **Попробовать** in the skill editor lists what was skipped, so you can tune
  the rules.
- The built-in extraction skill has clearer rules and Russian examples of what is not a
  requirement.

## 2.7.1 (2026-09-28): Bulk review of atoms

- **Review hundreds of atoms at once.** Tick atoms (shift-click selects a range), or tick
  **Все (N)** to take everything matching the current filters. Then **Принять**,
  **Отклонить**, **На ревью** or **Сменить тип…** for all of them in one go, with one
  **Undo** for the whole batch. The bar shows how many of the selected atoms are in conflicts.
- **Source filter** in the atoms list, e.g. to accept everything from one email.
- Keyboard: Space ticks the current atom, ⌘A (Ctrl+A) ticks everything under the filters, Esc clears.
- Every change in a batch is still recorded in the audit log.

## 2.7.0 (2026-09-28): Increment 3b, skills

- **A new Скиллы screen.** Every AI step has an editable, shareable skill:
  - summary
  - requirement extraction
  - duplicates and conflicts
  - document assembly
  - quality check
  - fixes
  - the Word template

  Plus **house rules** (Общие инструкции) that apply to every step: terminology, glossary,
  tone ("always write 'заявитель', never 'клиент'").
- **Control the AI's output.** Write the instructions in your own words. The app adds a small,
  visible "format contract" (answer shape, verbatim quotes, never invent facts), so no edit can
  break the pipeline.
  - The document assembly skill decides the FRD's sections, their titles and order, and extra
    AI-written sections with their own instructions (e.g. a glossary).
  - The quality skill has editable vague-word lists and **your own checks** (e.g. "every
    functional requirement names a role").
- **Built-in skills** are read-only. **Сделать копию** gives you your own, with:
  - edit history and restore
  - **Попробовать**: run the unsaved draft on a real source or on the current project and
    see the result, without saving anything
  - delete with undo
- **Share skills.** Export a skill as a .zip and import a .zip or a single SKILL.md. The
  format is a folder with SKILL.md, like Anthropic's Agent Skills. Your skills are also plain
  folders you can open.
- **Global and per-project.** Choose the default skill for each step, and switch any project
  to a different one (e.g. GOST for one client, a lean FRD for another).
- **Word templates with your own layout.** Copy "Word — ГОСТ" or "Word — обычный", press
  **Открыть в Word** (or download it and upload it back), and design the document yourself:
  title page, logo, approval sheet, headers and footers, fixed text. Placeholders mark where
  content goes:
  - inline, anywhere including tables and headers: `{{title}}`, `{{version}}`, `{{date}}`
  - on their own line: `{{toc}}`, `{{body}}`, and single sections such as `{{section:functional}}`

  The Document screen's export lets you pick any Word skill.
- A new built-in **Сборка ТЗ по мотивам ГОСТ 34**: GOST-style section names and official
  wording.

## 2.6.0 (2026-09-28): Increment 3a, the FRD document

- **Build the FRD from accepted atoms.** A new **Документ** screen (step 4) turns the accepted
  requirements into a structured document:
  - sections: purpose, context and assumptions, functional requirements grouped into
    sub-sections, non-functional requirements, out of scope, open questions
  - each requirement worded formally, in the language of your sources
- **Stable IDs and sources.** Every requirement keeps its ID (FR-3, NFR-1, Q-2) across
  rebuilds, and IDs are never reused. It links to the exact places in your sources it came from.
- **Versions.** Every build is a new version. You can view older versions and compare any
  version with the previous one (added / changed / removed).
- **Stale sections and rebuild.** Changing, rejecting or adding an atom marks the affected
  sections as out of date. **Rebuild** rewrites only what changed and keeps everything else word
  for word. **Rebuild everything** is there when you want a fresh pass.
- **Quality check.** Requirements are checked for vague words ("быстро", "удобно"), missing
  metrics, ambiguity, several requirements in one, and untestable wording. **Починить**
  proposes a rewrite. You can edit it and apply it to the atom, or dismiss the finding.
- **Your own text.** Add pinned paragraphs to any section. They're kept verbatim through
  every rebuild.
- **Export to Word.** A standard template or a **GOST** one (title page, Times New Roman 14,
  1.5 spacing, GOST margins, page numbers), both with a table of contents. Each requirement's
  sources become footnotes: date, time, speaker and the exact quote.
- **Unresolved conflicts don't block the build.** The affected requirements are marked in
  the document.
- Fixed: saving files (transcript .txt, Word export) in the desktop app now opens a native Save
  dialog, with **Показать** to find the file. Downloads were switched off in the app window.

## 2.5.0 (2026-09-28): Built-in local model

- **A local AI model with one click, with nothing else to install.** Settings → AI → **Built-in**:
  press **Download** and the app fetches the model and its engine itself, with progress. It
  resumes if the connection drops and checks both files by checksum. From then on,
  summaries and requirement extraction can run on your computer, offline, and nothing
  leaves it.
- The app picks the model that fits your computer: **Gemma 4 12B** (6.5 GB, 16 GB of memory
  or more) or **Qwen3.5 4B** (2.6 GB, from 8 GB of memory).
- The model starts by itself when needed, runs on the Apple GPU or on any Windows GPU (with
  a CPU fallback), and stops after 15 minutes of idleness and when you quit, freeing the
  memory. It listens only on this computer, behind a private key.
- **"Local only" projects** now use the built-in model, with nothing to set up. If it isn't
  downloaded yet, the app tells you where to get it and never falls back to the cloud.
- Ollama stays available as a third option for those who already use it.
- **GPU-aware choice.** What decides speed is GPU memory, not just RAM. The app reads the
  graphics card and its memory (on a Mac, the shared memory), recommends the model that
  runs at full speed on it, and says plainly when a model would be slower or when there's no
  suitable GPU.
- If the app is force-quit or crashes, a model server left running is stopped on the next
  launch. It only ever stops its own server, identified by the exact port.
- Turning on **"Local only"** for a project when the model isn't downloaded yet offers the
  download right there.
- The rail shows the app version. A long summary scrolls on its own. Recording has a big
  record button, and the record and upload cards line up.

## 2.4.0 (2026-09-25): Increment 2, requirement atoms

- **Extract requirements from any source.** On a transcript, email or document, click
  **Extract requirements**: the AI reads it in parts (with progress) and returns small,
  testable **atoms**: functional, non-functional, or open questions.
- **Every atom has proof.** Each one carries an exact quote with time and speaker. Quotes
  are checked against the real text, and atoms whose quote can't be found are dropped.
  Click a quote to open the source at that line.
- **New Atoms screen** (step 3 in the rail): "N to review · A of T accepted", filters by
  status and type, accept / edit / reject with the keyboard (`j` `k` `a` `x` `e`) and
  Undo. Edited atoms keep their original wording.
- **Duplicates and conflicts across sources.** New atoms are compared with the project's
  existing ones. Duplicates are merged, and their quotes move to the existing atom.
  Contradictions are shown as conflicts: keep A, keep B, merge into one statement, or turn
  the conflict into a question for the client (answering it closes the conflict).
- Extracting again replaces only the atoms you haven't reviewed yet. Accepted and rejected
  ones stay.
- "Local only" projects extract with the local model. Every decision goes into the audit log.
- Libraries from 2.3.0 are upgraded automatically.
- **UI fixes:** a long summary next to the transcript now scrolls on its own, with its
  header pinned. Recording has a big record button with the microphone menu right under it,
  and the record and upload cards line up. The rail shows the app version instead of
  "local".

## 2.3.0 (2026-09-23): Increment 1 complete

- **Recordings use their separate channels.** Your microphone is transcribed as **You (BA)**,
  and the call audio as the other side (with speaker separation if it's on). Both are merged in
  time order, so you never need speaker separation to tell yourself apart. Short clips get
  accurate start times too.
- **Emails as sources:** `.eml` and Outlook `.msg` (read without Outlook). Subject becomes the
  title, and sender, recipients and date are shown; the body is shown as paragraphs.
- **Documents as sources:** earlier specifications, notes (`.docx`, `.pdf`, `.txt`, `.md`)
  without speakers or timestamps are kept as documents and shown as paragraphs, not as a
  fake transcript.
- Summaries know whether they're summarising a call, an email or a document.
- Speakers show as "You (BA)", "Other side", "Speaker 1, 2…" until you rename them.
- Libraries created by 2.2.0 are upgraded automatically.
- Fixed: an email to several recipients lost its "To" field.

## 2.2.0 (2026-09-23): Increment 1, source library (part 1)

- **Everything is saved.** Recordings, uploaded audio, imported transcripts and summaries
  are kept in a local library per project, with their files. Close the app and it's all
  still there. Deleting is recoverable (Undo).
- **Projects.** Create and switch projects from the top of the left rail, rename or
  archive them in Settings. **Local only** per project: its summaries always use the local
  model, never the cloud.
- **New multi-screen interface** (the prototype's layout, Russian by default, English in
  Settings):
  - **Sources**: record or upload, live progress, the list of everything saved, with
    status, duration and speakers; rename and delete in place.
  - **Transcript**: audio player; click a timestamp to jump there, and the playing line is
    highlighted. Rename speakers once and the name appears everywhere, including the
    summary. Summary alongside, copy, download .txt, transcribe again.
  - **Settings**: a full screen for the project, AI summaries, speaker separation,
    language and environment status.
  - Steps 3–6 (Atoms, Document, Decomposition, Export) are shown as "later".
  - The previous single page is still at `/classic` while the new one settles.
- Recordings are named in the interface language; Russian plurals are correct everywhere.
- Fixed: project names differing only in Cyrillic letter case counted as different.

## 2.1.0 (2026-09-23)

- **Redesigned interface.**
  - Three collapsible sections: **Source** (upload or record), **Transcription options**
    (shared by both, collapsed to a one-line summary) and **Result** (summary, transcript,
    segments, word timestamps, each collapsible). The app remembers what you collapsed.
  - One spacing scale and one type scale across the page, Settings and the Setup screen.
    One set of components: section, panel, field, button, status.
  - Scales from phones (360 px) to wide screens: panels sit side by side when there's
    room and stack when there isn't; tables scroll instead of breaking the layout;
    Settings becomes a full-screen sheet on small windows.
  - Light and dark themes follow the system and use the prototype's palette.
    System fonts only, so nothing is fetched from the internet.
- **Fixed: recording on the Mac captured nothing ("No audio captured").**
  - The Mac app now runs Python inside its own process, so macOS asks for microphone
    and system-audio access *for Requirements Workbench*. Before, the app handed over to
    a separate Python program, which macOS silently refused without ever asking.
  - The app asks for the microphone before recording and, if access is off, says where
    to turn it on (System Settings → Privacy & Security → Microphone).
  - System audio no longer stalls when nothing is playing: silences are filled, so both
    channels stay in sync and Stop always works. A channel that delivers nothing, or
    system audio that stayed silent throughout, is reported with the likely reason.
- **Fixed:** the microphone list could be empty, and it offered "System audio" as a
  microphone (system audio is always recorded on its own).

- **AI summaries.** A **Summarize** button under every transcript (recorded, uploaded
  or imported) writes a summary in the transcript's language: overview, key points,
  requirements mentioned, decisions, open questions and action items. Each point
  cites the speaker and timestamp it came from. The text streams in live.
  - **Claude** (default: Claude Opus 5; Sonnet 5 or Haiku 4.5 selectable): add your
    Anthropic API key in **Settings → AI summaries**. Only the transcript text is sent,
    never audio.
  - **Local model via Ollama** (e.g. `qwen3:8b`): nothing leaves your computer.
  - Clear messages for a wrong key, rate limits, overload, no internet, or Ollama not running.
- Attaching a transcript file now says **Summarize**, and summarises right away.
- The **Summarize** button and the summary sit at the top of the results (the summary
  used to appear below a long transcript, out of sight). The page scrolls to the summary,
  shows elapsed time while waiting, and long transcripts scroll in their own box.
- If Summarize needs a key, entering it in Settings continues the summary automatically.
- Summary headings are written in the transcript's language too.
- **Fixed:** PDFs and transcript files were greyed out in the macOS desktop file picker.
- **Fixed:** keys and tokens from Settings are now stored in your user folder
  (private to you), not inside the app, where saving could break the macOS app or be
  lost on update. Existing tokens keep working.
- **Fixed:** pressing Save with an empty Hugging Face token field no longer deletes the saved token.
- **Import a transcript you already have.** Drop it where you drop audio: no speech
  recognition, it opens instantly with speakers and timestamps kept. Supported:
  - Microsoft Teams: `.vtt` or `.docx` transcript export (speaker names kept)
  - PDF with a text layer: Teams/Otter PDF exports or any document; page headers
    like "Page 2 of 5" are dropped. Scanned PDFs get a clear message (no OCR yet)
  - Zoom / Google Meet: `.vtt`
  - Subtitles: `.srt`
  - Plain text: `Name: text` lines, timestamped lines, or text copied from this app
  - This app's own `.json` result
  - Russian text in any common encoding (UTF-8, UTF-16, Windows-1251)
- Transcript tables show times as `mm:ss`, and file content is always shown as text,
  never interpreted as HTML (important for files from outside).
- Results appear without the 1.5 s polling delay.

## 1.1.1 (2026-09-23), published in release v2.0

- **Fixed: "Access to 127.0.0.1 was denied / HTTP ERROR 403" on startup.** The app used
  port 5000, which the macOS AirPlay Receiver (and sometimes other software) already
  uses. The app mistook it for an already-running copy of itself and showed that
  server's error page. It now uses its own port (47823), falls back to any free port
  when that's taken, and recognises a running copy only when it identifies itself.
- **Fixed: in browser mode the app quit right after first-run setup** instead of
  opening the app.
- Closing or killing the app always cleans up its instance record.

## 1.1.0 — Increment 0: stable base (2026-09-23), published in release v2.0

First step from GigaAM Transcriber towards Requirements Workbench
(`docs/specs/requirements-workbench-spec.md`, §12.2 increment 0). No new
end-user features yet: this makes the existing transcriber safe, installable
without prerequisites, and a native app on both Windows and macOS.

### Renamed: GigaAM Transcriber → Requirements Workbench
The app, installers and macOS bundle now carry the product's name. The Windows
installer upgrades an existing GigaAM Transcriber 1.0 in place and removes its
old shortcuts. GigaAM remains the speech-recognition engine.

### Install & platform
- **No prerequisites.** Installers bundle Python 3.12; the app's **Setup screen**
  installs PyTorch (CUDA / Apple GPU / CPU, picked for the machine), GigaAM (pinned),
  ffmpeg and the speech model on first launch, with progress, automatic retries and
  resume. Every later start re-checks in ~0.01 s and repairs anything missing.
- **macOS app** (`.dmg`, Apple Silicon, macOS 13+) with a native launcher, so the
  Dock and permission prompts show the app's name.
- **Windows installer**: per-user, no admin rights, installs WebView2 if missing,
  asks before deleting your data on uninstall.
- Desktop window by default on both OSes; `--browser` / "Browser Mode" shortcut optional.
  Falls back to the browser if the window can't open.
- Downloaded components, models and recordings live in
  `%LOCALAPPDATA%\RequirementsWorkbench` / `~/Library/Application Support/RequirementsWorkbench`.

### Recording
- **macOS desktop app records call audio** (macOS 14.2+, Core Audio process taps):
  no browser, screen sharing or virtual audio driver needed.
- Mic and system audio are recorded as **separate channels**, streamed to disk while
  recording (constant memory; a crash no longer loses the call).
- Problems with a channel (device missing, permission denied) are shown live and after
  recording instead of being silently dropped.

### Reliability & security
- The local server accepts only local connections in every mode (browser mode used to
  be reachable from the whole LAN, including the settings endpoint).
- Transcriptions are queued and run one at a time, showing the queue position.
- Fixed: temp upload leaked after ffmpeg conversion; desktop recordings downloaded
  as `.webm` although they were WAV; recording start ignored server errors.

### Test checklist for this increment
Windows 10/11 PC (ideally with an NVIDIA GPU) and a Mac (Apple Silicon, macOS 14.2+):
1. Install from the installer / `.dmg` on a machine **without Python** → app opens.
   *Mac: first open via right-click → Open (not notarized yet).*
2. Setup screen runs by itself and opens the app (few minutes, first run only).
   On NVIDIA check the console summary / GPU button shows the GPU.
3. Settings → paste a Hugging Face token (see README) → speaker separation works.
4. Upload an audio file → transcript (with and without speaker separation, a file > 1 min).
5. Record a short Teams/Zoom/YouTube call in the **desktop window**: both your voice and
   the other side are in the recording. Allow the microphone / system audio prompts.
6. Unplug the mic mid-recording (or deny a permission) → the app says which channel failed
   and still saves the other one.
7. Close and reopen the app → starts straight into the app (no setup), in a few seconds.
8. From another device on your network, open `http://<your-PC-IP>:47823` → must not connect.
