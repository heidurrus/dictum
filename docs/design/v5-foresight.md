# Requirements Workbench 5.0: the Foresight-inspired redesign

Brief for the next shell. It takes the four things we liked in Google AI Edge Foresight
(`docs/research/foresight-teardown.md`) and says what each one becomes in the Workbench, what it
changes in the code, and in what order. The clickable prototype is `prototype-v5.html` (open it from
Finder; ⌘1…⌘8 switch pages, the moon toggles dark, `#onboarding` restarts the first run).

What stays: the pipeline (sources → requirements → documents → backlog → Jira), the data model
(SQLite schema v8, source folders), the skills, two-channel recording, local-only mode. What changes:
the frame around it, the recording screen, the first run, and how materials are stored and browsed.

## 1. Interface: Material-style shell on a tonal canvas

Foresight's look is Material 3 Expressive on a Flutter canvas: a navigation rail, one large
headline per page, white cards on a tinted background, pill buttons, no hairlines. The Workbench
today is a macOS document-app frame: translucent sidebar, 52-px toolbar, panes separated by lines.
We copy the first and drop the second.

Decisions:

- **Navigation rail, 88 px, icons with labels**, instead of the sidebar. Order: Встречи, Материалы,
  Требования, Документы, Бэклог, Спросить; Настройки at the bottom. The active item sits in a
  tonal pill. The project switcher moves to the top of the content area (a chip with a menu). The
  pipeline rings move to the Встречи home as a status strip; the rail only shows a dot for "needs
  attention".
- **One page headline** (32/40, −0.02em) with the subtitle under it and the actions to the right.
  The toolbar bar disappears; actions live in the headline row and in cards.
- **Tonal surfaces instead of lines.** Background `surface-container-low`, cards `surface`,
  wells `surface-container-high`; 20–24 px radius on cards, 12 px on rows, pills for buttons and
  chips. Hairlines only inside tables.
- **Status chip in the top-right of every page**: what the machine is doing now (recognising 42%,
  1 задача; downloading a model; idle). Clicking it opens the jobs list. Replaces the sidebar job
  card.
- **Type.** Bundle one variable font with Cyrillic (Inter, OFL) instead of the system stack, so the
  app looks the same on every machine and headlines have the Expressive weight. Body 14/20,
  headline 32/40, title 18/24, label 12/16.
- **Dark theme** keeps the same structure with surfaces at 5 %, 8 %, 12 % lightness steps and a
  light-blue primary (`#A8C7FA` on `#0842A0` containers).
- **Recording HUD** stays dark and floating; it gets the Foresight proportions (compact, rounded
  28 px, big timer, pause/stop in a pill).

What this means in code: `tokens.css` gets a second token set (`--m-*`), `App.svelte` swaps
`Sidebar` for `Rail`, `Screen.svelte` renders the headline row instead of `.toolbar`, and the
per-screen pane CSS keeps working inside a card. The e2e selectors in `redesign.md` §12 stay as
aliases.

## 2. Meetings: the recording experience

Foresight's meeting is one object with a title, a timer, a transcript with Microphone/System
labels, a notes editor next to it, enhanced notes that never overwrite what you typed, a search
box, and a details panel with tabs. Ours is a source row that becomes a transcript page after the
job finishes.

Decisions:

- **Встречи is the home page.** The list is a list of meetings, not of files: title, date,
  duration, who (speakers), tags (Запись / Импорт / Текст), requirements count, and the status in
  words. Search by title and transcript text, sort (newest, oldest, A–Z). Selecting a row opens
  the details panel on the right with tabs **Резюме / Транскрипт / Заметки / Требования**.
- **Title at the top, editable in place,** from the first second of the recording (default:
  "Встреча 14 окт, 11:30"). Rename anywhere: the row, the panel, the session header.
