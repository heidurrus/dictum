import datetime
import functools
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import warnings

# Suppress pyannote's torchcodec warning — we pass waveform dicts so it's never used
warnings.filterwarnings("ignore", message=".*torchcodec.*")

import torch
import gigaam
from gigaam.preprocess import load_audio, SAMPLE_RATE
from core import asr_models, longform
longform.install()                  # long recordings: decode with our ffmpeg, not torchcodec
from gigaam.utils import AudioDataset
from torch.utils.data import DataLoader
from flask import Flask, request, jsonify, send_file, send_from_directory

from core.ffmpeg import ensure_ffmpeg_on_path
from core import audio_devices, live as live_mod, macos_audio, settings
from core.summarize import SummaryError, summarize
from core import notes as meeting_notes, summarize as summarize_mod
from core import ask as ask_mod, live_questions as live_questions_mod, whisper as whisper_mod
from core import hotkeys as hotkeys_mod
from core.atoms import extract_atoms
from core import backlog, discover, exports, frd, jira, materials, permissions, skills, suggest
from core import index as local_index
from core.atlassian_auth import MCP_URL, AtlassianAuth, AuthError, AuthRequired
from core.mcp_client import McpError, McpSession
from core import local_llm, paths as paths_mod, usage as usage_mod
from core.llm import for_project, language_rule, model_name
from core.jobs import JobCancelled, JobStore, SerialQueue
from core.paths import make_job_log, models_dir, recordings_dir, use_app_model_cache
from core.macos_permissions import microphone_access
from core.realtime import realtime
from core.recorder import (SAMPLE_RATE as REC_SAMPLE_RATE, DualChannelRecorder, mix_wavs, speech_bounds,
                           wav_duration, wav_peak)
from core.security import install_local_only_guard
from core.setup_plan import StateFile
from core.store import ATOM_PREFIX, Store, StoreError
from core.emails import EMAIL_EXTENSIONS, parse_email_file
from core.transcripts import (MAX_BYTES as MAX_TRANSCRIPT_BYTES, TranscriptError,
                              is_transcript_file, parse_transcript)

settings.load_env()
use_app_model_cache()

hf_token = os.getenv("HF_TOKEN")
if hf_token:
    os.environ["HF_TOKEN"] = hf_token


app = Flask(__name__, static_folder="static")
install_local_only_guard(app)
local_llm.cleanup_stale()          # a model server left over from a crash would hold gigabytes of memory

CUDA_AVAILABLE = torch.cuda.is_available()
GPU_NAME = torch.cuda.get_device_name(0) if CUDA_AVAILABLE else None
MPS_AVAILABLE = torch.backends.mps.is_available() if hasattr(torch.backends, "mps") else False

# System ffmpeg if present, else the one setup installs (imageio-ffmpeg), exposed on
# PATH because the speech package's load_audio calls a bare "ffmpeg"
FFMPEG_EXE = ensure_ffmpeg_on_path()
FFMPEG_AVAILABLE = FFMPEG_EXE is not None

_models = {}
_model_lock = threading.Lock()

_diarization_pipeline = None
_diarization_lock = threading.Lock()

jobs = JobStore()
job_log = make_job_log()                 # tracebacks of failed jobs: <app data>/logs/jobs.log
paths_mod.install_app_log()              # warnings and errors of every module: <app data>/logs/dictum.log
library = Store()  # projects, sources, transcripts, summaries (spec increment 1)
library.reset_stale_processing()      # jobs do not survive a restart; let those sources be transcribed again
library.recover_interrupted_recordings()   # a recording cut off by a quit or crash: its WAVs stay, offer Расшифровать


def _usage_sink(kind, tokens_in, tokens_out, seconds, project_id):
    """Settings → stats (5.0 C9): every model call, embedding batch and transcription, against the current project."""
    if project_id is None:
        try:
            project_id = library.current_project()["id"]
        except Exception:
            project_id = None
    library.add_usage(kind, tokens_in, tokens_out, seconds, project_id)


usage_mod.set_sink(_usage_sink)
transcription_queue = SerialQueue()  # one transcription at a time (spec D-12)
index_queue = SerialQueue()          # one index pass at a time (5.0 C5)

_recorder = None
_recorder_lock = threading.Lock()
_active_tap = None  # macOS system-audio tap while recording
# The meeting being recorded and the helpers around it: live transcript (5.0 C4.1), the question card and
# the silence watch (C4.3); the start request's transcription options and UI language (auto-stop uses them), and
# why the last recording stopped when it was not the Stop button.
_session = {"source_id": None, "live": None, "questions": None, "silence": None, "opts": None, "lang": "ru",
            "stopped": None}
IS_DESKTOP = False

AVAILABLE_MODELS = [
    "v3_e2e_rnnt",
    "v3_e2e_ctc",
    "v3_rnnt",
    "v3_ctc",
    "v2_rnnt",
    "v2_ctc",
    "v1_rnnt",
    "v1_ctc",
    "multilingual_ctc",
    "multilingual_large_ctc",
]

# Formats that need ffmpeg conversion to WAV before the speech model can read them
NEEDS_CONVERSION = {".webm", ".ogg", ".opus", ".mp4", ".m4a", ".weba"}
# Everything ffmpeg and the speech model can read that people actually upload; anything else gets a
# clear message instead of an ffmpeg error (the desktop file picker allows all files).
AUDIO_VIDEO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".wma", ".webm",
                          ".weba", ".mp4", ".m4v", ".mov", ".mkv", ".avi", ".aiff", ".aif", ".amr", ".3gp"}


def convert_to_wav(input_path):
    if not FFMPEG_AVAILABLE:
        raise RuntimeError("ffmpeg is missing. Restart the app to let setup reinstall it.")
    wav_path = input_path + ".wav"
    subprocess.run(
        [FFMPEG_EXE, "-y", "-i", input_path, "-ar", "16000", "-ac", "1", wav_path],
        check=True,
        capture_output=True,
    )
    return wav_path


def get_model(name, device):
    with _model_lock:
        if name not in _models:
            _models[name] = gigaam.load_model(name, download_root=models_dir("gigaam"))
        return _models[name].to(device)


def get_diarization_pipeline(device):
    global _diarization_pipeline
    with _diarization_lock:
        if _diarization_pipeline is None:
            if not hf_token:
                raise RuntimeError(
                    "HF_TOKEN is not set. Create a .env file with HF_TOKEN=your_token. "
                    "See README for instructions."
                )
            from pyannote.audio import Pipeline
            _diarization_pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                token=hf_token,
            )
        return _diarization_pipeline.to(torch.device(device))


def set_progress(job_id, pct, msg):
    jobs.set_progress(job_id, pct, msg)


def transcribe_with_diarization(job_id, model, audio_path, device):
    set_progress(job_id, 15, "Loading diarization pipeline…")
    pipeline = get_diarization_pipeline(device)

    set_progress(job_id, 25, "Loading audio…")
    audio = load_audio(audio_path)  # (time,) at 16kHz

    # Pass as waveform dict — pyannote uses it directly, bypassing file I/O and
    # the torchcodec dependency which is broken on Windows without full-shared FFmpeg DLLs.
    waveform_dict = {
        "waveform": audio.unsqueeze(0).float().cpu(),  # (1, time)
        "sample_rate": SAMPLE_RATE,
    }

    set_progress(job_id, 30, "Running speaker diarization…")
    diarization_output = pipeline(waveform_dict)
    # pyannote 4.x returns DiarizeOutput; exclusive variant has no overlapping turns
    annotation = diarization_output.exclusive_speaker_diarization

    chunks, boundaries, speakers = [], [], []
    for segment, _, speaker in annotation.itertracks(yield_label=True):
        start_sample = int(segment.start * SAMPLE_RATE)
        end_sample = int(segment.end * SAMPLE_RATE)
        chunk = audio[start_sample:end_sample]
        if chunk.shape[0] < 400:  # skip chunks shorter than ~25ms
            continue
        chunks.append(chunk)
        boundaries.append((segment.start, segment.end))
        speakers.append(speaker)

    if not chunks:
        return [], None

    total = len(chunks)
    set_progress(job_id, 55, f"Transcribing {total} segments…")
    decoded = longform.transcribe_chunks(model, chunks, progress=lambda done, n: set_progress(
        job_id, 55 + int(40 * done / max(n, 1)), f"Transcribing segments… {done}/{n}"))
    result_segments = [{"speaker": speakers[i], "start": round(boundaries[i][0], 3), "end": round(boundaries[i][1], 3), "text": text}
                       for i, (text, _) in enumerate(decoded)]
    return result_segments, None


def do_longform(model, audio_path, job_id=None):
    if not hf_token:
        return None, (
            "Audio is too long for short-form transcription (max ~25s). "
            "Add HF_TOKEN to .env to enable longform mode. See README."
        )
    progress = (lambda done, total: set_progress(job_id, 20 + int(75 * done / max(total, 1)), f"Transcribing segments… {done}/{total}")) if job_id else None
    segments = longform.transcribe_longform(model, audio_path, progress=progress)
    result_segments = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments]
    full_text = "\n".join(
        f"[{gigaam.format_time(seg['start'])} - {gigaam.format_time(seg['end'])}] {seg['text']}"
        for seg in result_segments
    )
    return {"text": full_text, "segments": result_segments}, None


def _wait_for_speech_model(job_id, poll=1.0):
    """A speech model download in progress (first run, Settings → Модели) holds the queue: the transcription
    starts once the model is in place instead of fetching it a second time (5.0 C8)."""
    while asr_downloads.busy():
        set_progress(job_id, 0, "Waiting for the speech model download…")
        time.sleep(poll)


def run_job(job_id, upload_path, audio_path, model_name, diarize, word_timestamps, device,
            source_id=None, channels=None):
    """Queue and run one transcription.

    With a source_id the files belong to a saved source and are kept; the result
    is stored in the library. Without one (legacy temp uploads) both files are
    deleted afterwards.
    """
    def on_wait(ahead):
        set_progress(job_id, 0, f"Queued — waiting for {ahead} job(s) to finish…")

    def work():
        _wait_for_speech_model(job_id)
        if channels:
            return _transcribe_channels(job_id, *channels, model_name, diarize, device)
        return _transcribe(job_id, audio_path, model_name, diarize, word_timestamps, device)

    result, error = None, None
    try:
        result = transcription_queue.run(job_id, work, on_wait=on_wait)
    except JobCancelled:
        jobs.cancel(job_id)             # replaced by a newer request for the same source; it owns the source now
        return
    except Exception as e:
        error = e
        job_log.exception("Transcription job %s failed", job_id)
    finally:
        if source_id is None:
            for path in {upload_path, audio_path}:
                try:
                    os.unlink(path)
                except OSError:
                    pass
    if source_id is not None:
        try:
            if error is not None:
                library.fail_source(source_id, error)
            else:
                library.save_transcript(source_id, result, asr_model=model_name)
                _index_after(source_id)
                result = {**result, "source_id": source_id, "extract_job": _after_transcription(source_id)}
        except Exception as e:  # never lose the job result because saving failed
            error = error or e
    # Report completion only after cleanup and saving, so "done" means it's all in place.
    if error is not None:
        jobs.fail(job_id, error)
    else:
        jobs.finish(job_id, result)


# Recordings keep the microphone (the BA) and system audio (everyone else) apart,
# so the BA never needs diarization (spec D-11, FR-SRC-01 AC6).
BA_LABEL, OTHER_LABEL = "BA", "OTHER"


def _channel_segments(job_id, path, model_name, diarize, device, label):
    result = _transcribe(job_id, path, model_name, diarize, False, device)
    segments = result.get("segments")
    if not segments:  # short audio comes back as plain text: one segment where the speech is
        text = (result.get("text") or "").strip()
        start, end = speech_bounds(path) or (0.0, round(wav_duration(path), 3))
        segments = [{"start": start, "end": end, "text": text}] if text else []
    out = []
    for s in segments:
        text = (s.get("text") or "").strip()
        if text:
            speaker = s.get("speaker") if diarize and s.get("speaker") else label
            out.append({"speaker": speaker, "start": s.get("start"), "end": s.get("end"), "text": text})
    return out


def _transcribe_channels(job_id, mic_path, sys_path, model_name, diarize, device):
    """Transcribe each recorded channel on its own and merge them in time order.

    Mic segments are the BA; system-audio segments are diarized when asked (the
    remote participants), otherwise labelled OTHER. A silent channel is skipped.
    """
    segments = []
    if mic_path and os.path.exists(mic_path) and wav_peak(mic_path) > 0:
        set_progress(job_id, 1, "Transcribing your microphone…")
        segments += _channel_segments(job_id, mic_path, model_name, False, device, BA_LABEL)
    if sys_path and os.path.exists(sys_path) and wav_peak(sys_path) > 0:
        set_progress(job_id, 50, "Transcribing the other side of the call…")
        segments += _channel_segments(job_id, sys_path, model_name, diarize, device, OTHER_LABEL)
    segments.sort(key=lambda s: (s["start"] is None, s["start"] or 0.0))
    text = "\n".join(f"[{s['speaker']}] [{gigaam.format_time(s['start'] or 0)} - "
                     f"{gigaam.format_time(s['end'] or 0)}] {s['text']}" for s in segments)
    return {"text": text, "segments": segments, "diarized": True, "channels": True}


def _is_long(audio_path):
    """Over the speech model's short-form limit (25 s)? Read from the WAV header when it is one; otherwise let the model decide."""
    if not audio_path.lower().endswith(".wav"):
        return False
    try:
        return wav_duration(audio_path) > 25
    except Exception:
        return False


def _transcribe(job_id, audio_path, model_name, diarize, word_timestamps, device):
    set_progress(job_id, 5, f"Loading model on {device.upper()}…")
    model = get_model(model_name, device)

    if diarize:
        set_progress(job_id, 10, "Starting diarization…")
        segments, error = transcribe_with_diarization(job_id, model, audio_path, device)
        if error:
            raise RuntimeError(error)
        full_text = "\n".join(
            f"[{s['speaker']}] [{gigaam.format_time(s['start'])} - {gigaam.format_time(s['end'])}] {s['text']}"
            for s in segments
        )
        result = {"text": full_text, "segments": segments, "diarized": True}

    elif word_timestamps:
        set_progress(job_id, 10, "Transcribing…")
        try:
            res = model.transcribe(audio_path, word_timestamps=True)
        except Exception as e:
            if "too long" in str(e).lower():
                set_progress(job_id, 20, "Long file — running VAD segmentation…")
                result, error = do_longform(model, audio_path, job_id)
                if error:
                    raise RuntimeError(error)
            else:
                raise
        else:
            words = [
                {"text": w.text, "start": round(w.start, 3), "end": round(w.end, 3)}
                for w in res.words
            ]
            result = {"text": " ".join(w["text"] for w in words), "words": words}

    else:
        set_progress(job_id, 10, "Transcribing…")
        if _is_long(audio_path):          # the short path would first load the whole file onto the GPU
            set_progress(job_id, 20, "Long file — running VAD segmentation…")
            result, error = do_longform(model, audio_path, job_id)
            if error:
                raise RuntimeError(error)
            return result
        try:
            res = model.transcribe(audio_path)
        except Exception as e:
            if "too long" in str(e).lower():
                set_progress(job_id, 20, "Long file — running VAD segmentation…")
                result, error = do_longform(model, audio_path, job_id)
                if error:
                    raise RuntimeError(error)
            else:
                raise
        else:
            text = res if isinstance(res, str) else str(res)
            result = {"text": text}

    return result


@app.route("/")
def index():
    """The multi-screen app (frontend/, built into static/app)."""
    if os.path.exists(os.path.join(app.static_folder, "app", "index.html")):
        return send_from_directory(os.path.join(app.static_folder, "app"), "index.html")
    return send_from_directory(app.static_folder, "index.html")


@app.route("/classic")
def classic():
    """The previous single-page UI, kept as a fallback while the new one settles."""
    return send_from_directory(app.static_folder, "index.html")


@app.route("/models")
def list_models():
    return jsonify(AVAILABLE_MODELS)


asr_downloads = asr_models.Downloader(models_dir("gigaam"))


@app.route("/api/asr/models")
def api_asr_models():
    return jsonify({"models": asr_models.list_models(models_dir("gigaam"), asr_downloads), "download": asr_downloads.status(),
                    "langs": _asr_langs()})


def _asr_langs(prefs=None):
    """Meeting language → the speech model it records with (Settings → Models, 5.0.5)."""
    prefs = prefs if prefs is not None else settings.load_settings()
    return {lang: settings.asr_model_for(lang, prefs) for lang in settings.ASR_LANG_DEFAULTS}


@app.route("/api/asr/models/<model_id>/download", methods=["POST"])
def api_asr_download(model_id):
    try:
        asr_downloads.start(model_id)
    except asr_models.AsrModelError as e:
        return jsonify({"error": str(e)}), 400
    return api_asr_models()


@app.route("/api/asr/download/cancel", methods=["POST"])
def api_asr_cancel():
    asr_downloads.cancel()
    return api_asr_models()


@app.route("/api/asr/models/<model_id>", methods=["DELETE"])
def api_asr_delete(model_id):
    try:
        asr_models.delete_model(model_id, models_dir("gigaam"))
    except asr_models.AsrModelError as e:
        return jsonify({"error": str(e)}), 400
    with _model_lock:
        _models.pop(model_id, None)       # a later transcription reloads from disk (or downloads)
    return api_asr_models()


@app.route("/device-info")
def device_info():
    return jsonify({"cuda": CUDA_AVAILABLE, "gpu_name": GPU_NAME, "mps": MPS_AVAILABLE, "desktop": IS_DESKTOP})


def _refresh_mics_if_idle():
    """Re-read the audio devices (5.0.5: AirPods, an iPhone microphone or Teams change the list while Dictum runs, and
    a stale index opens a device macOS no longer has) unless a meeting or a whisper is recording: a refresh would cut
    their streams."""
    with _recorder_lock:
        busy = (_recorder is not None and _recorder.recording) or _whisper_listening()
    if not busy:
        audio_devices.refresh()


