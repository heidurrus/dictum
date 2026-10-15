"""Live transcript while recording (spec 5.0 C4.1): core/live.py and the routes around it."""
import hashlib
import os
import threading
import time

import numpy as np
import pytest

from core.live import LiveTranscriber, WAV_HEADER_BYTES
from core.recorder import DualChannelRecorder, StreamingWavWriter, last_silence, speech_bounds_samples
from core.store import Store
from tests.test_recorder import read_wav, tone_source, wait_for

RATE = 16000


def speech(seconds, value=3000):
    return np.full(int(seconds * RATE), value, dtype=np.int16)


def silence(seconds):
    return np.zeros(int(seconds * RATE), dtype=np.int16)


class GrowingWav:
    """A fake recorder: appends to <dir>/<channel>.wav the way core.recorder does, and flushes."""

    def __init__(self, folder, channel):
        self.w = StreamingWavWriter(os.path.join(folder, f"{channel}.wav"))

    def add(self, *parts):
        for p in parts:
            self.w.write(p)
        self.w._file.flush()

    def close(self):
        self.w.close()


class FakeAsr:
    def __init__(self, clock=None, delay=0.0, fail=False):
        self.calls = []
        self.clock, self.delay, self.fail = clock, delay, fail

    def transcribe(self, chunks):
        if self.fail:
            raise RuntimeError("model exploded")
        self.calls.append([len(c) for c in chunks])
        if self.clock:
            self.clock.now += self.delay
        return [f"line {len(self.calls)}.{i}" for i in range(len(chunks))]


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Sink:
    """Stands in for the store: collects appended segments."""

    def __init__(self):
        self.segments = []

    def append_provisional_segments(self, source_id, segments):
        out = [{**s, "idx": len(self.segments) + i, "provisional": True} for i, s in enumerate(segments)]
        self.segments += out
        return out


def data_bytes(folder, channel):
    return os.path.getsize(os.path.join(folder, f"{channel}.wav")) - WAV_HEADER_BYTES


def test_samples_variant_matches_file_variant_and_finds_the_last_pause():
    audio = np.concatenate([silence(0.2), speech(1.0), silence(0.5), speech(0.4)])
    assert speech_bounds_samples(audio, RATE) == (0.2, 2.1)
    assert speech_bounds_samples(silence(1.0), RATE) is None
    cut = last_silence(audio, RATE)
    assert 1.2 * RATE <= cut <= 1.7 * RATE               # inside the 1.2–1.7 s pause
    assert last_silence(speech(2.0), RATE) is None


def test_reads_appended_bytes_across_three_passes_without_rereading(tmp_path):
    mic = GrowingWav(str(tmp_path), "mic")
    asr, sink = FakeAsr(), Sink()
    lt = LiveTranscriber("s1", str(tmp_path), asr, store=sink)
    for n in range(3):
        mic.add(speech(1.0), silence(0.5))
        lt.run_pass()
        assert lt.bytes_read["mic"] == data_bytes(str(tmp_path), "mic"), f"pass {n}"
        assert lt.offsets["mic"] == WAV_HEADER_BYTES + data_bytes(str(tmp_path), "mic")
    assert asr.calls == [[int(1.5 * RATE)]] * 3            # each pass transcribes only its own new audio
    assert [(s["start"], s["end"]) for s in sink.segments] == [(0.0, 1.0), (1.5, 2.5), (3.0, 4.0)]
    mic.close()


def test_cuts_at_the_last_silence_and_keeps_the_rest_for_the_next_pass(tmp_path):
    mic = GrowingWav(str(tmp_path), "mic")
    asr, sink = FakeAsr(), Sink()
    lt = LiveTranscriber("s1", str(tmp_path), asr, store=sink)
    mic.add(speech(1.0), silence(0.5), speech(0.6))       # the second phrase is still being spoken
    lt.run_pass()
    assert len(sink.segments) == 1 and (sink.segments[0]["start"], sink.segments[0]["end"]) == (0.0, 1.0)
    mic.add(speech(0.4), silence(0.5))                    # …and ends now
    lt.run_pass()
    assert lt.bytes_read["mic"] == data_bytes(str(tmp_path), "mic")     # nothing read twice
    second = sink.segments[1]
    assert (second["start"], second["end"]) == (1.5, 2.5)
    # the whole second phrase in one piece (from the middle of the pause), not cut mid-word
    assert len(asr.calls[1]) == 1 and 1.7 * RATE <= asr.calls[1][0] <= 1.8 * RATE
    mic.close()


