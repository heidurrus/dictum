// First run (5.0 C8): whether the onboarding is done and where to resume it, the model downloads it started, and the
// tutorial step. The downloads live here, not in the screen, so "В фоне" can leave the step while they keep going.
import { api } from "./api.js";
import { go } from "./state.svelte.js";

export const STEPS = 6;
export const TUTORIAL = ["rec", "whisper", "list", "library", "ask"];      // tut.<id>, target #t-<id>

export const onb = $state({
  loaded: false,
  done: true,               // until the server says otherwise: a failed request must not trap the BA in the onboarding
  step: 1,
  downloads: [],            // [{kind: "asr" | "llm", id, label, size, status: queued|downloading|done|error, done, total, error}]
  tutorial: 0,              // 1…5 while the tips are shown
});

export async function loadOnboarding() {
  try {
    const r = await api("/api/onboarding");
    onb.done = r.done;
    onb.step = Math.min(Math.max(r.step || 1, 1), STEPS);
  } catch (_) { onb.done = true; }
  onb.loaded = true;
}

export function setStep(step) {
  onb.step = step;
  api("/api/onboarding", { method: "POST", body: { step } }).catch(() => {});
}

export async function finishOnboarding(withTips) {
  onb.done = true;
  try { await api("/api/onboarding", { method: "POST", body: { done: true } }); } catch (_) { /* shown again next start */ }
  go("/meetings");
  onb.tutorial = withTips ? 1 : 0;
}

export function reopenOnboarding() {
  onb.step = 1;
  go("/onboarding");
}

export function startTutorial() {
  go("/meetings");
  onb.tutorial = 1;
}

// ── downloads: one after another (speech, index, language model), through the routes Settings uses ─────────────
const sleep = ms => new Promise(r => setTimeout(r, ms));
let running = false;

export const downloadsBusy = () => onb.downloads.some(d => d.status === "queued" || d.status === "downloading");

export function queueDownloads(list) {
  const keep = onb.downloads.filter(d => d.status === "downloading" || d.status === "done");
  const fresh = list.filter(n => !keep.some(d => d.kind === n.kind && d.id === n.id))
    .map(n => ({ ...n, status: "queued", done: 0, total: n.size || 0, error: "" }));
  onb.downloads = [...keep, ...fresh];
  if (!running) run();
}

export function retryDownload(d) {
  d.status = "queued";
  d.error = "";
  if (!running) run();
}

async function statusOf(d) {
  if (d.kind === "asr") return (await api("/api/asr/models")).download;
  return (await api("/api/local-llm")).download;
}

async function run() {
  running = true;
  try {
    for (let d = onb.downloads.find(x => x.status === "queued"); d; d = onb.downloads.find(x => x.status === "queued")) {
      try {
        if (d.kind === "asr") await api(`/api/asr/models/${d.id}/download`, { method: "POST" });
        else await api("/api/local-llm/download", { method: "POST", body: { model: d.id } });
        d.status = "downloading";
        for (;;) {
          await sleep(600);
          const st = await statusOf(d);
          if (!st || (st.model && st.model !== d.id)) continue;
          if (st.total) d.total = st.total;
          d.done = st.done || 0;
          if (st.status === "done") { d.status = "done"; d.done = d.total; break; }
          if (st.status === "error" || st.status === "cancelled") { d.status = "error"; d.error = st.error || st.status; break; }
        }
      } catch (err) { d.status = "error"; d.error = err.message; }
    }
  } finally { running = false; }
}
