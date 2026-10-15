# Dictum

Dictum is a desktop app for business analysts. It records client calls, transcribes them on your own computer while
you talk, and turns meetings, emails and documents into reviewed requirements, specification documents and a Jira
backlog, with every requirement linked to the exact quote it came from. Around that sit a project library that sorts
itself by meaning, answers with citations across everything in the project, and a private voice inbox for your own
tasks and reminders. The AI proposes and you decide: audio never leaves the machine, and nothing goes to Jira until
you confirm the push. The interface is in Russian and English, light and dark.

```
record / import → live transcript → requirements → documents → backlog → Jira
```

## Download

**[Download the latest release](https://github.com/heidurrus/dictum/releases/latest)**: macOS 14.2 or later on
Apple silicon (`Dictum-<version>-macos-arm64.dmg`), or Windows 10/11 x64 (`Dictum-<version>-windows-x64.exe`).
Release notes are in [`CHANGELOG.md`](CHANGELOG.md).

- **macOS:** open the `.dmg` and drag Dictum to Applications. Builds are not notarized, so the first time right-click
  the app → **Open** → **Open**.
- **Windows:** run the installer. No admin rights are needed; Microsoft Edge WebView2 is installed if it is missing.

Nothing else needs to be installed first. The first run walks through six steps: welcome, permissions (microphone,
system audio and notifications on macOS; the microphone on Windows), models (preselected for your machine), the
downloads, files from Downloads, Documents and Desktop to import, and a short tour. Every step can be skipped and
replayed later from Help.

The website is **[getdictum.app](https://getdictum.app)**.

## What it does

| Section | What you get |
|---|---|
| **Meetings** | The home page: every recording, import and text of the project, searchable by title and transcript. Record a call (microphone and system audio) and watch the transcript appear as people speak; take notes that save themselves; get a recap in one of three styles (brief, bullets, actions) that updates incrementally; pause, resume, and auto-stop after minutes of silence. |
| **Library** | Files, links and pasted notes of the project as a list, tiles or a graph of what is close in meaning. Labels assign themselves to related materials; each material shows similar materials and where it is used; keyword search covers the whole project. |
| **Ask** | Questions about the project answered from its meetings, requirements and materials, with citations that open the exact line, material or requirement. An answer can become a client question. |
| **Whisper** | Say a task, note, reminder or idea. It is transcribed locally, parsed (due date, the project it belongs to) and lands in a personal inbox that never mixes with project requirements. Reminders arrive as system notifications. On macOS ⌥ Space starts it from any app. |
| **Requirements** | Small, testable statements extracted by the AI, each with a quote checked against its source. Six types: BR, FR, NFR, RSK, AS, Q. Review with the keyboard or in bulk, with undo; duplicates are merged and conflicts shown side by side. |
| **Documents** | BRD, SRS, Vision & Scope, risk register, As-Is / To-Be, a GOST 34 specification or your own type, with stable IDs, versions, a quality check and sign-off. |
| **Backlog → Jira** | Epics, user stories with Given / When / Then criteria, sub-tasks and an INVEST check, then a push to Jira Cloud after a read-only preview. A retry finds what was already created instead of duplicating it. |
| **Skills** | The instructions behind every AI step are editable skills: change a prompt, add an example, or create your own document type. |
| **Meetings only** | Business analysis can be switched off per project (Settings → Project): requirements, documents, the backlog and Jira are hidden and Dictum is a meeting recorder with recaps, notes, the library and Ask. Switching it back on brings everything back; nothing is deleted. |
| **Export** | Jira, Word documents (standard or GOST templates), a traceability matrix in Excel, a follow-up letter with the open client questions, and the whole project as one file to move to another machine. Project files exported by 4.x still import. |

⌘K opens commands and search over every page, meeting, document and requirement; keys can be changed in Settings.

## Privacy

Everything runs on your computer by default: speech recognition, the built-in language model and the index behind
the library and Ask. The models are downloaded on the first run and kept in the data folder; after that the app
needs the internet only for what you ask of it (links you add, Jira, Claude).

| Engine | What is sent |
|---|---|
| Speech recognition | Nothing. Audio never leaves the computer. |
| Built-in language model | Nothing. Meeting and material text is processed locally. |
| Index | Nothing. Search by meaning is computed locally. |
| Claude (cloud, optional) | Meeting text, notes and materials go to Anthropic, only with your own API key. |
| Jira (optional) | An export sends stories and requirements; whether quotes go too is a per-project setting. |

A project marked **local only** makes no network calls for AI at all: no Claude, links are not fetched, and there
is no silent cloud fallback. Settings → Privacy says what goes where, per engine. Recordings are never deleted by
the app: not on stop, auto-stop, rename, crash or a move of the data folder.

## Models

Settings → Models shows each model as a card with its size, whether it is installed, and whether your machine can
run it. The registry is in [`core/asr_models.py`](core/asr_models.py) and [`core/local_llm.py`](core/local_llm.py).

| Kind | Model | Size | Needs |
|---|---|---|---|
| Speech | `v3_e2e_rnnt`, the built-in Russian model (default) | 450 MB | Apple silicon GPU, NVIDIA CUDA or CPU |
| | `multilingual_ctc` for English and other languages; `multilingual_large_ctc` is the larger variant | 880 MB; 2.3 GB | |
| Language | Qwen 3.6 35B-A3B | 17.7 GB | 32 GB of RAM |
| | Qwen 3.8 27B | 16.5 GB | 32 GB of RAM |
| | Gemma 4 12B | 7.0 GB | 16 GB of RAM |
| | Qwen 3.5 9B | 5.7 GB | 16 GB of RAM |
| | Qwen 3.5 4B | 2.7 GB | 8 GB of RAM |
| | Claude (cloud) | none | your Anthropic API key |
| Embedding | Qwen3 Embedding 0.6B, used by Library and Ask | 639 MB | 4 GB of RAM |

The language models run through [llama.cpp](https://github.com/ggml-org/llama.cpp), which Dictum downloads and
manages. The first model that fits your memory and runs at full speed is recommended. Speaker separation is optional
and needs a free Hugging Face token and accepting the terms of the pyannote models.

## Requirements for the machine

- **Mac:** Apple silicon, macOS 14.2 or later (recording the other side of a call uses the system-audio capture
  that arrived in 14.2). 16 GB of RAM for the recommended local models; 8 GB runs the smallest one.
- **Windows:** Windows 10 or 11, x64. An NVIDIA GPU makes transcription much faster; without one, live
  transcription may fall back to transcribing after the recording stops, and the recording itself is never affected.
- **Disk:** a few GB for the runtime and the speech model, plus the language models you choose.

## Data folder

Your data lives in your user folder, not in the app, so updates keep it:

- macOS: `~/Library/Application Support/Dictum`
- Windows: `%LOCALAPPDATA%\Dictum`
- Anywhere else: set `DICTUM_DATA_DIR` to a folder before starting the app (tests and portable setups do this).

Settings → Storage shows the folder's size and can move it. A 4.x data folder is moved to `Dictum` on the first start,
so nothing downloads again.

## Development

Backend: Flask in `app.py` with modules in `core/`, SQLite through `core/store.py`. Frontend: Svelte 5 (runes) in
`frontend/src`, built into `static/app`, which is committed. Desktop: pywebview from `launcher.py`.

```bash
git clone https://github.com/heidurrus/dictum.git
cd dictum
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt   # Python 3.10+
.venv/bin/python launcher.py          # desktop window; --browser opens it in the browser
.venv/bin/python -m pytest -q         # torch and the speech package are stubbed by tests/conftest.py
```

Frontend, from `frontend/` after `npm ci`:

| Command | What |
|---|---|
| `npm run dev` | Hot reload against a running app |
| `npm run build` | Build into `static/app` (commit the result) |
| `npm run check` | svelte-check (CI runs it with `--threshold warning`: 0 errors and 0 warnings) |
| `npm run i18n` | Every key in both languages, none left untranslated |
| `npm run tokens` | The built CSS uses only defined design tokens |

**End-to-end suites** drive Chrome through `playwright-core` against a stand-in server,
`frontend/e2e/fake_llm_server.py`, which stubs torch, speech recognition, the AI and Jira. Start a fresh server on a
fresh data folder for every suite:

```bash
DICTUM_DATA_DIR=$(mktemp -d) .venv/bin/python frontend/e2e/fake_llm_server.py 5312 &
node frontend/e2e/smoke.mjs http://127.0.0.1:5312
```

| Suites | Server flags |
|---|---|
| `smoke`, `atoms`, `bulk`, `document`, `skills`, `backlog`, `export`, `meetings`, `meeting`, `library`, `ask`, `settings` | none |
| `session`, `whisper` | `FAKE_RECORDER=1` (a fake microphone and system audio) |
| `onboarding` | `ONBOARDING=1` (otherwise the server marks the first run done) |

e2e scripts must live in `frontend/e2e/`, where `playwright-core` resolves.

**Installers:** `.venv/bin/python packaging/build.py --target macos-arm64` builds
`dist/Dictum-<version>-macos-arm64.dmg`; `--target windows-x64` (on Windows, with Inno Setup 6) builds
`dist/Dictum-<version>-windows-x64.exe`. CI runs the tests on every push and builds both installers on `master`; a
tag `vX.Y.Z` publishes them as a release.

## Repository layout

| Path | What |
|---|---|
| `app.py` | Flask app and the HTTP API |
| `launcher.py`, `boot.py` | Desktop entry point (window, menu bar) and the first-run runtime setup |
| `core/` | Storage, recording and live transcription, speech models, local language models and the index, AI steps, Ask, Whisper, hot keys, permissions, exports, Jira |
| `skills/` | Built-in skills: the prompts behind every AI step |
| `frontend/src/` | The Svelte UI: `screens/`, `components/`, `lib/` (state, i18n, hot keys), `tokens-m.css` |
| `frontend/e2e/`, `frontend/scripts/` | End-to-end suites and the stand-in server; the i18n and tokens checks |
| `static/app/` | The built UI, committed |
| `tests/` | pytest suite |
| `packaging/`, `installer/` | `build.py`, the pinned runtime, the macOS launcher and icons; the Inno Setup script for Windows |
| `site/` | The website, getdictum.app |
| `docs/design/` | Design notes: tokens, icon, the 5.0 prototype and screenshots |
| `docs/specs/` | The 5.0 specification and its increment plan |