def test_segments_carry_channel_labels_and_absolute_timestamps(tmp_path):
    mic, sys_ = GrowingWav(str(tmp_path), "mic"), GrowingWav(str(tmp_path), "sys")
    sink = Sink()
    lt = LiveTranscriber("s1", str(tmp_path), FakeAsr(), store=sink, labels={"mic": "BA", "sys": "OTHER"})
    mic.add(silence(2.0))
    sys_.add(silence(2.0))
    lt.run_pass()
    assert sink.segments == []                            # silence: nothing to say
    mic.add(speech(1.0), silence(1.0))
    sys_.add(silence(1.2), speech(0.5), silence(0.3))
    lt.run_pass()
    got = [(s["speaker"], s["start"], s["end"]) for s in sink.segments]
    assert got == [("BA", 2.0, 3.0), ("OTHER", 3.2, 3.7)]
    assert all(s["provisional"] for s in sink.segments)
    mic.close(); sys_.close()


def test_provisional_segments_land_in_the_store_and_the_final_save_replaces_them(tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    pid = store.ensure_default_project()["id"]
    src = store.create_source(pid, "recording", "Встреча", status="recording")
    folder = store.source_dir(src)
    mic = GrowingWav(folder, "mic")
    lt = LiveTranscriber(src["id"], folder, FakeAsr(), store=store)
    mic.add(speech(1.0), silence(0.5))
    lt.run_pass()
    mic.add(speech(1.0), silence(0.5))
    lt.run_pass()
    segs, _ = store.transcript(src["id"])
    assert [(s["idx"], s["speaker"], s["start"], s["provisional"]) for s in segs] == [(0, "BA", 0.0, True), (1, "BA", 1.5, True)]
    assert store.delete_provisional_segments(src["id"]) == 2
    store.save_transcript(src["id"], {"text": "x", "segments": [{"speaker": "BA", "start": 0.0, "end": 1.0, "text": "x"}]})
    segs, _ = store.transcript(src["id"])
    assert [(s["text"], s["provisional"]) for s in segs] == [("x", False)]
    mic.close()


def test_windows_entirely_inside_a_pause_are_skipped(tmp_path):
    mic = GrowingWav(str(tmp_path), "mic")
    pauses = [[0.0, None]]
    asr, sink = FakeAsr(), Sink()
    lt = LiveTranscriber("s1", str(tmp_path), asr, store=sink, pauses=lambda: pauses)
    mic.add(speech(2.0))                     # loud, but written while "paused": the window is skipped
    lt.run_pass()
    assert asr.calls == [] and lt.bytes_read["mic"] == data_bytes(str(tmp_path), "mic")
    pauses[0][1] = 2.0                       # resumed at 2 s
    mic.add(speech(1.0), silence(0.5))
    lt.run_pass()
    assert [(s["start"], s["end"]) for s in sink.segments] == [(2.0, 3.0)]
    mic.close()


def test_backpressure_doubles_the_window_then_turns_live_off(tmp_path):
    mic = GrowingWav(str(tmp_path), "mic")
    clock = FakeClock()
    asr = FakeAsr(clock=clock)
    lt = LiveTranscriber("s1", str(tmp_path), asr, store=Sink(), window=15, clock=clock)

    def slow_pass(delay):
        asr.delay = delay
        mic.add(speech(0.5), silence(0.5))
        lt.run_pass()

    slow_pass(20)
    assert lt.window == 15 and lt.state == "on"          # one slow pass is tolerated
    slow_pass(20)
    assert lt.window == 30 and lt.state == "catching_up"
    slow_pass(5)                                          # a fast pass resets the count
    slow_pass(40)
    assert lt.window == 30
    slow_pass(40)
    assert lt.window == 60
    slow_pass(70)
    assert lt.state == "off" and "slow" in lt.reason
    calls = len(asr.calls)
    slow_pass(1)
    assert len(asr.calls) == calls                        # off means off
    mic.close()


def test_an_exception_turns_live_off_and_the_recorder_is_unaffected(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": tone_source(3000), "sys": tone_source(2000)})
    rec.start()
    lt = LiveTranscriber("s1", rec.folder, FakeAsr(fail=True), store=Sink(), window=0.05).start()
    assert wait_for(lambda: lt.state == "off")
    assert "model exploded" in lt.reason
    frames = rec.status()["channels"]["mic"]["frames"]
    assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] > frames)   # still recording
    assert rec.recording
    result = rec.stop()
    lt.stop()
    assert set(read_wav(result["mic"])) == {3000} and set(read_wav(result["sys"])) == {2000}


def test_a_factory_that_cannot_load_the_model_turns_live_off(tmp_path):
    def no_model():
        raise OSError("weights missing")
    lt = LiveTranscriber("s1", str(tmp_path), no_model, store=Sink(), window=0.01).start()
    assert wait_for(lambda: lt.state == "off") and "weights missing" in lt.reason


