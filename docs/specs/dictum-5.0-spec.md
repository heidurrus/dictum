# Dictum 5.0: implementation specification

For the agent (or human) building release 5.0 of the app known until now as Requirements Workbench.
Everything in the clickable prototype `docs/design/prototype-v5.html` is in scope. The prototype is
the visual and behavioural source of truth; this document says what is behind it, in which order to
build it, and how to know a chunk is done. Read `docs/design/v5-foresight.md` for the reasoning.

Confidence tags: `[P]` seen in the prototype, `[I]` implied by it, `[A]` an assumption made here
(see §9). Every chunk ends with acceptance criteria and the tests it must add.

---

## 0. Ground rules for the builder

**Repo and stack.** `heidurrus/requirements-workbench`. Backend: Flask in `app.py`, modules in
`core/`, SQLite via `core/store.py` (schema v8). Frontend: Svelte 5 runes in `frontend/src`, built
to `static/app` (the build is committed). Desktop: pywebview (WebKit) from `launcher.py`;
`core/desktop_api.py` is the JS bridge (`window.pywebview.api`). Local ASR: GigaAM
(`core/longform.py`). Local LLM: llama.cpp `llama-server` managed by `core/local_llm.py`
(engine build pinned, models pinned by revision + SHA-256, `--reasoning off`). Jobs:
`core/jobs.py` (`JobStore`, `SerialQueue`; progress polled through `/job/<id>`).

**Commands.** Python: `.venv/bin/python -m pytest -q` (torch is stubbed by `tests/conftest.py`;
import `tests.conftest` before `app` to run the server without torch). Frontend, from `frontend/`:
`./node_modules/.bin/vite build`, `./node_modules/.bin/svelte-check --threshold warning`. e2e:
`WORKBENCH_DATA_DIR=$(mktemp -d) python3 frontend/e2e/fake_llm_server.py 5312` then
`node frontend/e2e/<suite>.mjs http://127.0.0.1:5312`. e2e scripts must live in `frontend/e2e/`
(that is where `playwright-core` resolves). Prefer `locator("tr.item", { hasText })` over
`getByText` because names repeat in the sidebar. Build: `.venv/bin/python packaging/build.py
--target macos-arm64`; never launch the built app from a shell on the dev machine (endpoint
security quarantines it), the user opens it from Finder.

**Conventions.** One feature branch per chunk, merged into `master` with `--no-ff`; the user pushes
and tags. Bump `VERSION` and add a `CHANGELOG.md` entry per shipped chunk. Pre-release builds are
numbered `4.9.N` (plain `x.y.z`, which is what `CFBundleShortVersionString` and the Windows
installer accept; maintenance of the old line, if any, stays on `4.2.x`); C11 sets `5.0.0`. i18n: every string in both languages in `frontend/src/lib/i18n.js`; `node frontend/scripts/i18n_check.mjs`
(also `npm run i18n`) fails on any key missing in either language or left untranslated and is a
gate for every increment; `t(key)` returns the key when missing, so leftovers show on screen. The
default language follows the OS language on first start (English unless the system is Russian),
and the switch in Settings keeps working. Keep the e2e class
selectors listed in `docs/design/redesign.md` §12 as aliases. Keep all existing backend tests
green; the suite is 399 tests at the start of 5.0.

**Hard rules.** Never create, edit or test anything in the Jira project QAAP on qi-iq.atlassian.net;
the only sandbox is SCRUM on sundocarme-1787295249165.atlassian.net through the app's own sign-in.
Jira sign-in is browser-based, never the OS keychain. Audio that is being recorded or processed is
never deleted or overwritten; stopping, auto-stopping, crashes and renames all keep every WAV.
"Только локально" projects make no network calls for AI; there is no silent cloud fallback.

---

## 1. What 5.0 is

| Area | Today (4.2.x) | 5.0 (prototype page) |
|---|---|---|
| Name, icon | Requirements Workbench, blue icon (4.2.2) | **Dictum**, same icon |
| Shell | macOS-style sidebar + toolbar + panes (`Sidebar.svelte`, `Screen.svelte`, `Panes.svelte`) | Navigation rail, page headline, tonal cards, status chip (`#meetings` etc.) |
| Home | Overview + Sources table | **Встречи**: meeting list, details panel with tabs (`#meetings`) |
| A source | Transcript page after the job | **Meeting page**: live transcript, notes pane, requirements on the fly, recap styles (`#session`) |
| Materials | none (non-audio sources go through Sources) | **Материалы**: files, links, notes; labels that assign themselves; list / grid / graph; "in context" (`#library`) |
| Ask | none | **Спросить**: answers across the project with citations, history (`#ask`) |
| Whisper | none | **Шепнуть**: voice to task / note / reminder / idea, personal inbox (`#whisper`) |
| First run | three rows in the empty Sources pane | six-step onboarding + four-step spotlight tutorial (`#onboarding`) |
| Settings | one form | sections with cards; models as cards; storage; hotkeys (`#settings`) |
| Requirements, Documents, Backlog, Export, Skills | as today | same behaviour inside the new shell, restyled (`#requirements`, `#documents`, `#backlog`) |

