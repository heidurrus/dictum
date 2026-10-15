# Changelog

## 5.0.5 (2026-10-15)

- **Whispers and meetings record again after your audio devices change.** Dictum read the list of microphones once, at start; when AirPods, an iPhone microphone or Teams appeared or disappeared later, it tried to open a device macOS no longer had and the whisper failed with an error. The list is now re-read every time a recording starts, and if the chosen microphone is gone, the default one is used. The microphone is remembered by name as well as by number, so it stays the same when devices renumber.
- **A log file for the app.** Warnings and errors from every part of Dictum go to `logs/dictum.log` in the data folder (next to `jobs.log`), so a failure like the one above leaves a trace.
- **The live transcript stays after you stop.** The lines written while recording no longer vanish when the full transcription starts: the meeting page and the Meetings panel keep them, lighter, under a line saying the full transcript is being made, and the full transcript replaces them in one step when it is ready. If the full transcription fails, the live lines stay as the rough version and "Transcribe" runs it again. Recaps, requirement extraction, search, Ask and the index still read only the full transcript.
- The project menu no longer shows the "Local only" / "Claude · cloud" row that only opened Settings. A local-only project still has the lock next to its name; the setting itself is in Settings → Privacy.
- **Choose the meeting's language, not the model.** The record panel on Meetings has a "Meeting language" row, Russian or Multilingual (English and other languages), in place of the model line. It opens with the project's language and remembers the last choice, so a project with English-speaking people starts on Multilingual next time while the other projects stay Russian. If the model behind the language is not downloaded, the row offers its download with the size. The live transcript and the full transcription use the language the recording started with, and the meeting's panel shows a Multilingual tag when that is how it was transcribed.
- Import has the same choice: the arrow next to Import opens the language row and the file picker. Audio and video are transcribed in that language; transcripts and documents come in as before.
- **Settings → Models picks a model per language**: "Model for Russian" and "Model for other languages", each listing only the models for it, with the download and delete cards as before. The model chosen in earlier versions is kept as the model of its language.
- Multilingual transcripts come out in lower case without punctuation: that is what the multilingual GigaAM models produce. The Russian models keep punctuation.

## 5.0.4 (2026-10-15)

- **Business analysis can be switched off per project.** Settings → Project has a new "Business analysis" switch, on by default, so existing projects do not change. Off, the project is a meeting recorder: record, transcribe, recaps, notes, the library, Ask, Whisper and Settings stay; Requirements, Documents and Backlog leave the rail, Export leaves More, and the ⌘K palette, ⌘3–⌘5, the pipeline strip and requirement counts on Meetings, the Requirements tab, Extract requirements, the requirements panel on the meeting page, the Jira section in Settings and the Jira line in Privacy are gone with them. Nothing is deleted: switch it back on and everything that was there is back.
- A project with business analysis off never extracts requirements by itself after a transcription, Ask does not turn an answer into a client question there, and Whisper's "Make a question" offers only projects that have it on.
- A new project can be created with business analysis off: the project menu has a checkbox under the name.

## 5.0.3 (2026-10-15)

- **Ollama is no longer a language model choice.** Settings → Models offers Claude (cloud) and the built-in local model. If Ollama was selected, Dictum switches to the built-in model on start, so nothing goes to the cloud unless you choose Claude; download the built-in model in Settings → Models if you have not yet. The Ollama line is gone from Settings → Privacy and Settings → System, and the `OLLAMA_HOST` setting is no longer read.
- **Requirements are no longer extracted while recording.** The "Requirements on the fly" block on the meeting page and its switch in Settings → Recording are removed. The live transcript, the question card and auto-stop on silence stay, and requirements are extracted from the full transcript after you stop, as before. Requirements already found during earlier recordings stay in the project as ordinary requirements.

## 5.0.2 (2026-10-15)