- **Session screen** (`#/meeting/<id>` while recording and after): header with the title, timer
  and the audio pill (pause, stop); left pane the live transcript with Микрофон / Собеседники
  labels and "Слушаю…"; right pane **Заметки** (Markdown shorthand, bold / italic / heading /
  list, saved as the meeting's note) and under it **Требования на лету**: items the extractor
  produced from the last minutes, each with its quote, each one click away from the requirements
  list. The user's notes are never rewritten; the enhanced side is a separate pane.
- **Search in the transcript** with hits highlighted and a counter, plus the "only lines with
  requirements" filter that exists today.
- **Recap tab** with three styles (Кратко / По пунктам / Действия) and "Обновить" that only
  summarises what changed since the last summary (incremental prompt, like Foresight's).
- **Auto-stop** after N minutes of silence (Settings), with a notification. The rule "audio being
  processed is never lost" stands: stopping only moves the file, never deletes it.

Code: `Sources.svelte` becomes `Meetings.svelte` (list + panel); `Transcript.svelte` becomes the
session screen with a notes pane; a `notes` column on `sources` (Markdown) and a `meeting_search`
FTS5 table over segments and notes; live extraction reuses the existing extractor on a window of
recent segments.

## 3. Onboarding: a first run that sets the machine up

Foresight: welcome with three illustrated panels, permissions with Allowed/Denied rows and
"Grant all", model cards with RAM requirement, a download page, discovery of files to import,
then a four-step spotlight tutorial. Ours: three rows in an empty list (name, AI, first source).
We keep the rule that optional set-up appears where it is first needed, and add a real gate for
the things nothing works without.

Steps (each one screen, back and skip where safe):

1. **Добро пожаловать**: three panels (record → requirements → document), the privacy sentence,
   "Начать".
2. **Разрешения**: Микрофон, Системный звук, Уведомления, each Разрешено / Не разрешено with a
   "Разрешить всё" button and "Открыть Системные настройки" per row.
3. **Модели**: a card for the speech model (GigaAM, size, downloaded or not) and one per local
   LLM size with RAM requirement and "рекомендуем" for this machine; "Или подключить Claude" as a
   secondary path. The cloud option is shown but not pushed.
4. **Загрузка**: progress per model, "Готовим Workbench…", can run in the background.
5. **Материалы**: scan Загрузки / Документы / Рабочий стол for audio, .docx, .pdf and .md not yet
   in the project; a checklist to import; "Выбрать папку".
6. **Подсказки**: a four-step spotlight on the home page: record, meetings, library, ask. Available
   again from Help.

Code: a `FirstRun` route (`#/onboarding`) driven by `setup-state.json`; the permissions page reads
the existing capture checks; model cards reuse `LocalModel.svelte`; discovery is a new
`/api/discover` that lists candidate files without importing.

## 4. Materials: an Obsidian-like library

Foresight keeps a library of knowledge sources (files, URLs, Drive) with list / grid / graph
views, labels, sync times and "include in meeting context". Obsidian keeps a vault: a folder of
Markdown files you can open in any tool, with links between notes and backlinks. We combine the
two: the project becomes a folder on disk that the app owns and the user can open.

Decisions:

- **A vault per project**: `~/RequirementsWorkbench/<project>/` with `Встречи/`, `Материалы/`,
  `Требования/`, `Документы/`, `Заметки/`. Every meeting is a folder with the audio, `transcript.md`,
  `notes.md` and `summary.md`; every requirement a small `.md` with frontmatter (id, type, status,
  source, quote); every document version a `.md` next to its `.docx`. SQLite stays the index and
  the source of truth for state; the vault is written on every change and read back when a file
  changes on disk (watcher), so editing a note in Obsidian or Finder is safe.
- **Wikilinks and backlinks.** Requirements link to their meeting (`[[Встречи/2026-10-14 Звонок]]`),
  documents link to requirements (`[[FR-12]]`). The library shows backlinks for the selected
  file: "Цитируется в FR-12, FR-30 · Входит в ТЗ v3".
- **Library page** (Материалы): a folder tree on the left (the vault), list or grid in the middle
  (name, labels, imported, changed, size), the selected file on the right with a preview,
  labels, backlinks, "Включать в контекст" and "Показать в Finder". Add files by drop, "Добавить
  файлы", "Добавить ссылку", "Вставить текст", "Импорт папки". Search across everything.
- **Context for AI.** Files marked "в контексте" are chunked and embedded locally; the extractor
  and Спросить cite them as `[Источник N]` the way Foresight does.
- **Спросить** page: ask across the project's meetings, requirements and materials; answers with
  citations that open the source; history kept.
- Not now: the force-directed graph, Drive sync, URL subscriptions.

Code: `core/vault.py` (layout, writers, watcher), `core/index.py` (FTS5 + local embeddings via
the existing local LLM runtime), routes `/api/projects/<id>/vault/*`, `/api/ask`, a `Library.svelte`
and `Ask.svelte`.

## 5. Шепнуть: voice capture for the analyst, not for the project

Taken from the quick voice-memo apps (HiNotes and the like): press, speak, and the thing you said
becomes a task, a note, a reminder or an idea. It lives in a personal inbox that is separate from
every project. Nothing from it reaches requirements, documents or Jira unless the user presses
"Сделать вопросом" on an item.

Decisions:

- **One screen (`#/whisper`)**, one big button. Idle: "Нажмите и скажите, что нужно сделать".
  Listening: the words appear as GigaAM recognises them, a second press or two seconds of silence
  stops. Result: what was said, the parsed card (type chips Задача / Заметка / Напоминание / Идея,
  an editable title, the due time parsed from speech, the project guessed from words), and when one
  utterance holds two things, both are offered. "Сохранить", "Переговорить", "Отменить".
- **Global shortcut** (⌥ Space) and a menu-bar microphone: the window comes forward on the whisper
  screen already listening. Reminders fire as macOS notifications.
- **Inbox** on the right: grouped Сегодня / Вчера / Раньше, filters Все / Открытые / Задачи /
  Заметки / Напоминания, a checkbox on tasks and reminders, search.
- **Storage**: a `whispers` table (kind, text, title, due_at, done, project_id nullable,
  audio file) and a `Шепот/` folder in the vault root, outside any project, one `.md` per item.
  The audio clip is kept next to it.
- **Parsing** runs through the local LLM with a small fixed prompt (type, title, due, project
  candidates); the raw transcript is always kept so a wrong parse costs one edit.

Code: `core/whisper.py` (capture → GigaAM → parse → store), `Whisper.svelte`, a global hotkey in
`desktop_api.py`, notifications through the existing macOS bridge.

## 6. Order of work

Each release ships on its own and keeps every existing test green.

| Release | What | Touches |
|---|---|---|
| 5.0 | Shell: tokens, bundled font, rail, headline rows, status chip, dark | `tokens.css`, `app.css`, `App.svelte`, `Screen.svelte`, new `Rail.svelte` |
| 5.1 | Meetings home with details panel; title editable everywhere; search | `Meetings.svelte`, `/api/sources` search, FTS5 |
| 5.2 | Session screen: notes pane, live requirements, recap styles, auto-stop | `Transcript.svelte` → `Meeting.svelte`, `notes` column, extractor window |
| 5.3 | Шепнуть: capture, parse, inbox, global shortcut | `core/whisper.py`, `Whisper.svelte`, `whispers` table |
| 5.4 | Onboarding gate and tutorial | `FirstRun` route, `/api/discover`, `setup-state.json` |
| 5.5 | Vault on disk with watcher; Library page | `core/vault.py`, `Library.svelte` |
| 5.6 | Local index and Спросить with citations | `core/index.py`, `Ask.svelte` |

## 7. Assumptions and open points

- Assumed: the whisper inbox is personal and cross-project; items can be linked to a project but never
  live inside one.
- Assumed: the app stays Russian-first with the English set; the prototype is Russian only.
- Assumed: we bundle Inter rather than license Google Sans. If you prefer the system font, only
  the headline weight changes.
- Assumed: the vault lives under the home folder, not inside Application Support, so Obsidian
  and Finder can reach it without digging; the current `library/` folder is migrated on first
  start of 5.4.
- Open: whether Спросить should answer only from materials marked "в контексте" or from the whole
  project by default. The prototype shows a toggle like Foresight's web-search switch.
- Open: whether the rail replaces the project switcher's place in the sidebar for good, or a
  multi-project user needs the list back (prototype: a chip with a menu).
