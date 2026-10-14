"""Live transcript while a meeting is being recorded (spec 5.0 C4.1).

AUDIO SAFETY, the first rule of this codebase: mic.wav, sys.wav and mixed.wav are never deleted, truncated,
moved or opened for writing by this module. The live reader opens each channel file read-only ("rb"), seeks
to the byte offset it reached last time and reads what the recorder appended since; it never locks, renames
or rewrites anything. Any failure here (a slow machine, a model error, a bug) turns live mode off and is
logged; it never stops, pauses or alters the recording, which keeps going untouched.

Every `window` seconds the transcriber reads the new samples of each channel (the WAV data region after the
44-byte header: mono 16 kHz int16, as core.recorder writes it), cuts at the last pause inside the window
(the rest waits in memory for the next pass, so no byte is read twice), runs speech recognition on what it
cut and appends the lines to the source as provisional segments with absolute timestamps. On stop the
normal full transcription replaces them.
"""
import logging
import os
import threading
import time

import numpy as np

from core.recorder import SAMPLE_RATE, last_silence, speech_bounds_samples

WAV_HEADER_BYTES = 44
CHANNELS = ("mic", "sys")
MAX_WINDOW = 60
MAX_CHUNK_SECONDS = 20         # GigaAM's short-form limit is ~25 s: longer cuts are split at pauses
LABELS = {"mic": "BA", "sys": "OTHER"}

log = logging.getLogger("dictum.live")


class GigaAMAsr:
    """The configured GigaAM model behind the live pass: batch size 1, device memory released after every pass.
    `load_model` is the loader the final pass uses (app.get_model)."""

    def __init__(self, load_model, model_name, device):
        self._load = load_model
        self.model_name = model_name
        self.device = device

    def transcribe(self, chunks):
        import torch
        from core import longform
        model = self._load(self.model_name, self.device)
        tensors = [torch.from_numpy(np.asarray(c, dtype=np.float32) / 32768.0) for c in chunks]
        try:
            return [text for text, _ in longform.transcribe_chunks(model, tensors, batch_size=1)]
        finally:
            longform.release_device_memory(model._device)


def split_at_pauses(samples, rate=SAMPLE_RATE, max_seconds=MAX_CHUNK_SECONDS):
    """[(offset, samples)] pieces no longer than max_seconds, cut at the last pause inside each."""
    limit = int(max_seconds * rate)
    out, at = [], 0
    while len(samples) - at > limit:
        cut = last_silence(samples[at:at + limit], rate) or limit
        out.append((at, samples[at:at + cut]))
        at += cut
    if at < len(samples):
        out.append((at, samples[at:]))
    return out


