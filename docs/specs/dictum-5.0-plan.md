# Dictum 5.0: increment plan and log

Process: the orchestrator (the main session) writes a brief per increment; a fresh dev agent
builds it on branch `inc/NN-<name>` with tests, `svelte-check` and the build committed, and
reports; the orchestrator verifies (pytest, e2e where relevant, screenshots, a dmg for increments
that touch recording, storage or packaging), merges with `--no-ff` into `master`, bumps nothing
itself (the increment sets `VERSION` and the changelog), and writes the next brief. The user
pushes and tags. Spec: `dictum-5.0-spec.md`. Pre-release versions are `4.9.N`.

Sizing rule: one increment = one agent run of roughly 2 to 4 hours of focused work, touching at
most one backend module and two or three Svelte files, with its own tests. Nothing in an increment
depends on an unmerged one.

| # | Increment | Spec | Version | Status |
|---|---|---|---|---|
| 01 | Rename to Dictum, data-dir migration, bundle id | C0 | 4.9.0 | merged |
| 02 | Shell A: tonal tokens, Inter, Rail, Page, TopBar, theme, phone bar; old screens inside; Sidebar removed | C1 | 4.9.1 | merged |
| 03 | Shell B: `/api/jobs`, status chip with jobs popover, `hotkeys` settings map, key handler, palette routes | C1 | 4.9.2 | merged |
| 04 | Встречи home: list, search (LIKE), sort, panel with tabs, rename, pipeline strip; Overview removed | C2 | 4.9.3 | merged |
| 05 | Meeting page: transcript search/filter, notes pane with append, per-style recap with incremental update | C3 | 4.9.4 | merged |
| 06 | Live transcript while recording, pause/resume, `recording` source state | C4.1 | 4.9.5 | merged |
| 07 | Requirements on the fly, auto-stop on silence (question card deferred to 10) | C4.2, C4.3 | 4.9.6 | merged |
| 08 | Materials A: materials as sources, import file/url/text/folder, kinds, in-context, list/grid, FTS5 `search` + `/search`, manual labels | C5 | 4.9.7 | merged |
| 09 | Materials B: embedding model, index job, related, graph, labels with auto-assign and tombstones, used-in | C5 | 4.9.8 | merged |
| 10 | Спросить with citations and history; question card in the live session | C6, C4.3 | 4.9.9 | merged |
| 11 | Шепнуть: capture, parse, inbox, reminders, to-question (window-level ⌥Space) | C7 | 4.9.10 | merged |
| 12 | Menu-bar item and global hotkey (macOS, Carbon hot keys so the App Store sandbox allows it) | C7 | 4.9.11 | merged, hand check pending |
| 13 | Onboarding, permissions API, discovery, tutorial, e2e gate | C8 | 4.9.12 | merged, hand check pending |
| 14 | Settings sections, stats, storage move, hotkeys UI | C9 | 4.9.13 | merged |
| 15 | Requirements, Documents, Backlog, Export, Skills restyled; old tokens deleted | C10 | 4.9.14 | merged |
| 16 | Release: Windows parity, README, changelog, screenshots, 5.0.0 | C11 | 5.0.0 | merged |
| 17 | Hand-test feedback 1: system-audio Allow no longer hangs, consent reminder toggle, calm record panel, archive in the project picker | C8, C9, C2 | 5.0.2 | merged |
| 18 | Hand-test feedback 2: remove Ollama and requirements on the fly | C4.2, C9 | 5.0.3 | merged |
| 19 | Per-project switch: business analysis off makes Dictum a meeting recorder | C9, C2 | 5.0.4 | in review |

## Log