@app.route("/audio-devices")
def api_audio_devices():
    try:
        import soundcard as sc
        _refresh_mics_if_idle()
        inputs = [{"index": i, "name": name} for i, name in audio_devices.inputs()]
        # Add system audio (loopback) option
        try:
            spk = sc.default_speaker()
            inputs.insert(0, {"index": "loopback", "name": f"System audio ({spk.name})"})
        except Exception:
            pass
        return jsonify(inputs)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


MIC_NO_AUDIO = ("the microphone delivers no audio. Check that it's connected and, on macOS, allowed in "
                "System Settings → Privacy & Security → Microphone")
SYS_SILENT = ("system audio was silent the whole time. If the call's audio was playing, allow "
              "Dictum in System Settings → Privacy & Security → Screen & System Audio Recording")


def _mic_source(device_index):
    def source(stop):
        import sounddevice as sd
        with sd.InputStream(device=device_index, samplerate=REC_SAMPLE_RATE, channels=1, dtype="int16") as s:
            while not stop.is_set():
                chunk, _ = s.read(1024)
                yield chunk[:, 0].copy()
    # Never block the recorder; fail with a reason if the mic stays silent (e.g. no permission).
    return realtime(source, REC_SAMPLE_RATE, no_audio_error=MIC_NO_AUDIO)


def system_audio_support():
    """(supported, reason) for desktop-mode system-audio capture, without opening anything."""
    if sys.platform == "darwin":
        return macos_audio.support()
    return True, None


def _system_source():
    """A recorder source for system audio, or a string saying why it's unavailable.

    macOS: Core Audio process tap (spec FR-PLAT-02), opened here, before the mic
    stream starts, because it makes PortAudio re-scan devices. Windows/Linux:
    soundcard loopback (WASAPI / PulseAudio).
    """
    if sys.platform == "darwin":
        ok, reason = macos_audio.support()
        if not ok:
            return reason
        try:
            tap = macos_audio.SystemAudioTap().open()
        except Exception as e:
            return f"system audio unavailable: {e}"
        _remember_permission("system_audio")
        # The tap delivers nothing while nothing plays: fill that with silence so the
        # system channel stays in step with the mic, and Stop never waits on it.
        wrapped = realtime(tap, REC_SAMPLE_RATE, fill_silence=True)
        wrapped.close = tap.close
        return wrapped

    def source(stop):
        import numpy as np
        import soundcard as sc
        spk = sc.default_speaker()
        lb = sc.get_microphone(id=str(spk.name), include_loopback=True)
        with lb.recorder(samplerate=REC_SAMPLE_RATE, channels=1, blocksize=1024) as rec:
            while not stop.is_set():
                chunk = rec.record(numframes=1024)[:, 0]
                yield (np.clip(chunk, -1.0, 1.0) * 32767).astype("int16")
    return realtime(source, REC_SAMPLE_RATE, fill_silence=True)


def _close_active_tap():
    global _active_tap
    if _active_tap is not None:
        try:
            _active_tap.close()
        finally:
            _active_tap = None


def _asr_installed(model_name):
    return any(m["id"] == model_name and m["installed"] for m in asr_models.list_models(models_dir("gigaam")))


def _start_live(source, folder, opts, recorder):
    """The live transcriber for this recording, or None when live mode is off from the start (setting off,
    no speech model installed). It only ever reads the channel files; see core/live.py."""
    if not settings.load_settings().get("live_transcription", True):
        return None
    if not opts or not _asr_installed(opts["model_name"]):
        return None
    asr = lambda: live_mod.SpeechAsr(get_model, opts["model_name"], opts["device"])  # noqa: E731  loaded in its thread
    return live_mod.LiveTranscriber(source["id"], folder, asr, store=library, pauses=recorder.pauses,
                                    labels={"mic": BA_LABEL, "sys": OTHER_LABEL}).start()


def _start_live_questions(source, window=None, generate=None):
    """The question card for this recording (5.0 C4.3), or None when the setting `live_questions` is off or the
    project's AI is not set up. It reads the transcript and the index through the store, never the audio; see
    core/live_questions.py."""
    if not settings.load_settings().get("live_questions", False):
        return None
    project = library.get_project(source["project_id"])
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        return None
    answer = live_questions_mod.answerer(library, project["id"], generate or _ask_generate(prefs, api_key),
                                         skillset=_skillset(project["id"]))
    return live_questions_mod.LiveQuestions(source["id"], library, answer,
                                            window=window or live_questions_mod.WINDOW).start()


def _start_silence_watch(source, folder, recorder):
    """Auto-stop after `silence_stop_minutes` without speech (5.0 C4.3); None when the setting is 0."""
    minutes = int(settings.load_settings().get("silence_stop_minutes", 10) or 0)
    if minutes <= 0:
        return None
    return live_mod.SilenceWatch(folder, minutes, lambda m: _auto_stop(source["id"], m), pauses=recorder.pauses).start()


AUTO_STOP_TEXT = {"ru": "Запись остановлена: тишина {n} {unit}", "en": "Recording stopped after {n} minutes of silence"}


def _minutes_ru(n):
    if n % 10 == 1 and n % 100 != 11:
        return "минута"
    return "минуты" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "минут"


def _auto_stop(source_id, minutes):
    """The silence watch's call: stop exactly as the Stop button does (finalise, start the transcription with the
    options the recording started with), then tell the user with a system notification."""
    with _recorder_lock:
        if _session["source_id"] != source_id:
            return None
        opts, lang = _session.get("opts"), _session.get("lang") or "ru"
    try:
        out, code = _finish_recording(opts, expect_source=source_id)
    except Exception:
        job_log.exception("Auto-stop failed for %s", source_id)
        return None
    if code != 200:
        return None
    _session["stopped"] = {"reason": "silence", "source_id": source_id, "job_id": out["job_id"], "minutes": minutes}
    text = AUTO_STOP_TEXT.get(lang, AUTO_STOP_TEXT["en"]).format(n=minutes, unit=_minutes_ru(minutes))
    try:
        notify("Dictum", text)
    except Exception:
        job_log.exception("Auto-stop notification failed")
    return out


def _live_state(source_id=None):
    lt = _session["live"]
    if lt is None or (source_id and _session["source_id"] != source_id):
        return "off"
    return lt.state


@app.route("/desktop-record/start", methods=["POST"])
def desktop_record_start():
    """Start recording mic + system audio as separate channels (desktop app mode). The meeting exists from the
    first second: its source row (status "recording") is created now and the channels are written into its folder."""
    global _recorder, _active_tap
    data = request.get_json(silent=True) or {}
    mic_index = data.get("mic_device")  # sounddevice index or None for default
    if _recorder is not None and _recorder.recording:
        return jsonify({"error": "A recording is already in progress"}), 409
    if _whisper_listening():
        return jsonify({"error": WHISPER_BUSY, "busy": "whisper"}), 409
    opts = None
    if data.get("model") or data.get("asr_lang"):
        opts, error = _transcription_options(data)
        if error:
            return jsonify({"error": error}), 400

    # macOS: ask for the microphone first (shows the system prompt once), outside the
    # lock because the user may take a while to answer.
    mic_ok, mic_reason = microphone_access()
    _refresh_mics_if_idle()
    mic_index = audio_devices.resolve_input_by_name(mic_index, data.get("mic_name"))
    mic = _mic_source(mic_index) if mic_ok else mic_reason

    with _recorder_lock:
        if _recorder is not None and _recorder.recording:
            return jsonify({"error": "A recording is already in progress"}), 409
        if _whisper_listening():
            return jsonify({"error": WHISPER_BUSY, "busy": "whisper"}), 409
        title = (data.get("title") or "").strip()            # localised by the UI
        source = library.create_source(library.current_project()["id"], "recording",
                                       title or "Recording " + time.strftime("%d.%m.%Y %H:%M"), status="recording")
        folder = library.source_dir(source)
        sys_source = _system_source()
        _active_tap = sys_source if hasattr(sys_source, "close") else None
        _recorder = DualChannelRecorder(recordings_dir(), {"mic": mic, "sys": sys_source})
        recording_id = _recorder.start(folder=folder)
        lang = data.get("lang") if data.get("lang") in AUTO_STOP_TEXT else "ru"
        _session.update(source_id=source["id"], live=None, questions=None, silence=None, opts=opts, lang=lang,
                        stopped=None)
        try:
            _session["live"] = _start_live(source, folder, opts, _recorder)
        except Exception:               # live mode is a convenience: the recording runs without it
            job_log.exception("Live transcript could not start")
        try:
            _session["questions"] = _start_live_questions(source)
        except Exception:               # so is the question card
            job_log.exception("Live questions could not start")
        try:
            _session["silence"] = _start_silence_watch(source, folder, _recorder)
        except Exception:               # and the auto-stop
            job_log.exception("Silence watch could not start")
    return jsonify({"ok": True, "recording_id": recording_id, "source_id": source["id"], "live": _live_state()})


@app.route("/desktop-record/status")
def desktop_record_status():
    """Live recorder state, including per-channel errors (spec gap #23)."""
    with _recorder_lock:
        if _recorder is None:
            return jsonify({"recording": False, "channels": {}, "source_id": None, "paused": False, "pauses": [],
                            "live": "off", "stopped": None})
        st = _recorder.status()
        return jsonify({**st, "source_id": _session["source_id"] if st["recording"] else None,
                        "live": _live_state() if st["recording"] else "off",
                        "stopped": None if st["recording"] else _session.get("stopped")})


def _pause_or_resume(action):
    with _recorder_lock:
        if _recorder is None or not _recorder.recording:
            return jsonify({"error": "No recording in progress"}), 409
        getattr(_recorder, action)()
        st = _recorder.status()
    return jsonify({"ok": True, "paused": st["paused"], "pauses": st["pauses"]})


@app.route("/desktop-record/pause", methods=["POST"])
def desktop_record_pause():
    """The recorder keeps writing silence while paused, so the timeline stays continuous."""
    return _pause_or_resume("pause")


@app.route("/desktop-record/resume", methods=["POST"])
def desktop_record_resume():
    return _pause_or_resume("resume")


def _finish_recording(opts, title=None, expect_source=None):
    """The Stop path, shared by the Stop button and the auto-stop on silence: stop the recorder and the live
    helpers, finalise the meeting's source (mic.wav / sys.wav stay where they were written, a mixed WAV is made
    for playback) and, given transcription options, start the full transcription, which replaces the live
    pass's provisional lines once it lands (they stay on the page until then, and stay as the rough version if the
    full pass fails). Returns (body, status)."""
    with _recorder_lock:
        if _recorder is None or not _recorder.recording:
            return {"error": "No recording in progress"}, 409
        if expect_source is not None and _session["source_id"] != expect_source:
            return {"error": "Another recording is in progress"}, 409
        result = _recorder.stop()
        _close_active_tap()
        source_id = _session["source_id"]
        helpers = [_session.get(k) for k in ("live", "questions", "silence")]
        _session.update(source_id=None, live=None, questions=None, silence=None)
    for helper in helpers:
        if helper is not None:
            helper.stop()                   # no provisional line is added after this

    if result.get("sys") and "sys" not in result["errors"] and wav_peak(result["sys"]) == 0:
        result["errors"]["sys"] = SYS_SILENT
    captured = [result[c] for c in ("sys", "mic") if result.get(c)]
    if not captured:
        details = "; ".join(f"{c}: {e}" for c, e in result["errors"].items())
        message = "No audio captured" + (f" ({details})" if details else "")
        if source_id:
            library.fail_source(source_id, message)
        return {"error": message, "errors": result["errors"], "source_id": source_id}, 400

    playback_path = captured[0] if len(captured) == 1 else mix_wavs(
        captured, os.path.join(result["folder"], "mixed.wav"))

    changes = dict(status="recorded", audio_file=os.path.basename(playback_path))
    title = (title or "").strip()                  # older clients name the recording at stop
    if title:
        changes["title"] = title
    source = library.update_source(source_id, **changes)

    job_id = None
    if opts:
        library.update_source(source_id, status="processing", asr_model=opts["model_name"], error=None)
        job_id = _start_transcription(source, playback_path, opts)

    return {"result": result, "source_id": source_id, "job_id": job_id, "playback_path": playback_path}, 200


@app.route("/desktop-record/stop", methods=["POST"])
def desktop_record_stop():
    """Stop recording and finalise the meeting's source: mic.wav / sys.wav stay where they were written, a mixed
    WAV is made for playback. With transcription options in the body the full transcription starts on it; when it
    lands it replaces the live pass's provisional lines in the same write."""
    data = request.get_json(silent=True) or {}
    opts = None
    if data.get("model"):
        opts, error = _transcription_options(data)
        if error:
            return jsonify({"error": error}), 400
    out, code = _finish_recording(opts, data.get("title"))
    if code != 200:
        return jsonify(out), code
    result, source_id, job_id, playback_path = out["result"], out["source_id"], out["job_id"], out["playback_path"]

    response = send_file(playback_path, mimetype="audio/wav", as_attachment=False,
                         download_name="recording.wav")
    response.headers["X-Recording-Id"] = result["recording_id"]
    response.headers["X-Source-Id"] = source_id
    response.headers["X-Recording-Errors"] = json.dumps(result["errors"])
    if job_id:
        response.headers["X-Job-Id"] = job_id
    return response


# ── Шепнуть: the personal voice inbox (5.0 C7) ───────────────────────────────
# One recorder at a time: a whisper is refused while a meeting records, and a meeting while a whisper does. The
# capture (core/whisper.py) records the microphone only, through the meeting recorder, into <data>/whispers/<id>/.
_whisper = {"capture": None, "opts": None, "lang": "ru"}
_whisper_finish_lock = threading.Lock()
_reminders = None
WHISPER_BUSY = "A whisper is being recorded: finish it first."
MEETING_BUSY = "A meeting is being recorded: a whisper can start once it stops."
WHISPER_AUDIO = re.compile(r"^[\w-]+/mic\.wav$")


def _whisper_listening():
    cap = _whisper.get("capture")
    return cap is not None and cap.recording


def _whisper_live_asr(opts):
    """The live words' speech model (the meeting's live pass, loaded in its own thread), or None when live mode is
    off or the model is not installed: then the words appear after the stop."""
    if not settings.load_settings().get("live_transcription", True):
        return None
    if not opts or not _asr_installed(opts["model_name"]):
        return None
    return lambda: live_mod.SpeechAsr(get_model, opts["model_name"], opts["device"])


def _new_whisper_capture(mic, opts):
    """The capture for one whisper; the e2e fake server replaces this."""
    return whisper_mod.Capture(mic, live_asr=_whisper_live_asr(opts))


def _whisper_final_text(path, opts):
    """The final speech-recognition pass on the whisper's mic.wav: transcribe_longform when diarization's VAD is available (an HF
    token), else the short-form pass on pieces cut at pauses (a whisper is at most 90 s). The e2e fake replaces this."""
    import wave
    import numpy as np
    opts = opts or {"model_name": "v3_e2e_rnnt", "device": "cpu"}
    if not _asr_installed(opts["model_name"]):
        raise RuntimeError("Download the speech model in Settings first.")
    model = get_model(opts["model_name"], opts["device"])
    if hf_token:
        try:
            return " ".join(s["text"].strip() for s in longform.transcribe_longform(model, path) if s["text"].strip())
        finally:
            longform.release_device_memory(model._device)
    with wave.open(path, "rb") as r:
        samples = np.frombuffer(r.readframes(r.getnframes()), dtype="<i2")
    pieces = [p for _, p in live_mod.split_at_pauses(samples) if live_mod.has_speech(p) is not None]
    if not pieces:
        return ""
    texts = live_mod.SpeechAsr(get_model, opts["model_name"], opts["device"]).transcribe(pieces)
    return " ".join(t.strip() for t in texts if t and t.strip())


def _whisper_complete(prefs, api_key):
    """The model call of the parse; the e2e fake server replaces this."""
    from core.llm import complete_json
    return lambda system, user, schema: complete_json(system, user, schema, prefs, api_key)


def _whisper_context():
    projects = library.list_projects()
    current = library.current_project()
    labels = [lb["name"] for lb in library.list_labels(current["id"])]
    return projects, current, labels


def _parse_whisper(transcript, lang):
    """(items, error, needs_setup): the configured provider (a "Только локально" current project stays local); with no
    provider ready, the transcript as one note and the setup error."""
    projects, current, labels = _whisper_context()
    now = datetime.datetime.now()
    prefs, api_key, problem = _ai_prefs(current)
    if problem:
        body, _code = problem
        return whisper_mod.fallback_items(transcript, now, projects, current["id"], labels), body.get_json()["error"], True
    try:
        items = whisper_mod.parse(transcript, _whisper_complete(prefs, api_key), now, lang, projects, current["id"],
                                  labels, skillset=_skillset(current["id"]))
        return items, None, False
    except Exception as e:                # the words are kept whatever the model does
        job_log.exception("Whisper parse failed")
        return whisper_mod.fallback_items(transcript, now, projects, current["id"], labels), str(e), False


@app.route("/api/whispers/record/start", methods=["POST"])
def api_whisper_start():
    """Start listening: the microphone only, the same device choice as meetings; no consent sheet (it is the BA's own
    voice), the same microphone permission."""
    data = request.get_json(silent=True) or {}
    with _recorder_lock:
        if _recorder is not None and _recorder.recording:
            return jsonify({"error": MEETING_BUSY, "busy": "meeting"}), 409
        if _whisper_listening():
            return jsonify({"error": "Already listening.", "busy": "whisper"}), 409
    opts = None
    if data.get("model"):
        opts, error = _transcription_options(data)
        if error:
            return jsonify({"error": error}), 400
    mic_ok, mic_reason = microphone_access()
    if not mic_ok:
        return jsonify({"error": mic_reason or MIC_NO_AUDIO, "permission": "microphone"}), 403
    with _recorder_lock:
        if _recorder is not None and _recorder.recording:
            return jsonify({"error": MEETING_BUSY, "busy": "meeting"}), 409
        if _whisper_listening():
            return jsonify({"error": "Already listening.", "busy": "whisper"}), 409
        _whisper.update(opts=opts, lang=request.args.get("lang") or data.get("lang") or "ru")
        audio_devices.refresh()                 # nothing records (checked above, under the lock)
        mic_index = audio_devices.resolve_input_by_name(data.get("mic_device"), data.get("mic_name"))
        capture = _new_whisper_capture(_mic_source(mic_index), opts)
        capture.start()
        _whisper["capture"] = capture
    return jsonify({"ok": True, "id": capture.id, "live": capture.live is not None, "max_seconds": capture.max_seconds})


