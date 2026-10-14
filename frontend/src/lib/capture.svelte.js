// Getting sources in: import and recording. The state lives here, not in a screen, so a recording
// or an import keeps going while the BA works elsewhere (the HUD and the sidebar job card show it).
import { api, pollJob } from "./api.js";
import { DesktopRecorder, BrowserRecorder, listMicrophones } from "./recorder.js";
import { fmtDate, isTranscriptFile } from "./format.js";
import { followExtraction, notify } from "./atoms.js";
import { app, t, go, loadSources, toast, rememberSource } from "./state.svelte.js";

export const cap = $state({
  uploading: false, error: "",
  mics: [], mic: "",
  recording: false, elapsed: 0, problems: [], recError: "",
  consentAsk: false,
});

function optionsPayload() {
  const o = app.options;
  return { model: o.model, device: o.device, diarize: String(o.diarize),
           word_timestamps: String(!o.diarize && o.word_timestamps) };
}

// ETA from the rate so far (PM-30): shown once the job has made some progress.
function eta(started, progress) {
  if (!progress || progress < 5) return "";
  const left = (Date.now() - started) / progress * (100 - progress) / 1000;
  return left < 60 ? t("sources.eta_s") : t("sources.eta_min", { n: Math.round(left / 60) });
}

// Follow a transcription job; the row and the sidebar show its progress.
export async function track(sourceId, jobId) {
  const started = Date.now();
  app.jobs[sourceId] = { jobId, progress: 0, message: "" };
  try {
    const job = await pollJob(jobId, j => {
      app.jobs[sourceId] = { jobId, progress: j.progress || 0, message: j.progress_msg || "", eta: eta(started, j.progress) };
    });
    delete app.jobs[sourceId];
    await loadSources();
    const s = app.sources.find(x => x.id === sourceId);
    const title = s ? s.title : "";
    if (job.result?.extract_job) {        // the project goes straight on to requirements (PM-13)
      toast(`${title} · ${t("sources.extracting")}`);
      followExtraction(sourceId, job.result.extract_job, { notifyTitle: title }).catch(() => {});
    } else {
      toast(`${title} · ${t("status.ready")}`, { action: t("src.open"), onAction: () => { rememberSource(sourceId); go(`/source/${sourceId}`); } });
      notify(title, t("status.ready"));
    }
  } catch (err) {
    delete app.jobs[sourceId];
    await loadSources();
    toast(err.message, { kind: "danger" });
  }
}

async function upload(f, kind = null) {
  const form = new FormData();
  form.append("audio", f);
  form.append("project_id", app.currentProjectId);
  Object.entries(optionsPayload()).forEach(([k, v]) => form.append(k, v));
  if (kind) form.append("kind", kind);
  return api("/transcribe", { method: "POST", form });
}

// One text file opens at its summary; audio and several files go to the queue and nothing opens by itself.
export async function importFiles(list, kind = null) {
  const files = [...(list || [])];
  if (!files.length || cap.uploading) return;
  cap.uploading = true;
  cap.error = "";
  let ok = 0;
  const failed = [];
  let only = null;
  for (const f of files) {
    try {
      const res = await upload(f, kind);
      ok++;
      if (isTranscriptFile(f.name)) only = res.source_id;
      else track(res.source_id, res.job_id);
    } catch (err) { failed.push(`${f.name}: ${err.message}`); }
  }
  cap.uploading = false;
  await loadSources();
  if (failed.length) cap.error = failed.join("; ");
  if (files.length === 1 && only) {
    rememberSource(only);
    go(`/source/${only}/summarize`);
  } else if (files.length > 1 || failed.length) {
    toast(t("sources.imported_n", { n: ok }) + (failed.length ? " · " + t("sources.failed_n", { n: failed.length }) : ""),
          failed.length ? { kind: "danger" } : {});
  }
}

export async function transcribeSaved(sourceId) {
  try {
    const res = await api(`/api/sources/${sourceId}/transcribe`, { method: "POST", body: optionsPayload() });
    await loadSources();
    track(sourceId, res.job_id);
  } catch (err) { toast(err.message, { kind: "danger" }); }
}

// ── recording ───────────────────────────────────────────────────────────────
let recorder = null;
let timer = null;
let started = 0;
const channelName = c => t(c === "mic" ? "channel.mic" : "channel.sys");

export function loadMics() { listMicrophones(app.device.desktop).then(m => (cap.mics = m)); }

// FR-SRC-02 / PM-05: remind about consent once per session, and log the confirmation.
function consented() { try { return sessionStorage.getItem("wb.consent") === "1"; } catch (_) { return false; } }
export function askThenRecord() {
  if (consented()) startRecording();
  else cap.consentAsk = true;
}
// The shell's record button (rail, phone header): the same flow; the consent sheet is part of Встречи.
export function recordFromShell() {
  if (cap.recording) return;
  askThenRecord();
  if (cap.consentAsk && app.route.name !== "meetings") go("/meetings");
}
export function confirmConsent() {
  cap.consentAsk = false;
  try { sessionStorage.setItem("wb.consent", "1"); } catch (_) { /* private mode */ }
  api("/api/consent", { method: "POST", body: { project_id: app.currentProjectId } }).catch(() => {});
  startRecording();
}

async function startRecording() {
  cap.recError = "";
  cap.problems = [];
  try {
    if (app.device.desktop) {
      recorder = new DesktopRecorder();
      await recorder.start(cap.mic === "" ? null : Number(cap.mic), st => {
        cap.problems = Object.entries(st.channels || {}).filter(([, c]) => c.error).map(([n, c]) => `${channelName(n)}: ${c.error}`);
      });
    } else {
      recorder = new BrowserRecorder();
      await recorder.start(cap.mic, which => (cap.problems = [...cap.problems, `${channelName(which)}: —`]));
    }
    cap.recording = true;
    started = Date.now();
    cap.elapsed = 0;
    timer = setInterval(() => (cap.elapsed = Math.floor((Date.now() - started) / 1000)), 500);
  } catch (err) {
    cap.recError = err.message;
    toast(err.message, { kind: "danger" });
  }
}

export async function stopRecording() {
  clearInterval(timer);
  cap.recording = false;
  try {
    if (recorder instanceof DesktopRecorder) {
      const { sourceId, errors } = await recorder.stop(`${t("rec.title")} ${fmtDate(Date.now() / 1000, app.lang)}`);
      cap.problems = Object.entries(errors).map(([n, e]) => `${channelName(n)}: ${e}`);
      if (sourceId) { await loadSources(); transcribeSaved(sourceId); }
    } else {
      const blob = await recorder.stop();
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      await importFiles([new File([blob], `recording_${ts}.webm`, { type: "audio/webm" })], "recording");
    }
    if (cap.problems.length) toast(`${t("rec.saved_partial")}: ${cap.problems.join(" · ")}`, { kind: "danger" });
  } catch (err) {
    cap.recError = err.message;
    cap.problems = Object.entries(err.errors || {}).map(([n, e]) => `${channelName(n)}: ${e}`);
    toast(err.message, { kind: "danger" });
  }
}

export const clock = s => `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
