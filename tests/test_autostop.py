"""Auto-stop on silence (spec 5.0 C4.3): core.live.SilenceWatch and the stop path around it in app.py."""
import hashlib
import os

import numpy as np
import pytest

from core.live import SilenceWatch, has_speech
from tests.test_live import GrowingWav, recording_app, silence, speech  # noqa: F401  (fixture)
from tests.test_recorder import wait_for

RATE = 16000


def noise(seconds, level=40):
    rng = np.random.default_rng(1)
    return rng.integers(-level, level, int(seconds * RATE)).astype(np.int16)


@pytest.fixture()
def channels(tmp_path):
    mic, sys_ = GrowingWav(str(tmp_path), "mic"), GrowingWav(str(tmp_path), "sys")
    yield mic, sys_
    mic.close()
    sys_.close()


def watch(tmp_path, minutes=1, pauses=None):
    fired = []
    return SilenceWatch(str(tmp_path), minutes, fired.append, pauses=(lambda: pauses) if pauses is not None else None), fired


def test_speech_is_louder_than_the_floor_room_noise_is_not():
    assert has_speech(silence(2)) is None
    assert has_speech(noise(2)) is None
    assert has_speech(np.concatenate([silence(1), speech(0.5), noise(1)])) == (1.0, 1.5)


def test_counts_seconds_since_the_last_speech_on_either_channel(tmp_path, channels):
    mic, sys_ = channels
    w, fired = watch(tmp_path)
    mic.add(speech(2), silence(20))
    sys_.add(silence(10), speech(1), silence(11))
    assert w.check() == pytest.approx(11.0)                    # the other side spoke last, at 11 s
    mic.add(noise(30))
    sys_.add(silence(30))
    assert w.check() == pytest.approx(41.0) and fired == []
    mic.add(speech(1), silence(5))
    sys_.add(silence(6))
    assert w.check() == pytest.approx(5.0)                     # speech resets the counter


def test_fires_once_when_the_silence_is_long_enough(tmp_path, channels):
    mic, sys_ = channels
    w, fired = watch(tmp_path, minutes=1)
    mic.add(speech(1), silence(59))
    sys_.add(silence(60))
    w.check()
    assert fired == []
    mic.add(silence(2))
    w.check()
    assert fired == [1] and w.fired
    mic.add(silence(30))
    w.check()
    assert fired == [1]                                        # once


def test_paused_spans_do_not_count_as_silence(tmp_path, channels):
    mic, sys_ = channels
    pauses = [[10.0, 80.0]]                                    # the recorder writes zeros while paused
    w, fired = watch(tmp_path, minutes=1, pauses=pauses)
    mic.add(speech(10), silence(75))
    w.check()
    assert w.silent == pytest.approx(5.0) and fired == []      # 70 s of the 75 were paused
    pauses.append([85.0, None])                                # paused again, still paused
    mic.add(silence(120))
    w.check()
    assert w.silent == pytest.approx(5.0) and fired == []
    pauses[-1][1] = 205.0
    mic.add(silence(55))
    w.check()
    assert fired == [1]


def test_zero_minutes_never_fires(tmp_path, channels):
    mic, _ = channels
    w, fired = watch(tmp_path, minutes=0)
    mic.add(silence(120))
    assert w.check() == pytest.approx(120.0) and fired == []


def test_the_watch_never_changes_the_audio_files(tmp_path, channels):
    mic, sys_ = channels
    mic.add(speech(1), silence(3))
    sys_.add(silence(4))
    paths = [os.path.join(str(tmp_path), f"{c}.wav") for c in ("mic", "sys")]
    before = [(os.path.getsize(p), hashlib.sha256(open(p, "rb").read()).hexdigest()) for p in paths]
    w, _ = watch(tmp_path)
    w.check()
    w.check()
    assert [(os.path.getsize(p), hashlib.sha256(open(p, "rb").read()).hexdigest()) for p in paths] == before


def test_the_thread_checks_on_its_own(tmp_path, channels):
    mic, _ = channels
    fired = []
    w = SilenceWatch(str(tmp_path), 1, fired.append, tick=0.02).start()
    try:
        mic.add(silence(61))
        assert wait_for(lambda: fired == [1])
    finally:
        w.stop()


# ── app: the stop path and the notification ──────────────────────────────────

