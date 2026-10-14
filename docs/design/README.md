# Requirements Workbench: design proposal

This is a design review of the current Svelte UI (v2.9.3), with a proposed design system and a clickable prototype. **Nothing outside `docs/design/` was changed.**

| File | What |
|---|---|
| [`review.md`](review.md) | Critique of the current UI: 12 problems ranked by impact, screen-by-screen notes, references and HIG research |
| [`design-system.md`](design-system.md) | Principles, colour tokens (light and dark) with measured WCAG ratios, type, space, radii, elevation, motion, components, keyboard and focus, responsive rules, and the **migration map onto `app.css`** |
| [`prototype.html`](prototype.html) | A single self-contained file with no dependencies. Screens: Источники, Транскрипт, Атомы (bulk selection works), Документ (diff and *Починить* work), Декомпозиция (keyboard tree), Выгрузка (preview filter, confirmation sheet, push and results), Скиллы (tabs, try-it), Настройки. Light/dark toggle in the toolbar, or *Настройки → Оформление* |
| `current/` | Screenshots of today's app: 1440 and 900, light and dark, plus empty states |
| `prototype-screens/` | Screenshots of the prototype: 1440 light, 1440 dark and 900 light for every screen, plus bulk selection, the confirmation sheet, and diff with fix |

To open the prototype, use `open docs/design/prototype.html`. Things to try:

- **Atoms:** `J`/`K`, `A`, `X`, `Space`, shift-click, `⌘A`, `Esc`, `⌘Z`.
- **Decomposition:** `↑`/`↓`/`←`/`→`/`Space`.
- **Anywhere:** `⌘1…⌘6` to switch screens.

---

## Top 10 changes

| # | Before | After | Why |
|---|---|---|---|
| 1 | `--ink-3` meta text at **3.26:1** (2.82 on the canvas). Input borders at **1.66:1** | `--text-3` #63666D at **5.75:1**. New `--line-control` for control borders at **3.28:1**. Every pair is checked in both themes | Passes WCAG AA (NFR-A11Y-01). Counts and timestamps are what BAs scan all day |
| 2 | A stack of equal white `<details>` cards. On Atoms the list starts at about 720 px | The main work area first. Conflicts become a one-line banner that expands in place. Section headings sit *outside* the cards | The main task is above the fold, and hierarchy comes from placement rather than boxes |
| 3 | Actions scattered (header, card bottom, page bottom), up to 6 mixed controls per header | **One sticky toolbar** on every screen: title and live state on the left, actions on the right, **one primary last**. Lower-priority items move into "…" as the window narrows | Users learn one pattern. The "next step" is always top-right |
| 4 | The rail is a numbered list with no state, fixed at 224 px until 820 px | The sidebar shows **pipeline state badges** (9 to review, v2 stale, ✓ exported), a clearer project switcher with a privacy line, and **auto-collapse to a 60-px icon rail at ≤ 1120 px** (⌘\ to toggle) | You can see where the work is, and a 900-px window keeps about 840 px for content |
| 5 | Toasts persist across screens and cover the bulk bar's *Принять* | Toasts are **screen-scoped**, stacked (at most 2), and sit above the bulk bar. Errors become inline banners with a recovery action. HUD material in both themes | Undo stays reachable. No stale messages |
| 6 | Always-on ✓ ✎ ✕ per row (and 4–5 icons per backlog row). Focus and selection look alike | Row actions **appear on hover or focus** with shortcut tooltips. Focus = an accent bar and ring. Selection = a tint. 28-px checkbox hit areas | About 70 % fewer icons on screen. Keyboard position is always clear |
| 7 | Atoms: identical filter pills, conflict boxes inside rows, hints at the bottom | Status as a **segmented control** and type as **chips** (including "В конфликте"). Conflict shown as one red meta line. A **floating HUD bulk bar** with `A`/`X` chips. An **inspector** with the evidence in context (≥ 1240 px) | Faster review of hundreds of atoms, with evidence visible without leaving the list |
| 8 | Document paper in 14-px UI type, a heavy left rule per block, findings in a block at the top, 6 header controls | A **reading-mode paper** (15/24, a 70-character line) with **hanging FR-n IDs** in the margin, source chips, **quality findings as margin notes** with inline *Починить*, split *Экспорт DOCX ▾* and *Пересобрать ▾* buttons, and a *Сравнить с v1* toggle | It reads like a document and is still traceable |
| 9 | Backlog: a flat indented list and run-on Дано/Когда/Тогда. Export: a flat 21-row list with the push at the bottom | Backlog becomes a **tree table** (E/S/· glyphs, criteria / INVEST / FRD columns, ←/→/Space) with a **criteria table** per story. Export gets a **stepper**, finished steps collapse to summaries, a **filter by action**, a sticky push bar, and a **confirmation sheet with facts** | Structure is visible, and Jira pushes stay explicit and trustworthy |
| 10 | Unbundled IBM Plex (inconsistent between machines), mono for dates and meta, 5-step scale. Dark primary light-blue with dark text | **System fonts** (SF Pro / Segoe UI Variable, both Cyrillic), mono only for IDs and code, a macOS-based scale 11–26 with tabular numbers. Dark primary #2F6DAE with white text | The app looks native and the same everywhere, and dark mode has a real primary |