@app.route("/api/whispers/live")
def api_whisper_live():
    """{recording, text (the provisional words so far), elapsed, stopped_by}."""
    cap = _whisper.get("capture")
    if cap is None:
        return jsonify({"recording": False, "text": "", "elapsed": 0, "stopped_by": None, "id": None})
    return jsonify(cap.status())


@app.route("/api/whispers/record/stop", methods=["POST"])
def api_whisper_stop():
    """Stop (or pick up a whisper that stopped itself), run the final speech pass and the parse. Nothing is saved:
    → {transcript, items, duration, audio_file}. A second call returns the same answer."""
    cap = _whisper.get("capture")
    if cap is None:
        return jsonify({"error": "Not listening."}), 409
    with _whisper_finish_lock:
        if cap.finished is not None:
            return jsonify(cap.finished)
        result = cap.stop("button")
        mic = result.get("mic")
        if not mic:
            error = (result.get("errors") or {}).get("mic") or MIC_NO_AUDIO
            return jsonify({"error": error, "duration": 0}), 400
        lang = _whisper.get("lang") or "ru"
        try:
            transcript = _whisper_final_text(mic, _whisper.get("opts")) or ""
            asr_error = None
        except Exception as e:            # the live words, if any, still say what was said
            job_log.exception("Whisper speech recognition failed")
            transcript, asr_error = "", str(e)
        transcript = " ".join((transcript or cap.words.text).split())
        if not transcript:
            body = {"transcript": "", "items": [], "duration": cap.duration(), "audio_file": cap.audio_file,
                    "error": asr_error, "empty": asr_error is None}
            cap.finished = body
            return jsonify(body)
        items, error, needs_setup = _parse_whisper(transcript, lang)
        body = {"transcript": transcript, "items": items, "duration": cap.duration(), "audio_file": cap.audio_file,
                "stopped_by": cap.stopped_by, "error": error, "needs_setup": needs_setup,
                "asr_model": (_whisper.get("opts") or {}).get("model_name")}
        cap.finished = body
    return jsonify(body)


def _whisper_payload(w, names=None):
    names = names if names is not None else {p["id"]: p["name"] for p in library.list_projects(include_archived=True)}
    return {**w, "project_name": names.get(w["project_id"])}


def _due_value(d):
    """due_at as epoch seconds from a body: `due_at` (a number or null) or `due` (ISO-8601, local unless an offset)."""
    if "due_at" in d:
        return d["due_at"] if d["due_at"] in (None, "") else float(d["due_at"])
    due = whisper_mod.parse_iso(d.get("due"), datetime.datetime.now())
    return due.timestamp() if due else None


@app.route("/api/whispers", methods=["POST"])
def api_whispers_save():
    """Save the items of one utterance: one row per item, all with the same transcript and audio."""
    d = request.get_json(silent=True) or {}
    audio = d.get("audio_file") or None
    if audio is not None and not WHISPER_AUDIO.match(str(audio)):
        return jsonify({"error": "unknown audio file"}), 400
    try:
        items = [{**i, "due_at": _due_value(i)} for i in d.get("items") or [] if isinstance(i, dict)]
        rows = library.add_whispers(items, d.get("transcript"), audio)
    except (StoreError, ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"items": [_whisper_payload(w) for w in rows], "open": library.open_whispers()})


@app.route("/api/whispers")
def api_whispers_list():
    """The inbox, whatever project is current: ?filter=all|open|task|note|remind|idea&q=."""
    try:
        rows = library.list_whispers(request.args.get("filter") or "all", request.args.get("q"))
    except StoreError as e:
        return jsonify({"error": str(e)}), 400
    names = {p["id"]: p["name"] for p in library.list_projects(include_archived=True)}
    return jsonify({"items": [_whisper_payload(w, names) for w in rows], "open": library.open_whispers()})


@app.route("/api/whispers/<whisper_id>", methods=["PATCH"])
def api_whisper_update(whisper_id):
    d = request.get_json(silent=True) or {}
    changes = {k: d[k] for k in ("kind", "title", "text", "done", "project_id") if k in d}
    try:
        if "due_at" in d or "due" in d:
            changes["due_at"] = _due_value(d)
        w = library.update_whisper(whisper_id, **changes)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({**_whisper_payload(w), "open": library.open_whispers()})


@app.route("/api/whispers/<whisper_id>", methods=["DELETE"])
def api_whisper_delete(whisper_id):
    """Soft: the row and its audio stay; POST …/restore undoes it."""
    return _store_call(lambda: {**library.delete_whisper(whisper_id), "open": library.open_whispers()})


@app.route("/api/whispers/<whisper_id>/restore", methods=["POST"])
def api_whisper_restore(whisper_id):
    return _store_call(lambda: {**_whisper_payload(library.delete_whisper(whisper_id, restore=True)),
                                "open": library.open_whispers()})


@app.route("/api/whispers/<whisper_id>/to-question", methods=["POST"])
def api_whisper_to_question(whisper_id):
    """A Q atom in the given, else the linked, else the current project, quoting the transcript."""
    d = request.get_json(silent=True) or {}
    try:
        w = library.get_whisper(whisper_id)
        pid = d.get("project_id") or None
        if not pid and w["project_id"]:
            try:
                pid = library.get_project(w["project_id"])["id"]
            except StoreError:            # the linked project is gone: the soft link points nowhere
                pid = None
        pid = pid or library.current_project()["id"]
        out = whisper_mod.to_question(library, w, pid)
    except whisper_mod.AnalysisOff as e:
        return jsonify({"error": str(e)}), 409
    except StoreError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    _index_after(pid, is_source=False)
    project = library.get_project(pid)
    return jsonify({**out, "project_name": project["name"], "whisper": _whisper_payload(out["whisper"])})


def _busy_state():
    """For the menu-bar item (core/hotkeys.py): is a meeting or a whisper being recorded."""
    rec = _recorder
    return {"recording": bool(rec is not None and rec.recording), "whisper": _whisper_listening()}


hotkeys_mod.set_state_source(_busy_state)


@app.route("/api/ui-lang", methods=["POST"])
def api_ui_lang():
    """The page's language, sent on boot and on switch: the menu-bar titles follow it."""
    lang = (request.get_json(silent=True) or {}).get("lang")
    try:
        hotkeys_mod.set_ui_lang(lang)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "lang": lang})


@app.route("/api/hotkeys/status")
def api_hotkeys_status():
    """Whether the global hot keys are registered: "ok", "taken" (by the system or another app), "window" (⌘ plus one
    key stays a window-level key), "invalid", or "off" (not macOS, browser mode)."""
    return jsonify(hotkeys_mod.status())


@app.route("/api/i18n/menu")
def api_i18n_menu():
    """The menu-bar titles (menu.* from i18n.js, exported by the build into static/app/menu.json)."""
    lang = request.args.get("lang") or "en"
    return jsonify({"lang": lang if lang in ("ru", "en") else "en", "strings": hotkeys_mod.menu_strings(lang)})


def start_background():
    """Started with the app (launcher), not on import: the reminder check every 30 s (spec C7, A6: only while the
    app runs)."""
    global _reminders
    if _reminders is None:
        _reminders = whisper_mod.ReminderScheduler(library, lambda title, text: notify(title, text)).start()
    return _reminders


def app_version():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


@app.route("/health")
def health():
    """Environment checks for the UI (spec FR-SET-01)."""
    return jsonify({
        "ffmpeg": FFMPEG_AVAILABLE,
        "gpu": {"cuda": CUDA_AVAILABLE, "gpu_name": GPU_NAME, "mps": MPS_AVAILABLE},
        "hf_token": bool(hf_token),
        "platform": sys.platform,
        "system_audio_capture": system_audio_support()[0],
        "version": app_version(),
    })


def _skillset(project_id):
    """Skills in effect for this project: its own choices, else the global ones, else built-in."""
    return skills.resolve(library.project_skills(project_id) if project_id else None)


def _ai_prefs(project):
    """Settings for an AI call in this project, or an error response telling the user what to set up."""
    # "Local only" project: nothing may go to a cloud model (spec FR-PRJ-05, D-02).
    prefs = for_project(settings.load_settings(), project)
    api_key = settings.secret("ANTHROPIC_API_KEY")
    problem = None
    if prefs["llm_provider"] == "claude" and not api_key:
        problem = "Add your Anthropic API key in Settings, or download the local model."
    elif prefs["llm_provider"] == "local" and not local_llm.ready():
        problem = ("This project is “Local only”: download the local model in Settings → AI first."
                   if project and project["local_only"] else "Download the local model in Settings → AI first.")
    if problem:
        return prefs, api_key, (jsonify({"error": problem, "needs_setup": True}), 400)
    return prefs, api_key, None


def _settings_payload():
    prefs = settings.load_settings()
    return {
        "hf_token_set": bool(hf_token),
        "anthropic_key_set": bool(settings.secret("ANTHROPIC_API_KEY")),
        "llm_provider": prefs["llm_provider"],
        "claude_model": prefs["claude_model"],
        "local_model": prefs["local_model"],
        "hotkeys": prefs["hotkeys"],
        "live_transcription": prefs["live_transcription"],
        "live_questions": prefs["live_questions"],
        "silence_stop_minutes": prefs["silence_stop_minutes"],
        "menubar": prefs["menubar"],
        "consent_reminder": prefs["consent_reminder"],
        "embed_model": prefs["embed_model"],
        "recap_style": prefs["recap_style"],
        "notes_style": prefs["notes_style"],
        "tuning": prefs["tuning"],
        "asr_model_ru": prefs["asr_model_ru"],
        "asr_model_multi": prefs["asr_model_multi"],
        "asr_langs": _asr_langs(prefs),
        "claude_models": [{"id": m, "label": label} for m, label in settings.CLAUDE_MODELS],
    }


@app.route("/settings", methods=["GET"])
def get_settings():
    return jsonify(_settings_payload())


@app.route("/settings", methods=["POST"])
def save_settings():
    """Update only the fields present: hf_token, anthropic_api_key, llm_provider, claude_model and the rest."""
    global hf_token, _diarization_pipeline
    data = request.get_json(silent=True) or {}
    prefs = {k: data[k] for k in ("llm_provider", "claude_model", "local_model", "hotkeys",
                                 "live_transcription", "live_questions",
                                 "silence_stop_minutes", "menubar", "consent_reminder", "embed_model", "recap_style",
                                 "notes_style", "tuning", "asr_model_ru", "asr_model_multi", "model") if k in data}
    try:
        if prefs:
            settings.save_settings(prefs)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if "hf_token" in data:
        settings.set_secret("HF_TOKEN", data.get("hf_token"))
        hf_token = settings.secret("HF_TOKEN")
        # Reset pipeline so it reloads with the new token next time
        with _diarization_lock:
            _diarization_pipeline = None
    if "anthropic_api_key" in data:
        settings.set_secret("ANTHROPIC_API_KEY", data.get("anthropic_api_key"))

    return jsonify({"ok": True, **_settings_payload()})


STATS_PERIODS = {"7d": 7 * 86400, "30d": 30 * 86400, "all": None}


@app.route("/api/stats")
def api_stats():
    """Settings → Модели, the stats row (5.0 C9): what this computer processed in the period (7d | 30d | all)."""
    period = request.args.get("period") or "7d"
    if period not in STATS_PERIODS:
        return jsonify({"error": f"period must be one of {sorted(STATS_PERIODS)}"}), 400
    span = STATS_PERIODS[period]
    return jsonify({"period": period, **library.usage_stats(time.time() - span if span else None)})


@app.route("/api/storage")
def api_storage():
    """Settings → Хранилище: the data folder, what it holds and its size on disk. Paths are built with os.path, so
    they carry the platform's separator (backslashes on Windows); the UI shows them as they are."""
    path = paths_mod.app_data_dir()
    return jsonify({"path": path, "logs": os.path.join(path, "logs", "jobs.log"), "counts": library.storage_counts(), "bytes": paths_mod.tree_bytes(path),
                    "default": os.path.realpath(path) == os.path.realpath(paths_mod.default_data_dir()),
                    "movable": not paths_mod._override(), "moved_to": _data_move.get("moved_to")})


_data_move = {"job": None, "moved_to": None}


def _data_move_busy():
    """Why the data folder cannot move right now, or None: something is writing into it."""
    rec = _recorder
    if (rec is not None and rec.recording) or _whisper_listening():
        return "recording"
    if asr_downloads.busy() or (local_llm.installer.status() or {}).get("status") in ("downloading", "verifying"):
        return "downloading"
    if _data_move["job"] and (jobs.get(_data_move["job"]) or {}).get("status") == "processing":
        return "moving"
    return None


def _run_data_move(job_id, current, target):
    try:
        library.checkpoint()
        new = paths_mod.move_data_dir(target, current=current)
    except paths_mod.DataDirError as e:
        jobs.fail(job_id, e)
    except OSError as e:
        job_log.exception("Data folder move failed")
        jobs.fail(job_id, f"The data folder could not be moved: {e}")
    else:
        _data_move["moved_to"] = new
        jobs.finish(job_id, {"path": new, "restart": True})


@app.route("/api/data-dir/move", methods=["POST"])
def api_data_dir_move():
    """Settings → Хранилище → "Сменить папку…" (5.0 C9): move the data folder as a job, then ask for a restart.
    Refused (409 / 400 with a `code`) while a recording, a download or another move runs, when the folder is set by
    DICTUM_DATA_DIR, or when the target is the same folder, inside it, not empty or not writable."""
    target = (request.get_json(silent=True) or {}).get("path")
    if paths_mod._override():
        return jsonify({"error": "The data folder is set by DICTUM_DATA_DIR.", "code": "override"}), 400
    busy = _data_move_busy()
    if busy:
        return jsonify({"error": f"The data folder cannot move while {busy} is in progress.", "code": busy}), 409
    current = paths_mod.app_data_dir()
    try:
        target = paths_mod.check_move_target(current, target)
    except paths_mod.DataDirError as e:
        return jsonify({"error": str(e), "code": e.code}), 400
    job_id = jobs.create("data_move", target)
    _data_move["job"] = job_id
    jobs.set_progress(job_id, 0, "Moving the data folder…")
    threading.Thread(target=_run_data_move, args=(job_id, current, target), daemon=True).start()
    return jsonify({"job_id": job_id, "path": target})


@app.route("/api/local-llm")
def api_local_llm():
    return jsonify(local_llm.status())


@app.route("/api/local-llm/download", methods=["POST"])
def api_local_llm_download():
    model_id = (request.get_json(silent=True) or {}).get("model") or local_llm.recommended_model_id()
    try:
        local_llm.installer.start(model_id)
    except local_llm.LocalModelError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(local_llm.status())


@app.route("/api/local-llm/cancel", methods=["POST"])
def api_local_llm_cancel():
    local_llm.installer.cancel()
    return jsonify({"ok": True})


@app.route("/api/local-llm/models/<model_id>", methods=["DELETE"])
def api_local_llm_delete(model_id):
    try:
        local_llm.delete_model(model_id)
    except local_llm.LocalModelError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(local_llm.status())


def _run_summary(job_id, text, title, prefs, api_key, source_id=None, project_id=None):
    try:
        project = library.get_project(project_id) if project_id else None
        result = summarize(text, prefs, api_key, on_delta=lambda piece: jobs.append_partial(job_id, piece),
                           title=title, skillset=_skillset(project_id), language_rule=language_rule(project))
    except SummaryError as e:
        jobs.fail(job_id, e)
    except Exception as e:  # unexpected: keep the message, don't crash the worker
        jobs.fail(job_id, f"Summary failed: {e}")
    else:
        model = model_name(prefs)
        if source_id:                                   # the legacy route writes the 'brief' recap over the whole text
            library.add_summary(source_id, prefs["llm_provider"], model, result, style="brief",
                                through_idx=library.last_segment_idx(source_id))
        jobs.finish(job_id, {"summary": result, "provider": prefs["llm_provider"], "model": model,
                             "source_id": source_id})


@app.route("/summarize", methods=["POST"])
def summarize_route():
    """Summarise transcript text with the provider chosen in Settings (streams into the job)."""
    data = request.get_json(silent=True) or {}
    source_id, title = data.get("source_id"), data.get("title")
    project = None
    if source_id:
        try:
            source = library.get_source(source_id)
        except StoreError as e:
            return jsonify({"error": str(e)}), 404
        project = library.get_project(source["project_id"])
        title = title or source["title"]
        kind_label = {"email": "Email", "document": "Document"}.get(source["kind"], "Call or meeting")
        title = f"{kind_label} — {title}"
        text = library.transcript_text(source_id)   # renamed speakers included
    else:
        text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "There is no transcript text to summarise."}), 400
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        return problem
    job_id = jobs.create("summarize", title or "")
    jobs.set_progress(job_id, 0, "Writing summary…")
    threading.Thread(target=_run_summary, args=(job_id, text, title, prefs, api_key, source_id,
                                                project["id"] if project else None), daemon=True).start()
    return jsonify({"job_id": job_id})


def _request_project():
    """Project named in the request (form or JSON), else the current one."""
    data = request.get_json(silent=True) if request.is_json else None
    pid = (data or {}).get("project_id") or request.form.get("project_id")
    return library.get_project(pid) if pid else library.current_project()


