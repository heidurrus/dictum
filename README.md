# Dictum

> **По-русски.** Dictum записывает встречи, расшифровывает их на вашем компьютере и превращает разговоры,
> письма и документы в проверенные требования, ТЗ и бэклог для Jira. Интерфейс полностью на русском:
> при первом запуске язык берётся из системы, переключается в Настройки → Интерфейс. Ниже описание на английском.

Dictum is a desktop app for business analysts (called Requirements Workbench up to 4.2). It records your client
calls, transcribes them on your own computer while you talk, and turns meetings, emails and documents into reviewed
requirements, specification documents and a Jira backlog, with every requirement linked to the exact quote it came
from. Around that sit a project library that sorts itself by meaning, answers with citations across everything in
the project, and a private voice inbox for your own tasks and reminders. The AI proposes, you decide: audio never
leaves the machine, and nothing goes to Jira until you confirm the push.

```
record / import → live transcript → requirements → documents → backlog → Jira
```

**[Download the latest release](https://github.com/heidurrus/requirements-workbench/releases/latest)**
for macOS 13+ (Apple Silicon) or Windows 10/11 (x64). Release notes are in [`CHANGELOG.md`](CHANGELOG.md).

## What it does

The navigation rail on the left holds the sections below (⌘1 … ⌘7), the record button on top and Settings at the
bottom; Скиллы and Выгрузка are under «Ещё» and in the ⌘K palette.

| Section | What you get |
|---|---|
| **Встречи** (Meetings) | The home page: every recording, import and text of the project with search over titles and transcripts, a details panel (recap, transcript, notes, requirements) and the pipeline strip. A meeting page shows the transcript as it is spoken, notes with autosave, requirements found on the fly, recap styles (brief, bullets, actions) with an incremental update, pause and resume, and auto-stop after minutes of silence. |
| **Материалы** (Materials) | Files, links and pasted notes of the project, as a list, tiles or a graph of what is similar in meaning. Labels assign themselves to related materials; «Похожие материалы» and «Где используется» per material; keyword search across the whole project. |
| **Требования** (Requirements) | Small, testable statements extracted by the AI, each with a quote checked against its source. Six types: BR, FR, NFR, RSK, AS, Q. Review with the keyboard or in bulk, with undo; duplicates merged, conflicts side by side. |
| **Документы** (Documents) | BRD, SRS, Vision & Scope, risk register, As-Is / To-Be, a GOST 34 specification or your own type, with stable IDs, versions, a quality check, sign-off and Word export. |
| **Бэклог** (Backlog) | Epics, user stories with Given / When / Then criteria, sub-tasks and an INVEST check, then Jira Cloud with a read-only preview (Выгрузка). |
| **Спросить** (Ask) | Questions about the project answered from its meetings, requirements and materials, with source chips that open the exact line, material or requirement; history per project. Can turn an answer into a client question (Q). |
| **Шепнуть** (Whisper) | Say a task, note, reminder or idea; it is transcribed locally, parsed (due dates, the project it belongs to) and lands in a personal inbox that never mixes with project requirements. Reminders arrive as system notifications. |

The instructions behind every AI step are editable skills (Скиллы). The interface is in Russian and English, light
and dark, and works down to phone width.

## Install

- **macOS:** open `Dictum-<version>-macos-arm64.dmg` and drag Dictum to Applications. Builds are not notarized, so the
  first time right-click the app → **Open** → **Open**.
- **Windows:** run `Dictum-<version>-windows-x64.exe`. No admin rights needed; Microsoft Edge WebView2 is installed if
  it is missing.

Nothing else needs to be installed first. **The first run** walks through six steps: welcome, permissions
(microphone, system audio on macOS 14.2+, notifications; on Windows only the microphone applies), models (speech,
index and language model, preselected for your machine), the downloads, candidate files from Downloads, Documents and
Desktop to import, and a short spotlight tour. Every step can be skipped and replayed from Help → Первый запуск заново.

Your data lives in your user folder, not in the app, so updates keep it: `~/Library/Application Support/Dictum` or
`%LOCALAPPDATA%\Dictum`. Settings → Хранилище shows its size and can move it elsewhere.

**Upgrading from 4.x:** the `RequirementsWorkbench` data folder is renamed to `Dictum` on the first start (nothing
downloads again); because the Mac bundle id is now `com.heidurrus.dictum`, macOS asks for the microphone and
system-audio permissions once more.

## Privacy

Speech recognition (GigaAM), the built-in language model and the index model run on your computer. What leaves it
depends only on the providers you choose, and Settings → Приватность says it per engine:

| Engine | What is sent |
|---|---|
| GigaAM speech recognition | Nothing. Audio never leaves the computer. |
| Built-in model (llama.cpp) | Nothing. Meeting and material text is processed locally. |
| Index model | Nothing. Search by meaning is computed locally. |
| Ollama | Text goes to the Ollama server at `OLLAMA_HOST`, usually the same computer. |
| Claude (cloud) | Meeting text, notes and materials go to Anthropic with your API key. |
| Jira | An export sends stories and requirements; quotes follow the project's «Что уходит в Jira» setting. |

A project marked **«Только локально»** (local only) makes no network calls for AI at all: no Claude, links are not
fetched, and there is no silent cloud fallback. Recordings are never deleted by the app: not on stop, auto-stop,
rename, crash or a data-folder move.

## Keyboard

The keys come from one map in the settings and can be changed in Settings → Горячие клавиши.

| Keys (macOS) | Action |
|---|---|
| ⌥ Space | Шепнуть: start and stop a whisper. **Global on macOS**: works from any app and brings Dictum forward |
| ⌘R | Record a meeting (in the Dictum window) |
| ⌘K | Commands and search: any screen, meeting, document, requirement or command |
| ⌘J | Спросить, with the cursor in the composer |
| ⌘1 … ⌘7, ⌘8 | The rail sections in order, Settings |
| ⌘⇧L | Light or dark theme |
| J / K or ↑ / ↓, A, X, E | Move through requirements, accept, reject, edit |
| Space, ⌘A, Esc | Tick a row, tick all, clear |

On Windows use Ctrl instead of ⌘ and Alt instead of ⌥; every key, including Alt+Space, works in the Dictum window
only (there is no menu-bar item or global hot key on Windows). On macOS the menu-bar item offers Шепнуть, Записать
встречу, Показать Dictum and Выйти. Letter keys work on the Russian layout too.

## Models

Settings → Модели shows each model as a card with its size, whether it is installed, and a line about your machine
(«На этом Mac 16 ГБ памяти и чип M1 Pro»).

| Kind | Models | Memory |
|---|---|---|
| Speech (GigaAM) | `v3_e2e_rnnt` (450 MB, recommended for Russian); `multilingual_ctc` (880 MB) and `multilingual_large_ctc` (2.3 GB) for English and other languages | Runs on Apple Silicon GPU, NVIDIA CUDA or CPU |
| Language (llama.cpp, built-in) | Qwen3.6 35B-A3B (17.7 GB), Qwen3.8 27B (16.5 GB) | needs 32 GB of RAM |
| | Gemma 4 12B (7.0 GB), Qwen3.5 9B (5.7 GB) | needs 16 GB of RAM |
| | Qwen3.5 4B (2.7 GB) | needs 8 GB of RAM |
| Index | Qwen3 Embedding 0.6B (639 MB), used by Материалы and Спросить | 4 GB |

Each language-model card says «нужно n ГБ памяти», «не хватает памяти» when the machine is short, and how fast it
will run; the first one that fits and runs at full speed is recommended. Claude (cloud) is a card too, with the API
key field. Ollama also works. Speaker separation (optional) needs a free Hugging Face token and accepting the terms of
the pyannote models.

Live transcription needs a machine that keeps up: when a pass takes longer than its window, the window doubles (up
to a minute), and if it still cannot keep up (typically CPU-only Windows PCs) live mode turns off and the page says
«Транскрипт появится после остановки»; the recording itself is never affected.

## Development

Backend: Flask in `app.py` with modules in `core/`, SQLite through `core/store.py`. Frontend: Svelte 5 (runes) in
`frontend/src`, built into `static/app`, which is committed. Desktop: pywebview from `launcher.py`.

```bash
git clone https://github.com/heidurrus/requirements-workbench.git
cd requirements-workbench
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt   # Python 3.10+
.venv/bin/python launcher.py          # desktop window; --browser opens it in the browser
.venv/bin/python -m pytest -q         # torch is stubbed by tests/conftest.py, no GPU or weights needed
```

Frontend, from `frontend/`:

```bash
npm ci
npm run dev                                          # hot reload against a running app
./node_modules/.bin/svelte-check --threshold warning # must report 0 errors and 0 warnings
npm run i18n                                         # every key in both languages, none untranslated
npm run tokens                                       # the CSS uses only defined design tokens
./node_modules/.bin/vite build                       # commit static/app
```

These gates (pytest, svelte-check, `npm run i18n`, `npm run tokens`) run in CI on every push and pull request.

**End-to-end tests** drive Chrome through `playwright-core` against a stand-in server that stubs torch, speech
recognition, the AI and Jira. Start a fresh server with a fresh data folder for every suite:

```bash
WORKBENCH_DATA_DIR=$(mktemp -d) .venv/bin/python frontend/e2e/fake_llm_server.py 5312 &
node frontend/e2e/smoke.mjs http://127.0.0.1:5312
```

| Suites | Server flags |
|---|---|
| `smoke`, `atoms`, `bulk`, `document`, `skills`, `backlog`, `export`, `meetings`, `meeting`, `library`, `ask`, `settings` | none |
| `session`, `whisper` | `FAKE_RECORDER=1` (a fake microphone and system audio) |
| `onboarding` | `ONBOARDING=1` (the server otherwise marks the first run done) |

`frontend/e2e/restyle_shots.mjs` writes the screenshots in `docs/design/5.0/`. e2e scripts must live in
`frontend/e2e/`, where `playwright-core` resolves.

**Installers:** `.venv/bin/python packaging/build.py --target macos-arm64` builds
`dist/Dictum-<version>-macos-arm64.dmg`; `--target windows-x64` (on Windows, with Inno Setup 6) builds
`dist/Dictum-<version>-windows-x64.exe`. CI builds both on `master`, and a tag `vX.Y.Z` publishes them as a release.

### Repo map

| Path | What |
|---|---|
| `launcher.py`, `boot.py` | Desktop entry point (pywebview window, menu bar) and first-run runtime setup |
| `app.py` | Flask app and the HTTP API |
| `core/` | Storage, recording and live transcription, speech models, local LLM and index, AI steps, ask, whisper, hot keys, permissions, exports, Jira |
| `skills/` | Built-in skills (the prompts behind every AI step) |
| `frontend/src/` | The Svelte UI: `screens/`, `components/`, `lib/` (state, i18n, hotkeys) |
| `frontend/e2e/`, `frontend/scripts/` | End-to-end suites and the stand-in server; the i18n and tokens checks |
| `static/app/` | The built UI, committed |
| `tests/` | pytest suite |
| `packaging/`, `installer/` | `build.py`, macOS launcher and icons, `windows/Dictum.ico`; the Inno Setup script |
| `docs/design/` | Design system, the 5.0 prototype and screenshots (`docs/design/5.0/`), icon sources |
| `docs/specs/` | Product requirements, the 5.0 specification and its increment plan |

## Troubleshooting

| Problem | What to do |
|---|---|
| "ffmpeg is missing" | Restart the app: the startup check reinstalls it. |
| GPU not used (Windows) | Update the NVIDIA driver and restart the app. |
| macOS recording has no call audio | System Settings → Privacy & Security → Screen & System Audio Recording → allow Dictum. |
| ⌥ Space does nothing outside Dictum | Settings → Горячие клавиши shows «занято» when another app holds it; pick another combination. |
| Jira connected to the wrong account | Выгрузка → Подключение → Отключить, then connect again. |
| Summaries or extraction fail | Settings → Модели: add a Claude key or download a built-in model. |

## Credits

Speech recognition by [GigaAM](https://github.com/salute-developers/GigaAM) (Salute Developers), speaker separation
by [pyannote.audio](https://github.com/pyannote/pyannote-audio), local language and index models through
[llama.cpp](https://github.com/ggml-org/llama.cpp) (Qwen, Gemma), desktop window by
[pywebview](https://pywebview.flowrl.com/), interface in [Svelte](https://svelte.dev/) with the
[Inter](https://rsms.me/inter/) typeface.