- **Allowing system audio no longer hangs.** On the first-run Permissions step, Allow for system audio could spin forever when macOS was still showing its prompt or the permission was off. It now answers within a couple of seconds; if no sound came through, it stays "Not allowed" and explains what to do: macOS may be asking right now, or turn on Dictum in System Settings → Privacy & Security → Screen & System Audio Recording, then press Allow again.
- **"Remind about recording consent" can be turned off.** The switch in Settings → Privacy now works and is remembered; with it off, Record starts straight away without the consent question.
- **A calmer "Record a meeting" menu.** The arrow next to Record opens a short panel: the microphone, one line for system audio (with Allow if macOS has not allowed it yet), one line for the speech model with a link to Settings (or a single Download button if it is missing), who-said-what and a full-width Start. The model list, CPU/GPU and word timestamps are in Settings → Models.
- **Archive a project from the project menu.** "Archive project" moved from Settings → Project to the project menu at the top, with a confirmation; archived projects come back from Archived in the same menu.

## 5.0.1 (2026-10-15)

- **The window opens at once.** Starting Dictum used to show nothing for up to a minute while the speech models loaded (the Dock icon bounced, then sat there), which looked like the app had not opened. The window now appears immediately with a "Starting Dictum" page and switches to the app on the same address when it is ready; if the start fails, that page shows the error instead of a silent exit.
- The first-run setup page is titled Dictum (it still said Requirements Workbench).

## 5.0.0 (2026-10-15): Dictum

Requirements Workbench becomes Dictum: a meeting-first app with a live transcript, a knowledge library, answers with
citations and a voice inbox, in a new shell. This entry consolidates the pre-releases 4.9.0 to 4.9.14.

### Name and icon
- **The app is called Dictum.** The Mac app is `Dictum.app` (bundle id `com.heidurrus.dictum`); the downloads are `Dictum-<version>-macos-arm64.dmg` and `Dictum-<version>-windows-x64.exe`. The Windows installer, its shortcuts and the uninstall entry use `Dictum.ico` (16 to 256 px, made from the 1024 px icon). Project exports are written as `dictum-project`; files exported by 4.x still import. `DICTUM_DATA_DIR` overrides the data folder (`WORKBENCH_DATA_DIR` still works).

### Shell
- **A navigation rail** replaces the sidebar: the Dictum mark, the record button, Встречи, Материалы, Требования, Документы, Бэклог, Спросить, Шепнуть, Настройки at the bottom (⌘1 … ⌘8); Скиллы and Выгрузка under «Ещё» and in the ⌘K palette. Требования shows how many requirements wait for review, Документы a dot when a document is out of date. Phone-width windows (≤ 760 px) get a bottom bar.
- **A top bar and page headers**: the project chip (switch, create, archive, «Только локально»; ⌘⇧P), the theme toggle (⌘⇧L), help (Команды и поиск, Подсказки, Первый запуск заново); every screen has a large title with its status line and actions, its content in tonal cards.
- **A tonal theme**, light and dark (following the system or the choice in Settings), with **Inter** bundled (Cyrillic included; nothing loads from the network). Every screen uses the 5.0 tokens; `npm run tokens` fails on a deleted or undefined token.
- **A status chip** says what the machine is doing: «Идёт запись · 12:04», the first job with its progress ring («Распознаю · 42% · 1 задача»), model downloads (cancellable), or «Готово»; a click lists every job. `GET /api/jobs`.
- **One hotkeys map** in the settings drives every shortcut, the tooltips and the palette: ⌘R record, ⌘K commands, ⌘⇧L theme, ⌘J Спросить, ⌥Space Шепнуть, ⌘1…⌘8 the rail. On first start the interface language follows the system (Russian for ru-*, English otherwise).