def _transcription_options(values):
    """Validate model / device / flags from a form or JSON body; returns (options, error)."""
    # The UI sends the model of the meeting's language; a client that sends only the language gets the mapped model.
    lang = values.get("asr_lang")
    model_name = values.get("model") or (settings.asr_model_for(lang) if lang else "v3_e2e_rnnt")
    if model_name not in AVAILABLE_MODELS:
        return None, f"Unknown model: {model_name}"
    device = values.get("device", "cpu")
    if device == "cuda" and not CUDA_AVAILABLE:
        return None, "GPU requested but CUDA is not available. Install PyTorch with CUDA support — see README."
    if device == "mps" and not MPS_AVAILABLE:
        return None, "MPS requested but Apple Silicon GPU is not available."
    flag = lambda k: str(values.get(k, "false")).lower() == "true"  # noqa: E731
    return dict(model_name=model_name, diarize=flag("diarize"), word_timestamps=flag("word_timestamps"),
                device=device), None


def _recorded_channels(source):
    """(mic.wav, sys.wav) when a desktop recording kept both channels, else None."""
    if source.get("kind") != "recording":
        return None
    folder = library.source_dir(source)
    mic, sys_ = os.path.join(folder, "mic.wav"), os.path.join(folder, "sys.wav")
    return (mic, sys_) if os.path.exists(mic) and os.path.exists(sys_) else None


_transcribing = {}        # source_id → job_id of the transcription queued or running for it


def _transcription_in_progress(source_id):
    """The running job for this source, or None. A job still waiting in the queue is dropped,
    so pressing Transcribe again with other settings does not line up behind the old request."""
    old = _transcribing.get(source_id)
    if old is None or (jobs.get(old) or {}).get("status") != "processing":
        return None
    if transcription_queue.cancel(old):
        return None
    return old


def _start_transcription(source, audio_path, opts):
    job_id = jobs.create("transcribe", source["title"])
    _transcribing[source["id"]] = job_id
    threading.Thread(target=run_job, daemon=True, args=(
        job_id, audio_path, audio_path, opts["model_name"], opts["diarize"], opts["word_timestamps"],
        opts["device"], source["id"], _recorded_channels(source))).start()
    return job_id


@app.route("/transcribe", methods=["POST"])
def transcribe():
    """Upload audio/video to transcribe, or a transcript to import. Always saved as a source."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400
    try:
        project = _request_project()
    except StoreError as e:
        return jsonify({"error": str(e)}), 400

    upload = request.files["audio"]
    filename = os.path.basename(upload.filename or "upload")
    title = os.path.splitext(filename)[0] or filename
    is_email = os.path.splitext(filename)[1].lower() in EMAIL_EXTENSIONS
    if is_email or is_transcript_file(filename):
        # Text sources skip speech recognition (spec FR-SRC-03 AC2): a ready-made
        # transcript (Teams/Zoom .vtt, .srt, .docx, .pdf, .txt…), an email (.eml/.msg),
        # or a document such as an earlier specification.
        data = upload.read(MAX_TRANSCRIPT_BYTES + 1)
        try:
            result = parse_email_file(filename, data) if is_email else parse_transcript(filename, data)
        except TranscriptError as e:
            return jsonify({"error": f"Could not read this file: {e}"}), 400
        if is_email:
            kind, title = "email", result.get("title") or title
        else:
            # Speakers or timestamps make it a transcript; plain prose is a document.
            timed = any(s.get("speaker") or s.get("start") is not None for s in result.get("segments", []))
            kind = "transcript" if timed else "document"
        source = library.create_source(project["id"], kind, title, original_filename=filename)
        with open(os.path.join(library.source_dir(source), filename), "wb") as f:
            f.write(data)
        library.save_transcript(source["id"], result)
        _index_after(source["id"])
        job_id = jobs.create("import", source["title"])
        jobs.finish(job_id, {**result, "source_id": source["id"]})
        return jsonify({"job_id": job_id, "source_id": source["id"]})

    opts, error = _transcription_options(request.form)
    if error:
        return jsonify({"error": error}), 400
    kind = "recording" if request.form.get("kind") == "recording" else "audio"
    try:
        source, job_id = _import_audio(project, filename, upload.save, opts, kind)
    except _ImportFailed as e:
        return jsonify({"error": str(e), **({"source_id": e.source_id} if e.source_id else {})}), e.status
    return jsonify({"job_id": job_id, "source_id": source["id"]})


class _ImportFailed(Exception):
    def __init__(self, message, status=400, source_id=None):
        super().__init__(message)
        self.status, self.source_id = status, source_id


def _import_audio(project, filename, save, opts, kind="audio"):
    """An audio or video file → a meeting with its transcription queued: (source, job_id). `save(path)` writes the
    file's bytes there (a dropped file's upload, or a copy of a file found on disk)."""
    suffix = os.path.splitext(filename)[1].lower() or ".wav"
    if suffix not in AUDIO_VIDEO_EXTENSIONS:
        raise _ImportFailed(f"{filename}: unsupported file type. Use audio or video "
                            "(WAV, MP3, M4A, WebM, MP4…) or a transcript (.vtt, .srt, .docx, .pdf, .txt).")
    title = os.path.splitext(filename)[0] or filename
    source = library.create_source(project["id"], kind, title, original_filename=filename,
                                   asr_model=opts["model_name"])
    original = os.path.join(library.source_dir(source), "original" + suffix)
    save(original)
    if suffix in NEEDS_CONVERSION:
        try:
            converted = convert_to_wav(original)
            audio_path = os.path.join(library.source_dir(source), "audio.wav")
            os.replace(converted, audio_path)
        except Exception as e:
            library.fail_source(source["id"], e)
            raise _ImportFailed(str(e), 500, source["id"])
    else:
        audio_path = original
    library.update_source(source["id"], audit=False, audio_file=os.path.basename(audio_path))
    return source, _start_transcription(source, audio_path, opts)


@app.route("/job/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


def _download_entry(job_id, kind_label, st, cancel_url):
    done, total = st.get("done") or 0, st.get("total") or 0
    return {"id": job_id, "kind": "download", "label": f"{kind_label} · {done / 1024 ** 3:.1f} / {total / 1024 ** 3:.1f} GB",
            "progress": int(100 * done / total) if total else None, "message": st.get("status"),
            "cancellable": True, "cancel_url": cancel_url, "started_at": None, "done": done, "total": total}


@app.route("/api/jobs")
def api_jobs():
    """What the machine is doing now, for the status chip: running or queued jobs, downloads, the recorder."""
    out = []
    for job in jobs.active():
        pct = job.get("progress")
        out.append({"id": job["id"], "kind": job.get("kind"), "label": job.get("label") or "",
                    "progress": pct if pct else None, "message": job.get("progress_msg") or "",
                    "cancellable": False, "cancel_url": None, "started_at": job.get("started_at")})
    st = local_llm.installer.status()
    if st.get("status") in ("downloading", "verifying"):
        model = local_llm._any_model(st.get("model"))
        out.append(_download_entry("local-llm", model.label if model else st.get("model"), st, "/api/local-llm/cancel"))
    st = asr_downloads.status()
    if st and st.get("status") in ("downloading", "verifying"):
        out.append(_download_entry("asr", "GigaAM " + st["model"], st, "/api/asr/download/cancel"))
    with _recorder_lock:
        rec = _recorder.status() if _recorder is not None else None
    return jsonify({"jobs": out, "recording": rec if rec and rec.get("recording") else None})


# ── First run (5.0 C8): onboarding state, permissions, discovery ─────────────

ONBOARDING_KEY = "onboarding:v5"
ONBOARDING_STEPS = 6
READY_NOTIFICATION = {"ru": "Dictum готов", "en": "Dictum is ready"}


def _setup_state():
    return StateFile()               # <app data>/setup-state.json, read fresh every time


def _remember_permission(which):
    """A tap or a notification just worked: from now on that permission reads as granted."""
    try:
        _setup_state().set(permissions.STATE_KEY.format(which), permissions.GRANTED)
    except OSError:
        pass


@app.route("/api/onboarding")
def api_onboarding():
    state = _setup_state()
    return jsonify({"done": bool(state.get(ONBOARDING_KEY)), "step": state.get(ONBOARDING_KEY + ":step") or 1})


@app.route("/api/onboarding", methods=["POST"])
def api_onboarding_save():
    """{done: true} after the last step or Пропустить; {step} on every step, so a restart resumes there."""
    data = request.get_json(silent=True) or {}
    state = _setup_state()
    if "step" in data:
        step = data["step"]
        if not isinstance(step, int) or isinstance(step, bool) or not 1 <= step <= ONBOARDING_STEPS:
            return jsonify({"error": f"step must be 1…{ONBOARDING_STEPS}"}), 400
        state.set(ONBOARDING_KEY + ":step", step)
    if "done" in data:
        state.set(ONBOARDING_KEY, bool(data["done"]))
    return api_onboarding()


def _system_tap_dry_run():
    """About a second of the system-audio tap, dropped as it arrives; refused while something records, because
    opening a tap makes PortAudio re-scan its devices."""
    with _recorder_lock:
        if _recorder is not None and (_recorder.status() or {}).get("recording"):
            raise OSError("a recording is running")
    return macos_audio.dry_run(1.0)


@app.route("/api/permissions")
def api_permissions():
    return jsonify(permissions.read(_setup_state()))


@app.route("/api/permissions/request/<which>", methods=["POST"])
def api_permissions_request(which):
    if which not in permissions.WHICH:
        return jsonify({"error": "unknown permission"}), 404
    lang = request.args.get("lang") if request.args.get("lang") in READY_NOTIFICATION else "ru"
    hint = permissions.request(which, _setup_state(), mic_access=lambda: microphone_access(),
                               tap_dry_run=_system_tap_dry_run,
                               send_notification=lambda: notify("Dictum", READY_NOTIFICATION[lang]))
    out = permissions.read(_setup_state())
    if hint:
        out["hint"] = hint     # for this permission only, e.g. "no_audio" when the tap stayed silent
    return jsonify(out)


@app.route("/api/permissions/open-settings/<which>", methods=["POST"])
def api_permissions_open_settings(which):
    url = permissions.settings_url(which)
    if not url:
        return jsonify({"error": "no settings pane for this permission here"}), 404
    try:
        if sys.platform == "win32":
            os.startfile(url)  # noqa: S606 — a fixed ms-settings: address
        else:
            subprocess.Popen(["open", url])
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "url": url})


@app.route("/api/discover")
def api_discover():
    """Candidate files for the first run's Материалы step; ?folder= lists a folder the BA typed instead."""
    folder = (request.args.get("folder") or "").strip()
    if folder:
        folder = os.path.expanduser(folder)
        if not os.path.isdir(folder):
            return jsonify({"error": "folder not found"}), 400
    roots = [folder] if folder else discover.default_roots()
    found = discover.candidates(roots, AUDIO_VIDEO_EXTENSIONS, library.imported_files())
    return jsonify({"candidates": found, "roots": roots})


@app.route("/api/discover/import", methods=["POST"])
def api_discover_import():
    """{paths, project_id, options?}: audio and video become meetings (transcription queued as for a dropped file),
    documents become materials. The files are copied; the originals stay where they are."""
    data = request.get_json(silent=True) or {}
    try:
        project = library.get_project(data["project_id"]) if data.get("project_id") else library.current_project()
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    opts, error = _transcription_options(data.get("options") or {})
    if error:
        return jsonify({"error": error}), 400
    meetings, added, failed = [], [], []
    for path in data.get("paths") or []:
        name = os.path.basename(str(path))
        try:
            if not os.path.isfile(path):
                raise _ImportFailed("file not found")
            size = os.path.getsize(path)
            if size > discover.MAX_SIZE:
                raise _ImportFailed("the file is larger than 2 GB")
            kind = discover.kind_of(name, AUDIO_VIDEO_EXTENSIONS)
            if kind == "audio":
                source, job_id = _import_audio(project, name, lambda dest, src=path: shutil.copyfile(src, dest), opts)
                meetings.append({"source_id": source["id"], "job_id": job_id})
            elif kind == "document":
                with open(path, "rb") as f:
                    added.append(materials.import_file(library, project, name, f.read(materials.MAX_BYTES + 1))["id"])
            else:
                raise _ImportFailed("unsupported file type")
        except (_ImportFailed, materials.MaterialError, StoreError, OSError) as e:
            failed.append(f"{name}: {e}")
    return jsonify({"meetings": meetings, "materials": added, "failed": failed,
                    "index_job": _index_after(project["id"], is_source=False) if added else None})


# ── Library API (projects, sources) ──────────────────────────────────────────

def _store_call(fn, *args, **kwargs):
    try:
        return jsonify(fn(*args, **kwargs)), 200
    except StoreError as e:
        status = 404 if "not found" in str(e) else 400
        return jsonify({"error": str(e)}), status


@app.route("/api/projects", methods=["GET"])
def api_projects():
    include_archived = request.args.get("archived") == "1"
    current = library.current_project()
    return jsonify({"projects": library.list_projects(include_archived), "current_project_id": current["id"]})


@app.route("/api/projects", methods=["POST"])
def api_create_project():
    data = request.get_json(silent=True) or {}
    return _store_call(library.create_project, data.get("name"), bool(data.get("local_only")),
                       bool(data.get("analysis", True)))


@app.route("/api/projects/<project_id>", methods=["PATCH"])
def api_update_project(project_id):
    data = request.get_json(silent=True) or {}
    return _store_call(library.update_project, project_id,
                       **{k: data[k] for k in ("name", "local_only", "archived", "language", "jira_quotes", "auto_extract",
                                                "analysis", "asr_lang") if k in data})


@app.route("/api/projects/<project_id>/current", methods=["POST"])
def api_switch_project(project_id):
    return _store_call(library.set_current_project, project_id)


@app.route("/api/projects/<project_id>/sources", methods=["GET"])
def api_sources(project_id):
    try:
        library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    sort = request.args.get("sort") or "new"
    if sort not in library.SOURCE_SORTS:
        return jsonify({"error": f"unknown sort {sort}"}), 400
    return jsonify({"sources": library.list_sources(project_id, q=request.args.get("q"), sort=sort)})


@app.route("/api/projects/<project_id>/status")
def api_project_status(project_id):
    """Per-step state for the sidebar and the project home. Staleness flows downstream (PM-03):
    a changed atom makes the document stale, which makes the backlog and the Jira step stale too."""
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    stats = library.atom_stats(project_id)
    docs = library.documents(project_id)
    doc = frd.requirements_document(library, project_id) if docs else None
    latest = library.version(doc["id"]) if doc else None
    stale = frd.staleness(library, project_id, latest) if latest else None
    others_stale = 0
    for d in docs:
        if doc and d["id"] == doc["id"]:
            continue
        v = library.version(d["id"])
        st = frd.staleness(library, project_id, v) if v else None
        others_stale += bool(st and st["stale"])
    items = library.backlog(project_id)
    bl_stale = backlog.stale(library, project_id)["stale"] if items else False
    doc_stale = bool(stale and stale["stale"])
    local = jira.local_status(library, project_id)
    questions = [a for a in library.list_atoms(project_id, type="question") if a["status"] != "rejected"]
    actions = [a for a in library.list_actions(project_id) if a["status"] == "open"]
    sources = library.list_sources(project_id)
    return jsonify({
        "sources": len(sources),
        "processing": sum(1 for s in sources if s["status"] == "processing"),
        "atoms": {"review": stats["pending"], "total": stats["total"], "accepted": stats["accepted"],
                  "conflicts": stats["open_conflicts"]},
        "document": {"version": latest["number"] if latest else None, "stale": doc_stale, "count": len(docs),
                     "others_stale": others_stale,
                     "status": latest.get("status") if latest else None, "changed": (stale or {}).get("changed", 0)
                     + (stale or {}).get("added", 0) + (stale or {}).get("removed", 0)},
        "backlog": {"items": len(items), "included": sum(1 for i in items if i["included"]),
                    "stale": bl_stale or (doc_stale and bool(items))},
        "export": {"pushed": local["pushed"], "pending": local["pending"],
                   "stale": bool(local["pushed"]) and (bool(local["pending"]) or doc_stale or bl_stale),
                   "orphans": len(library.jira_orphans(project_id))},
        "open_items": {"questions": sum(1 for q in questions if q.get("q_state") != "answered"),
                       "actions": len(actions)},
        "project": {"name": project["name"], "local_only": project["local_only"]},
    })


# ── open items, activity, project files (PM review) ─────────────────────────

@app.route("/api/projects/<project_id>/actions")
def api_actions(project_id):
    return _store_call(lambda: {"actions": library.list_actions(project_id)})


@app.route("/api/projects/<project_id>/actions", methods=["POST"])
def api_add_action(project_id):
    d = request.get_json(silent=True) or {}

    def add():
        library.get_project(project_id)
        library.add_actions(project_id, d.get("source_id"), [{"text": d.get("text"), "owner": d.get("owner"), "due": d.get("due")}])
        return {"actions": library.list_actions(project_id)}
    return _store_call(add)


@app.route("/api/actions/<action_id>", methods=["PATCH"])
def api_update_action(action_id):
    return _store_call(lambda: (library.update_action(action_id, **(request.get_json(silent=True) or {})), {"ok": True})[1])


@app.route("/api/actions/<action_id>", methods=["DELETE"])
def api_delete_action(action_id):
    return _store_call(lambda: (library.delete_action(action_id), {"ok": True})[1])


@app.route("/api/projects/<project_id>/followup")
def api_followup(project_id):
    """The follow-up email: open questions, conflicts waiting for the client, action items (PM-15)."""
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    lang = request.args.get("lang") or ({"ru": "ru", "en": "en"}.get(project.get("language")) or "ru")
    return jsonify(exports.followup(library, project_id, lang))


@app.route("/api/projects/<project_id>/followup/sent", methods=["POST"])
def api_followup_sent(project_id):
    """The BA sent the email: its questions are now "asked"."""
    ids = (request.get_json(silent=True) or {}).get("question_ids") or []

    def mark():
        for qid in ids:
            atom = library.get_atom(qid)
            if atom["project_id"] == project_id and atom.get("q_state") != "answered":
                library.update_atom(qid, q_state="asked")
        library.audit_event("project", project_id, "followup_sent", after={"questions": len(ids)})
        return {"marked": len(ids)}
    return _store_call(mark)


