# Requirements Workbench

A desktop app for business analysts. It turns client calls, emails and documents into
reviewed requirements, specification documents and a Jira backlog, and keeps every
requirement linked to the exact quote it came from.

```
record / import → transcribe → requirements → documents → backlog → Jira
```

The AI proposes, you decide. Audio never leaves your computer: speech recognition runs
locally with [GigaAM](https://github.com/salute-developers/GigaAM). Text steps use Claude
or a model that runs on your machine. Nothing goes to Jira until you confirm the push.

**[Download the latest release](https://github.com/heidurrus/requirements-workbench/releases/latest)**
for Windows 10/11 (x64) or macOS 13+ (Apple Silicon). Release notes are in
[`CHANGELOG.md`](CHANGELOG.md).

## What it does

| Step | What you get |
|---|---|
| **Sources** | Record a call (microphone and the other side as separate channels), or drop in audio, video, transcripts (`.vtt`, `.srt`, Teams `.docx`), emails (`.eml`, `.msg`) and documents (`.docx`, `.pdf`, `.txt`, `.md`). Speaker separation, summaries, search. Save the audio back out, each channel separately. |
| **Requirements** | The AI extracts small, testable statements, each with a quote checked against the source. Six types: business (BR), functional (FR), non-functional (NFR), risk (RSK), current state (AS), question (Q). Review with the keyboard or in bulk, with undo. Duplicates are merged, conflicts are shown side by side. |
| **Documents** | BRD, SRS, Vision & Scope, risk register with its matrix, As-Is / To-Be, a GOST 34 specification, or your own type. Each takes the requirement types it needs. Stable IDs, versions, quality check with suggested fixes, sign-off, export to Word. |
| **Backlog** | Epics, user stories with Given / When / Then criteria, sub-tasks, an INVEST check. Your edits survive rebuilds. |
| **Export** | Jira Cloud with a read-only preview first; re-pushing updates issues instead of duplicating them. Also Word, a traceability table (`.xlsx`) and a follow-up letter to the client. |
| **Skills** | The instructions behind every AI step are editable. Try a change on your own data, keep a history, share as `.zip`, choose per project. Word templates with your own layout. |

The interface is in Russian and English, light and dark.

## Install

Nothing needs to be installed first. On first launch the app sets up PyTorch, GigaAM, ffmpeg
and the speech model by itself (a few minutes, once).

- **Windows:** run `RequirementsWorkbench-<version>-Setup.exe`. No admin rights needed.
- **macOS:** open the `.dmg` and drag the app to Applications. Builds are not notarized, so
  the first time right-click the app → **Open** → **Open**. On the first recording, allow
  the microphone and system audio prompts (system audio needs macOS 14.2+).

Your data lives in your user folder, not in the app, so updates keep it:
`%LOCALAPPDATA%\RequirementsWorkbench` or `~/Library/Application Support/RequirementsWorkbench`.

### Set up

| What | Where | Notes |
|---|---|---|
| **AI for requirements** | Settings → ИИ для требований | **Claude**: paste an [Anthropic API key](https://console.anthropic.com/settings/keys); only text is sent. **Built-in**: one click downloads a local model (2.6–6.5 GB) that works offline, less accurate than Claude. **Ollama** also works. |
| **Speech model** | Settings → Запись и распознавание | `v3_e2e_rnnt` (installed by setup) is best for Russian. For English and other languages download `multilingual_ctc` or `multilingual_large_ctc` there; the list shows what is on disk. |
| **Speaker separation** (optional) | Settings → Запись и распознавание | Needs a free [Hugging Face](https://huggingface.co/settings/tokens) token, and accepting the terms of [segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0), [speaker-diarization-3.1](https://huggingface.co/pyannote/speaker-diarization-3.1) and [speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1). |
| **Jira** (optional) | Export → Задачи в Jira | Sign-in opens in a private browser window, so you choose the account. The sign-in is kept in a private file in the app's data folder. |

A project marked **local only** never uses a cloud model.

## Keyboard

| Keys | Action |
|---|---|
| ⌘K | Find any screen, source, document, requirement or command |
| ⌘0 … ⌘5 | Overview, Sources, Requirements, Documents, Backlog, Export |
| J / K or ↑ / ↓ | Move through a list |
| A, X, E | Accept, reject, edit the selected requirement |
| Space, ⌘A | Tick a row, tick all |
| 1 … 4, 0 | Priority: Must, Should, Could, Won't, none |
| [ and ] | Previous and next quality finding in a document |
| ⌘\\, ⌥⌘I, ⌘⇧L | Sidebar, inspector, light or dark theme |

On Windows use Ctrl instead of ⌘. Letter keys work on the Russian layout too.

## Troubleshooting

| Problem | What to do |
|---|---|
| "ffmpeg is missing" | Restart the app: the startup check reinstalls it. |
| GPU not used (Windows) | Update the NVIDIA driver and restart the app. |
| macOS recording has no call audio | System Settings → Privacy & Security → Screen & System Audio Recording → allow the app. |
| Jira connected to the wrong account | Export → Подключение → Отключить, then connect again. |
| Summaries or extraction fail | Settings → ИИ для требований: add a key or download the built-in model. |

## Development

```bash
git clone https://github.com/heidurrus/requirements-workbench.git
cd requirements-workbench
python3 -m pip install -r requirements.txt -r requirements-dev.txt   # Python 3.10+
python3 launcher.py            # desktop window; --browser opens it in the browser
python3 -m pytest              # no GPU or model weights needed
```

The UI is Svelte 5 in `frontend/`, built into `static/app`, which is committed:

```bash
cd frontend && npm install
npm run dev                          # hot reload against a running app
npx svelte-check --threshold warning
npm run build                        # commit the result
```

End-to-end tests drive Chrome against the app with a stand-in for the AI and for Jira.
Use a fresh data folder for each suite:

```bash
WORKBENCH_DATA_DIR=$(mktemp -d) python3 frontend/e2e/fake_llm_server.py 5312 &
node frontend/e2e/smoke.mjs http://127.0.0.1:5312   # also: atoms, bulk, document, skills, backlog, export
```

Installers: `python3 packaging/build.py --target macos-arm64` (or `windows-x64`, which needs
Inno Setup 6). CI tests every push, and a tag `vX.Y.Z` publishes a release with both installers.

| Path | What |
|---|---|
| `launcher.py`, `boot.py` | Entry point and first-run setup |
| `app.py` | Flask app and API |
| `core/` | Storage, recording, AI steps, exports, Jira |
| `frontend/`, `static/app/` | UI source and its build |
| `skills/` | Built-in skills |
| `docs/design/` | Design specification and prototype of the interface |
| `docs/specs/` | Product requirements |

## Credits

Speech recognition by [GigaAM](https://github.com/salute-developers/GigaAM) (Salute Developers),
speaker separation by [pyannote.audio](https://github.com/pyannote/pyannote-audio),
local models through [llama.cpp](https://github.com/ggml-org/llama.cpp).