Routes in 5.0 (hash): `#/meetings`, `#/meeting/<id>`, `#/library`, `#/library/<material_id>`,
`#/requirements` (alias of today's `#/atoms`, keep both), `#/documents`, `#/document/<id>`,
`#/backlog`, `#/export`, `#/ask`, `#/whisper`, `#/skills`, `#/settings/<section>`, `#/onboarding`.
Old routes keep working through aliases in `parseRoute` (`#/sources` → meetings, `#/source/<id>`
→ meeting, `#/overview` → meetings).

---

## 2. Architecture deltas

### 2.1 Backend

New modules in `core/`:

| Module | Responsibility |
|---|---|
| `live.py` | Live transcription of a recording in progress: tails `mic.wav` / `sys.wav`, transcribes new audio in windows, appends segments to the source. |
| `notes.py` | Meeting notes (Markdown) and recap styles with incremental update. |
| `materials.py` | Materials: import (file / URL / text / folder), text extraction, chunking, labels, related, context flag. |
| `index.py` | Local index: FTS5 over segments, notes, materials, atoms; embeddings through `llama-server --embedding`; cosine search; label clustering. |
| `ask.py` | Retrieval + answer with `[Источник N]` citations, history. |
| `whisper.py` | Whisper capture → ASR → parse → inbox; reminders. |
| `discover.py` | First-run discovery of candidate files in Загрузки / Документы / Рабочий стол. |
| `hotkeys.py` (macOS) | Global shortcut and menu-bar item through PyObjC (`AppKit`), optional, see C7. |

Schema goes to **v9** (migration in `store._migrate`, additive only):

```sql
ALTER TABLE sources ADD COLUMN notes TEXT;                    -- Markdown, the user's own words
ALTER TABLE sources ADD COLUMN recap_style TEXT;              -- the style last chosen for this meeting
-- A material IS a source (sources.kind = 'material'; import_format = ext; text; segments = paragraphs),
-- so import, extraction, evidence, search and audit reuse the existing pipeline. This table extends it.
CREATE TABLE materials (
  source_id TEXT PRIMARY KEY REFERENCES sources(id),
  material_kind TEXT NOT NULL,        -- file | url | note
  path TEXT, url TEXT, size INTEGER,
  in_context INTEGER NOT NULL DEFAULT 1, synced_at REAL, error TEXT);
CREATE TABLE material_chunks (
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
  idx INTEGER NOT NULL, text TEXT NOT NULL, embedding BLOB);   -- float32 little-endian
ALTER TABLE segments ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0;   -- live pass, replaced on stop
ALTER TABLE atoms ADD COLUMN live INTEGER NOT NULL DEFAULT 0;             -- came from the live extractor
ALTER TABLE atoms ADD COLUMN stale_evidence INTEGER NOT NULL DEFAULT 0;   -- quote not re-found after the final pass
ALTER TABLE summaries ADD COLUMN style TEXT NOT NULL DEFAULT 'brief';     -- brief | bullets | actions, one row per style
ALTER TABLE summaries ADD COLUMN through_idx INTEGER;                     -- last segment idx this recap covers
CREATE TABLE usage (                  -- Settings → stats; one row per event
  id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL,            -- llm_local | llm_cloud | asr | embed
  tokens_in INTEGER, tokens_out INTEGER, seconds REAL, project_id TEXT);
CREATE TABLE labels (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
  name TEXT NOT NULL, color TEXT NOT NULL, centroid BLOB, created_at REAL NOT NULL,
  UNIQUE(project_id, name));
CREATE TABLE material_labels (
  source_id TEXT NOT NULL REFERENCES sources(id), label_id TEXT NOT NULL REFERENCES labels(id),
  assigned_by TEXT NOT NULL,          -- user | auto | removed  (a removal is kept as a tombstone so auto never re-adds it)
  score REAL, PRIMARY KEY(source_id, label_id));
-- "Где используется" needs no table: evidence.source_id already points at the material, and
-- documents cite atoms, so material → atoms (evidence) → documents (requirement_ids) is a query.
CREATE TABLE source_embeddings (      -- meetings and atoms in the same vector space
  entity TEXT NOT NULL, entity_id TEXT NOT NULL, idx INTEGER NOT NULL, text TEXT NOT NULL, embedding BLOB,
  PRIMARY KEY(entity, entity_id, idx));
CREATE VIRTUAL TABLE search USING fts5(entity, entity_id, project_id UNINDEXED, text, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE ask_history (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL,
  citations_json TEXT NOT NULL, context_only INTEGER NOT NULL, created_at REAL NOT NULL);
CREATE TABLE whispers (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL,          -- task | note | remind | idea
  text TEXT NOT NULL, title TEXT NOT NULL, transcript TEXT NOT NULL, audio_file TEXT,
  due_at REAL, done_at REAL, project_id TEXT, notified_at REAL, deleted_at REAL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL);
```

`whispers` has no `project_id` foreign key on purpose: the inbox is personal and survives project
deletion; `project_id` is a soft link.

Settings (`core/settings.py` `DEFAULTS`) gain: `silence_stop_minutes` (10), `live_transcription`
(true), `live_requirements` (true), `live_questions` (false), `recap_style` ("brief"),
`embed_model` (""), `hotkeys` (a map: `{"whisper": "alt+space", "record": "cmd+r", ...}`, one place
read by both the frontend handler and `core/hotkeys.py`), `menubar` (true), `notes_style`
("standard" | "concise"), `tuning` (`{"label_assign": 0.45, "graph_edge": 0.30, "retrieve_k": 12}`).
`onboarding:v5` lives in `setup-state.json`, not in settings.

### 2.2 Frontend

```
frontend/src/
  App.svelte                 routes → screens; Rail instead of Sidebar; Onboarding gate
  components/
    Rail.svelte              [new] navigation rail, record button, settings, badges, phone bar
    Page.svelte              [new] headline row + actions; replaces Screen.svelte's toolbar
    TopBar.svelte            [new] project chip, status chip (jobs), theme, help
    StatusChip.svelte        [new] what the machine is doing; opens the jobs popover
    Tutorial.svelte          [new] spotlight overlay
    Onboarding.svelte        [new] six steps
    AudioPill.svelte         [new] timer, pause, stop, levels
    NotesEditor.svelte       [new] Markdown shorthand with the format bar
    Graph.svelte             [new] force layout of materials (SVG)
    LabelColumn.svelte       [new] labels with counts, create-and-assign
    Panes.svelte, PopMenu, Toast, Icon, LocalModel, AsrOptions, CommandPalette  (kept)
  screens/
    Meetings.svelte          [new, replaces Sources + Overview]
    Meeting.svelte           [new, replaces Transcript] live and post-recording
    Library.svelte           [new]
    Ask.svelte               [new]
    Whisper.svelte           [new]
    Settings.svelte          [rewritten as sections]
    Atoms.svelte, Document.svelte, Backlog.svelte, Export.svelte, Skills.svelte  (restyled, same logic)
  lib/
    tokens-m.css             [new] tonal tokens from the prototype (light + dark)
    live.svelte.js           [new] polling of the live transcript and live requirements
    index.js                 [new] API helpers for search / ask / labels
```

Tokens: copy the `:root` block of the prototype into `tokens-m.css` under the names used there
(`--bg`, `--surface`, `--surface-2/3/4`, `--text`, `--text-2/3`, `--primary`, `--on-primary`,
`--primary-c`, `--on-primary-c`, `--secondary-c`, `--on-secondary-c`, `--outline`, `--outline-2`,
status colours, `--hud*`, `--shadow-1/2/3`, radii). Keep `tokens.css` aliases alive until the last
old screen is restyled, then delete it. Bundle **Inter** (variable, OFL, Cyrillic) in
`frontend/src/assets/fonts/` and reference it from `app.css`; no runtime font download.

---

## 3. Chunks

Order matters: C0 and C1 first, then C2 → C3 → C4 (meetings), C5 → C6 (materials and ask), C7,
C8, C9, C10, C11. Cross-chunk dependencies to respect: C2's transcript search uses `LIKE` until
C5's FTS5 exists; C4.3's question card needs C5's index (ships off until then); C7 needs C4.1's
live transcriber; C8's model step needs C5's embedding model entry; C9's stats need the `usage`
rows that C3–C7 write. C4 and C6 are the risky ones; each has a fallback that still ships.

### C0. Rename to Dictum

[P] Name everywhere in the prototype. [A] Bundle id `com.heidurrus.dictum`.

- `packaging/build.py`: `APP_NAME = "Dictum"`, `BUNDLE_ID = "com.heidurrus.dictum"`, `ARTIFACT =
  "Dictum"`; `packaging/macos/launcher_stub.c` comments and strings; Windows `installer/*.iss`
  names; `Info.plist.in` usage descriptions ("Dictum records your microphone…").
- Data folder: `core/paths.py` returns `~/Library/Application Support/Dictum` (Windows:
  `%APPDATA%\Dictum`). On first start, if the new folder does not exist and the old
  `RequirementsWorkbench` one does, **move** it (rename, same volume) and write a
  `migrated-from.txt`. The runtime, models and engine move with it, so nothing downloads again.
- Strings: every "Requirements Workbench" in `i18n.js`, `README.md`, `app.py` notifications,
  `launcher.py` `APP_TITLE`, `core/exports.py` docx footers, skills templates. Keep the export format
  id `requirements-workbench-project` readable on import (accept both ids, write `dictum-project`).
- Jira OAuth app name and callback stay as they are (they are registered externally).

Acceptance: fresh install starts with an empty `Dictum` folder; an install over 4.2.2 starts with
all projects, models and settings present and the old folder gone; `grep -ri "requirements
workbench"` in `frontend/src`, `core`, `app.py`, `packaging` returns only the import-compat line and
the changelog. Tests: `test_paths_migration` (old folder moved, nothing copied twice), `test_boot`
updated, `test_store` import of a 4.x export.

### C1. Shell: tokens, rail, page header, status chip

[P] `#meetings` frame: rail of 88 px with the logo, the red record button, items Встречи ·
Материалы · Требования · Документы · Бэклог · Спросить · Шепнуть, Настройки at the bottom; top
bar with the project chip (menu: switch, new, archive), status chip, theme, help. Badges: a count on
Требования (atoms pending review), a dot on Документы (stale), both from `/api/projects/<id>/status`.
Phone width (≤ 760 px): the rail becomes a bottom bar with Встречи, Материалы, Требования, Шепнуть,
Настройки; the record button moves into the page header.

- `tokens-m.css`, Inter, `Rail.svelte`, `Page.svelte` (same props as today's `Screen.svelte`:
  `title`, `sub`, `crumb`, `crumbPath`, `inspector`, `heading` and `actions` snippets, so the
  inspector toggle and the back crumb keep working), `TopBar.svelte`, `StatusChip.svelte`.
  `Sidebar.svelte` is deleted in this chunk; its project switcher moves into the project chip and
  its pipeline rings into C2's strip (until C2 lands, the rings are not shown anywhere, which is
  acceptable for an alpha).