@app.route("/api/projects/<project_id>/activity")
def api_activity(project_id):
    since = request.args.get("since")
    return _store_call(lambda: {"entries": library.activity(project_id, min(int(request.args.get("limit", 100)), 500),
                                                            float(since) if since else None)})


@app.route("/api/projects/<project_id>/suggestions")
def api_suggestions(project_id):
    """Rules proposed from repeated review decisions (bet 4.3)."""
    lang = request.args.get("lang") or "ru"
    return _store_call(lambda: {"suggestions": suggest.suggestions(library, project_id, lang)})


@app.route("/api/projects/<project_id>/suggestions/apply", methods=["POST"])
def api_apply_suggestion(project_id):
    d = request.get_json(silent=True) or {}
    if not (d.get("rule") or "").strip():
        return jsonify({"error": "no rule"}), 400
    try:
        name = suggest.apply(library, project_id, d["rule"], d.get("lang") or "ru")
    except (StoreError, skills.SkillError) as e:
        return jsonify({"error": str(e)}), 400
    library.audit_event("project", project_id, "rule_from_review", after={"skill": name, "rule": d["rule"][:500]})
    return jsonify({"skill": name})


@app.route("/api/projects/<project_id>/jira/orphans/<key>/forget", methods=["POST"])
def api_forget_orphan(project_id, key):
    return _store_call(lambda: (library.forget_jira_orphan(project_id, key), {"orphans": library.jira_orphans(project_id)})[1])


@app.route("/api/projects/<project_id>/export.zip")
def api_export_project(project_id):
    """The whole project in one file, to hand over or back up (PM-31)."""
    try:
        data = library.export_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps(data, ensure_ascii=False))
        for src in data["tables"]["sources"]:
            folder = library.source_dir(src)
            for name in (os.listdir(folder) if os.path.isdir(folder) else []):
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    z.write(path, f"sources/{src['id']}/{name}")
    library.audit_event("project", project_id, "export_project")
    name = "".join(ch for ch in data["tables"]["projects"][0]["name"] if ch not in '\\/:*?"<>|').strip() or "project"
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"{name}.rwproject.zip", mimetype="application/zip")


@app.route("/api/projects/import", methods=["POST"])
def api_import_project():
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "attach a .rwproject.zip file"}), 400
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(upload.read()))
        data = json.loads(z.read("project.json"))
        project = library.import_project(data)
    except (zipfile.BadZipFile, KeyError, ValueError):
        return jsonify({"error": "this is not a Dictum project file"}), 400
    except StoreError as e:
        return jsonify({"error": str(e)}), 400
    for src in data["tables"].get("sources") or []:
        folder = library.source_dir(library.get_source(src["id"]))
        prefix = f"sources/{src['id']}/"
        for name in z.namelist():
            if name.startswith(prefix) and "/" not in name[len(prefix):] and ".." not in name:
                with open(os.path.join(folder, name[len(prefix):]), "wb") as f:
                    f.write(z.read(name))
    return jsonify(project)


def notify(title, text):
    """A system notification; True when it was shown. macOS only for now."""
    title, text = str(title or "Dictum")[:120], str(text or "")[:240]
    if sys.platform == "darwin":
        script = f'display notification {json.dumps(text)} with title {json.dumps(title)}'
        try:
            done = subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return False
        if done.returncode == 0:
            _remember_permission("notifications")
        return True
    return False


@app.route("/api/notify", methods=["POST"])
def api_notify():
    """A system notification when a long job finishes and the BA is elsewhere (PM-30)."""
    d = request.get_json(silent=True) or {}
    return jsonify({"shown": notify(d.get("title"), d.get("text"))})


@app.route("/api/ai/check", methods=["POST"])
def api_ai_check():
    """Setup checklist "Проверить": is the AI for this project ready to answer? (PM-26)"""
    pid = (request.get_json(silent=True) or {}).get("project_id")
    project = library.get_project(pid) if pid else library.current_project()
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        body, code = problem
        return jsonify({"ok": False, **body.get_json()}), 200
    try:
        from core.llm import complete_json
        complete_json("Reply with ok=true.", "ping", {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                      "required": ["ok"], "additionalProperties": False},
                      prefs, api_key)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200
    return jsonify({"ok": True, "provider": prefs["llm_provider"], "model": model_name(prefs)})


@app.route("/api/sources/<source_id>", methods=["GET"])
def api_source(source_id):
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    segments, speaker_names = library.transcript(source_id)
    notes_text, recap_style = library.notes(source_id)
    summaries = library.summaries(source_id)
    current = recap_style or "brief"
    return jsonify({**source, "segments": segments, "speaker_names": speaker_names,
                    "text": library.transcript_text(source_id) if segments else "",
                    "notes": notes_text, "recap_style": recap_style,
                    "summaries": {k: {f: v[f] for f in ("text", "model", "created_at", "through_idx")}
                                  for k, v in summaries.items()},
                    # legacy: the summary of the current style, else the newest of any style
                    "summary": summaries.get(current) or library.latest_summary(source_id),
                    "atom_marks": library.atom_marks(source_id),
                    "audio_url": f"/api/sources/{source_id}/audio" if source.get("audio_file") else None,
                    "audio_files": _audio_files(source)})


@app.route("/api/sources/<source_id>/live")
def api_source_live(source_id):
    """The transcript as it grows while the meeting is recorded (5.0 C4.1): the lines after `after`; the silence
    counter, the question card and, once the recording stopped by itself, why (C4.3)."""
    try:
        library.get_source(source_id)
        after = int(request.args.get("after", -1))
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError:
        return jsonify({"error": "after must be a number"}), 400
    segments, _ = library.transcript(source_id)
    with _recorder_lock:
        st = _recorder.status() if _recorder is not None else None
        mine = bool(st and st["recording"] and _session["source_id"] == source_id)
        live = _live_state(source_id) if mine else "off"
        watch = _session.get("silence") if mine else None
        questions = _session.get("questions") if mine else None
        stopped = _session.get("stopped")
    paused = bool(mine and st["paused"])
    stopped = stopped if stopped and stopped["source_id"] == source_id and not mine else None
    return jsonify({"segments": [s for s in segments if s["idx"] > after], "recording": mine, "paused": paused,
                    "elapsed": st["elapsed"] if mine else 0, "live": live,
                    "listening": mine and not paused and live != "off",
                    "silence": int(watch.silent) if watch else 0, "silence_stop": watch.limit if watch else 0,
                    "question": questions.current() if questions else None,
                    "stopped": stopped and {"reason": stopped["reason"], "minutes": stopped["minutes"],
                                            "job_id": stopped["job_id"]}})


@app.route("/api/sources/<source_id>/live/question/dismiss", methods=["POST"])
def api_live_question_dismiss(source_id):
    """"Скрыть" (or "Добавить в заметки") on the question card: it is not shown again."""
    card_id = (request.get_json(silent=True) or {}).get("id")
    with _recorder_lock:
        questions = _session.get("questions") if _session["source_id"] == source_id else None
    return jsonify({"ok": True, "dismissed": bool(questions and questions.dismiss(card_id))})


# ── meeting notes and recap styles (5.0 C3) ──────────────────────────────────
@app.route("/api/sources/<source_id>/notes", methods=["PUT"])
def api_save_notes(source_id):
    text = (request.get_json(silent=True) or {}).get("text")
    if not isinstance(text, str):
        return jsonify({"error": "text must be a string"}), 400
    return _store_call(meeting_notes.save_notes, library, source_id, text)


@app.route("/api/sources/<source_id>/notes/append", methods=["POST"])
def api_append_note(source_id):
    try:
        return _store_call(meeting_notes.append_note, library, source_id, (request.get_json(silent=True) or {}).get("line"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


def _recap_generate(prefs, api_key):
    """The model call of a recap; the e2e fake server replaces this."""
    return lambda system, user, on_delta: summarize_mod.generate(system, user, prefs, api_key, on_delta)


def _run_recap(job_id, source_id, style, incremental, prefs, api_key, project):
    try:
        row = meeting_notes.recap(library, source_id, style, incremental, _recap_generate(prefs, api_key),
                                  _skillset(project["id"]), prefs["llm_provider"], model_name(prefs),
                                  language_rule(project), on_delta=lambda piece: jobs.append_partial(job_id, piece),
                                  concise=prefs.get("notes_style") == "concise")
    except (SummaryError, ValueError, StoreError) as e:
        jobs.fail(job_id, e)
    except Exception as e:  # unexpected: keep the message, don't crash the worker
        jobs.fail(job_id, f"Recap failed: {e}")
    else:
        jobs.finish(job_id, {"summary": row["text"], "style": style, "model": row["model"], "provider": row["provider"],
                             "through_idx": row["through_idx"], "incremental": row["incremental"],
                             "unchanged": row["unchanged"], "source_id": source_id})


@app.route("/api/sources/<source_id>/recap", methods=["POST"])
def api_recap(source_id):
    """Write or update the recap of one style (brief | bullets | actions) as a job."""
    data = request.get_json(silent=True) or {}
    style, incremental = data.get("style") or "brief", bool(data.get("incremental"))
    if style not in meeting_notes.RECAP_STYLES:
        return jsonify({"error": f"unknown recap style {style}"}), 400
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if library.last_segment_idx(source_id) is None:
        return jsonify({"error": "There is no transcript text to summarise."}), 400
    project = library.get_project(source["project_id"])
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        return problem
    job_id = jobs.create("summarize", source["title"])
    jobs.set_progress(job_id, 0, "Updating the recap…" if incremental else "Writing the recap…")
    threading.Thread(target=_run_recap, args=(job_id, source_id, style, incremental, prefs, api_key, project),
                     daemon=True).start()
    return jsonify({"job_id": job_id, "job": job_id})


# ── Спросить (5.0 C6) ────────────────────────────────────────────────────────
def _ask_generate(prefs, api_key):
    """The model call of an answer (and of the question card); the e2e fake server replaces this."""
    return lambda system, user, on_delta: summarize_mod.generate(system, user, prefs, api_key, on_delta)


ASK_PROGRESS = {"search": (10, "Searching the project…"), "generate": (40, "Writing the answer…")}


def _run_ask(job_id, project, question, context_only, prefs, api_key):
    try:
        out = ask_mod.answer(library, project["id"], question, context_only, _ask_generate(prefs, api_key),
                             skillset=_skillset(project["id"]), model=model_name(prefs),
                             language_rule=language_rule(project),
                             on_delta=lambda piece: jobs.append_partial(job_id, piece),
                             on_stage=lambda st: jobs.set_progress(job_id, *ASK_PROGRESS[st]))
    except (SummaryError, ValueError, StoreError) as e:
        jobs.fail(job_id, e)
    except Exception as e:  # unexpected: keep the message, don't crash the worker
        job_log.exception("Answer failed")
        jobs.fail(job_id, f"Answer failed: {e}")
    else:
        jobs.finish(job_id, out)


@app.route("/api/projects/<project_id>/ask", methods=["POST"])
def api_ask(project_id):
    """A question across the project's meetings, requirements and materials; the answer streams into the job."""
    data = request.get_json(silent=True) or {}
    question = str(data.get("question") or "").strip()
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if not question:
        return jsonify({"error": "Ask a question first."}), 400
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        return problem
    job_id = jobs.create("ask", question[:80])
    jobs.set_progress(job_id, *ASK_PROGRESS["search"])
    threading.Thread(target=_run_ask, args=(job_id, project, question, data.get("context_only", True) is not False,
                                            prefs, api_key), daemon=True).start()
    return jsonify({"job": job_id, "job_id": job_id})


@app.route("/api/projects/<project_id>/ask/history")
def api_ask_history(project_id):
    """The project's questions, newest first; whether there is anything to ask about and whether the index works."""
    try:
        library.get_project(project_id)
        limit = int(request.args.get("limit") or 50)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError:
        return jsonify({"error": "limit must be a number"}), 400
    return jsonify({"items": library.ask_history(project_id, limit), "searchable": library.has_searchable(project_id),
                    "indexed": local_index.available()})


@app.route("/api/ask/<ask_id>", methods=["DELETE"])
def api_ask_delete(ask_id):
    return _store_call(library.delete_ask, ask_id)


@app.route("/api/sources/<source_id>/segments/<int:idx>", methods=["PATCH"])
def api_edit_segment(source_id, idx):
    """Correct a recognition error; returns atoms whose quote no longer matches (PM-25)."""
    return _store_call(library.edit_segment, source_id, idx, (request.get_json(silent=True) or {}).get("text"))


@app.route("/api/consent", methods=["POST"])
def api_consent():
    """The BA confirmed the participants know the call is recorded (FR-SRC-02, PM-05)."""
    d = request.get_json(silent=True) or {}
    pid = d.get("project_id") or library.current_project()["id"]
    library.audit_event("project", pid, "recording_consent", after={"note": (d.get("note") or "")[:200]})
    return jsonify({"ok": True})


@app.route("/api/sources/<source_id>", methods=["PATCH"])
def api_update_source(source_id):
    data = request.get_json(silent=True) or {}
    if set(data) - {"title", "recap_style"}:
        return jsonify({"error": "only the title and the recap style can be changed here"}), 400
    if "recap_style" in data:                       # the style chosen on the meeting page (5.0 C3)
        style = data.pop("recap_style")
        try:
            library.get_source(source_id)
            library.set_recap_style(source_id, style)
        except StoreError as e:
            return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
        if not data:
            return jsonify({**library.get_source(source_id), "recap_style": style})
    return _store_call(library.update_source, source_id, **data)


@app.route("/api/sources/<source_id>", methods=["DELETE"])
def api_delete_source(source_id):
    return _store_call(lambda: (library.delete_source(source_id), {"ok": True})[1])


@app.route("/api/sources/<source_id>/restore", methods=["POST"])
def api_restore_source(source_id):
    return _store_call(lambda: (library.restore_source(source_id), {"ok": True})[1])


# ── Материалы, labels and keyword search (5.0 C5) ────────────────────────────

def _material_payload(m, full=False):
    """A material for the client: the preview instead of the whole text, unless `full`."""
    text = m.pop("text", "") or ""
    out = {**m, "preview": text[:library.PREVIEW_CHARS], "has_file": bool(m.get("path") and os.path.exists(m["path"]))}
    if full:
        out["text"] = text
    return out


def _material_call(fn, *args, **kwargs):
    try:
        return jsonify(fn(*args, **kwargs)), 200
    except (StoreError, materials.MaterialError) as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400


@app.route("/api/projects/<project_id>/materials", methods=["GET"])
def api_materials(project_id):
    try:
        library.get_project(project_id)
        a = request.args
        rows = library.list_materials(project_id, kind=a.get("kind") or None, label=a.get("label") or None, q=a.get("q"))
    except StoreError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    return jsonify({"materials": rows})


def _run_folder_import(job_id, project, folder):
    def progress(done, total, name):
        jobs.set_progress(job_id, int(100 * done / max(total, 1)), f"{done}/{total} {name}".strip())
    try:
        result = materials.import_folder(library, project, folder, progress)
    except Exception as e:
        jobs.fail(job_id, str(e))
    else:
        jobs.finish(job_id, result)
        _index_after(project["id"], is_source=False)


@app.route("/api/projects/<project_id>/materials", methods=["POST"])
def api_add_materials(project_id):
    """Multipart files, or JSON {url}, {text, title} or {folder} (a job). Files, links and text are imported at once."""
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if request.files:
        uploads = request.files.getlist("files") + request.files.getlist("file")
        done, failed = [], []
        for up in uploads:
            name = os.path.basename(up.filename or "file")
            try:
                done.append(_material_payload(materials.import_file(library, project, name,
                                                                    up.read(materials.MAX_BYTES + 1))))
            except (materials.MaterialError, StoreError) as e:
                failed.append(f"{name}: {e}")
        if not done and failed:
            return jsonify({"error": "; ".join(failed), "failed": failed}), 400
        return jsonify({"materials": done, "failed": failed,
                        "index_job": _index_after(project_id, is_source=False) if done else None})
    data = request.get_json(silent=True) or {}
    try:
        if data.get("folder"):
            materials.folder_files(data["folder"])           # a wrong path fails here, not inside the job
            job_id = jobs.create("import", os.path.basename(os.path.normpath(data["folder"])))
            jobs.set_progress(job_id, 0, "")
            threading.Thread(target=_run_folder_import, args=(job_id, project, data["folder"]), daemon=True).start()
            return jsonify({"job_id": job_id})
        if data.get("url"):
            m = materials.import_url(library, project, data["url"])
        elif data.get("text") is not None:
            m = materials.import_text(library, project, data.get("text"), data.get("title"))
        else:
            return jsonify({"error": "send files, a url, a text or a folder"}), 400
    except (materials.MaterialError, StoreError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"materials": [_material_payload(m)], "failed": [],
                    "index_job": _index_after(project_id, is_source=False)})


@app.route("/api/materials/<material_id>", methods=["GET"])
def api_material(material_id):
    return _material_call(lambda: _material_payload(library.get_material(material_id), request.args.get("full") == "1"))


@app.route("/api/materials/<material_id>", methods=["PATCH"])
def api_update_material(material_id):
    data = request.get_json(silent=True) or {}
    return _material_call(lambda: _material_payload(library.update_material(material_id, **data)))


@app.route("/api/materials/<material_id>", methods=["DELETE"])
def api_delete_material(material_id):
    """Soft delete, like a source: POST /api/sources/<id>/restore (or /api/materials/<id>/restore) undoes it."""
    def delete():
        library.get_material(material_id)
        library.delete_source(material_id)
        return {"ok": True}
    return _material_call(delete)


@app.route("/api/materials/<material_id>/restore", methods=["POST"])
def api_restore_material(material_id):
    return _material_call(lambda: (library.restore_source(material_id), {"ok": True})[1])


@app.route("/api/materials/<material_id>/resync", methods=["POST"])
def api_resync_material(material_id):
    def run():
        m = library.get_material(material_id)
        return _material_payload(materials.resync(library, library.get_project(m["project_id"]), material_id))
    return _material_call(run)


@app.route("/api/materials/<material_id>/open", methods=["POST"])
def api_open_material(material_id):
    """Open the library's copy of the file with its default app (desktop only; the browser shows the text)."""
    try:
        m = library.get_material(material_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    path = m.get("path")
    if not IS_DESKTOP or not path or not os.path.exists(path):
        return jsonify({"error": "no file to open here"}), 400
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — the library's own copy of the user's file
    else:
        subprocess.Popen(["xdg-open", path])
    return jsonify({"ok": True, "path": path})


@app.route("/api/projects/<project_id>/search")
def api_search(project_id):
    try:
        library.get_project(project_id)
        limit = int(request.args.get("limit", 30))
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    except ValueError:
        return jsonify({"error": "limit must be a number"}), 400
    return jsonify({"hits": library.search(project_id, request.args.get("q"), limit)})


@app.route("/api/projects/<project_id>/labels", methods=["GET"])
def api_labels(project_id):
    return _material_call(lambda: (library.get_project(project_id), {"labels": library.list_labels(project_id)})[1])


@app.route("/api/projects/<project_id>/labels", methods=["POST"])
def api_create_label(project_id):
    """{name, seed_material_id?} → {label, assigned: [material ids], auto: [{id, score}], index}. The seed gets the label
    (by hand); with the index, materials close to the seed (or, without a seed, to the label's name) get it too."""
    data = request.get_json(silent=True) or {}

    def create():
        seed = data.get("seed_material_id")
        if seed:
            m = library.get_material(seed)
            if m["project_id"] != project_id:
                raise StoreError("the material belongs to another project")
        label = library.create_label(project_id, data.get("name"))
        assigned, auto, ready = [], [], local_index.available()
        if seed and library.assign_label(seed, label["id"], by="user"):
            assigned.append(seed)
        if ready:
            try:
                auto = local_index.auto_assign_label(library, project_id, label, seed)
            except (local_index.IndexUnavailable, local_llm.LocalModelError) as e:
                job_log.warning("auto labels for %s: %s", label["id"], e)
                ready = False
        local_index.refresh_centroid(library, label["id"])
        assigned += [a["id"] for a in auto]
        return {"label": {**label, "count": len(assigned)}, "assigned": assigned, "auto": auto, "index": ready}
    return _material_call(create)


@app.route("/api/labels/<label_id>", methods=["DELETE"])
def api_delete_label(label_id):
    return _material_call(lambda: (library.delete_label(label_id), {"ok": True})[1])


@app.route("/api/materials/<material_id>/labels/<label_id>", methods=["POST"])
def api_assign_label(material_id, label_id):
    def assign():
        library.assign_label(material_id, label_id, by="user")
        local_index.refresh_centroid(library, label_id)
        return {"labels": library.get_material(material_id)["labels"]}
    return _material_call(assign)


@app.route("/api/materials/<material_id>/labels/<label_id>", methods=["DELETE"])
def api_unassign_label(material_id, label_id):
    """An automatic label taken off leaves a tombstone, so auto runs never put it back."""
    def unassign():
        library.unassign_label(material_id, label_id)
        local_index.refresh_centroid(library, label_id)
        return {"labels": library.get_material(material_id)["labels"]}
    return _material_call(unassign)


# ── the local index (5.0 C5): related materials, the graph, "Где используется" ──
_index_pending = {}       # project id → the job id of an index pass that has not started yet
_index_lock = threading.Lock()


def schedule_index(project_id, force_material=None):
    """Queue an index pass for the project. A pass already waiting covers this request too; one already running
    does not (what changed after it started needs another), so at most one runs and one waits per project.
    Nothing happens while the index model is not downloaded."""
    if not local_index.available():
        return None
    with _index_lock:
        waiting = _index_pending.get(project_id)
        if waiting and not force_material:
            return waiting
        try:
            name = library.get_project(project_id)["name"]
        except StoreError:
            return None
        job_id = jobs.create("index", name)
        jobs.set_progress(job_id, 0, "")
        _index_pending[project_id] = job_id
    threading.Thread(target=_run_index, args=(job_id, project_id, force_material), daemon=True).start()
    return job_id


def _run_index(job_id, project_id, force_material=None):
    def progress(done, total):
        jobs.set_progress(job_id, int(100 * done / max(total, 1)), f"{done}/{total}")

    def work():
        with _index_lock:
            if _index_pending.get(project_id) == job_id:
                del _index_pending[project_id]          # changes from now on need another pass
        return local_index.index_project(library, project_id, progress, force_material=force_material)
    try:
        result = index_queue.run(job_id, work)
    except Exception as e:
        job_log.exception("Index job %s failed", job_id)
        jobs.fail(job_id, e)
    else:
        jobs.finish(job_id, result)


def _index_after(source_or_project_id, is_source=True):
    """A trigger (import, transcript saved, atoms added): never fails the request that caused it."""
    try:
        pid = library.get_source(source_or_project_id)["project_id"] if is_source else source_or_project_id
        return schedule_index(pid)
    except Exception:
        job_log.exception("could not schedule the index")
        return None


@app.route("/api/projects/<project_id>/index", methods=["POST"])
def api_index_project(project_id):
    """{material_id?}: bring the project's index up to date; with a material, re-embed that one from scratch."""
    data = request.get_json(silent=True) or {}
    try:
        library.get_project(project_id)
        if data.get("material_id") and library.get_material(data["material_id"])["project_id"] != project_id:
            raise StoreError("the material belongs to another project")
    except StoreError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    return jsonify({"job_id": schedule_index(project_id, data.get("material_id")), **local_index.info()})


@app.route("/api/materials/<material_id>/related")
def api_material_related(material_id):
    """The 5 materials most like this one, by their best pair of chunks: {related: [{id, title, ext, kind, score}]}."""
    def related():
        m = library.get_material(material_id)
        info = local_index.info()
        if not info["available"]:
            return {"related": [], **info}
        rows = {x["id"]: x for x in library.list_materials(m["project_id"])}
        out = [{"id": sid, "title": rows[sid]["title"], "ext": rows[sid]["ext"], "kind": rows[sid]["material_kind"],
                "score": score} for sid, score in local_index.related(library, m["project_id"], material_id) if sid in rows]
        return {"related": out, **info}
    return _material_call(related)


@app.route("/api/projects/<project_id>/materials/graph")
def api_materials_graph(project_id):
    """{nodes: [{id, title, ext, kind, label, color}], edges: [{a, b, w}], truncated}: the graph view."""
    def build():
        library.get_project(project_id)
        info = local_index.info()
        if not info["available"]:
            return {"nodes": [], "edges": [], "truncated": False, **info}
        return {**local_index.graph(library, project_id), **info}
    return _material_call(build)


@app.route("/api/materials/<material_id>/used-in")
def api_material_used_in(material_id):
    """"Где используется": {atoms: [{id, type, statement, status, rid}], documents: [{id, title, version}]}."""
    def used_in():
        library.get_material(material_id)
        return library.used_in(material_id)
    return _material_call(used_in)


@app.route("/api/sources/<source_id>/speakers/<path:label>", methods=["PUT"])
def api_rename_speaker(source_id, label):
    data = request.get_json(silent=True) or {}
    return _store_call(lambda: (library.rename_speaker(source_id, label, data.get("name")),
                                {"ok": True, "speaker_names": library.transcript(source_id)[1]})[1])


AUDIO_FILES = (("mixed", "mixed.wav"), ("mic", "mic.wav"), ("sys", "sys.wav"))


def _audio_files(source):
    """What the user can save from a source: the recording's channels, or the file they imported."""
    folder = library.source_dir(source)
    out = []
    if source.get("kind") == "recording":
        for which, name in AUDIO_FILES:
            path = os.path.join(folder, name)
            if os.path.exists(path):
                out.append({"id": which, "name": name, "size": os.path.getsize(path)})
    originals = [n for n in os.listdir(folder) if n.startswith("original.")] if os.path.isdir(folder) else []
    for name in originals:
        out.append({"id": "original", "name": name, "size": os.path.getsize(os.path.join(folder, name)),
                    "filename": source.get("original_filename") or name})
    if not out and source.get("audio_file") and os.path.exists(os.path.join(folder, source["audio_file"])):
        out.append({"id": "audio", "name": source["audio_file"],
                    "size": os.path.getsize(os.path.join(folder, source["audio_file"]))})
    return out


@app.route("/api/sources/<source_id>/audio/files")
def api_source_audio_files(source_id):
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"files": _audio_files(source)})


