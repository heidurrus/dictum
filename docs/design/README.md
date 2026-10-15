# Dictum design notes

Where the design of Dictum lives and how to look at it. The app itself is the reference: when this folder and
`frontend/src` disagree, the code wins.

| Path | What |
|---|---|
| [`frontend/src/tokens-m.css`](../../frontend/src/tokens-m.css) | The design tokens: the tonal colour set (light, system dark, forced dark with `data-theme`, more contrast), type sizes and line heights, the 4-px space grid, radii, pane sizes, motion and focus. Every screen uses only these; `npm run tokens` fails the build on a token that is not defined here |
| [`frontend/src/app.css`](../../frontend/src/app.css) | Global styles and the shared pieces (shell, cards, segmented controls, chips, tags, tables) built on the tokens |
| [`icon/`](icon/) | The app icon: `dictum.svg` (source), `dictum-1024.png`, the `.iconset` and `.icns` for macOS, the menu-bar template images, and two HTML sheets: `dictum.html` (the icon at every size, in the Dock light and dark) and `candidates.html` (the variants that were considered) |
| [`prototype-v5.html`](prototype-v5.html) | The clickable prototype of 5.0, one file, no build step. `#onboarding` restarts the first run, ⌘1…⌘8 switch pages, the moon toggles dark. Sample content is invented |
| [`prototype-v5-screens/`](prototype-v5-screens/) | Screenshots of the prototype: the six first-run steps, the tour, every page at 1440 light and dark, and phone width |
| [`5.0/`](5.0/) | 5.0 as shipped: Требования, Документы, Бэклог, Выгрузка and Скиллы in ru and en, light and dark, at 1440 and 390 px (written by `frontend/e2e/restyle_shots.mjs`), and the record menu of Встречи (`frontend/e2e/record_menu_shots.mjs`) |
| [`../specs/dictum-5.0-spec.md`](../specs/dictum-5.0-spec.md) | What is behind the prototype: chunks C0–C11, API, schema, acceptance criteria |
| [`../specs/dictum-5.0-plan.md`](../specs/dictum-5.0-plan.md) | How 5.0 was built, increment by increment, and how each one was checked |

To open the prototype: `open docs/design/prototype-v5.html`. To refresh the 5.0 screenshots, start the e2e
stand-in server on a fresh data folder and run the script:

```bash
DICTUM_DATA_DIR=$(mktemp -d) .venv/bin/python frontend/e2e/fake_llm_server.py 5098 &
node frontend/e2e/restyle_shots.mjs http://127.0.0.1:5098
```

## Principles

1. **The content is the interface.** Chrome stays quiet; colour goes on status and on one primary action per page.
   The analyst's material (meetings, requirements, documents) is what stands out.
2. **The main task comes first.** Each page opens on its main work area; secondary things are a line that expands in
   place.
3. **Keyboard first, visibly.** Every repeated action has a key, and the key is shown where the action is. Focus is
   always visible and never looks like selection.
4. **Trust through provenance.** Every derived item shows where it came from (a source chip, a timestamp, a quote).
   External actions, such as a Jira push, go through a confirmation that states the facts.
5. **Long Russian strings.** Labels wrap before they truncate; controls size to their content.
6. **Calm motion.** Short and ease-out, only to show where something came from or went; with reduced motion it is
   off.
7. **Both themes, both languages, down to phone width.** Every page is checked in light and dark, ru and en, at
   1440 and 390 px.
