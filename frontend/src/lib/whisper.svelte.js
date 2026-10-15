// Шепнуть (spec 5.0 C7): the capture's state lives here, not in the screen, so the window-level ⌥Space can start and
// stop it from anywhere (the hotkeys map's "whisper" action goes to #/whisper first).
// idle → listening (words from /api/whispers/live) → processing (final speech pass and parse) → result (nothing saved
// until "Сохранить").
import { api } from "./api.js";
import { cap, micName } from "./capture.svelte.js";
import { app, t, toast } from "./state.svelte.js";

export const wh = $state({
  state: "idle",            // idle | listening | processing | result
  text: "",                 // the words so far (live), then the final transcript
  elapsed: 0,
  result: null,             // {transcript, duration, audio_file, error, needs_setup, asr_model}
  items: [],                // the parsed items, editable on the result card
  error: "",
  saved: 0,                 // bumped after a save, so the inbox reloads
});

let poll = null;

function payload() {
  const o = app.options;
  return { mic_device: cap.mic === "" || cap.mic == null ? null : Number(cap.mic), mic_name: micName(), model: o.model, device: o.device };
}

export async function startWhisper() {
  if (wh.state === "listening" || wh.state === "processing") return;
  wh.error = "";
  try {
    await api("/api/whispers/record/start", { method: "POST", body: payload() });
  } catch (err) {
    wh.error = err.body?.busy === "meeting" ? t("wh.busy_meeting") : err.message;
    toast(wh.error, { kind: "danger" });
    return;
  }
  Object.assign(wh, { state: "listening", text: "", elapsed: 0, result: null, items: [] });
  clearInterval(poll);
  poll = setInterval(tick, 300);
}

async function tick() {
  if (wh.state !== "listening") { clearInterval(poll); return; }
  try {
    const live = await api("/api/whispers/live");
    if (wh.state !== "listening") return;
    wh.text = live.text || "";
    wh.elapsed = live.elapsed || 0;
    if (!live.recording) stopWhisper();            // it stopped by itself: silence after speech, or 90 s
  } catch (_) { /* the next poll tries again */ }
}

export async function stopWhisper() {
  if (wh.state !== "listening") return;
  clearInterval(poll);
  wh.state = "processing";
  try {
    const body = await api("/api/whispers/record/stop", { method: "POST" });
    wh.result = body;
    wh.text = body.transcript || wh.text;
    wh.items = (body.items || []).map(i => ({ ...i }));
    if (!body.transcript) {
      wh.state = "idle";
      toast(body.error || t("wh.heard_nothing"), { kind: body.error ? "danger" : "info" });
      return;
    }
    wh.state = "result";
  } catch (err) {
    wh.state = "idle";
    wh.error = err.message;
    toast(err.message, { kind: "danger" });
  }
}

// ⌥Space and the big button: start, or stop when listening.
export function toggleWhisper() {
  if (wh.state === "listening") stopWhisper();
  else startWhisper();
}

export function cancelWhisper() {
  Object.assign(wh, { state: "idle", text: "", result: null, items: [], error: "" });
}

export async function saveWhisper() {
  if (wh.state !== "result" || !wh.items.length) return null;
  const items = wh.items.map(i => ({ kind: i.kind, title: i.title, text: i.text, due_at: i.due_at ?? null,
                                     project_id: i.project_id || null }));
  const body = await api("/api/whispers", { method: "POST",
    body: { items, transcript: wh.result.transcript, audio_file: wh.result.audio_file } });
  cancelWhisper();
  wh.saved++;
  return body;
}