### Meetings and the meeting page
- **Встречи is the home page** (`#/meetings`; `#/sources` and `#/overview` open it): «<project> · n встреч · n требований», Импорт (⌘O or drop anywhere), Записать встречу; the pipeline strip Встречи · Требования · ТЗ vN · Бэклог · Jira; the list with search over titles and transcript text, sort Новые / Старые / А–Я, kind, date, duration, people, state and requirement count; the details panel with rename in place and tabs Резюме, Транскрипт, Заметки, Требования.
- **The meeting page** (`#/meeting/<id>`; old `#/source/<id>` links open it): the title renamed in place; the transcript with Микрофон / Собеседники chips, search with «2 из 5», Все реплики / С требованиями, click-to-play; **Заметки** in Markdown with a format bar and autosave («Сохранено в 14:02»), shown rendered in the panel; **recap styles** Кратко / По пунктам / Действия (built-in skills), «Обновить по новым репликам» sends only the lines said since the last recap, «Пересобрать» everything; the style is remembered per meeting.

### Live transcript, requirements on the fly, auto-stop
- **A meeting from the first second**: recording creates the meeting and opens its page; the channels are written straight into its folder; Stop finalises the same meeting and transcribes it in full.
- **Live transcript**: every 15 s the new audio of each channel is read (read-only, by byte offset), cut at the last pause and recognised with the GigaAM model you transcribe with; the lines appear as provisional text and the final transcription replaces them. **When the machine cannot keep up** (CPU-only PCs), the window doubles up to a minute and then live mode turns off with «Транскрипт появится после остановки»; errors do the same; the recording is never affected.
- **Pause and resume** in the audio pill and the recording HUD (silence is written, so times stay continuous). A crash mid-recording leaves the WAVs untouched; the next start offers «Расшифровать».
- **Requirements on the fly**: every 90 s, with at least 4 new lines, the normal extractor runs on them (with context) and the requirements appear under the notes with a checkbox that accepts them and a «n новых» tag. After stop the final extraction keeps them; a quote that is gone from the final transcript is marked `stale_evidence`.
- **Answers to questions heard in a call** (setting `live_questions`, off by default): a question in the transcript with a close material «в контексте» gets a two-sentence answer with its source in a card, «Добавить в заметки».
- **Auto-stop on silence** after `silence_stop_minutes` (10 by default; 0 off) without speech on either channel, through the same path as Stop, with a notification and a countdown in the audio pill.

### Materials, index, graph, labels
- **Материалы** (`#/library`): files (.docx .pdf .md .txt .rtf .html .eml), links (fetched once; never in «Только локально» projects), pasted text and folder imports, copied into the data folder; list, tiles or **graph** of materials similar in meaning; the panel with the text, labels, «Включать в контекст ИИ», Открыть, Показать в Finder (Проводнике on Windows). A material is a source, so extraction and evidence work on it.
- **A local index**: Qwen3-Embedding-0.6B (GGUF Q8_0, 639 MB, pinned) in a second llama-server embeds materials, meeting windows and requirements as an «Индексирую» job; «Похожие материалы» with a percentage, «Где используется» (requirements and documents).
- **Labels that assign themselves** by meaning when created («назначена: 5 материалов по смыслу»), on new materials by centroid; removing an automatic label leaves a tombstone so it never comes back; labels set by hand are never changed.
- **Keyword search** across meetings, notes, materials and requirements (FTS5) from the header field.

### Ask
- **Спросить** (`#/ask`, ⌘J): answers from the project's meetings, requirements and materials with source chips at the cited spot (the material, «Встреча · 04:05», the requirement id), streamed, with history per project; «Только материалы «в контексте»»; the composer says whether anything leaves the computer. Asking for a client question creates a Q requirement with evidence. The prompt is the built-in skill **Спросить**; without the index model, keyword search only.

### Whisper
- **Шепнуть** (`#/whisper`, ⌥Space): say a task, note, reminder or idea; the words appear while you speak; the result is parsed into items with type, title, due date and project (date rules in code: «завтра в десять», «до вечера», «через час»…), saved to a **personal inbox** that never reaches project requirements, search, Jira or export. Filters, groups by day, checkboxes, delete with undo, «Сделать вопросом» (a Q requirement on demand). **Reminders** as system notifications while the app runs. The audio is kept.

