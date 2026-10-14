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
| 06 | Live transcript while recording, pause/resume, `recording` source state | C4.1 | 4.9.5 | in progress |
| 07 | Requirements on the fly, auto-stop on silence (question card deferred to 10) | C4.2, C4.3 | 4.9.6 | planned |
| 08 | Materials A: materials as sources, import file/url/text/folder, kinds, in-context, list/grid, FTS5 `search` + `/search` | C5 | 4.9.7 | planned |
| 09 | Materials B: embedding model, index job, related, graph, labels with auto-assign and tombstones, used-in | C5 | 4.9.8 | planned |
| 10 | Спросить with citations and history; question card in the live session | C6, C4.3 | 4.9.9 | planned |
| 11 | Шепнуть: capture, parse, inbox, reminders, to-question (window-level ⌥Space) | C7 | 4.9.10 | planned |
| 12 | Menu-bar item and global hotkey (macOS) | C7 | 4.9.11 | planned |
| 13 | Onboarding, permissions API, discovery, tutorial, e2e gate | C8 | 4.9.12 | planned |
| 14 | Settings sections, stats, storage move, hotkeys UI | C9 | 4.9.13 | planned |
| 15 | Requirements, Documents, Backlog, Export, Skills restyled; old tokens deleted | C10 | 4.9.14 | planned |
| 16 | Release: Windows parity, README, changelog, screenshots, 5.0.0 | C11 | 5.0.0 | planned |

## Log

(one line per increment: date, outcome, what the verification found, what was sent back)
- 2026-10-14 · 01 merged (c34c0f4). 410 tests, dmg 4.9.0 built and installed as Dictum.app; migration code reviewed (rename, copy-verify across volumes, refuses while 4.x runs). Deviation accepted: Windows data stays in LOCALAPPDATA.
- 2026-10-14 · 02 merged (3f58fd5). 410 tests, svelte-check clean, all 7 e2e suites pass on fresh servers; screenshots light/phone OK. Carried into 03: duplicate record FAB on phone width, Transcript's inner crumb duplicates Page's, fake_llm_server should stub torch itself.
- 2026-10-15 · 03 merged (ec98efd). 416 tests, smoke with the chip step passes; chip shows the job and the popover, phone OK. Note: jobs have no cancel endpoint yet (only downloads are cancellable).
- 2026-10-15 · 04 merged (a09b290). 420 tests, i18n parity 1188 keys, 8 e2e suites; home verified in ru and en, dark, phone. Language now follows the OS on first start. Process fix: agents get their own worktree from 05 on (an orchestrator commit landed on 04's branch because the tree was shared).
- 2026-10-15 · 05 merged (c8f2a71). 434 tests, i18n 1236 keys, meeting.mjs in ru and en, screenshots ru/en/dark OK. Recap prompts are built-in skills (recap-brief/-bullets/-actions). Worktree isolation worked; .claude/ added to .gitignore.