Proposed IA tweaks, marked as proposals (the six steps plus Skills and Settings stay):

- an Atoms **inspector** pane
- the Document **margin notes** column
- a **⌘K command palette** and a `?` shortcut sheet
- a list **density** setting
- an **Оформление** (theme) row in Settings
- a sidebar step "running" dot

---

## Suggested implementation order (small, safe steps)

Each step ships on its own. The e2e scripts (`frontend/e2e/*.mjs`) find most elements by text and role, but they also use a few class selectors: `.screen-sub`, `.bulkbar`, `.check-all`, `.row-check`, `.pill`, `.src-select`, `.seg-row`, `.counts`, `.list`, `.sec`, `.atom`, `.result`, `.types`. Keep those class names as aliases, or update the scripts in the same PR.

1. **Tokens only (1 PR, `app.css`).** Add the new tokens and alias the old names to them (see the table in `design-system.md` §10). Darken `--ink-3`, split `--rule-2` into `--line-strong` and `--line-control`, fix the dark primary, and remove IBM Plex from `--sans`/`--mono`. *Visual change only; about 60 lines.*
2. **Toast fixes (`Toast.svelte`, `state.svelte.js`).** Clear toasts on route change, allow a 2-item stack, and move the stack above `.bulkbar`. Show inline banners for API errors, and translate the Anthropic error through i18n. *Fixes P3 and the English error.*
3. **Checkbox and hit areas.** A custom `.cb` with a 28-px wrapper, applied to Atoms, Backlog and Export. Add labels to the 16 unlabeled fields (spec issue #14).
4. **Row actions on hover or focus, and focus ≠ selection** (Atoms, Backlog, Sources). CSS plus `:focus-within`, with a roving tabindex on lists.
5. **`Toolbar.svelte`.** Replace `.screen-head` on every screen, one screen per commit. Use `opt-1`/`opt-2` classes and the overflow menu. Put the primaries in the places listed in `design-system.md` §7.2.
6. **Sidebar.** State badges (reuse the counts already in `app` state), collapse at ≤ 1120 px, ⌘\, ⌘1…⌘6, and the project switcher restyle.
7. **Atoms.** The conflict banner that expands in place, segmented status plus type chips, the HUD bulk bar, then (optional) the inspector.
8. **Document.** Paper typography, hanging IDs, source chips, split buttons, then margin notes.
9. **Backlog tree table and criteria table**, then **Export stepper, filter, push bar and sheet**.
10. **Skills tabs, Settings grouped form, empty states**, then the proposals (⌘K, density, `?` sheet).

Steps 1–4 are low-risk polish that fixes every AA failure. Steps 5–6 change the frame. Steps 7–10 are per-screen and can be done in any order.

---

## 5.0: the Foresight-inspired shell (October 2026)

| File | What |
|---|---|
| [`v5-foresight.md`](v5-foresight.md) | Brief for the next shell: Material-style rail and tonal cards, Meetings as the home with a notes pane in the session, a voice inbox (Шепнуть), a real first-run gate, and an Obsidian-like vault for materials. Release order 5.0–5.6 |
| [`prototype-v5.html`](prototype-v5.html) | Clickable prototype, no dependencies. `#onboarding` restarts the first run; ⌘1…⌘8 switch pages; the moon toggles dark |
| `prototype-v5-screens/` | Screenshots of every page at 1440, light and dark, plus a phone width |
| [`../research/foresight-teardown.md`](../research/foresight-teardown.md) | The teardown the brief is based on |