@app.route("/api/sources/<source_id>/audio/download/<which>")
def api_source_audio_download(source_id, which):
    """The audio as a file to save (the player streams from /audio instead)."""
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    entry = next((f for f in _audio_files(source) if f["id"] == which), None)
    if not entry:
        return jsonify({"error": "no such audio file"}), 404
    ext = os.path.splitext(entry["name"])[1]
    # The page names the file (title + channel in the user's language); the browser follows the header, not the link.
    asked = re.sub(r'[\\/:*?"<>|]+', " ", os.path.basename(request.args.get("name") or "")).strip()
    name = asked if asked.lower().endswith(ext.lower()) else (
        entry.get("filename") or (re.sub(r'[\\/:*?"<>|]+', " ", source["title"]).strip() or "audio") + ext)
    return send_file(os.path.join(library.source_dir(source), entry["name"]), as_attachment=True,
                     download_name=name, conditional=True)


@app.route("/api/sources/<source_id>/audio")
def api_source_audio(source_id):
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if not source.get("audio_file"):
        return jsonify({"error": "this source has no audio"}), 404
    # conditional=True answers Range requests, so the player can seek.
    return send_file(os.path.join(library.source_dir(source), source["audio_file"]), conditional=True)


@app.route("/api/sources/<source_id>/transcribe", methods=["POST"])
def api_transcribe_source(source_id):
    """(Re)transcribe a saved source's audio, e.g. a recording after Stop."""
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if not source.get("audio_file"):
        return jsonify({"error": "this source has no audio to transcribe"}), 400
    opts, error = _transcription_options(request.get_json(silent=True) or {})
    if error:
        return jsonify({"error": error}), 400
    if _transcription_in_progress(source_id):
        return jsonify({"error": "This source is being transcribed right now. Let it finish, or quit and "
                                 "reopen the app to stop it; then transcribe again."}), 409
    library.update_source(source_id, status="processing", asr_model=opts["model_name"], error=None)
    job_id = _start_transcription(source, os.path.join(library.source_dir(source), source["audio_file"]), opts)
    return jsonify({"job_id": job_id, "source_id": source_id})


@app.route("/api/audit")
def api_audit():
    return jsonify({"entries": library.audit(request.args.get("entity"), request.args.get("entity_id"),
                                             min(int(request.args.get("limit", 200)), 1000))})


# ── requirement atoms (increment 2) ─────────────────────────────────────────
_extracting = {}          # source_id → job_id, so a double click doesn't run two extractions


def _run_extraction(job_id, source_id, prefs, api_key, note=None):
    def progress(done, total, message):
        jobs.set_progress(job_id, int(100 * done / max(total, 1)), message)
    try:
        project_id = library.get_source(source_id)["project_id"]
        result = extract_atoms(library, source_id, prefs, api_key, progress=progress,
                               skillset=_skillset(project_id), note=note)
    except SummaryError as e:
        jobs.fail(job_id, e)
    except Exception as e:  # unexpected: keep the message, don't crash the worker
        jobs.fail(job_id, f"Extraction failed: {e}")
    else:
        library.audit_event("source", source_id, "extract_atoms", after=result)
        jobs.finish(job_id, {**result, "source_id": source_id})
        _index_after(source_id)
    finally:
        _extracting.pop(source_id, None)


@app.route("/api/sources/<source_id>/atoms/extract", methods=["POST"])
def api_extract_atoms(source_id):
    try:
        source = library.get_source(source_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    if source["status"] != "ready":
        return jsonify({"error": "This source has no text yet."}), 400
    running = _extracting.get(source_id)
    if running and (jobs.get(running) or {}).get("status") == "processing":
        return jsonify({"job_id": running, "source_id": source_id})
    prefs, api_key, problem = _ai_prefs(library.get_project(source["project_id"]))
    if problem:
        return problem
    note = (request.get_json(silent=True) or {}).get("note")
    return jsonify(_start_extraction(source_id, prefs, api_key, note))


def _start_extraction(source_id, prefs, api_key, note=None):
    try:
        label = library.get_source(source_id)["title"]
    except StoreError:
        label = ""
    job_id = jobs.create("extract", label)
    _extracting[source_id] = job_id
    jobs.set_progress(job_id, 0, "Reading the source…")
    threading.Thread(target=_run_extraction, args=(job_id, source_id, prefs, api_key, note), daemon=True).start()
    return {"job_id": job_id, "source_id": source_id}


def _after_transcription(source_id):
    """PM-13: when the project wants it and the AI is set up, go straight on to requirement extraction. A project with
    business analysis off (a meeting recorder, 5.0.4) never starts extraction by itself."""
    try:
        source = library.get_source(source_id)
        project = library.get_project(source["project_id"])
    except StoreError:
        return None
    if not project.get("analysis", True) or not project.get("auto_extract") or source["status"] != "ready" or source_id in _extracting:
        return None
    try:                                    # a convenience: it must never fail the transcription itself
        prefs, api_key, problem = _ai_prefs(project)
        if problem:
            return None
        return _start_extraction(source_id, prefs, api_key)["job_id"]
    except Exception:
        return None


@app.route("/api/projects/<project_id>/atoms")
def api_atoms(project_id):
    try:
        library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    a = request.args
    atoms = library.list_atoms(project_id, status=a.get("status"), type=a.get("type"), source_id=a.get("source_id"))
    if a.get("status") is None:
        atoms = [x for x in atoms if x["status"] != "merged"]
    known = library.known_requirement_ids(project_id)
    for x in atoms:                       # the ID the atom has in documents, if it has been given one
        x["rid"] = known.get(x["id"], {}).get(ATOM_PREFIX[x["type"]])
    return jsonify({"atoms": atoms, "stats": library.atom_stats(project_id)})


@app.route("/api/atoms/<atom_id>", methods=["PATCH"])
def api_update_atom(atom_id):
    data = request.get_json(silent=True) or {}
    changes = dict(data)            # the store rejects fields that can't be changed

    def update():
        atom = library.update_atom(atom_id, **changes)
        return {**atom, "stats": library.atom_stats(atom["project_id"])}
    return _store_call(update)


@app.route("/api/atoms/<atom_id>/answer", methods=["POST"])
def api_answer_question(atom_id):
    """The client's answer to a question; for a conflict's question it may settle the conflict (PM-21)."""
    d = request.get_json(silent=True) or {}

    def answer():
        atom = library.answer_question(atom_id, d.get("answer"), d.get("source"), d.get("resolution"), d.get("statement"))
        return {**atom, "stats": library.atom_stats(atom["project_id"])}
    return _store_call(answer)


@app.route("/api/projects/<project_id>/atoms", methods=["POST"])
def api_add_ba_atom(project_id):
    """A requirement the BA writes down themselves (PM-16)."""
    d = request.get_json(silent=True) or {}

    def add():
        atom = library.add_ba_atom(project_id, d.get("type") or "functional", d.get("statement"), d.get("note"),
                                   d.get("source_id"), d.get("segment_idx"))
        _index_after(project_id, is_source=False)
        return {**atom, "stats": library.atom_stats(project_id)}
    return _store_call(add)


@app.route("/api/projects/<project_id>/atoms/reclassify", methods=["POST"])
def api_reclassify_atoms(project_id):
    """Let the AI re-type existing atoms (business / risk / current state were added in 3.3); applied at once,
    with the previous types returned for undo."""
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        return problem
    job_id = jobs.create("extract", project["name"])
    jobs.set_progress(job_id, 0, "Reading the source…")

    def run():
        from core import atoms as atoms_mod
        try:
            changes = atoms_mod.reclassify(library, project_id, prefs, api_key, skillset=_skillset(project_id),
                                           progress=lambda d, t, m: jobs.set_progress(job_id, int(100 * d / max(t, 1)), m))
            if changes:
                library.bulk_update_atoms(project_id, [{"id": c["id"], "type": c["to"]} for c in changes])
            library.audit_event("project", project_id, "reclassify_atoms", after={"changed": len(changes)})
            jobs.finish(job_id, {"changes": changes, "stats": library.atom_stats(project_id)})
        except SummaryError as e:
            jobs.fail(job_id, e)
        except Exception as e:  # unexpected: keep the message, don't crash the worker
            jobs.fail(job_id, f"Reclassifying failed: {e}")
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/projects/<project_id>/atoms/bulk", methods=["POST"])
def api_bulk_atoms(project_id):
    """Accept / reject / return to review / retype many atoms at once (items = [{id, status?, type?}])."""
    items = (request.get_json(silent=True) or {}).get("items")
    return _store_call(lambda: {"changed": library.bulk_update_atoms(project_id, items),
                                "stats": library.atom_stats(project_id)})


@app.route("/api/projects/<project_id>/atoms/delete", methods=["POST"])
def api_delete_atoms(project_id):
    ids = (request.get_json(silent=True) or {}).get("ids")
    return _store_call(lambda: {"deleted": library.delete_atoms(project_id, ids), "stats": library.atom_stats(project_id)})


@app.route("/api/projects/<project_id>/atoms/restore", methods=["POST"])
def api_restore_atoms(project_id):
    ids = (request.get_json(silent=True) or {}).get("ids")
    return _store_call(lambda: {"restored": library.restore_atoms(project_id, ids), "stats": library.atom_stats(project_id)})


@app.route("/api/atoms/<atom_id>/merge", methods=["POST"])
def api_merge_atom(atom_id):
    into = (request.get_json(silent=True) or {}).get("into")
    return _store_call(lambda: (library.merge_atoms(atom_id, into), library.get_atom(into))[1])


@app.route("/api/projects/<project_id>/conflicts")
def api_conflicts(project_id):
    return _store_call(lambda: {"conflicts": library.list_conflicts(project_id)})


@app.route("/api/conflicts/<conflict_id>/resolve", methods=["POST"])
def api_resolve_conflict(conflict_id):
    data = request.get_json(silent=True) or {}
    return _store_call(library.resolve_conflict, conflict_id, data.get("action"), data.get("statement"))


# ── FRD document (increment 3) ──────────────────────────────────────────────
_building = {}            # document_id → job_id


def _visible_issues(document_id, content):
    """Hide quality findings the BA dismissed; a dismissal lapses once the atom's wording changes."""
    dismissed = library.dismissed(document_id)
    if not dismissed:
        return content
    current = {}
    for _num, _key, b in frd.req_blocks(content):
        aid = b["atom_id"]
        if aid not in current:
            try:
                current[aid] = library.get_atom(aid)["statement"]
            except StoreError:
                current[aid] = None
        b["issues"] = [i for i in b.get("issues") or [] if dismissed.get((aid, i["rule"])) != current[aid]]
    return content


def _doc_summary(doc, project_id, lang):
    """A document for the tab bar: its type, latest version and whether it is behind the atoms."""
    skill = frd.document_skill(doc, _skillset(project_id))
    latest = library.version(doc["id"])
    stale = frd.staleness(library, project_id, latest) if latest else None
    placed, context = skills.doc_atom_types(skill.meta)
    return {**doc, "kind": skill.name, "type": skill.title_in(lang), "short": title_text_short(skill, lang),
            "version": latest["number"] if latest else None, "stale": bool(stale and stale["stale"]),
            "status": latest.get("status") if latest else None, "atom_types": placed, "context_types": context,
            "decomposes": frd.decomposes(doc, skill), "decompose_default": frd.decomposes({}, skill)}


def title_text_short(skill, lang):
    return skills.title_text(skill.meta.get("short"), lang) if skill.meta.get("short") else skill.title_in(lang)


@app.route("/api/projects/<project_id>/documents")
def api_documents(project_id):
    """The project's documents (BRD, SRS, Vision & Scope, risks, As-Is/To-Be…) and the types one can add."""
    lang = _lang()
    try:
        library.document(project_id)                 # every project has at least its primary document
        docs = [_doc_summary(d, project_id, lang) for d in library.documents(project_id)]
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    types = [{"name": sk.name, "title": sk.title_in(lang), "short": title_text_short(sk, lang),
              "description": sk.description_in(lang), "builtin": sk.builtin,
              "atom_types": skills.doc_atom_types(sk.meta)[0], "decomposes": frd.decomposes({}, sk)}
             for sk in skills.all_skills() if sk.stage == "frd" and not sk.error]
    return jsonify({"documents": docs, "types": types,
                    "requirements_document": frd.requirements_document(library, project_id)["id"]})


@app.route("/api/projects/<project_id>/documents", methods=["POST"])
def api_create_document(project_id):
    d = request.get_json(silent=True) or {}
    lang = _lang()

    def create():
        project = library.get_project(project_id)
        skill = skills.get(d.get("kind") or "")
        if skill.stage != "frd" or skill.error:
            raise StoreError("choose a document type")
        title = (d.get("title") or "").strip() or f"{title_text_short(skill, lang)} — {project['name']}"
        return _doc_summary(library.create_document(project_id, skill.name, title), project_id, lang)
    try:
        return _store_call(create)
    except skills.SkillError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/documents/<document_id>", methods=["DELETE"])
def api_delete_document(document_id):
    try:
        doc = library.get_document(document_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    try:
        library.delete_document(document_id)          # any document, as long as one stays
    except StoreError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "documents": [d["id"] for d in library.documents(doc["project_id"])]})


