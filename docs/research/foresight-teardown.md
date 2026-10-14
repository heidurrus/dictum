# Google AI Edge Foresight 1.0.0.28: interface teardown

Static analysis of `foresight_mac.dmg` (build 1.0.0.28.20261005, bundle `com.google.AIEdgeForesight`),
done 14.10.2026 without running the app. Sources: `Info.plist`, the Flutter asset bundle, the Dart AOT
snapshot (source paths, class names, UI strings, prompts), the bundled launch agent, and the onboarding
artwork. Nothing here is from Google documentation; where I infer, I say so.

## 1. What it is

A Mac meeting assistant for knowledge workers, framed as a "second brain": it records calls, keeps a
local knowledge library (Drive, local folders, URLs, pasted transcripts), enhances shorthand notes
with the transcript, answers spoken questions live in a floating HUD, and chats over everything with
citations. Google calls it experimental. Requirements: macOS 14.2+, Apple Silicon, Google account
(Drive, Calendar, Docs and Slides read scopes plus an `aiedge` scope).

## 2. How it is built

| Layer | What |
|---|---|
| UI | Flutter 3 / Dart, Material 3 Expressive (internal `material_ui` package), Google Sans Flex variable font, Google Symbols icons. Impeller disabled. |
| Native | One AppKit window; Carbon hot-keys; Google Sign-In; Keystone updater; Firebase Messaging for Calendar push. |
| Inference | A separate **launch agent** (`ForesightHelper`, v1.0.3) hosts LiteRT-LM, ML Drift (Metal/WebGPU) and a `RagService` over gRPC on a Unix socket: `ChunkText`, `ComputeEmbedding`, `ComputeImageEmbedding`, `ComputeAudioEmbedding`, `IndexDocument`, `RetrieveContext`, `TruncateText`, `UpdateModelPaths`, `Ping`. The app shows its state in Settings ("Launch Agent Monitor": Running / Not Running / version mismatch). |
| Models | Gemma 4 E2B (needs 6 GB), E4B (15 GB) or 12B (30 GB), chosen on the Model Selection page; EmbeddingGemma V2 for retrieval; a Gemma-4 200M + USM 300M speech model ("TinyGemma ASR") for transcription; a small on-device query detector; optional "expert models". Config in `lib/assets/on_device_model_configure.json` (temperature 0.4, top-k 40, top-p 0.9, 4096 context, speculative decoding). Downloaded from Google servers after sign-in. |
| Storage | Drift (SQLite) with an encrypted-file layer. Tables: Notes, SourceText, ContextSourceText, EventTranscript, EventDocument, EventInsight, DocumentEmbeddings, DocumentEdges, DocumentClusters, DocumentLabels, DocumentEntities, DocumentEntityState, GraphRagDocumentState, Nodes, NodeEmbeddings, Edges, Contacts, DriveFileSubscription, ProcessedUri. So: a document graph with labels and clusters, plus GraphRAG. |
| Audio | CoreAudio process tap + aggregate device for system audio, separate microphone recorder, mixed when both run. Speakers are labelled **Microphone / System / Unknown**; there is no diarization. Transcription languages: about 40 (one spoken "transcription started" chime per language). |
| Files | Local parsers for PDF, DOCX, PPTX, XLSX, ODT, EPUB, TXT/MD, HTML; images and audio are embedded directly (omnimodal search). |

## 3. The interface

### 3.1 Onboarding flow (`onboarding_flow.dart`)

1. **Intro**: "Welcome to Google AI Edge Foresight", notice that models will be downloaded, terms +
   Generative AI prohibited-use policy + privacy policy as inline links, "Get Started". Three
   illustrated panels (the artwork is in the bundle): (a) the dark floating HUD answering "Why is it
   important?" / "How does that work?" with "Ask Foresight a question…" at the bottom; (b) three
   source cards (Slides, URL, Docs) each with "Synced 1 min ago" and an "Include in meeting context"
   checkbox, feeding the HUD; (c) the same cards behind a shield: privacy.
2. **Sign in** (`fam_sign_in_page`): Google account; an admin can block the app for a Workspace account.
3. **Permissions** (`permissions_page`): Microphone, System audio, Notifications; each row shows
   Allowed / Denied, a "Grant All Permissions" button, per-item "open System Settings" guidance, and
   an explainer "How AI Edge Foresight uses audio".
4. **Model selection** (`model_selection_page`): one card per Gemma size with RAM requirement,
   "recommended", "downloaded" badge, "click to download"; an info panel explaining on-device models.
