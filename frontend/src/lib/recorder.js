// Call recording in two modes (ported from the classic page):
// - desktop app: the Python side captures mic + system audio as separate channels;
// - browser: getDisplayMedia (system audio) + getUserMedia (mic) → MediaRecorder.

import { api } from "./api.js";

export class DesktopRecorder {
  constructor() { this.statusTimer = null; }

  // The meeting exists from the first second: resolves { source_id, live } (5.0 C4.1).
  // `extra` carries the localised title and the speech-recognition options (the live pass uses them).
  async start(micDevice, onStatus, extra = {}) {
    const body = await api("/desktop-record/start", { method: "POST", body: { mic_device: micDevice, ...extra } });
    this.watch(onStatus);
    return body;
  }

  // Follow the server recorder's status (also used to take over a recording after a reload).
  watch(onStatus) {
    clearInterval(this.statusTimer);
    this.statusTimer = setInterval(async () => {
      try { onStatus(await api("/desktop-record/status")); } catch (_) { /* transient */ }
    }, 1500);
  }

  pause() { return api("/desktop-record/pause", { method: "POST" }); }
  resume() { return api("/desktop-record/resume", { method: "POST" }); }

  // Resolves { sourceId, jobId, errors }. The server finalises the meeting's source and, given the
  // transcription options, starts the full transcription on it.
  async stop(body = {}) {
    clearInterval(this.statusTimer);
    const res = await fetch("/desktop-record/stop", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const err = new Error(body.error || "Recording failed");
      err.errors = body.errors || {};
      throw err;
    }
    return {
      sourceId: res.headers.get("X-Source-Id"),
      jobId: res.headers.get("X-Job-Id"),
      errors: JSON.parse(res.headers.get("X-Recording-Errors") || "{}"),
    };
  }
}

export class BrowserRecorder {
  async start(micDeviceId, onWarning) {
    this.display = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    try {
      this.mic = await navigator.mediaDevices.getUserMedia({
        audio: { deviceId: micDeviceId ? { ideal: micDeviceId } : undefined,
                 echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
    } catch (_) {
      this.mic = null;
      onWarning("mic");
    }
    this.display.getVideoTracks().forEach(t => t.stop());
    this.ctx = new AudioContext();
    const dest = this.ctx.createMediaStreamDestination();
    this.sysTracks = this.display.getAudioTracks();
    if (this.sysTracks.length) this.ctx.createMediaStreamSource(new MediaStream(this.sysTracks)).connect(dest);
    else onWarning("sys");
    if (this.mic) {
      const gain = this.ctx.createGain();
      gain.gain.value = 1.5;
      this.ctx.createMediaStreamSource(this.mic).connect(gain);
      gain.connect(dest);
    }
    this.chunks = [];
    this.rec = new MediaRecorder(dest.stream);
    this.rec.ondataavailable = e => { if (e.data.size) this.chunks.push(e.data); };
    this.rec.start(1000);
  }

  // Resolves a webm Blob; the caller uploads it as a recording.
  stop() {
    return new Promise(resolve => {
      this.rec.onstop = () => {
        if (this.mic) this.mic.getTracks().forEach(t => t.stop());
        this.sysTracks.forEach(t => t.stop());
        this.ctx.close();
        resolve(new Blob(this.chunks, { type: "audio/webm" }));
      };
      this.rec.stop();
    });
  }
}

export async function listMicrophones(desktop) {
  if (desktop) {
    const devices = await api("/audio-devices").catch(() => []);
    if (!Array.isArray(devices)) return [];
    return devices.filter(d => d.index !== "loopback").map(d => ({ id: String(d.index), name: d.name }));
  }
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.filter(d => d.kind === "audioinput" && d.deviceId && d.deviceId !== "default")
    .map((d, i) => ({ id: d.deviceId, name: d.label || `Microphone ${i + 1}` }));
}