def test_nothing_is_appended_after_stop(tmp_path):
    mic = GrowingWav(str(tmp_path), "mic")
    sink = Sink()
    lt = LiveTranscriber("s1", str(tmp_path), FakeAsr(), store=sink)
    lt.stop()
    mic.add(speech(1.0), silence(0.5))
    lt.run_pass()
    assert sink.segments == []
    mic.close()


def test_the_reader_never_changes_the_audio_files(tmp_path):
    mic = GrowingWav(str(tmp_path), "mic")
    mic.add(speech(1.0), silence(0.5))
    mic.close()
    path = os.path.join(str(tmp_path), "mic.wav")
    before = (hashlib.sha256(open(path, "rb").read()).hexdigest(), os.stat(path).st_mtime_ns)
    LiveTranscriber("s1", str(tmp_path), FakeAsr(), store=Sink()).run_pass()
    assert (hashlib.sha256(open(path, "rb").read()).hexdigest(), os.stat(path).st_mtime_ns) == before


def test_recorder_writes_silence_while_paused_and_reports_the_spans(tmp_path):
    rec = DualChannelRecorder(str(tmp_path), {"mic": tone_source(500), "sys": "not here"})
    rec.start()
    assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] > 2048)
    rec.pause()
    st = rec.status()
    assert st["paused"] and st["pauses"][0][1] is None
    at = st["channels"]["mic"]["frames"]
    assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] > at + 4096)
    rec.resume()
    end = rec.status()["channels"]["mic"]["frames"]
    assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] > end + 2048)
    st = rec.status()
    assert not st["paused"] and st["pauses"][0][1] is not None
    path = rec.stop()["mic"]
    audio = read_wav(path)
    assert 0 in set(audio[at + 1024:end - 1024]) and set(audio[at + 1024:end - 1024]) == {0}
    assert set(audio[:1024]) == {500} and set(audio[-1024:]) == {500}