@app.route("/api/projects/<project_id>/document")
def api_document(project_id):
    try:
        doc = library.get_document(request.args["document"]) if request.args.get("document") else library.document(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    version = library.version(doc["id"], request.args.get("version"))
    stats = library.atom_stats(project_id)
    if version:
        version["content"] = _visible_issues(doc["id"], version["content"])
        latest = library.versions(doc["id"])[0]["number"]
        stale = frd.staleness(library, project_id, library.version(doc["id"]) if version["number"] != latest else version)
        version.pop("snapshot", None)
    else:
        stale = None
    job = _building.get(doc["id"])
    doc = _doc_summary(doc, project_id, _lang())
    relevant = sum(1 for a in library.list_atoms(project_id, status="accepted") if a["type"] in doc["atom_types"])
    return jsonify({"document": doc, "versions": library.versions(doc["id"]), "version": version, "stale": stale,
                    "relevant": relevant,
                    "free_blocks": library.free_blocks(doc["id"]), "stats": stats,
                    "building": job if job and (jobs.get(job) or {}).get("status") == "processing" else None})


def _run_build(job_id, project_id, prefs, api_key, mode, note=None, document_id=None):
    try:
        result = frd.build(library, project_id, prefs, api_key, mode=mode, note=note, document_id=document_id,
                           progress=lambda pct, msg: jobs.set_progress(job_id, pct, msg), skillset=_skillset(project_id))
    except (frd.BuildError, SummaryError) as e:
        jobs.fail(job_id, e)
    except Exception as e:  # unexpected: keep the message, don't crash the worker
        jobs.fail(job_id, f"Building the document failed: {e}")
    else:
        jobs.finish(job_id, result)
    finally:
        _building.pop(document_id or library.document(project_id)["id"], None)


@app.route("/api/projects/<project_id>/document/build", methods=["POST"])
def api_build_document(project_id):
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    body = request.get_json(silent=True) or {}
    mode, note = body.get("mode", "changed"), body.get("note")
    if mode not in ("changed", "full"):
        return jsonify({"error": "mode must be changed or full"}), 400
    if not library.atom_stats(project_id)["accepted"]:
        return jsonify({"error": "There are no accepted atoms yet. Review the atoms first."}), 400
    try:
        doc = library.get_document(body["document_id"]) if body.get("document_id") else library.document(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    running = _building.get(doc["id"])
    if running and (jobs.get(running) or {}).get("status") == "processing":
        return jsonify({"job_id": running})
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        return problem
    job_id = jobs.create("document", doc["title"])
    _building[doc["id"]] = job_id
    jobs.set_progress(job_id, 0, "Writing the document…")
    threading.Thread(target=_run_build, args=(job_id, project_id, prefs, api_key, mode, note, doc["id"]),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/documents/<document_id>", methods=["PATCH"])
def api_update_document(document_id):
    return _store_call(library.update_document, document_id, **(request.get_json(silent=True) or {}))


@app.route("/api/documents/<document_id>/diff")
def api_document_diff(document_id):
    try:
        new = library.version(document_id, request.args.get("to"))
        old = library.version(document_id, request.args.get("from") or (new["number"] - 1 if new else None))
    except (StoreError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    if not new or not old or old["number"] == new["number"]:
        return jsonify({"error": "there is no earlier version to compare with"}), 400
    return jsonify({"from": old["number"], "to": new["number"], "changes": frd.diff(old, new)})


@app.route("/api/documents/<document_id>/versions/<int:number>/status", methods=["POST"])
def api_version_status(document_id, number):
    """Sign-off: draft / review / approved (PM-34)."""
    status = (request.get_json(silent=True) or {}).get("status")
    return _store_call(lambda: (library.set_version_status(document_id, number, status),
                                {"versions": library.versions(document_id), "baseline": library.baseline(document_id)})[1])


@app.route("/api/documents/<document_id>/changes")
def api_document_changes(document_id):
    """Change requests: everything that differs from the approved baseline, and what it touches downstream."""
    try:
        doc = library.get_document(document_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    base_n = library.baseline(document_id)
    latest = library.version(document_id)
    if not base_n or not latest or latest["number"] == base_n:
        return jsonify({"baseline": base_n, "changes": []})
    changes = frd.diff(library.version(document_id, base_n), latest)
    by_ref = {}
    for item in library.backlog(doc["project_id"]):
        for r in item.get("refs") or []:
            by_ref.setdefault(r["id"], []).append({"title": item["title"], "key": item.get("jira_key"),
                                                   "url": item.get("jira_url")})
    for c in changes:
        c["impact"] = by_ref.get(c["id"], [])
    return jsonify({"baseline": base_n, "to": latest["number"], "changes": changes})


@app.route("/api/documents/<document_id>/export.md")
def api_export_markdown(document_id):
    try:
        doc = library.get_document(document_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    version = library.version(document_id, request.args.get("version"))
    if not version:
        return jsonify({"error": "build the document first"}), 400
    lang = version["content"].get("language", "ru")
    text = exports.markdown(doc, version, library.free_blocks(document_id), lang)
    library.audit_event("document", document_id, "export", after={"version": version["number"], "format": "md"})
    name = "".join(ch for ch in doc["title"] if ch not in '\\/:*?"<>|').strip() or "FRD"
    return send_file(io.BytesIO(text.encode("utf-8")), as_attachment=True, download_name=f"{name} v{version['number']}.md",
                     mimetype="text/markdown; charset=utf-8")


@app.route("/api/projects/<project_id>/traceability.xlsx")
def api_traceability(project_id):
    """Quote → atom → FR → story → Jira, one row per piece of evidence (PM-28)."""
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    lang = request.args.get("lang") or "ru"
    rows, version = exports.traceability_rows(library, project_id, lang)
    if version is None:
        return jsonify({"error": "build the document first"}), 400
    name = "".join(ch for ch in project["name"] if ch not in '\\/:*?"<>|').strip() or "project"
    return send_file(io.BytesIO(exports.xlsx(rows)), as_attachment=True,
                     download_name=f"{name} — traceability v{version['number']}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/api/documents/<document_id>/review", methods=["POST"])
def api_import_review(document_id):
    """A reviewed .docx comes back: each comment becomes a line of a new source, tagged with its FR id (bet 4.4)."""
    try:
        doc = library.get_document(document_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    upload = request.files.get("file")
    if not upload:
        return jsonify({"error": "attach the reviewed .docx"}), 400
    found = exports.docx_comments(upload.read())
    if not found:
        return jsonify({"error": "No review comments found in this file."}), 400
    title = f"{os.path.splitext(upload.filename or 'review')[0]} — замечания"
    source = library.create_source(doc["project_id"], "document", title, original_filename=upload.filename)
    segments = [{"speaker": author or None, "text": (f"[{req}] " if req else "") + text +
                 (f" (к тексту: «{anchor}»)" if anchor else "")} for req, author, text, anchor in found]
    library.save_transcript(source["id"], {"segments": segments, "text": "\n".join(s["text"] for s in segments)})
    return jsonify({"source_id": source["id"], "comments": len(found),
                    "linked": sum(1 for req, *_ in found if req)})


@app.route("/api/documents/<document_id>/export.docx")
def api_export_docx(document_id):
    try:
        doc = library.get_document(document_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    version = library.version(document_id, request.args.get("version"))
    if not version:
        return jsonify({"error": "build the document first"}), 400
    name = request.args.get("template") or doc["template"]
    try:
        skill = skills.get(library.LEGACY_TEMPLATES.get(name, name))
        if skill.stage != "export" or skill.error:
            raise skills.SkillError(f"'{name}' is not a working export skill")
        template = skills.template_bytes(skill)
    except (skills.SkillError, OSError) as e:
        return jsonify({"error": str(e)}), 400
    try:
        from core import docx_export          # loaded on demand: the rest of the app works without it
    except ImportError:
        return jsonify({"error": "Word export is still being installed: restart the app to let setup finish."}), 503
    project = library.get_project(doc["project_id"])
    data = docx_export.render(doc, version, library.free_blocks(document_id), template=template,
                              numbering=skill.meta.get("numbering", "dot"), project_name=project["name"])
    library.audit_event("document", document_id, "export", after={"version": version["number"], "template": skill.name})
    name = "".join(ch for ch in doc["title"] if ch not in '\\/:*?"<>|').strip() or "FRD"
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{name} v{version['number']}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.route("/api/documents/<document_id>/free-blocks", methods=["POST"])
def api_add_free_block(document_id):
    data = request.get_json(silent=True) or {}
    return _store_call(lambda: {"id": library.add_free_block(document_id, data.get("section"), data.get("text")),
                                "free_blocks": library.free_blocks(document_id)})


@app.route("/api/free-blocks/<block_id>", methods=["PATCH"])
def api_update_free_block(block_id):
    return _store_call(lambda: (library.update_free_block(block_id, (request.get_json(silent=True) or {}).get("text")),
                                {"ok": True})[1])


@app.route("/api/free-blocks/<block_id>", methods=["DELETE"])
def api_delete_free_block(block_id):
    return _store_call(lambda: (library.delete_free_block(block_id), {"ok": True})[1])


@app.route("/api/free-blocks/<block_id>/restore", methods=["POST"])
def api_restore_free_block(block_id):
    return _store_call(lambda: (library.delete_free_block(block_id, restore=True), {"ok": True})[1])


def _run_fix(job_id, project_id, atom_id, rule, message, prefs, api_key):
    try:
        jobs.finish(job_id, frd.suggest_fix(library, project_id, atom_id, rule, message, prefs, api_key,
                                            skillset=_skillset(project_id)))
    except (SummaryError, StoreError) as e:
        jobs.fail(job_id, e)
    except Exception as e:
        jobs.fail(job_id, f"Could not suggest a fix: {e}")


@app.route("/api/documents/<document_id>/fix", methods=["POST"])
def api_fix(document_id):
    data = request.get_json(silent=True) or {}
    try:
        doc = library.get_document(document_id)
        library.get_atom(data.get("atom_id"))
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    prefs, api_key, problem = _ai_prefs(library.get_project(doc["project_id"]))
    if problem:
        return problem
    job_id = jobs.create("document", doc["title"])
    threading.Thread(target=_run_fix, args=(job_id, doc["project_id"], data["atom_id"], data.get("rule", ""),
                                            data.get("message", ""), prefs, api_key), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/documents/<document_id>/dismiss", methods=["POST"])
def api_dismiss(document_id):
    data = request.get_json(silent=True) or {}
    return _store_call(lambda: (library.dismiss_finding(document_id, data.get("atom_id"), data.get("rule")), {"ok": True})[1])


# ── backlog (increment 4): epics, stories, criteria, INVEST ──────────────────
_backlog_jobs = {}        # project_id → job_id


def _backlog_payload(project_id):
    items = library.backlog(project_id)
    count = lambda kind: sum(1 for i in items if i["kind"] == kind)  # noqa: E731
    job = _backlog_jobs.get(project_id)
    lang = _lang()
    skillset = _skillset(project_id)
    srcs = [{"id": d["id"], "title": d["title"], "short": title_text_short(frd.document_skill(d, skillset), lang),
             "version": v["number"]} for d, v in frd.decompose_documents(library, project_id)]
    return {"items": items, **backlog.stale(library, project_id), "sources": srcs,
            "counts": {k: count(k) for k in ("epic", "story", "subtask", "nfr")},
            "included": sum(1 for i in items if i["included"]),
            "running": job if job and (jobs.get(job) or {}).get("status") == "processing" else None}


@app.route("/api/projects/<project_id>/backlog")
def api_backlog(project_id):
    try:
        library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify(_backlog_payload(project_id))


def _run_backlog(job_id, fn, project_id, prefs, api_key):
    try:
        result = fn(library, project_id, prefs, api_key,
                    progress=lambda pct, msg: jobs.set_progress(job_id, pct, msg), skillset=_skillset(project_id))
    except (backlog.BacklogError, SummaryError, StoreError) as e:
        jobs.fail(job_id, e)
    except Exception as e:  # unexpected: keep the message, don't crash the worker
        jobs.fail(job_id, f"The backlog step failed: {e}")
    else:
        jobs.finish(job_id, result)
    finally:
        _backlog_jobs.pop(project_id, None)


def _start_backlog_job(project_id, fn, message):
    try:
        project = library.get_project(project_id)
    except StoreError as e:
        return jsonify({"error": str(e)}), 404
    running = _backlog_jobs.get(project_id)
    if running and (jobs.get(running) or {}).get("status") == "processing":
        return jsonify({"job_id": running})
    prefs, api_key, problem = _ai_prefs(project)
    if problem:
        return problem
    job_id = jobs.create("backlog", project["name"])
    _backlog_jobs[project_id] = job_id
    jobs.set_progress(job_id, 0, message)
    threading.Thread(target=_run_backlog, args=(job_id, fn, project_id, prefs, api_key), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/projects/<project_id>/backlog/build", methods=["POST"])
def api_backlog_build(project_id):
    doc = library.document(project_id)
    if library.version(doc["id"]) is None:
        return jsonify({"error": "Build the document first: the backlog is made from its requirements."}), 400
    note = (request.get_json(silent=True) or {}).get("note")
    return _start_backlog_job(project_id, functools.partial(backlog.build, note=note), "Writing stories…")


@app.route("/api/projects/<project_id>/backlog/invest", methods=["POST"])
def api_backlog_invest(project_id):
    if not any(i["kind"] == "story" for i in library.backlog(project_id)):
        return jsonify({"error": "There are no stories to check yet."}), 400
    return _start_backlog_job(project_id, backlog.invest, "Checking stories…")


@app.route("/api/projects/<project_id>/backlog", methods=["POST"])
def api_backlog_add(project_id):
    data = request.get_json(silent=True) or {}
    item = {k: data[k] for k in ("kind", "title", "body", "goal", "acceptance") if k in data}
    item.setdefault("kind", "story")
    if not str(item.get("title") or "").strip():
        return jsonify({"error": "the title must not be empty"}), 400
    return _store_call(library.add_backlog_item, project_id, item, data.get("parent_id"), data.get("after_id"))


@app.route("/api/backlog/<item_id>", methods=["PATCH"])
def api_backlog_update(item_id):
    return _store_call(library.update_backlog_item, item_id, **(request.get_json(silent=True) or {}))


@app.route("/api/backlog/<item_id>", methods=["DELETE"])
def api_backlog_delete(item_id):
    return _store_call(lambda: {"ids": library.delete_backlog_item(item_id)})


@app.route("/api/backlog/<item_id>/restore", methods=["POST"])
def api_backlog_restore(item_id):
    return _store_call(lambda: {"ids": library.delete_backlog_item(item_id, restore=True)})


@app.route("/api/projects/<project_id>/backlog/include", methods=["POST"])
def api_backlog_include(project_id):
    data = request.get_json(silent=True) or {}
    return _store_call(lambda: {"ids": library.set_backlog_included(project_id, data.get("ids") or [],
                                                                    bool(data.get("included"))),
                                **_backlog_payload(project_id)})


@app.route("/api/backlog/<item_id>/move", methods=["POST"])
def api_backlog_move(item_id):
    """Reorder among siblings: direction up / down."""
    direction = (request.get_json(silent=True) or {}).get("direction")
    try:
        item = library.get_backlog_item(item_id)
        siblings = [i for i in library.backlog(item["project_id"]) if i["parent_id"] == item["parent_id"]]
        idx = next(n for n, i in enumerate(siblings) if i["id"] == item_id)
        j = idx - 1 if direction == "up" else idx + 1
        if 0 <= j < len(siblings):
            a, b = siblings[idx], siblings[j]
            library.update_backlog_item(a["id"], pin=False, position=b["position"])
            library.update_backlog_item(b["id"], pin=False, position=a["position"])
    except (StoreError, StopIteration) as e:
        return jsonify({"error": str(e) or "not found"}), 404
    return jsonify(_backlog_payload(item["project_id"]))


@app.route("/api/backlog/<item_id>/move-into/<story_id>", methods=["POST"])
def api_backlog_move_into(item_id, story_id):
    try:
        return jsonify(backlog.move_nfr_into(library, item_id, story_id))
    except (backlog.BacklogError, StoreError) as e:
        return jsonify({"error": str(e)}), 400


# ── Jira through the Atlassian Remote MCP (increment 4b, FR-JIRA-*, D-05/D-08) ──
jira_auth = AtlassianAuth()
_jira_jobs = {}


def _jira_session():
    return McpSession(MCP_URL, jira_auth.access_token)


def _jira_call(fn):
    """Run a Jira read; turn sign-in and MCP problems into clear JSON errors."""
    try:
        return jsonify(fn())
    except AuthRequired as e:
        return jsonify({"error": str(e), "needs_connect": True}), 401
    except (AuthError, McpError, jira.JiraError, StoreError) as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/jira/status")
def api_jira_status():
    try:
        return jsonify({"connected": jira_auth.connected()})
    except Exception as e:                                  # e.g. no credential store available
        return jsonify({"connected": False, "error": str(e)})


@app.route("/api/jira/connect", methods=["POST"])
def api_jira_connect():
    """Start the sign-in. By default it opens in a private browser window, so Atlassian asks which account
    to use instead of silently reusing the one the normal browser is logged into."""
    from core.private_browser import open_private
    redirect_uri = request.host_url.rstrip("/") + "/api/jira/callback"
    private = (request.get_json(silent=True) or {}).get("private", True)

    def start():
        url = jira_auth.start(redirect_uri)
        opened = open_private(url) if private else None
        return {"url": url, "opened_private": opened}
    return _jira_call(start)


@app.route("/api/jira/callback")
def api_jira_callback():
    """Atlassian sends the browser back here after sign-in."""
    if request.args.get("error"):
        ok, text = False, request.args.get("error_description") or request.args.get("error")
    else:
        try:
            jira_auth.finish(request.args.get("state"), request.args.get("code"))
            library.audit_event("jira", "account", "connect")
            ok, text = True, "Jira подключена. Вернитесь в Dictum — это окно можно закрыть."
        except AuthError as e:
            ok, text = False, str(e)
    colour = "#3A6A4B" if ok else "#9E3626"
    safe = text.replace("&", "&amp;").replace("<", "&lt;")
    return (f"<!doctype html><meta charset=utf-8><title>Dictum</title>"
            f"<body style='font:16px -apple-system,Segoe UI,sans-serif;display:grid;place-items:center;height:90vh;"
            f"background:#EDEFEC'><p style='max-width:520px;color:{colour}'>{safe}</p></body>")


@app.route("/api/jira/disconnect", methods=["POST"])
def api_jira_disconnect():
    jira_auth.disconnect()
    library.audit_event("jira", "account", "disconnect")
    return jsonify({"connected": False})


@app.route("/api/jira/sites")
def api_jira_sites():
    return _jira_call(lambda: {"sites": jira.sites(_jira_session())})


@app.route("/api/jira/projects")
def api_jira_projects():
    cloud_id = request.args.get("cloud_id")
    if not cloud_id:
        return jsonify({"error": "choose a Jira site"}), 400

    def load():
        found = jira.projects(_jira_session(), cloud_id, request.args.get("q"))
        for p in found:
            p["suggested_types"] = jira.suggest_types(p["issue_types"])
        return {"projects": found}
    return _jira_call(load)


@app.route("/api/projects/<project_id>/jira/target", methods=["GET"])
def api_jira_target(project_id):
    return _store_call(lambda: {"target": library.jira_target(project_id)})


@app.route("/api/projects/<project_id>/jira/target", methods=["PUT"])
def api_jira_set_target(project_id):
    d = request.get_json(silent=True) or {}
    return _store_call(lambda: {"target": library.set_jira_target(
        project_id, d.get("cloud_id"), d.get("site_url"), d.get("project_key"), d.get("project_name"), d.get("types"))})


def _run_jira(job_id, project_id, kind, item_ids):
    try:
        session = _jira_session()
        if kind == "preview":
            jobs.set_progress(job_id, 20, "Reading Jira…")
            result = jira.plan(library, project_id, session)
        else:
            result = jira.push(library, project_id, session, item_ids,
                               progress=lambda pct, msg: jobs.set_progress(job_id, pct, msg))
            library.audit_event("jira", project_id, "push", after={"done": len(result["done"]),
                                                                   "failed": len(result["failed"])})
    except AuthRequired as e:
        jobs.fail(job_id, f"{e} (Выгрузка → Подключить Jira)")
    except (AuthError, McpError, jira.JiraError, StoreError) as e:
        jobs.fail(job_id, e)
    except Exception as e:
        jobs.fail(job_id, f"Jira step failed: {e}")
    else:
        jobs.finish(job_id, result)
    finally:
        _jira_jobs.pop(project_id, None)


def _start_jira(project_id, kind, item_ids=None):
    running = _jira_jobs.get(project_id)
    if running and (jobs.get(running) or {}).get("status") == "processing":
        return jsonify({"error": "A Jira step is already running for this project."}), 409
    job_id = jobs.create("jira", kind)
    _jira_jobs[project_id] = job_id
    jobs.set_progress(job_id, 0, "Connecting to Jira…")
    threading.Thread(target=_run_jira, args=(job_id, project_id, kind, item_ids), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/projects/<project_id>/jira/preview", methods=["POST"])
def api_jira_preview(project_id):
    """Dry run: read-only calls only, nothing is written to Jira (BR-11)."""
    if not library.jira_target(project_id):
        return jsonify({"error": "Choose the Jira site and project first."}), 400
    return _start_jira(project_id, "preview")


@app.route("/api/projects/<project_id>/jira/push", methods=["POST"])
def api_jira_push(project_id):
    """Write to Jira. The request must name the target project key, so a push never lands somewhere unexpected."""
    d = request.get_json(silent=True) or {}
    target = library.jira_target(project_id)
    if not target:
        return jsonify({"error": "Choose the Jira site and project first."}), 400
    if d.get("confirm_project_key") != target["project_key"]:
        return jsonify({"error": f"Confirm the target project ({target['project_key']}) to push."}), 400
    if not d.get("item_ids"):
        return jsonify({"error": "Отметь хотя бы одну строку."}), 400
    return _start_jira(project_id, "push", d["item_ids"])


# ── skills (FR-SET-04): editable, shareable instructions per AI stage ─────────
def _contracts():
    """What the app adds to each stage's skill, shown read-only in the editor."""
    from core import atoms as atoms_mod
    return {"extract": atoms_mod.EXTRACT_CONTRACT, "dedup": atoms_mod.DEDUP_CONTRACT,
            "frd": frd.FULL_CONTRACT.replace("{extra}", "").replace("{rules}", "(from the quality skill)"),
            "quality": "The rules are applied while the FRD is written; vague words are also checked by the app.",
            "fix": frd.FIX_CONTRACT, "summary": "", "global": "", "export": "",
            "ask": ask_mod.CONTRACT + "\n\nShort mode (the question card in a live call):\n" + ask_mod.SHORT_CONTRACT}


def _skill_call(fn, *args, **kwargs):
    try:
        out = fn(*args, **kwargs)
    except skills.SkillError as e:
        return jsonify({"error": str(e)}), 404 if "not found" in str(e) else 400
    if isinstance(out, skills.Skill):
        return jsonify(_skill_payload(out))
    return jsonify(out if out is not None else {"ok": True})


def _lang():
    """The interface language a request asks for (skill titles and descriptions are in both)."""
    lang = request.args.get("lang") or (request.get_json(silent=True) or {}).get("lang") if request else None
    return lang if lang in ("ru", "en") else "ru"


def _skill_payload(skill):
    body = skill.full(_lang())
    body["contract"] = _contracts().get(skill.stage, "")
    body["history"] = [] if skill.builtin or skill.error else skills.history(skill.name)
    if skill.stage == "export":
        from core.docx_export import PLACEHOLDER_HELP
        body["placeholders"] = [{"code": c, "label": lbl} for c, lbl in PLACEHOLDER_HELP]
        body["has_template_file"] = not skill.builtin and os.path.isfile(os.path.join(skill.path, "template.docx"))
    return body


@app.route("/api/skills")
def api_skills():
    project_id = request.args.get("project_id") or library.current_project()["id"]
    overrides = library.project_skills(project_id)
    effective = skills.resolve(overrides)
    chosen = skills.global_choices()
    return jsonify({
        "stages": [{"id": st, "default": skills.DEFAULTS[st], "global": chosen.get(st) or skills.DEFAULTS[st],
                    "project": overrides.get(st), "effective": effective[st].name if effective[st] else None}
                   for st in skills.STAGES],
        "skills": [s.summary(_lang()) for s in skills.all_skills()],
        "project_id": project_id,
    })


@app.route("/api/skills/<name>")
def api_skill(name):
    return _skill_call(skills.get, name)


@app.route("/api/skills", methods=["POST"])
def api_skill_create():
    data = request.get_json(silent=True) or {}
    return _skill_call(skills.create, data.get("from") or "", title=data.get("title"))


@app.route("/api/skills/<name>", methods=["PUT"])
def api_skill_save(name):
    data = request.get_json(silent=True) or {}
    return _skill_call(skills.save, name, title=data.get("title"), description=data.get("description"),
                       instructions=data.get("instructions"), settings=data.get("meta"), lang=data.get("lang"))


@app.route("/api/skills/<name>", methods=["DELETE"])
def api_skill_delete(name):
    library.audit_event("skill", name, "delete")
    return _skill_call(skills.delete, name)


@app.route("/api/skills/<name>/undelete", methods=["POST"])
def api_skill_undelete(name):
    return _skill_call(skills.undelete, name)


@app.route("/api/skills/<name>/history/<entry>")
def api_skill_history_entry(name, entry):
    return _skill_call(lambda: {"text": skills.history_text(name, entry)})


@app.route("/api/skills/<name>/history/<entry>/restore", methods=["POST"])
def api_skill_restore(name, entry):
    return _skill_call(skills.restore, name, entry)


@app.route("/api/skills/<name>/export.zip")
def api_skill_export(name):
    try:
        data = skills.export_zip(name)
    except skills.SkillError as e:
        return jsonify({"error": str(e)}), 404
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{name}.zip", mimetype="application/zip")


@app.route("/api/skills/import", methods=["POST"])
def api_skill_import():
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "choose a .zip or SKILL.md file"}), 400
    result = _skill_call(skills.import_file, f.filename or "skill.zip", f.read(skills.MAX_IMPORT_BYTES + 1))
    return result


@app.route("/api/skills/<name>/template.docx")
def api_skill_template(name):
    try:
        skill = skills.get(name)
        if skill.stage != "export":
            raise skills.SkillError("only export skills have a Word template")
        data = skills.template_bytes(skill)
    except skills.SkillError as e:
        return jsonify({"error": str(e)}), 404
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{name}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@app.route("/api/skills/<name>/template", methods=["POST"])
def api_skill_upload_template(name):
    f = request.files.get("file")
    if f is None:
        return jsonify({"error": "choose a .docx file"}), 400
    return _skill_call(skills.set_template, name, f.read(skills.MAX_IMPORT_BYTES + 1))


@app.route("/api/skills/<name>/open", methods=["POST"])
def api_skill_open(name):
    """Open the skill's Word template in Word (or its folder), for editing on this computer."""
    what = (request.get_json(silent=True) or {}).get("what", "folder")
    try:
        skill = skills.get(name)
        if skill.builtin:
            raise skills.SkillError("built-in skills can't be changed: make a copy first")
        path = skill.path
        if what == "template":
            path = skills.template_path(name)
            skills._snapshot(skill, "docx")          # keep the version before editing in Word
    except skills.SkillError as e:
        return jsonify({"error": str(e)}), 400
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — opening the user's own file with its default app
    else:
        subprocess.Popen(["xdg-open", path])
    return jsonify({"ok": True, "path": path})


@app.route("/api/skills/active", methods=["PUT"])
def api_skill_active():
    """Choose the skill for a stage: globally, or for one project (skill null = follow the global choice)."""
    data = request.get_json(silent=True) or {}
    stage, name, project_id = data.get("stage"), data.get("skill"), data.get("project_id")
    try:
        if name:
            skill = skills.get(name)
            if skill.stage != stage or skill.error:
                raise skills.SkillError(f"'{name}' is not a working {stage} skill")
        if project_id:
            library.set_project_skill(project_id, stage, name)
        else:
            if not name:
                raise skills.SkillError("choose a skill")
            skills.set_global(stage, name)
            library.audit_event("skill", name, "use_globally", after={"stage": stage})
    except (skills.SkillError, StoreError) as e:
        return jsonify({"error": str(e)}), 400
    return api_skills()


def _draft_skill(data):
    """A skill as it is being edited (not saved yet), for "try it"."""
    base = skills.get(data["name"])
    meta = {**base.meta, **(data.get("meta") or {})}
    for key in ("title", "description"):
        if data.get(key) is not None:
            meta[key] = data[key]
    instructions = data.get("instructions", base.instructions)
    skills.validate(meta, instructions, base.path)
    return skills.Skill(base.name, str(meta["title"]), str(meta.get("description") or ""), base.stage,
                        instructions, meta, base.builtin, base.path)


def _run_try(job_id, stage, skill, project_id, source_id, prefs, api_key):
    from core import atoms as atoms_mod
    try:
        skillset = {**_skillset(project_id), stage: skill}
        report = lambda pct, msg: jobs.set_progress(job_id, pct, msg)  # noqa: E731
        if stage in ("summary", "global"):
            source = library.get_source(source_id)
            text = summarize(library.transcript_text(source_id), prefs, api_key,
                             on_delta=lambda piece: jobs.append_partial(job_id, piece), title=source["title"],
                             skillset=skillset, language_rule=language_rule(library.get_project(project_id)))
            jobs.finish(job_id, {"kind": "markdown", "text": text})
        elif stage == "extract":
            found, dropped, _, skipped = atoms_mod.extract_candidates(
                library, source_id, prefs, api_key, skillset,
                progress=lambda d, t, m: report(int(100 * d / max(t, 1)), m))
            # PM-33: show the effect, not just the output: what this draft adds or loses vs. the atoms now in place.
            norm = atoms_mod.normalize
            current = [a for a in library.list_atoms(library.get_source(source_id)["project_id"], source_id=source_id)
                       if a["status"] != "rejected"]
            have = {norm(a["statement"]) for a in current}
            got = {norm(a["statement"]) for a in found}
            compare = {"new": [a["statement"] for a in found if norm(a["statement"]) not in have],
                       "missing": [a["statement"] for a in current if norm(a["statement"]) not in got],
                       "same": len(have & got), "current": len(current)}
            jobs.finish(job_id, {"kind": "atoms", "atoms": found, "dropped": dropped, "skipped": skipped,
                                 "compare": compare})
        elif stage in ("frd", "quality"):
            out = frd.build(library, project_id, prefs, api_key, mode="full", progress=report,
                            skillset=skillset, save=False)
            jobs.finish(job_id, {"kind": "document", "content": out["content"]})
        else:
            raise skills.SkillError("this stage can't be tried here")
    except (skills.SkillError, SummaryError, frd.BuildError, StoreError) as e:
        jobs.fail(job_id, e)
    except Exception as e:
        jobs.fail(job_id, f"The try failed: {e}")


@app.route("/api/skills/try", methods=["POST"])
def api_skill_try():
    """Run a stage with a draft skill on a real source or the current project, without saving anything."""
    data = request.get_json(silent=True) or {}
    try:
        skill = _draft_skill(data)
    except (skills.SkillError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    project_id = data.get("project_id") or library.current_project()["id"]
    source_id = data.get("source_id")
    if skill.stage in ("summary", "global", "extract"):
        try:
            source = library.get_source(source_id or "")
        except StoreError:
            return jsonify({"error": "choose a source to try this skill on"}), 400
        if source["status"] != "ready":
            return jsonify({"error": "This source has no text yet."}), 400
        project_id = source["project_id"]
    prefs, api_key, problem = _ai_prefs(library.get_project(project_id))
    if problem:
        return problem
    job_id = jobs.create("skill", skill.name)
    jobs.set_progress(job_id, 0, "Trying the skill…")
    threading.Thread(target=_run_try, args=(job_id, skill.stage, skill, project_id, source_id, prefs, api_key),
                     daemon=True).start()
    return jsonify({"job_id": job_id})


if __name__ == "__main__":
    # Dev entry point; the installed app starts through launcher.py.
    import launcher
    sys.exit(launcher.main(app_module=sys.modules[__name__]))