5. **Model download** (`model_download_page`) with progress, then "Getting Foresight ready for you…"
   (downloading expert models, setting up knowledge sources).
6. **Knowledge import disclaimer** then **local file discovery**: the app scans Downloads, Documents
   and Desktop for documents not yet in the library and offers a checklist to import ("Choose a
   folder instead" if nothing is found).
7. **Tutorial overlay** with four spotlight steps: start a meeting recording, access meetings,
   manage sources, control chat answers (knowledge-only vs. web). "Access this tutorial again anytime
   from the help center."

### 3.2 Main shell

A Material **navigation rail** with four destinations: **Meetings**, **Ask**, **Stats**, **Settings**.
Top bar: a "Powered by Gemma" chip, an activity status chip with a tooltip (what is indexing or
downloading, task counts), a Gemma token tracker, an account switcher, a help menu (start tutorial,
contact us, file a bug). A status-bar (menu bar) icon with "Show Foresight" (default hot-key
⌘⇧F), "Start Foresight Session", "Mute Notifications", "Quit".

### 3.3 Meetings (home)

- **Daily briefing**: "Recommended: Today's agenda", upcoming Google Calendar events with attendees,
  recurrence, a refresh button and "Link scheduled meeting". For each event a **Meeting Brief**
  (preparation summary from calendar attachments and past meetings), **Attachments Summary**, and
  the attachments themselves as cards with Docs/Sheets/Slides icons and "Include in meeting context".
- **Recent meetings**: rows with meeting content tags (Calendar / Foresight), a search box
  ("Search meetings"), sort (most recent, oldest, A–Z), and a details panel on the right
  (`home_meeting_details_panel`) with tabs **AI summary / Transcript / Notes / Recap / Live Q&A**.
- **Start recording popover**: "Start Foresight Session" either linked to a calendar event or an
  empty session ("Need to manually add the meeting title and context"), with a consent reminder
  popover before transcription starts.
- **Export meeting notes** view: date range (today, 7/30/90 days, custom, anytime), filter, "Download
  as" or "Copy content", with a tip that pasting as Markdown keeps formatting.

### 3.4 Note session (the core screen, `note_edit_dialog/`)

Opens as a large dialog with an **immersive** and a **non-immersive** layout.

- Header: title input (or the linked event name), recording timer, an **audio control pill**
  (start / pause / stop with gradient ripples while listening), "Link scheduled meeting".
- **Session tabs panel** on the side: several note sessions can be open at once.
- Two panes: **Shorthand** (a Markdown editor with a formatting bar: bold, italic, heading, bullet
  list, numbered list; placeholder "Enter your notes here. Markdown formatting is supported.") and
  **Enhanced notes** (read-only Markdown, with copy / edit / expand / collapse, a "Live enhanced
  notes" toggle, and "Enhancement up to date" state). Status line while working: "Evaluating
  scribbles…", "Retrieving chunks…", "Structuring notes…".
- **Transcription view** underneath or as a tab: lines labelled Microphone / System, "Listening…",
  a transcript navigator, "Copy transcript", "Clear transcript".
- **Question detected overlay**: when the on-device query detector hears a question in the call, a
  card slides in with the detected question and the grounded answer ("Add to notes" puts it into the
  shorthand pane as a topic).
- Recap tab: a **streaming summary card** with transcript styles **Executive Summary / Bulletized
  Recap / Action Items**, "Update summary", "Re-summarize", confidence score, topics discussed that
  are not in the notes.
- Auto-stop: "Automatically stop transcribing and finalize notes when no speech or audio is detected"
  (silence timeout in minutes, in Settings), with a notification when that happens.

### 3.5 AI sidecar / HUD (`ai_sidecar/`, `floating_eye.dart`, `window_service.dart`)

A compact dark floating window shown over Meet/Zoom/Teams (the onboarding artwork shows it docked
right of a Google Meet window): logo, a clear button, **A− / A+** font size, a stack of
**proactive cards** (question as heading, answer as text, × to dismiss), and a single input "Ask
Foresight a question…". A small "floating eye" widget appears when the sidecar is collapsed.
The sidecar listens to the transcript stream and only reacts while transcribing.

### 3.6 Ask (chat, `chat_page.dart`)

Full-page chat "Ask Foresight about your meetings" with: a **web search toggle** (answers are
marked "Answer includes web search results" / "does not use web search"; the setting is explained
in the tutorial as "control chat answers"), status lines ("Searching through your Knowledge
Sources", "Searching the Web", "Generating the response"), answers with `[Source:N]` citations
rendered as hover previews of the source (text or image thumbnails), an **Insights history** (every
answer is stored, can be copied or deleted), a **voice command** mode ("Tap to Speak", "Speak to
create an event…", which creates a calendar event from speech), and a "Create calendar event"
intent.

### 3.7 Knowledge sources (`context_management_page.dart`)

Title "Knowledge Sources", counters ("Knowledge sources added"), search ("Search knowledge
sources…"). Left column of **add** actions: Add Files (text, PDF, Office documents), Add from URL,
Add files from Drive, Add an entire Drive folder (with "Include subfolders"), Import folder (local),
Import last 1 year from Drive, Import Custom Transcript (paste text). A drop zone: "Drop a text,
PDF, or DocX file here. Its content will be indexed and search-ready locally." Import can be paused
and resumed; a queue shows "Awaiting import…", "Importing…", "Imported just now".

Three views: **List** (columns Name, Labels, Imported, Last changed, Actions), **Grid** (cards with
file-type icon, "Synced … ago", "Include in meeting context" checkbox), and **Graph** (a force
layout of documents; edges by embedding similarity; labels as coloured clusters; zoom, centre,
start/pause rotation; an inspector with related documents; "+ Add Label" on any document and
"Create & Auto-Assign" which clusters related documents under a new label; "Finding Related
Docs…"). Drive sources are subscribed to for changes.

### 3.8 Calendar event page

Event details (time, recurrence, attendees with avatars, location), "Join Meeting", "Open in
Calendar", attachments with per-file summaries, "Generate Summary" / "Summarize Attachments",
"View Transcript" of the linked recording, meeting brief.

### 3.9 Stats

Cards for **Tokens saved** (tokens processed on device, "saved" vs. a cloud model), **Meetings
transcribed**, **Chat assistances provided**, an activity metrics row, a **weekly token usage bar
chart**, and a "Get to know on-device models" education card about Gemma.

### 3.10 Settings

Sections, as far as the strings show:

- **General**: open at login, mute notifications, imminent meeting reminders, **Transcript History**
  ("Automatically saves meeting transcripts from the Foresight overlay to history"), silence timeout.
- **Inference model**: pick the Gemma size (disabled while recording), "Manage Models", "Clear Model
  Cache", expert models list.
- **Privacy Mode (100% on-device processing with local Gemma models)**: "If enabled, Foresight will
  perform all processing locally on your device. Otherwise, server-side Gemini may be used for
  generating responses." Likewise **Run transcription on device** ("Otherwise, it will use a
  server-side transcription service") and **Detect queries on device** ("Otherwise, it will use a
  server-side query detection service").
- **Note enhancement style**: Standard (complete sentences) or Concise (brief phrases).
- **Refresh interval** for Calendar events and Drive files (hours), "Refresh Data".
- **Hotkeys**: editable list, double-click to rebind, at least three keys.
- **Knowledge Graph** toggle ("Activates the local semantic knowledge graph pipeline and
  visualisation page") and **V2 Retrieval (Advanced RAG)** ("knowledge graph results, expanded
  vector search, and semantic reranking").
- **Launch Agent Monitor**: status, bundled vs. running version, logs, restart.
- **Developer**: dogfood chat, diagnostics, "Show Logs".
- **About**: version, third-party licences, Generative AI policy, privacy policy, terms;
  **Clear Data** ("Delete all user data and models", app restarts).

### 3.11 Notifications and sounds

Imminent meeting reminder, "scheduled meeting time elapsed" (the recording is still running past
the end), "recording stopped after inactivity", "Update available" (restart to apply). Sounds:
chime, recorder warning, and a spoken transcription-start notification in each UI language.

## 4. The AI pipeline, from the prompts

- **Meeting brief** (one shot or chunked): "You are a multilingual expert at note taking…", rules:
  ground everything in the transcript, keep speaker names exactly, gender-neutral pronouns,
  professional tone; fixed template `# Overview` (3–5 sentences, max 10, readable in 30 s),
  `# Action Items` (`* **[Assignee]**: Task`, or "None identified"), `# Details` (bullets with a
  3–5 word header and a one or two sentence body under 30 words). Long transcripts go through a
  map-reduce: per-chunk "expert note taker" bullets, then "synthesize the partial summaries… output
  only the final requested artifact". A separate **incremental** prompt updates an existing brief
  with "new discussion recorded later in the meeting", and explicitly forbids attributing anything to
  "Microphone" or "Remote" (device channels, not people).
- **Action items**: a long rubric (concrete, originated in the discussion, assigned, after the
  meeting; "The group" for "we"; assignee must be a speaker label; no object nouns as subjects;
  combine related items) with JSON output `{assigner, assignees, task, type: request | offer |
  proposal | assignment | other, is_confirmed_by_assignee, specific_enough}`.
- **Notes enhancer**: "You are an executive assistant…" given `<shorthand_notes>` where each item
  links to deduplicated `<relevant_excerpts>` by `<excerpt_refs>`; output exactly one bullet per
  note, `* **[Topic]:** text`, 1–2 sentences, keep the user's spelling and acronyms over the
  transcript's, do not rewrite items that are already full notes, update `<previous_enhanced>` only
  when the excerpts add something. Unmatched notes are kept as "Personal Note".
- **Chat**: priority order context → current date → internal knowledge → tools (calendar search,
  meeting search, web search) by native function calling; `[Source:N]` citation required for text and
  images; conversation history is compressed into a bulleted "Context Memo" by an "archivist" prompt;
  a "JSON repair expert" prompt fixes malformed tool-call JSON.
- **Relational queries** over meeting metadata ("last week", "previous quarter") are detected by a
  regex and resolved against the calendar before retrieval.
- Grounding helpers: numeric grounding (numbers in the answer are checked against the sources),
  a dictionary extractor that learns names and terms from documents to bias ASR.

## 5. Privacy, as shipped

The marketing says nothing leaves the device. The binary says: on-device is a **setting**, with
server-side fallbacks for generation (Gemini), transcription and query detection via
`odml.pa.googleapis.com` and Vertex AI endpoints; Drive, Calendar, Docs, Slides and Custom Search
are called with the signed-in account; Calendar push goes through Firebase Messaging; Keystone
checks for updates; Firebase Analytics is off in the config but a Clearcut logger is compiled in.
Model weights are fetched from Google after sign-in. The local database is encrypted.

## 6. Worth borrowing for Requirements Workbench

- **Shorthand → enhanced notes, item by item with excerpt references.** Our "requirement with a
  checked quote" is the same idea; their trick is to run it live during the call and to never
  overwrite the user's own wording. A "Notes" pane next to the live transcript, enhanced in place,
  would suit discovery calls.
- **Three-tab recap** (Executive summary / Bulletized recap / Action items) with an incremental
  update prompt instead of re-summarising the whole transcript.
- **Action items as structured JSON** with assigner, type and "confirmed by assignee". That maps
  cleanly onto our Q and open-question atoms.
- **Channel labels, not speakers.** They stopped at Microphone/System and wrote prompt rules to stop
  the model from treating channels as people. Our two-channel recording has the same failure mode.
- **Onboarding by model card** with RAM requirement and a download page before the first screen,
  then a guided tutorial. Our Settings model list is close; the first-run gate is not.
- **Context cards with "Include in meeting context"** and sync time, and a document graph with
  labels. A lighter version for us: project documents as sources that the extractor can cite.
- **Status chip in the top bar** showing what the machine is doing (indexing, downloading, jobs)
  instead of only a sidebar job card.
- **Stats page** that turns on-device processing into a number (tokens kept local, meetings
  transcribed). Cheap, and it sells the local-first story.
- Things to avoid: the dialog-in-dialog note editor, a HUD that only works while recording, and the
  on-device toggle that silently falls back to the cloud.

Files used for this analysis are not in the repo; the DMG is in `~/Downloads/foresight_mac.dmg`.

## 7. Product comparison with Requirements Workbench

Foresight is a meeting companion; Requirements Workbench is an analyst's workbench. They overlap only
on recording and transcribing a call.

**Foresight does better:** live enhancement of shorthand notes during the call; a question-detected
HUD; calendar-driven daily briefings and prep summaries; a cross-meeting, cross-document knowledge
library with search, chat and a document graph; model cards with RAM requirements and a resident
inference agent with a health monitor; a stats page that quantifies on-device processing; polished
onboarding and tutorial; about forty transcription languages.

**Requirements Workbench does better:** the output is a work product (typed requirements with
verified quotes, review with undo, duplicates and conflicts), full traceability from quote to Jira
issue, specification documents with versions, quality check, sign-off and Word export, a backlog with
INVEST check and idempotent Jira push, editable and shareable skills, non-audio sources in the same
pipeline, a hard "local only" rule (Foresight's on-device mode has server-side fallbacks and requires
a Google account), two-channel recording with per-channel transcription.

**Gap to close (upstream):** live transcript with a notes pane enhanced item by item against quotes;
search and ask across all project sources; incremental summaries; a first-run gate with model cards
and a local-processing stat. **Not worth chasing:** calendar briefings, Drive indexing, document
graph, floating HUD.