class LiveTranscriber:
    """Provisional segments for a recording in progress. `store` needs append_provisional_segments();
    `pauses` returns the recorder's paused spans [[start, end or None], ...] in seconds of audio."""

    def __init__(self, source_id, recording_dir, asr, window=15, store=None, pauses=None, labels=None,
                 clock=time.monotonic, rate=SAMPLE_RATE, max_window=MAX_WINDOW):
        self.source_id = source_id
        self.recording_dir = recording_dir
        self._asr = asr                     # an object with transcribe(chunks) → [text], or a factory returning one
        self.base_window = self.window = window
        self.max_window = max_window
        self._store = store
        self._pauses = pauses or (lambda: [])
        self.labels = {**LABELS, **(labels or {})}
        self._clock = clock
        self.rate = rate
        self.offsets = {c: WAV_HEADER_BYTES for c in CHANNELS}   # next byte to read in each file
        self.bytes_read = {c: 0 for c in CHANNELS}
        self._carry = {c: np.zeros(0, dtype=np.int16) for c in CHANNELS}   # read but not transcribed yet
        self._carry_start = {c: 0 for c in CHANNELS}                       # sample index of the carry's start
        self._slow = 0
        self._off = False
        self.reason = None
        self.passes = 0
        self._lock = threading.Lock()
        self._closed = False
        self._stop = threading.Event()
        self._thread = None

    # ── state ────────────────────────────────────────────────────────────────
    @property
    def state(self):
        if self._off:
            return "off"
        return "catching_up" if self.window > self.base_window else "on"

    def turn_off(self, reason):
        if not self._off:
            self._off = True
            self.reason = reason
            log.warning("Live transcript off for %s: %s", self.source_id, reason)

    # ── thread ───────────────────────────────────────────────────────────────
    def start(self):
        self._thread = threading.Thread(target=self._run, name="live-transcript", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        try:
            if not hasattr(self._asr, "transcribe") and callable(self._asr):
                self._asr = self._asr()          # load the model here, not in the request that started recording
            while not self._off and not self._stop.wait(self.window):
                self.run_pass()
        except Exception as e:                  # never reaches the recorder: it runs in its own threads
            log.exception("Live transcript failed for %s", self.source_id)
            self.turn_off(f"error: {e}")

    def stop(self, join_timeout=2.0):
        """No segment is appended after this returns (a pass still running drops its result)."""
        self._stop.set()
        with self._lock:
            self._closed = True
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=join_timeout)

    # ── one pass ─────────────────────────────────────────────────────────────
    def _read_new(self, channel):
        """Samples appended to <channel>.wav since the last read. Read-only; the file is never locked or moved."""
        path = os.path.join(self.recording_dir, f"{channel}.wav")
        try:
            f = open(path, "rb")
        except FileNotFoundError:            # the channel has not delivered audio yet (or cannot)
            return np.zeros(0, dtype=np.int16)
        with f:
            size = os.fstat(f.fileno()).st_size
            start = self.offsets[channel]
            n = (size - start) // 2 * 2         # whole samples only
            if n <= 0:
                return np.zeros(0, dtype=np.int16)
            f.seek(start)
            data = f.read(n)
        n = len(data) // 2 * 2
        self.offsets[channel] = start + n
        self.bytes_read[channel] += n
        return np.frombuffer(data[:n], dtype="<i2")

    def _inside_pause(self, t0, t1):
        for start, end in self._pauses() or []:
            if start is not None and start <= t0 and (end is None or t1 <= end):
                return True
        return False

    def run_pass(self):
        """Read, cut, transcribe, append. Returns the appended segments."""
        if self._off:
            return []
        began = self._clock()
        pieces = []                          # (channel, start seconds, samples)
        for ch in CHANNELS:
            new = self._read_new(ch)
            buf = np.concatenate([self._carry[ch], new]) if len(self._carry[ch]) else new
            first = self._carry_start[ch]
            if not len(buf):
                continue
            t0, t1 = first / self.rate, (first + len(buf)) / self.rate
            if self._inside_pause(t0, t1):   # nothing but the silence the recorder wrote while paused
                self._carry[ch], self._carry_start[ch] = np.zeros(0, dtype=np.int16), first + len(buf)
                continue
            bounds = speech_bounds_samples(buf, self.rate)
            if bounds is None:
                cut = len(buf)               # all silence: nothing to wait for
            elif bounds[1] * self.rate <= len(buf) - int(0.3 * self.rate):
                cut = len(buf)               # the speech ended inside the window
            else:                            # speech runs to the end: cut at the last pause, keep the rest
                cut = last_silence(buf, self.rate) or len(buf)
            if len(buf) - cut > MAX_CHUNK_SECONDS * self.rate:
                cut = len(buf)
            chunk = buf[:cut]
            self._carry[ch], self._carry_start[ch] = buf[cut:].copy(), first + cut
            for at, piece in split_at_pauses(chunk, self.rate):
                b = speech_bounds_samples(piece, self.rate)
                if b is not None:
                    pieces.append((ch, (first + at) / self.rate, b, piece))
        segments = []
        if pieces:
            texts = self._asr.transcribe([p[3] for p in pieces])
            for (ch, start, (b0, b1), _), text in zip(pieces, texts):
                text = (text or "").strip()
                if text:
                    segments.append({"speaker": self.labels[ch], "start": round(start + b0, 3),
                                     "end": round(start + b1, 3), "text": text})
            segments.sort(key=lambda s: s["start"])
        appended = []
        with self._lock:
            if segments and not self._closed and self._store is not None:
                appended = self._store.append_provisional_segments(self.source_id, segments)
        self.passes += 1
        self._pace(self._clock() - began)
        return appended

    def _pace(self, took):
        """Backpressure: two slow passes in a row double the window (up to max_window); a slow pass at the
        largest window turns live mode off. The recording is never affected."""
        if took <= self.window:
            self._slow = 0
            return
        if self.window >= self.max_window:
            self.turn_off("too slow to keep up")
            return
        self._slow += 1
        if self._slow >= 2:
            self.window = min(self.window * 2, self.max_window)
            self._slow = 0