(one line per increment: date, outcome, what the verification found, what was sent back)
- 2026-10-14 · 01 merged (c34c0f4). 410 tests, dmg 4.9.0 built and installed as Dictum.app; migration code reviewed (rename, copy-verify across volumes, refuses while 4.x runs). Deviation accepted: Windows data stays in LOCALAPPDATA.
- 2026-10-14 · 02 merged (3f58fd5). 410 tests, svelte-check clean, all 7 e2e suites pass on fresh servers; screenshots light/phone OK. Carried into 03: duplicate record FAB on phone width, Transcript's inner crumb duplicates Page's, fake_llm_server should stub torch itself.
- 2026-10-15 · 03 merged (ec98efd). 416 tests, smoke with the chip step passes; chip shows the job and the popover, phone OK. Note: jobs have no cancel endpoint yet (only downloads are cancellable).
- 2026-10-15 · 04 merged (a09b290). 420 tests, i18n parity 1188 keys, 8 e2e suites; home verified in ru and en, dark, phone. Language now follows the OS on first start. Process fix: agents get their own worktree from 05 on (an orchestrator commit landed on 04's branch because the tree was shared).
- 2026-10-15 · 05 merged (c8f2a71). 434 tests, i18n 1236 keys, meeting.mjs in ru and en, screenshots ru/en/dark OK. Recap prompts are built-in skills (recap-brief/-bullets/-actions). Worktree isolation worked; .claude/ added to .gitignore.
- 2026-10-15 · 06 merged (dcb0997). 454 tests, i18n 1247, session.mjs ru/en with FAKE_RECORDER=1; live reader audited (read-only, no file ops). dmg 4.9.5 built from the worktree for a real-recording check by the user. Deviation accepted: stop only transcribes when options are sent (the client always sends them).
- 2026-10-15 · 07 merged (333b7b2). 479 tests, i18n 1256, session.mjs ru/en shows a live requirement; sent back once (stale_evidence not cleared on merge), fixed. Speech floor -50 dBFS for auto-stop accepted.
- 2026-10-15 · 08 merged (c6999de). 508 tests, i18n 1326, library.mjs ru/en, 11 suites; screenshots OK. Known: FTS5 prefix search misses Russian endings (no stemmer); folder import takes a typed path. material_chunks deferred to 09.
- 2026-10-15 · 09 merged (18e833d). 541 tests, i18n 1343, library.mjs ru/en with the graph and auto-labels; graph screenshot OK. Embedding model pinned (Qwen/Qwen3-Embedding-0.6B-GGUF Q8_0, 639 MB) on a second llama-server. Carry to 14: the index model must appear in Settings → Модели (download is offered in Материалы for now).
- 2026-10-15 · 10 merged (3b6edc9). 582 tests, i18n 1381, ask.mjs ru/en, session with the question card; Ask screenshot OK. The ask prompt is skills/ask/SKILL.md with a fixed citation contract in core/ask.py. live_questions has no UI toggle yet (14).
- 2026-10-15 · 11 merged (d91e1e7). 614 tests, i18n 1446, whisper.mjs ru/en with FAKE_RECORDER, 13 suites; screenshot OK. Date rules applied in code over the model's output. Post-5.0 idea noted: English speech engine (Parakeet TDT via sherpa-onnx, Whisper via whisper.cpp).
- 2026-10-15 · 12 merged (95c8258). 659 tests, i18n 1454, 13 suites; Cocoa/Carbon path reviewed (callAfter from webview.start, every call wrapped), not launched here: user to check the glyph, ⌥Space from another app, menu language, red dot while recording, Выйти keeps the WAV. ⌘R stays window-only by design.
- 2026-10-15 · 13 merged (ce4c63f). 682 tests, i18n 1580, onboarding.mjs ru/en (20 steps) + 13 suites; welcome screenshot OK. Hand check: real permission prompts, download progress, discovery on real folders, tutorial at narrow widths. Help menu now has Подсказки and Первый запуск заново.
- 2026-10-15 · 14 merged (4dcacf1). 696 tests, i18n 1711, settings.mjs ru/en + 14 suites; model cards screenshot OK (machine line, RAM tags, index model). Data-dir move writes a pointer file in the default folder; refused while recording/downloading or with DICTUM_DATA_DIR set.
- 2026-10-15 · 15 merged (fe9dcaa). 696 tests, i18n 1731, tokens check (old set deleted), 15 suites; 40 screenshots in docs/design/5.0. Deviations accepted: Документы cards double as the switcher (no list screen), 'Извлечь из новых встреч' is a per-meeting menu (no bulk endpoint).
- 2026-10-15 · 16 merged (b8e8dae). 701 tests, i18n 1735, tokens check, CI yaml valid, 15 suites; README and the consolidated 5.0.0 changelog reviewed. Windows left to check on a real machine: Alt+Space may be taken by the window menu; the taskbar may show Python's icon (no launcher exe). 5.0.0 dmg built and installed; the user pushes master and tags v5.0.0.
- 2026-10-15 · 5.0.1 (b1c0d8f), orchestrator fix, no agent. First launch of 5.0.0 showed no window for 64 s (process 10:55:45, window 10:56:49: torch + speech package import before the window), read as "app not opening". The launcher now serves a starting page at once and imports the app on a thread, handing over on the same port like the setup screen; a failed import is shown on that page. 3 launcher tests added (703 total). dmg 5.0.1 built; install waits until the running copy is quit.
- 2026-10-15 · 17 merged (f23ea23). 707 tests, i18n 1747, 15 suites by the agent; dry-run fix reviewed (reader thread, bounded wait, tap closed by whoever finishes last), record panel screenshots ru/en OK. Hand check: the real macOS system-audio prompt. Note for the user: ad-hoc signing makes TCC re-prompt after every build (Developer ID would fix it).
- 2026-10-15 · 18 merged. 692 tests, i18n 1728, 15 suites by the agent; session.mjs re-run here; greps clean except the migration fixture. Deviation accepted: pending requirements found live in earlier recordings are no longer protected from re-extraction. 5.0.3 dmg built and installed.
- 2026-10-15 · docs sweep merged (082c808): README rewritten for 5.0.3, stale 4.x docs deleted, specs and comments scrubbed of the old names; code identifiers kept for compatibility. 692 tests.