@pytest.fixture()
def autostop_app(recording_app, monkeypatch):  # noqa: F811
    a = recording_app
    for key, value in (("atoms", None), ("silence", None), ("opts", None), ("lang", "ru"), ("stopped", None)):
        monkeypatch.setitem(a._session, key, value)
    shown, finishes = [], []
    monkeypatch.setattr(a, "notify", lambda title, text: shown.append((title, text)) or True)
    real = a._finish_recording

    def spy(*args, **kw):
        finishes.append((args, kw))
        return real(*args, **kw)
    monkeypatch.setattr(a, "_finish_recording", spy)
    monkeypatch.setattr(a, "_start_transcription", lambda source, path, opts: "job-1")
    a.shown, a.finishes = shown, finishes
    return a


def _wait_audio(client):
    assert wait_for(lambda: all(c["frames"] >= 2048 for c in client.get("/desktop-record/status").get_json()["channels"].values()))


def test_auto_stop_uses_the_stop_path_once_and_notifies_once(client, autostop_app):
    a = autostop_app
    sid = client.post("/desktop-record/start", json={"model": "v3_e2e_rnnt", "device": "cpu"}).get_json()["source_id"]
    assert isinstance(a._session["silence"], SilenceWatch) and a._session["silence"].minutes == 10
    _wait_audio(client)
    a._session["silence"]._on_silence(10)                      # what the watch calls after 10 silent minutes
    a._auto_stop(sid, 10)                                      # a second call finds nothing to stop
    assert len(a.finishes) == 1 and a.finishes[0][1] == {"expect_source": sid}
    assert a.shown == [("Dictum", "Запись остановлена: тишина 10 минут")]
    src = a.library.get_source(sid)
    assert src["status"] == "processing" and src["audio_file"] == "mixed.wav"     # transcription started
    folder = a.library.source_dir(src)
    assert {"mic.wav", "sys.wav", "mixed.wav"} <= set(os.listdir(folder))
    st = client.get("/desktop-record/status").get_json()
    assert st["recording"] is False and st["stopped"] == {"reason": "silence", "source_id": sid, "job_id": "job-1", "minutes": 10}
    live = client.get(f"/api/sources/{sid}/live").get_json()
    assert live["recording"] is False and live["stopped"] == {"reason": "silence", "minutes": 10, "job_id": "job-1"}


def test_the_notification_follows_the_ui_language(client, autostop_app):
    a = autostop_app
    sid = client.post("/desktop-record/start", json={"lang": "en"}).get_json()["source_id"]
    _wait_audio(client)
    a._auto_stop(sid, 3)
    assert a.shown == [("Dictum", "Recording stopped after 3 minutes of silence")]
    sid = client.post("/desktop-record/start", json={"lang": "ru"}).get_json()["source_id"]
    assert client.get("/desktop-record/status").get_json()["stopped"] is None       # a new recording clears it
    _wait_audio(client)
    a._auto_stop(sid, 2)
    assert a.shown[-1] == ("Dictum", "Запись остановлена: тишина 2 минуты")


def test_the_live_route_reports_the_silence_countdown(client, autostop_app):
    a = autostop_app
    sid = client.post("/desktop-record/start", json={}).get_json()["source_id"]
    a._session["silence"].silent = 125.4
    body = client.get(f"/api/sources/{sid}/live").get_json()
    assert body["silence"] == 125 and body["silence_stop"] == 600 and body["stopped"] is None


def test_zero_minutes_disables_the_watch(client, autostop_app, monkeypatch):
    a = autostop_app
    monkeypatch.setattr(a.settings, "load_settings", lambda: {"silence_stop_minutes": 0})
    sid = client.post("/desktop-record/start", json={}).get_json()["source_id"]
    assert a._session["silence"] is None
    assert client.get(f"/api/sources/{sid}/live").get_json()["silence_stop"] == 0


def test_settings_round_trip(client, app_module):
    body = client.post("/settings", json={"silence_stop_minutes": 0}).get_json()
    assert body["silence_stop_minutes"] == 0
    got = client.get("/settings").get_json()
    assert got["silence_stop_minutes"] == 0
    assert client.post("/settings", json={"silence_stop_minutes": -1}).status_code == 400
    assert client.post("/settings", json={"silence_stop_minutes": "soon"}).status_code == 400
    client.post("/settings", json={"silence_stop_minutes": 10})