- Status chip text, in priority order: a running recording ("Идёт запись · 12:04"), a running job
  from `JobStore` ("Распознаю · 42% · 1 задача" / "Извлекаю требования…" / "Загружаю модель ·
  1,2 ГБ из 7"), else "Готово". Click opens a popover listing jobs with progress and cancel where
  the job supports it. Polls `/api/jobs` (new: list active jobs, each `{id, kind, label, progress,
  cancellable}`), every 2 s while something runs, every 15 s otherwise.
- Keyboard: ⌘1…⌘8 switch rail items in order (Настройки is ⌘8), ⌘R record (desktop window
  only; in `--browser` mode ⌘R stays the browser's reload and the button is the way), ⌘K palette
  (kept), ⌘⇧L theme, ⌘J ask, ⌥Space whisper (see C7), Esc closes overlays. All bindings come
  from the `hotkeys` settings map. `CommandPalette.svelte` gets the new routes.
- Old screens render inside `Page.svelte` unchanged for now (their `Screen` import is swapped to
  `Page` with the same props). Inspector toggling keeps working through `Panes.svelte`.
- Dark theme per the prototype tokens; system follow + forced light/dark pref as today.

Acceptance: every existing route renders inside the rail without console errors; e2e `smoke.mjs`
passes with selector updates only; `svelte-check` clean; the status chip shows a transcription job
end to end (start transcription in the e2e, chip text changes, returns to "Готово"). Tests:
`test_jobs_api` for `/api/jobs`.

### C2. Встречи: home with list and details panel

[P] `#meetings`: headline "Встречи" + subtitle (project · n встреч · n требований); actions
"Импорт" and "Записать встречу"; the pipeline strip (five chips with rings: Встречи, Требования,
ТЗ vN, Бэклог, Jira, each with its state in words, clickable); list card with search, sort
(Новые / Старые / А–Я), rows (icon by kind: mic / upload / doc; title; date · duration · people ·
tags Запись / Импорт / Текст; status tag Идёт запись (C4, `status = "recording"`) / Разобран /
Распознаю · n% / Без расшифровки; "n треб."). The list excludes `kind = "material"` sources (C5);
text sources that are conversations (emails, interview notes) stay meetings.
details panel with an editable title (contenteditable, saves on blur), meta line, tabs Резюме /
Транскрипт / Заметки / Требования, footer "Открыть встречу", "Требования · n", "Ещё" menu (save
audio per channel, copy, delete).

- Backend: `GET /api/projects/<id>/sources?q=` adds full-text search over title, segments and
  notes through the FTS5 `search` table (C5 builds the table; until then, title + `LIKE` on text).
  `PATCH /api/sources/<id>` already renames. Response of the list adds `people` (speaker names),
  `atoms` (count), `tags`.
- Frontend: `Meetings.svelte` with `Panes` (content + inspector) or the prototype's two cards;
  the panel's tabs load `/api/sources/<id>` (summary, segments with atom marks, notes, atoms). The
  Резюме tab shows the recap with its style switch (C3 provides styles; until then the existing
  summary). Processing sources show the spinner state; raw ones the "Расшифровать" / "Сохранить
  аудио" state. Empty project shows the first-run content (C8) in place of the list.
- The sidebar's "running jobs" card is gone (status chip replaces it). The Overview screen is
  removed; `nextStep()` from `lib/next.js` feeds the pipeline strip's wording.

Acceptance: double-click or "Открыть встречу" opens `#/meeting/<id>`; renaming in the panel updates
the row and the meeting page; search by a word that only appears in a transcript finds the
meeting; sort orders are correct; all existing e2e flows that started on Sources start on Meetings.
Tests: `test_sources_search`, e2e `meetings.mjs` (list, search, rename, open).

### C3. Meeting page: transcript, notes, recap

[P] `#session` after the recording ended, and the Transcript tab of the panel. Header card: back
arrow, editable title, meta (date · microphone + system · model), levels (only while recording),
timer, audio pill (C4). Left card "Транскрипт": speaker chips Микрофон / Собеседники (channel
labels, not people; renaming to people stays in the inspector as today), search field with hits
highlighted, chips "Все реплики" / "С требованиями", lines with time · speaker · text · quote
highlight · atom chips, click a time to seek, the player at the bottom as today. Right card
"Заметки": format bar (B, I, H, •, 1., ☐), textarea, "сохраняются сами"; under it "Требования на
лету" (C4) or, for a finished meeting, "Требования из встречи" with the same rows.

Recap (Резюме tab in the panel and in the meeting inspector): style switch Кратко / По пунктам /
Действия; sections Главное / Открытые вопросы / Риски with `[mm:ss]` links; footer "Обновлено …
· модель · Обновить по новым репликам".

- `core/notes.py`: `save_notes(source_id, md)` (debounced on the client, 1 s) and
  `append_note(source_id, line)` for server-side additions (the question card in C4.3, whisper
  later); the editor applies an appended line to its own state through the live poll so a debounce
  in flight does not overwrite it. `recap(source_id, style, incremental)`: one `summaries` row per
  style with `through_idx`; incremental means the prompt gets that style's previous recap plus
  only the segments after `through_idx` and is asked to update, not rewrite (Foresight's pattern);
  "Re-summarize" sends everything. Switching style with no row yet runs a full recap. Styles are three prompts in `skills/` as a built-in
  skill (`recap.brief.md`, `recap.bullets.md`, `recap.actions.md`), editable like other skills.
- Routes: `PUT /api/sources/<id>/notes` `{text}`, `POST /api/sources/<id>/notes/append`
  `{line}`; `POST /api/sources/<id>/recap` `{style, incremental}` → job; `GET` of the source
  returns `notes`, `recap_style`, and `summaries` keyed by style with `through_idx`.
- Frontend: `Meeting.svelte`, `NotesEditor.svelte` (Markdown stays raw text; the preview is the
  Заметки tab in the panel rendered with the existing `renderMarkdown`). Search in the transcript
  is client-side with a hit counter and ↑/↓ (Enter / ⇧Enter).

Acceptance: notes typed during or after a meeting survive reload and show in the panel's Заметки
tab; the recap style switch changes the text without re-sending the whole transcript when only
new segments exist (assert on the fake LLM server's received prompt length); transcript search
highlights and counts. Tests: `test_notes`, `test_recap_incremental` (prompt contains only new
segments), e2e `meeting.mjs`.

### C4. Live session: transcript and requirements while recording

[P] `#session` while recording: the audio pill (Идёт запись · pause · stop), the transcript grows
("Слушаю…" at the end), "Требования на лету" with new items and a "6 новых" tag, the
question-detected card (Foresight's), auto-stop on silence with a notification. Pause shows "На
паузе — звук не пишется".

This is the riskiest chunk. Ship it in three steps; each step is releasable.

**C4.1 Live transcript.** `core/live.py` `LiveTranscriber(recording_dir, model)`: every
`window` seconds (default 15) reads the audio appended since the last pass from `mic.wav` and
`sys.wav` (the recorder writes continuously; read the WAV data region by byte offset, never move
or lock the file), cuts at the last silence inside the window (`recorder.speech_bounds`), runs
GigaAM on each channel through the existing `transcribe_chunks`, and appends segments
`{t0, t1, channel, text, provisional: true}` to the source (the source row is created at
recording start with `status = "recording"`). On stop, the normal full transcription runs as today
and **replaces** the provisional segments (timestamps from the full pass win), so nothing the live
pass got wrong survives. GPU memory: run the live pass on the same device as the final pass with
`batch_size = 1`, release memory after every window (`longform.release_device_memory`). If a
window takes longer than `window` to transcribe twice in a row, drop to `window = 30`; if it
still cannot keep up, stop live mode and show "Транскрипт появится после остановки" (the
recording continues untouched). Route: `GET /api/sources/<id>/live?after=<idx>` returns new
segments; the page polls every 2 s. Pause: `POST /desktop-record/pause|resume` (recorder writes
silence while paused so the timeline stays continuous; the pill shows the paused state; paused
spans are recorded in the recorder status and are skipped by the live pass and **excluded from
the silence counter** of C4.3, otherwise a long pause would auto-stop the meeting). After the
final pass, the index job (C5) embeds the segments; before C5 ships there is no index job.

**C4.2 Requirements on the fly.** Every `live_window_atoms` seconds (default 90) with at least
`min_segments` new segments, run the existing extractor (`atoms.extract_candidates`) on the
segments since the last pass with the source header and the last 10 previous segments as
context; candidates get `status = "pending"` and `live = 1`. The "Требования на лету" list shows
them with the checkbox meaning accept (bulk accept uses the existing endpoint). Dedup against
existing atoms runs as today. On stop, the final extraction runs over the whole transcript as
today; live atoms that the final pass does not re-find are kept (they are the user's); their evidence is
re-verified **by quote text** against the final segments (`atoms.verify_evidence`, segment indices
are rewritten to the final ones) and marked `stale_evidence` when the quote is not found.

**C4.3 Auto-stop and the question card.** Auto-stop: when `silence_stop_minutes` pass with no
speech on either channel (`speech_bounds` on the last window), stop the recording exactly as the
Stop button does, then `POST /api/notify` "Запись остановлена: тишина 10 минут". The question
card: a cheap detector on the live segments (regex for interrogatives plus a `?` from the ASR, or
one local-LLM call per window with a short "is there a question addressed to the analyst"
prompt) → look up the answer in materials marked "в контексте" (C5 index) → show the card with
"Добавить в заметки" (appends a bullet to notes) and "Скрыть". Off by default until C5 ships;
setting `live_questions`.

Acceptance (C4.1): on a 3-minute recording with speech, provisional segments appear within 20 s
of being spoken; after stop, the transcript equals what the batch path produces (same segment
count ± merge differences; compare text); killing the app mid-recording leaves `mic.wav` and
`sys.wav` intact and the source in state `recording` with a "Расшифровать" action. (C4.2): at
least one live atom appears during the sample recording when the fake LLM returns one; accepting
it marks the segment. (C4.3): silence for the configured minutes stops the recording and notifies.
Tests: `test_live` (byte-offset reading of a growing WAV, window cut at silence, fallback when
slow), `test_live_atoms`, `test_autostop`; e2e `session.mjs` with the fake ASR (the e2e server
needs a fake ASR mode that emits scripted segments).

### C5. Материалы: knowledge library

[P] `#library`: headline + search + "Добавить"; left column kinds Все материалы · Файлы · Ссылки ·
Заметки with counts, Метки with colour dots and counts, "Создать метку" → inline form "Название" +
"Создать и назначить" with the hint; middle card: add row (Файлы · Ссылка · Вставить текст ·
Импорт папки) and the view switch **Граф · Список · Плитка** (graph is the default); list columns
Имя (type badge) · Метки · Изменён · Размер · Контекст (checkbox); grid cards with label chips and
"В контексте ИИ"; graph with nodes coloured by first label, edges by similarity, selected node
with its edges highlighted, +/−/centre buttons, legend; drop zone text; right panel: title, type ·
size · changed, preview, labels + "+ метка", "Включать в контекст ИИ" switch, "Похожие материалы"
with percentages, "Где используется" backlinks to requirements and meetings, footer Открыть ·
Показать в Finder · Ещё.

- Import (`core/materials.py`): a material is a `sources` row with `kind = "material"` and a
  `materials` extension row, created through the same import path as text sources today
  (`importFiles` → `/api/projects/<id>/sources` with `material=1`), so paragraphs become
  `segments`, the extractor can run on it on demand ("Извлечь требования" in the "Ещё" menu, off by
  default), and `evidence.source_id` gives "Где используется" for free. Files (`.docx`, `.pdf`,
  `.md`, `.txt`, `.rtf`, `.html`, `.eml` using the existing extractors in `core/transcripts.py` /
  `core/emails.py` and `python-docx`, `pypdf` already in requirements), URLs (fetch once with a 10 s timeout, store the readable text,
  `synced_at`, re-sync on demand; no network in "Только локально" projects: the URL is stored but
  not fetched, with the error shown), pasted text (`kind = note`), folder import (walk, skip
  hidden, 200 files max per import with a progress job). Materials are copied into
  `<data>/library/<project>/materials/<id>.<ext>`; the original stays where it was.
- Index (`core/index.py`): chunk text (about 800 characters, sentence-aware), embed each chunk
  through `llama-server --embedding` with the pinned embedding model (see §9 A3; this chunk adds
  it to `local_llm.EMBED_MODELS`, to Settings → Модели and to the download flow, since C8's
  onboarding comes later), store float32 BLOBs, cosine similarity in Python with numpy; FTS5 rows
  for keyword search. While the embedding model is not downloaded, import still works, FTS5 search
  works, and the graph, related, auto-labels and Ask show "Скачайте модель индекса" with a button. Meetings' segments
  and accepted atoms are embedded too (`source_embeddings`) so Ask (C6) and "Где используется"
  can span them. Indexing is a job (status chip shows "Индексирую · 3 из 7").
- Related: `GET /api/materials/<id>/related` → top 5 by max-chunk cosine, with the score.
  Graph: `GET /api/projects/<id>/materials/graph` → nodes (materials with first label) and edges
  (pairs above `0.30`, at most 5 per node). The force layout runs on the client
  (`Graph.svelte`, the prototype's `layout()` is adequate up to about 200 nodes; above that,
  show the top 200 by degree and say so).
- Labels: `POST /api/projects/<id>/labels` `{name, seed_material_id?}` creates the label with the
  next colour from the palette and **auto-assigns**: candidates are the seed (if any) and every
  material whose best chunk is within `0.45` cosine of the seed, or, with no seed, materials whose
  text embedding is closest to the embedding of the label name itself (top 5 above `0.35`). Rows
  in `material_labels` get `assigned_by = "auto"` and the score; the response lists what was
  assigned so the toast can say "назначена: 5 материалов". `DELETE
  /api/materials/<id>/labels/<label_id>` removes one; a removed auto label is kept as a tombstone
  (`assigned_by = "removed"`) so later auto runs never put it back, and user-added rows
  (`assigned_by = "user"`) are never changed by auto runs. New imports get labels whose centroid (mean of the
  members' embeddings, kept in `labels.centroid`) is within `0.45`. Labels filter the list, colour
  the graph nodes and the legend.
- Context flag: `in_context` on the material; only in-context materials are retrieved by the
  extractor's question card and by Ask when "Только материалы «в контексте»" is on.
- "Где используется": atoms whose `evidence.source_id` is the material, and documents whose
  `requirement_ids` include those atoms; meetings appear when Ask or the question card cited the
  material for that meeting (`ask_history.citations_json`). Links open `#/requirements/atom/<id>`,
  `#/document/<id>` or `#/meeting/<id>`.

Acceptance: drop a `.docx`, it appears in the list within the job's time, is indexed, gets labels
from existing clusters when close enough; create a label from a selected material, it lands on the
seed and on its neighbours above the threshold, the toast counts them, the graph recolours; remove
an auto label, re-running auto-assign does not put it back; "Похожие материалы" shows percentages
that match the graph's edges; a "Только локально" project never fetches a URL. Tests:
`test_materials_import` (each type), `test_index` (chunking, cosine, FTS5), `test_labels_auto`
(seeded, unseeded, user override), `test_graph_endpoint`; e2e `library.mjs` (add text, label,
graph node select).

### C6. Спросить: ask across the project

[P] `#ask`: headline + subtitle "всё считается на этом компьютере"; chat card with user bubbles
and answers; each answer has a status line (Найдено в n материалах · model · time) and inline
citations rendered as chips that open the source (meeting at a timestamp, requirement, material);
answers can create entities ("Сделай из этого вопрос для клиента" → a Q atom with quotes); the
composer with "Только материалы «в контексте»" switch and the privacy line; a history column with
previous questions grouped by day.

- `core/ask.py`: retrieve top 12 chunks across `material_chunks` (filtered by `in_context` when
  the switch is on) and `source_embeddings` (segments, atoms) by cosine, add FTS5 hits for exact
  terms, build the prompt with numbered sources (`[Источник N]` with entity, id, locator: segment
  idx or chunk idx), ask the configured LLM (local or Claude, honouring "Только локально"), parse
  citations back into `{n, entity, entity_id, locator}`. Tool-like intents are a second small
  prompt: if the answer requests `create_question`, call the existing atom creation with the
  quotes it cites. Partial text streams into the job exactly as `/summarize` does today (the job's message carries
the text so far; the page polls `/job/<id>`); no second streaming mechanism.
- Routes: `POST /api/projects/<id>/ask` `{question, context_only}` → job id; `GET
  /api/projects/<id>/ask/history`; `DELETE /api/ask/<id>`.
- Frontend: `Ask.svelte`; citations are `<button class="cite">` with `go()` targets;
  `#/meeting/<id>/seg/<idx>` (existing `focusSeg`) and `#/requirements/atom/<id>`.

Acceptance: a question whose answer is only in a material returns a citation to that material;
with the context switch on, a material with `in_context = 0` is never cited; "сделай вопрос"
creates a Q atom with the cited quotes; history persists across restarts; a "Только локально"
project uses the local model only (assert no Claude call in the test). Tests: `test_ask_retrieval`,
`test_ask_citations_parse`, `test_ask_local_only`; e2e `ask.mjs`.

### C7. Шепнуть: voice inbox

[P] `#whisper`: headline, filter switch Все · Открытые · Задачи · Заметки · Напоминания; capture
card with three states: idle (big button, "Нажмите и скажите, что нужно сделать", hints ⌥ Пробел,
menu bar), listening (red pulsing button, "Слушаю…", words appearing, stop on second press or two
seconds of silence), result ("Вы сказали · 0:07 · GigaAM, локально" + the transcript; parsed card
with type chips Задача / Заметка / Напоминание / Идея, editable title, due tag, project tag with
the reason "проект угадан по словам…", "Ещё одно в этой же фразе" when two items were found,
buttons "Сохранить n", "Переговорить", "Отменить"; the privacy line); inbox card with search,
"n открытых", groups Сегодня / Вчера / Раньше, rows with checkbox (tasks and reminders only), kind
icon, text, meta (kind · due · project) and "Сделать вопросом".

- Capture: microphone only, through the existing recorder with one channel into
  `<data>/whispers/<id>/mic.wav`; stop on button or after 2 s of silence once speech was heard
  (`speech_bounds` on the live window, C4.1's tailing); ASR with GigaAM (`transcribe_longform`,
  short file); the live words come from C4.1's live transcriber with `window = 2`. Depends on
  C4.1; on a machine where live mode fell back (C4.1's rule) the words appear after the stop,
  which is acceptable. A whisper is refused while a meeting is being recorded (one recorder).
- Parse (`core/whisper.py`): one LLM call with a fixed JSON schema: `items: [{kind, title, text,
  due: ISO or null, project_hint: string|null}]`, `now` and the project names given in the prompt
  so relative dates ("завтра в десять", "до вечера" = 18:00 today) resolve locally; project
  match is a name/keyword match against project titles and the labels of the current project.
  The raw transcript is always stored. Reminders: `due_at` set and `kind = remind` (or a task with
  a due time); a scheduler thread in the app checks every 30 s and calls the notification function behind
  `/api/notify` directly, once (`notified_at`). Notifications work only while the app runs; say so in Settings.
- Routes: `POST /api/whispers/record/start|stop`, `GET /api/whispers/live`, `POST /api/whispers`
  (save parsed items), `GET /api/whispers?filter=`, `PATCH /api/whispers/<id>` (done, text, kind,
  due), `DELETE`, `POST /api/whispers/<id>/to-question` (creates a Q atom in the linked or current
  project with the transcript as evidence and marks the whisper).
- Hotkey and menu bar (macOS, `core/hotkeys.py`): an `NSStatusItem` with the template glyph
  (`docs/design/icon/dictumTemplate.png`) and a menu (Шепнуть, Показать Dictum, Записать встречу,
  Выйти); a global ⌥Space through `NSEvent.addGlobalMonitorForEventsMatchingMask_handler_`, which
  needs Accessibility permission; if not granted, the hotkey works only while the window is
  focused (document-level key handler) and Settings → Горячие клавиши shows the button to open
  the Accessibility pane. AppKit objects must be created on the main thread: pywebview owns the Cocoa run loop, so
  create the status item and the monitor through `PyObjCTools.AppHelper.callAfter` (or a
  `performSelectorOnMainThread_`) from the `webview.start` callback, never from a Flask thread.
  Windows: document-level only in 5.0.

Acceptance: pressing the button, speaking, and stopping yields a parsed card within 5 s on the
dev machine with the local model; "Напомни завтра в десять позвонить Ирине" produces a reminder
due tomorrow 10:00 local; two actions in one sentence produce two items; the reminder fires a
notification at its time while the app runs; "Сделать вопросом" creates a Q atom and the whisper
shows it; whispers never appear in any project's requirements, documents or exports unless
converted. Tests: `test_whisper_parse_dates` (fixed `now`), `test_whisper_two_items`,
`test_whisper_reminder_scheduler`, `test_whisper_to_question`; e2e `whisper.mjs` with the fake ASR.

### C8. Onboarding and tutorial

[P] `#onboarding`: top bar with logo, "Dictum · первый запуск", six progress bars; steps:

1. Добро пожаловать: headline, lead (local-only sentence), three illustrated panels
   (Записывайте встречи / Проверяйте требования / Собирайте документы, as CSS illustrations in
   the prototype, keep them as components, no bitmaps), terms line, "Начать".
2. Разрешения: Микрофон / Системный звук / Уведомления rows with Разрешено / Не разрешено,
   per-row "Разрешить" and "Системные настройки", "Разрешить всё", "Позже".
3. Модели: speech model cards (GigaAM variants from `/api/asr/models`) and LLM cards (from
   `/api/local-llm` plus "Claude (облако)"), RAM line computed from the machine ("На этом Mac
   32 ГБ памяти и чип M3 Pro"), recommended tag, "Загрузить".
4. Загрузка: per-model progress, "В фоне" continues onboarding while downloads run (status chip
   shows them), "Готово" state with a check.
5. Материалы: discovery checklist from `GET /api/discover` (audio, docx, pdf, md, txt in
   Загрузки, Документы, Рабочий стол, newest 50, not already imported), "Выбрать папку", "Ничего
   не добавлять", "Добавить n и продолжить" (imports into the current project: audio → meetings,
   the rest → materials; the imports are queued behind the model downloads on the same
   `SerialQueue`, so audio picked here is transcribed as soon as the speech model is in place).
6. Всё готово: four cards (Записать, Встречи, Материалы, Спросить) plus Шепнуть and Настройки,
   "Показать подсказки" / "Пропустить".

Tutorial (`Tutorial.svelte`): spotlight with a cut-out over the target element (`t-rec`,
`t-whisper`, `t-list`, `t-library`, `t-ask`) and a tip card with n из 5, Закрыть, Дальше; Esc
closes; reachable again from the help menu.

- Permissions API: `GET /api/permissions` → `{microphone, system_audio, notifications}` each
  `granted | denied | undetermined`; `POST /api/permissions/request/<which>` triggers the system
  prompt (`macos_permissions.microphone_access`, the audio tap support check in
  `macos_audio.support()`, notifications through a first `osascript` call); `POST
  /api/permissions/open-settings/<which>` opens the right pane
  (`x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone` etc.).
- State: `onboarding:v5` in `setup-state.json`; the route guard in `App.svelte` sends a fresh
  install to `#/onboarding` and never again after step 6 (or skip). The e2e suites start from a
  fresh data dir, so `fake_llm_server.py` writes `onboarding:v5 = true` before the app starts
  (and `onboarding.mjs` is the one suite that does not), otherwise every suite would land on the
  onboarding. "Позже" on permissions and a
  closed download are allowed; the first recording re-asks what is missing (today's behaviour).
- The old `FirstRun.svelte` three-row card stays as the empty state of Встречи for projects
  created later (name, AI check, first source), restyled.

Acceptance: fresh data dir → onboarding on first start, main shell on the second; permissions
reflect the real state on macOS; choosing a model starts its download and the status chip shows
it after "В фоне"; discovery lists only candidate files and imports the checked ones into the
right place; the tutorial highlights the five targets in order and does not reappear. Tests:
`test_discover` (filters, limit, already-imported exclusion), `test_permissions_api` (mocked
platform calls), `test_onboarding_state`; e2e `onboarding.mjs`.

### C9. Settings as sections

[P] `#settings`: left column Модели · Приватность · Хранилище · Запись · Jira · Горячие клавиши;
cards per section. Модели: speech cards (GigaAM, installed / active), LLM cards (the real registry:
Qwen3.5 4B, Qwen3.5 9B, Gemma 4 12B, Qwen3.6 35B-A3B, Qwen3.8 27B, Claude), the stats row ("За
неделю на этом компьютере обработано n тыс. токенов · n встреч · n отправлено в облако").
Приватность: "Только локально" per project, consent reminder. Хранилище: the data folder path,
counts and size, "Сменить папку", "Показать", "Хранить аудио рядом с транскриптом". Запись:
microphone, "Останавливать при тишине" with minutes, "Требования на лету", "Живой транскрипт".
Jira: the current connection. Горячие клавиши: list with rebinding by double-click (conflicts
refused), ⌥ Пробел for Шепнуть.

- Stats: the `usage` table (schema v9) gets a row from every local LLM call (prompt + completion
  tokens from llama-server's response), every embedding batch, every transcription (seconds) and
  every cloud call; `GET /api/stats?period=7d` aggregates it.
- "Сменить папку": moves the data dir with a progress job and a restart notice; refuse if the
  target is inside the old one or not writable.
- Hotkeys are the settings `hotkeys` map (§2.1); the frontend key handler and `core/hotkeys.py`
  read the same map; a binding already used by another action or by macOS (⌘Space, ⌘Tab, ⌘Q) is
  refused with a message.

Acceptance: every setting round-trips through `/settings`; the stats row changes after a local
summary; the model cards show "not enough memory" exactly as `/api/local-llm` reports. Tests:
`test_stats_counters`, `test_settings_hotkeys_conflict`.

### C10. Requirements, Documents, Backlog, Export, Skills in the new shell

[P] `#requirements`: headline with counts, actions "Извлечь из новых встреч" and "Проверить n";
scope row (segmented На проверку / Принятые / Все, type chips, "В конфликте · n"); the table in a
card. `#documents`: headline with the staleness sentence, "Сравнить с v2", "Пересобрать ТЗ";
document cards (icon, title, version · date · count, status tag) and a dashed "Новый документ по
скиллу" card. `#backlog`: headline with counts and INVEST remarks, "Проверить INVEST", "В Jira ·
n"; the tree table in a card. Export and Skills: same content in cards. Behaviour, endpoints and
keyboard review on Atoms stay exactly as today; only `Screen` → `Page`, pane chrome → cards, and
tokens change. The Atoms inspector, Document margin notes, Backlog tree, Export stepper and sheet
keep their e2e selectors.

Acceptance: e2e `atoms.mjs`, `bulk.mjs`, `document.mjs`, `backlog.mjs`, `export.mjs`,
`skills.mjs` pass with selector-only updates; `tokens.css` and `Sidebar.svelte` are deleted.

### C11. Release

- Windows parity: the rail, pages and whisper (document-level hotkey) build and run on Windows;
  live transcription on CPU falls back to post-stop transcription automatically (C4.1's rule);
  the installer carries a `.ico` made from `docs/design/icon/dictum-1024.png`.
- `README.md` rewritten for Dictum (what it does, install, keyboard, development, the new routes),
  `CHANGELOG.md` 5.0.0 entry consolidating the alphas, `VERSION` 5.0.0, screenshots in
  `docs/design/5.0/` captured through the e2e harness at 1440 light and dark.
- Build both installers; install the macOS one locally; run every e2e suite against the built
  app's server port.

### C12 (optional, after 5.0). Vault on disk

Markdown mirror of meetings, notes, requirements and documents in `<data>/vault/<project>/` with
wikilinks, written on change and read back by a watcher. Not needed by anything in 5.0; kept here
so nobody designs it out.

---

## 4. API contract summary (new or changed)

| Method, path | Body → response | Chunk |
|---|---|---|
| `GET /api/jobs` | → `[{id, kind, label, progress, cancellable}]` | C1 |
| `GET /api/projects/<id>/sources?q=&sort=` | → list rows with `people, atoms, tags` | C2 |
| `PUT /api/sources/<id>/notes` · `POST .../notes/append` | `{text}` / `{line}` → `{saved_at, text}` | C3 |
| `POST /api/sources/<id>/recap` | `{style, incremental}` → `{job}` | C3 |
| `GET /api/sources/<id>/live?after=` | → `{segments: [...], atoms: [...], listening: bool}` | C4 |
| `POST /desktop-record/pause`, `/resume` | → `{ok}` | C4 |
| `GET/POST /api/projects/<id>/materials` | list `kind = material` sources with their extension; import: multipart files, or `{url}`, or `{text, title}`, or `{folder}` → `{job}` | C5 |
| `GET /api/materials/<id>` · `PATCH` (`title, in_context`) · `DELETE` · `/related` · `/resync` · `/used-in` | `<id>` is the source id | C5 |
| `GET /api/projects/<id>/materials/graph` | → `{nodes, edges}` | C5 |
| `GET/POST /api/projects/<id>/labels`, `DELETE /api/labels/<id>` | create: `{name, seed_material_id?}` → `{label, assigned: [...]}` | C5 |
| `POST/DELETE /api/materials/<id>/labels/<label_id>` | | C5 |
| `GET /api/projects/<id>/search?q=` | → mixed hits (meetings, materials, atoms) | C5 |
| `POST /api/projects/<id>/ask`, `GET .../ask/history`, `DELETE /api/ask/<id>` | | C6 |
| `POST /api/whispers/record/start|stop`, `GET /api/whispers/live`, CRUD `/api/whispers`, `POST /api/whispers/<id>/to-question` | | C7 |
| `GET /api/permissions`, `POST /api/permissions/request/<w>`, `POST /api/permissions/open-settings/<w>` | | C8 |
| `GET /api/discover` | → `{candidates: [{path, kind, size, modified}]}` | C8 |
| `GET /api/stats?period=` | → `{tokens_local, tokens_cloud, meetings, seconds_transcribed, cloud_calls}` | C9 |
| `POST /api/data-dir/move` | `{path}` → `{job}` | C9 |

All job-returning routes use the existing `/job/<id>` polling contract (`{status, progress,
message, result, error}`) and `JobCancelled`.

---

## 5. Data dictionary (new fields the UI shows)

| Entity.field | Type | Source | Shown as |
|---|---|---|---|
| source.notes | Markdown | user | Заметки pane and tab |
| source.recap_style | enum | user | Кратко / По пунктам / Действия |
| source.status `recording` | enum (new value) | app | "Идёт запись" row and pill |
| segment.provisional | bool | live pass | lighter text until the final pass |
| atom.live | bool | live extractor | "n новых" tag |
| source.kind `material` + materials.material_kind | file / url / note | import | type badge, kind filter; hidden from Встречи |
| material.in_context | bool | user, default on | switch and column |
| material.synced_at | time | fetch | "синхр. 2 ч назад" |
| label.color | hex | palette | dot, chip, graph node |
| material_labels.assigned_by, score | user / auto / removed, 0–1 | assign | tooltip "назначена автоматически · 72 %"; removed rows are invisible |
| summaries.style, through_idx | enum, int | recap | style switch; "Обновить по новым репликам" enabled when segments exist past `through_idx` |
| whisper.kind | task / note / remind / idea | parse, user | icon and filter |
| whisper.due_at | time | parse, user | red due tag, green when done |
| whisper.project_id | soft link | parse, user | project tag |

---

## 6. Non-functional requirements

- **Local by default.** With the local LLM selected, no network request leaves the machine for
  AI, indexing, labels, ask or whisper; "Только локально" projects enforce it for URL materials
  too. Verified by a test that patches `urllib` / `httpx` and asserts no calls.
- **Live latency.** Provisional segments appear within `window + 5 s` of speech on an M-series
  Mac with Gemma 4 12B idle; the recorder's write path is never blocked by the live pass (separate
  thread, read-only file access, measured by `test_live` timing with a fake ASR).
- **Index size.** Embedding at 1024 floats per chunk: 1,000 materials × 20 chunks ≈ 80 MB in
  SQLite; acceptable. Graph endpoint returns within 1 s for 500 materials (if the on-demand cosine proves slow, precompute edges at index time into a `material_edges`
  table added in the same v9 migration, empty until used).
- **Accessibility.** Every control reachable by keyboard; focus visible (2 px primary outline);
  contrast of text on tonal surfaces ≥ 4.5:1 (check `--text-2` on `--surface-2` in both themes);
  motion respects `prefers-reduced-motion`.
- **Languages.** UI in Russian and English; transcript language follows the ASR model; prompts
  carry the project's output language rule as today.
- **Windows.** Everything except the menu-bar item and the global hotkey; live transcription
  degrades gracefully on CPU.
- **Data safety.** Schema migration v8 → v9 is additive and idempotent; data-dir rename is a
  single `os.rename` on the same volume, with a copy-then-verify fallback across volumes; recordings
  in progress are never touched by migrations (migration refuses to run while a recording is
  active).

---

## 7. Definition of done, per chunk

1. Backend tests for the chunk added and the whole suite green.
2. `svelte-check` clean, `vite build` committed.
3. The chunk's e2e suite passes against `fake_llm_server.py` (extend the fake server for ASR and
   embeddings: scripted segments, deterministic embeddings = hashed bag of words).
4. `node frontend/scripts/i18n_check.mjs` passes; no raw keys visible in a screenshot pass of the
   chunk's pages in **both languages** (light and dark, 1440 and 390 px) saved under `docs/design/5.0/`.
5. `CHANGELOG.md` entry, `VERSION` bumped, merged to `master` with `--no-ff`.
6. A dmg built and installed for chunks that change recording, storage or packaging (C0, C4, C7,
   C9, C11).

---

## 8. Mapping prototype → chunk, for cross-checking coverage

| Prototype element | Chunk |
|---|---|
| Rail, record button, badges, phone bottom bar, project chip, status chip, theme, help | C1 |
| Pipeline strip, meeting list, search, sort, row states, details panel tabs, rename, footer, "Ещё" | C2 |
| Session header, transcript search/filter, speaker chips, notes editor and format bar, recap styles and "Обновить по новым репликам" | C3 |
| Audio pill, levels, pause, "Слушаю…", "Требования на лету", question card, auto-stop | C4 |
| Kinds, labels with counts and colours, create-and-assign form, add row, Граф / Список / Плитка, graph tools and legend, drop zone, preview, context switch, similar materials, where used, Finder | C5 |
| Chat, citations, status lines, create-question intent, context-only switch, privacy line, history | C6 |
| Capture states, parsed card (types, title, due, project reason, second item), inbox groups, filters, checkbox, "Сделать вопросом", ⌥ Пробел, menu bar | C7 |
| Six onboarding steps, progress bars, panels art, permissions rows, model cards, download, discovery, done cards, tutorial spotlight | C8 |
| Settings sections and cards, model cards with RAM, stats row, storage, record options, hotkeys list | C9 |
| Requirements scope row and table, Documents cards, Backlog tree table, Export and Skills in cards | C10 |
| Dictum name in title, onboarding, folder path | C0 |

---

## 9. Assumptions and decisions left open

- **A1 Bundle id and data folder** change with the rename (`com.heidurrus.dictum`,
  `Application Support/Dictum`), with automatic migration. If keeping the old id is preferred for
  update-in-place reasons, C0 keeps the id and only renames the display name and folder.
- **A2 Inter is bundled** rather than the system font. Reverting is one line in `app.css`.
- **A3 Embedding model.** Default: `Qwen3-Embedding-0.6B` in GGUF (Q8_0, about 600 MB,
  multilingual, runs through the same llama-server with `--embedding --pooling last`). The builder
  pins the Hugging Face repo revision and SHA-256 in `local_llm.EMBED_MODELS` the same way the LLMs
  are pinned, and adds it to the onboarding download step. Alternative if quality on Russian is
  poor in testing: `multilingual-e5-small` (smaller, weaker).
- **A4 Thresholds** (0.45 label assign, 0.30 graph edge, top 12 retrieval) are starting points;
  expose them in a `tuning` block of settings, not in the UI.
- **A5 Live transcription** uses the same GigaAM model as the final pass. If the M1 Pro cannot keep
  a 15 s window under 15 s with the 12B LLM resident, the live pass should pause the LLM server
  (`local_llm` idle stop) while recording and restart it on stop.
- **A6 Whisper reminders** only fire while the app runs. A launch agent for reminders is out of
  scope for 5.0.
- **A7 Question card** ships off by default and only after C5, because without materials it has
  nothing to answer from.
- **Open: ask scope default.** The prototype's switch is on by default ("Только материалы «в
  контексте»"). Meetings and requirements are always searched; the switch only filters materials.
- **Open: Windows menu bar.** Tray icon and global hotkey on Windows are deferred to 5.1.