### Menu bar and hotkey
- **Global ⌥Space on macOS** from any app (Carbon `RegisterEventHotKey`: no Accessibility permission, App Store sandbox friendly); the record key is global too when it is not a plain ⌘ + key. A taken combination is reported («⌥Space занято другой программой»).
- **Menu-bar item on macOS**: Шепнуть, Записать встречу, Показать Dictum, Выйти, a red dot while recording, titles in the interface language; switch in Settings → Горячие клавиши. Windows and browser mode keep the window-level keys only, and the switch is hidden there.

### Onboarding
- **Six first-run steps**, resumable: Добро пожаловать, Разрешения (microphone, system audio, notifications with their real state; Windows: microphone only, the rest «не нужно»), Модели (preselected for the machine: «На этом Mac 16 ГБ памяти и чип M1 Pro»), Загрузка (in the background if you like), Материалы (candidate files from Загрузки, Документы, Рабочий стол, copied, never moved), Всё готово. Then a five-stop **spotlight tour**. Both can be replayed from Help.

### Settings and stats
- **Settings as sections** (`#/settings/<section>`): Проект · Модели · Приватность · Хранилище · Запись · Jira · Горячие клавиши · Интерфейс · Система; every 4.x control is still there.
- **Приватность**: «Только локально», the consent reminder, one line per engine on what leaves the computer.
- **Хранилище**: the data folder with counts and size, «Показать», «Сменить папку…» (the whole folder moves as a job, verified across volumes, refused while recording or downloading; restart afterwards). Audio is never deleted.
- **Запись**: live transcript, requirements on the fly, answers to questions, auto-stop minutes, the default recap style and detail.
- **Горячие клавиши**: every action rebindable by pressing the keys, conflicts and system keys refused, reset per row, status (from any app / in the Dictum window / taken).
- **Stats**: «За неделю на этом компьютере обработано n токенов · n встреч · n отправлено в облако» with tiles, from a `usage` row for every model call, embedding batch and transcription pass.

### Models
- **Model cards** in Settings → Модели and the first run: speech models (GigaAM `v3_e2e_rnnt` recommended for Russian, the multilingual ones for other languages), built-in language models with «нужно n ГБ памяти», «не хватает памяти» and a speed tag, the index model, and Claude (cloud) with its key. A transcription queued while a speech model downloads waits for it.

### Requirements, Documents, Backlog, Export, Skills
- Restyled in the new shell with the same behaviour and keys: Требования with headline counts, scope tabs, type chips and «Проверить n»; Документы as cards with status tags and «Сравнить с v<n-1>»; Бэклог with INVEST counts; Выгрузка and Скиллы in tonal cards.

### Windows
- Parity checked: the data folder stays in `%LOCALAPPDATA%\Dictum`; no global keys or menu-bar item (the UI says the keys work in the Dictum window); permissions other than the microphone read `unsupported`; paths keep Windows separators; key hints show Ctrl / Alt.

### Migration notes
- **The data folder moves by itself**: on the first start `RequirementsWorkbench` (`~/Library/Application Support` or `%LOCALAPPDATA%`) is renamed to `Dictum` before anything can record; projects, recordings, settings, the runtime and models are kept and nothing downloads again (`migrated-from.txt` notes the origin). If a 4.x copy runs or the move fails, the old folder is used and the move is retried next start; if both exist, neither is touched.
- **New bundle id**: macOS asks again for the microphone and system-audio permissions on the first recording. On Windows the old Start menu and desktop shortcuts are replaced.
- **Schema v9** (additive, applied on start): notes and recap styles, provisional segments, live requirements, materials, labels and search, the index tables, ask history, whispers, usage. 4.x project files still import.
- **API**: new routes for jobs, live sessions, materials, labels, search, index, ask, whispers, hot keys, onboarding, permissions, discovery, stats and storage; the old routes keep working. See `docs/specs/dictum-5.0-spec.md` §4.

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