def test_boot_recovery_offers_an_interrupted_recording_for_transcription(tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    pid = store.ensure_default_project()["id"]
    src = store.create_source(pid, "recording", "Встреча", status="recording")
    empty = store.create_source(pid, "recording", "Пусто", status="recording")
    mic = GrowingWav(store.source_dir(src), "mic")
    mic.add(speech(1.0))                     # the app died here: the writer was never closed
    path = os.path.join(store.source_dir(src), "mic.wav")
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert Store(root=str(tmp_path / "lib"), user="ba").recover_interrupted_recordings() == 2
    got = store.get_source(src["id"])
    assert got["status"] == "recorded" and got["audio_file"] == "mic.wav"
    assert store.get_source(empty["id"])["status"] == "failed"
    assert hashlib.sha256(open(path, "rb").read()).hexdigest() == digest   # untouched
    mic.close()


# ── routes ────────────────────────────────────────────────────────────────────

@pytest.fixture()
def recording_app(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "microphone_access", lambda: (True, None))
    monkeypatch.setattr(app_module, "_mic_source", lambda idx: tone_source(1000))
    monkeypatch.setattr(app_module, "_system_source", lambda: tone_source(2000))
    monkeypatch.setattr(app_module, "_recorder", None)
    monkeypatch.setitem(app_module._session, "source_id", None)
    monkeypatch.setitem(app_module._session, "live", None)
    yield app_module
    with app_module._recorder_lock:
        rec = app_module._recorder
    if rec is not None and rec.recording:
        rec.stop()


def _count_sources(app_module):
    return len(app_module.library.list_sources(app_module.library.current_project()["id"]))


def test_start_creates_the_meeting_and_records_into_its_folder(client, recording_app):
    a = recording_app
    before = _count_sources(a)
    body = client.post("/desktop-record/start", json={"title": "Встреча 15.10.2026, 10:00"}).get_json()
    src = a.library.get_source(body["source_id"])
    assert src["status"] == "recording" and src["kind"] == "recording" and src["title"] == "Встреча 15.10.2026, 10:00"
    assert _count_sources(a) == before + 1
    assert body["live"] == "off"             # no model named: no live pass
    assert wait_for(lambda: os.path.exists(os.path.join(a.library.source_dir(src), "mic.wav")))
    st = client.get("/desktop-record/status").get_json()
    assert st["source_id"] == src["id"] and st["paused"] is False and st["pauses"] == [] and st["live"] == "off"


def test_stop_finalises_the_same_source(client, recording_app):
    a = recording_app
    sid = client.post("/desktop-record/start", json={}).get_json()["source_id"]
    assert wait_for(lambda: all(c["frames"] >= 2048 for c in client.get("/desktop-record/status").get_json()["channels"].values()))
    before = _count_sources(a)
    res = client.post("/desktop-record/stop")
    assert res.status_code == 200 and res.headers["X-Source-Id"] == sid
    assert _count_sources(a) == before                    # no new source
    src = a.library.get_source(sid)
    assert src["status"] == "recorded" and src["audio_file"] == "mixed.wav"
    folder = a.library.source_dir(src)
    assert {"mic.wav", "sys.wav", "mixed.wav"} <= set(os.listdir(folder))


def test_pause_and_resume_routes(client, recording_app):
    assert client.post("/desktop-record/pause").status_code == 409
    client.post("/desktop-record/start", json={})
    body = client.post("/desktop-record/pause").get_json()
    assert body["paused"] is True and body["pauses"][0][1] is None
    assert client.get("/desktop-record/status").get_json()["paused"] is True
    body = client.post("/desktop-record/resume").get_json()
    assert body["paused"] is False and body["pauses"][0][1] is not None


def test_live_route_returns_new_segments_and_the_recording_state(client, recording_app):
    a = recording_app
    sid = client.post("/desktop-record/start", json={}).get_json()["source_id"]
    a.library.append_provisional_segments(sid, [{"speaker": "BA", "start": 0.0, "end": 1.0, "text": "раз"},
                                                {"speaker": "OTHER", "start": 1.2, "end": 2.0, "text": "два"}])
    body = client.get(f"/api/sources/{sid}/live?after=-1").get_json()
    assert [s["text"] for s in body["segments"]] == ["раз", "два"] and all(s["provisional"] for s in body["segments"])
    assert body["recording"] is True and body["paused"] is False and body["live"] == "off" and body["listening"] is False
    assert [s["text"] for s in client.get(f"/api/sources/{sid}/live?after=0").get_json()["segments"]] == ["два"]
    client.post("/desktop-record/pause")
    assert client.get(f"/api/sources/{sid}/live").get_json()["paused"] is True
    client.post("/desktop-record/stop")
    assert client.get(f"/api/sources/{sid}/live").get_json()["recording"] is False
    assert client.get("/api/sources/nope/live").status_code == 404


def test_live_mode_starts_when_a_model_is_installed_and_reports_its_state(client, recording_app, monkeypatch):
    a = recording_app
    monkeypatch.setattr(a, "_asr_installed", lambda name: True)
    monkeypatch.setattr(a.live_mod, "SpeechAsr", lambda load, name, device: FakeAsr())
    body = client.post("/desktop-record/start", json={"model": "v3_e2e_rnnt", "device": "cpu"}).get_json()
    assert body["live"] == "on"
    sid = body["source_id"]
    live = client.get(f"/api/sources/{sid}/live").get_json()
    assert live["live"] == "on" and live["listening"] is True
    a._session["live"].turn_off("test")
    assert client.get(f"/api/sources/{sid}/live").get_json()["live"] == "off"
    assert client.get("/desktop-record/status").get_json()["live"] == "off"


def test_live_mode_is_off_without_an_installed_model_or_when_the_setting_is_off(client, recording_app, monkeypatch):
    a = recording_app
    monkeypatch.setattr(a, "_asr_installed", lambda name: False)
    assert client.post("/desktop-record/start", json={"model": "v3_e2e_rnnt"}).get_json()["live"] == "off"
    client.post("/desktop-record/stop")
    monkeypatch.setattr(a, "_asr_installed", lambda name: True)
    monkeypatch.setattr(a.settings, "load_settings", lambda: {"live_transcription": False})
    assert client.post("/desktop-record/start", json={"model": "v3_e2e_rnnt"}).get_json()["live"] == "off"


def test_stop_deletes_provisional_segments_before_the_final_job(client, recording_app, monkeypatch):
    a = recording_app
    sid = client.post("/desktop-record/start", json={}).get_json()["source_id"]
    a.library.append_provisional_segments(sid, [{"speaker": "BA", "start": 0.0, "end": 1.0, "text": "черновик"}])
    assert wait_for(lambda: client.get("/desktop-record/status").get_json()["channels"]["mic"]["frames"] >= 2048)
    seen = {}

    def fake_start(source, audio_path, opts):
        seen["segments"] = a.library.transcript(source["id"])[0]
        seen["status"] = a.library.get_source(source["id"])["status"]
        seen["audio"] = os.path.basename(audio_path)
        return "job-1"
    monkeypatch.setattr(a, "_start_transcription", fake_start)
    res = client.post("/desktop-record/stop", json={"model": "v3_e2e_rnnt", "device": "cpu"})
    assert res.status_code == 200 and res.headers["X-Job-Id"] == "job-1" and res.headers["X-Source-Id"] == sid
    assert seen == {"segments": [], "status": "processing", "audio": "mixed.wav"}
