"""Шепнуть (5.0 C7): relative dates in both languages, the parse (two items, project by name and by label), capture
through the meeting recorder (one channel, auto-stop after speech then silence), the one-recorder 409 rules, the
reminder scheduler, "Сделать вопросом", and the inbox staying out of every project."""
import datetime as dt
import os
import threading
import time

import numpy as np
import pytest

from core import whisper as wm
from core.store import Store
from tests.test_recorder import tone_source, wait_for

TZ = dt.timezone(dt.timedelta(hours=5))
NOW = dt.datetime(2026, 10, 15, 9, 30, tzinfo=TZ)          # a Thursday


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=TZ)


# ── dates ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("Напомни завтра в десять позвонить Ирине", at(16, 10)),
    ("отправить Олегу регламент до вечера", at(15, 18)),
    ("в понедельник созвон с дилером", at(19, 9)),
    ("через час проверить почту", at(15, 10, 30)),
    ("купить переходник USB-C", None),
    ("Remind me tomorrow at ten to call Irina", at(16, 10)),
    ("send Oleg the policy by tonight", at(15, 18)),
    ("on Monday call the dealer", at(19, 9)),
    ("in an hour check the mail", at(15, 10, 30)),
    ("buy a USB-C adapter", None),
])
def test_whisper_parse_dates(text, expected):
    assert wm.resolve_due(text, NOW) == expected


def test_dates_details():
    assert wm.resolve_due("в 3 часа дня", NOW) == at(15, 15)
    assert wm.resolve_due("at 4pm", NOW) == at(15, 16)
    assert wm.resolve_due("в 9", NOW) == at(16, 9)                 # a time already past today: tomorrow
    assert wm.resolve_due("в среду утром", NOW) == at(21, 9)
    assert wm.resolve_due("в четверг", NOW) == at(22, 9)           # today is Thursday: the next one
    assert wm.resolve_due("через 15 минут", NOW) == at(15, 9, 45)
    assert wm.resolve_due("среди прочего", NOW) is None
    assert wm.parse_iso("2026-10-16T10:00", NOW) == at(16, 10)
    assert wm.parse_iso("not a date", NOW) is None


# ── parse ────────────────────────────────────────────────────────────────────
PROJECTS = [{"id": "p1", "name": "Портал дилера"}, {"id": "p2", "name": "Заявки"}]
SAID = "Напомни завтра в десять позвонить Ирине насчёт истории, и ещё надо отправить Олегу регламент до вечера"


def fake_complete(calls):
    def complete(system, user, schema):
        calls.append((system, user, schema))
        return {"items": [
            {"kind": "remind", "title": "Позвонить Ирине насчёт истории", "text": "завтра в десять позвонить Ирине",
             "due": "2026-10-16T11:00", "project_hint": "Ирина"},
            {"kind": "task", "title": "Отправить Олегу регламент", "text": "отправить Олегу регламент до вечера",
             "due": None, "project_hint": None}]}
    return complete


def test_whisper_two_items():
    calls = []
    items = wm.parse(SAID, fake_complete(calls), NOW, "ru", PROJECTS, current_id="p1", labels=["Ирина"])
    assert [i["kind"] for i in items] == ["remind", "task"]
    assert items[0]["due_at"] == at(16, 10).timestamp()           # the rules win over the model's 11:00
    assert items[0]["due"] == "2026-10-16T10:00+05:00"
    assert items[1]["due_at"] == at(15, 18).timestamp()
    assert items[0]["project_id"] == "p1" and items[0]["project_words"] == ["Ирина"]   # a label of the current project
    assert items[1]["project_id"] is None
    system, user, schema = calls[0]
    assert "2026-10-15T09:30" in user and "Thursday" in user and "UTC+05:00" in user
    assert "Портал дилера" in user and "Russian" in user
    assert "завтра в десять" in system and '"items"' in system      # the fixed contract is in the prompt
    assert schema["properties"]["items"]["items"]["required"] == ["kind", "title", "text", "due", "project_hint"]


def test_project_by_name_and_by_label():
    by_name = wm.match_project("отправить регламент по заявкам", PROJECTS, "p1", ["Ирина"])
    assert by_name["project_id"] == "p2" and by_name["words"] == ["заявкам"]
    by_label = wm.match_project("позвонить Ирине", PROJECTS, "p1", ["Ирина"])
    assert by_label["project_id"] == "p1" and by_label["words"] == ["Ирине"]
    assert wm.match_project("позвонить Ирине", PROJECTS, "p2", []) is None
    assert wm.match_project("call about the dealer portal", [{"id": "e", "name": "Dealer portal"}])["project_id"] == "e"


def test_fallback_is_one_note():
    items = wm.fallback_items("просто мысль про SLA", NOW, PROJECTS)
    assert len(items) == 1 and items[0]["kind"] == "note" and items[0]["text"] == "просто мысль про SLA"


def test_whisper_skill_is_editable_and_used():
    from core import skills
    assert skills.resolve()["whisper"].name == "whisper"
    assert "voice note" in wm.system_prompt()


# ── capture ──────────────────────────────────────────────────────────────────
def spoken(speech_seconds, rate=16000, chunk=1600):
    """Speech for `speech_seconds` of audio, then silence, faster than real time."""
    def source(stop):
        n = 0
        while not stop.is_set():
            loud = n * chunk < speech_seconds * rate
            yield np.full(chunk, 3000 if loud else 0, dtype=np.int16)
            n += 1
            time.sleep(0.01)
    return source


def test_capture_stops_after_silence_once_speech_was_heard(tmp_path):
    cap = wm.Capture(spoken(0.5), root=str(tmp_path), silence_seconds=0.5, tick=0.05).start()
    assert wait_for(lambda: not cap.recording, timeout=5)
    assert cap.stopped_by == "silence"
    assert os.path.exists(os.path.join(cap.folder, "mic.wav")) and not os.path.exists(os.path.join(cap.folder, "sys.wav"))
    assert wait_for(lambda: cap.result is not None)
    assert cap.audio_file == f"{cap.id}/mic.wav" and cap.duration() >= 0.9


def test_capture_waits_for_the_first_word(tmp_path):
    cap = wm.Capture(spoken(0), root=str(tmp_path), silence_seconds=0.2, tick=0.05).start()
    time.sleep(0.6)
    assert cap.recording                                  # silence alone never stops it
    cap.stop()
    assert cap.stopped_by == "button" and cap.stop() is cap.result      # idempotent


def test_capture_stops_at_the_limit(tmp_path):
    cap = wm.Capture(tone_source(3000), root=str(tmp_path), max_seconds=0.3).start()
    assert wait_for(lambda: not cap.recording, timeout=3)
    assert cap.stopped_by == "limit"


def test_capture_live_words_use_a_two_second_window(tmp_path):
    class Asr:
        def transcribe(self, chunks):
            return ["слово"] * len(chunks)
    cap = wm.Capture(spoken(30), live_asr=Asr(), root=str(tmp_path))
    cap.start()
    mic = os.path.join(cap.folder, "mic.wav")
    try:
        assert cap.live.window == 2
        assert wait_for(lambda: os.path.exists(mic) and os.path.getsize(mic) > 44 + 16000)
        cap.live.run_pass()
        assert "слово" in cap.status()["text"]
    finally:
        cap.stop()
    assert "слово" in cap.status()["text"]               # the words stay readable after the stop


# ── routes ───────────────────────────────────────────────────────────────────
@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    monkeypatch.setattr(app_module, "schedule_index", lambda project_id, force_material=None: None)
    store.ensure_default_project()
    return store


@pytest.fixture()
def rec(app_module, lib, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "microphone_access", lambda: (True, None))
    monkeypatch.setattr(app_module, "_mic_source", lambda idx: tone_source(1000))
    monkeypatch.setattr(app_module, "_system_source", lambda: tone_source(2000))
    monkeypatch.setattr(app_module, "_recorder", None)
    monkeypatch.setitem(app_module._session, "source_id", None)
    monkeypatch.setitem(app_module._session, "live", None)
    monkeypatch.setitem(app_module._whisper, "capture", None)
    monkeypatch.setattr(app_module, "_new_whisper_capture",
                        lambda mic, opts: wm.Capture(mic, root=str(tmp_path / "whispers")))
    yield app_module
    if app_module._recorder is not None and app_module._recorder.recording:
        app_module._recorder.stop()
    cap = app_module._whisper.get("capture")
    if cap is not None and cap.recording:
        cap.stop()


def test_whisper_refused_while_a_meeting_records_and_vice_versa(client, rec):
    assert client.post("/desktop-record/start", json={}).status_code == 200
    r = client.post("/api/whispers/record/start", json={})
    assert r.status_code == 409 and r.get_json()["busy"] == "meeting"
    rec._recorder.stop()
    r = client.post("/api/whispers/record/start", json={})
    assert r.status_code == 200
    r = client.post("/desktop-record/start", json={})
    assert r.status_code == 409 and r.get_json()["busy"] == "whisper"
    assert client.post("/api/whispers/record/start", json={}).status_code == 409    # one whisper at a time


def test_whisper_needs_the_microphone(client, rec, monkeypatch):
    monkeypatch.setattr(rec, "microphone_access", lambda: (False, "microphone access denied"))
    r = client.post("/api/whispers/record/start", json={})
    assert r.status_code == 403 and r.get_json()["permission"] == "microphone"


def test_stop_returns_the_parse_without_saving(client, rec, lib, monkeypatch):
    lib.create_project("Заявки")
    monkeypatch.setattr(rec, "_whisper_final_text", lambda path, opts: SAID)
    monkeypatch.setattr(rec, "_ai_prefs", lambda project: ({"llm_provider": "claude"}, "k", None))
    monkeypatch.setattr(rec, "_whisper_complete", lambda prefs, key: fake_complete([]))
    assert client.post("/api/whispers/record/start", json={}).status_code == 200
    live = client.get("/api/whispers/live").get_json()
    assert live["recording"] is True and live["text"] == ""
    body = client.post("/api/whispers/record/stop").get_json()
    assert body["transcript"] == SAID and len(body["items"]) == 2 and body["audio_file"].endswith("/mic.wav")
    assert body["items"][0]["kind"] == "remind"
    assert lib.list_whispers() == []                                   # nothing saved yet
    assert client.post("/api/whispers/record/stop").get_json() == body  # the same answer again
    assert os.path.exists(os.path.join(str(rec._whisper["capture"].root), body["audio_file"]))


def test_stop_without_a_provider_keeps_the_words_as_a_note(client, rec, lib, monkeypatch):
    monkeypatch.setattr(rec, "_whisper_final_text", lambda path, opts: "просто мысль")
    monkeypatch.setattr(rec.settings, "secret", lambda name: None)
    monkeypatch.setattr(rec.settings, "load_settings", lambda: {**rec.settings.DEFAULTS, "llm_provider": "claude"})
    client.post("/api/whispers/record/start", json={})
    body = client.post("/api/whispers/record/stop").get_json()
    assert body["needs_setup"] is True and body["error"]
    assert [(i["kind"], i["text"]) for i in body["items"]] == [("note", "просто мысль")]


def save(client, items, transcript=SAID, audio="20261015-093000-abcdef/mic.wav"):
    r = client.post("/api/whispers", json={"items": items, "transcript": transcript, "audio_file": audio})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["items"]


def test_listing_filters_search_and_soft_delete(client, lib):
    rows = save(client, [{"kind": "remind", "title": "Позвонить Ирине", "text": "позвонить Ирине",
                          "due": "2026-10-16T10:00"},
                         {"kind": "task", "title": "Отправить регламент", "text": "отправить регламент"}])
    save(client, [{"kind": "idea", "title": "Шаблон для воркшопов", "text": "шаблон"}], transcript="идея: шаблон")
    assert all(r["transcript"] == SAID and r["audio_file"].endswith("mic.wav") for r in rows)
    get = lambda q: client.get("/api/whispers" + q).get_json()      # noqa: E731
    assert len(get("")["items"]) == 3 and get("")["open"] == 2
    assert [w["kind"] for w in get("?filter=remind")["items"]] == ["remind"]
    assert len(get("?filter=open")["items"]) == 2 and len(get("?filter=idea")["items"]) == 1
    assert [w["title"] for w in get("?q=ВОРКШОП")["items"]] == ["Шаблон для воркшопов"]
    assert len(get("?q=ирине")["items"]) == 2                      # the transcript is searched too: both items
    assert client.get("/api/whispers?filter=bogus").status_code == 400
    task = next(r for r in rows if r["kind"] == "task")
    done = client.patch(f"/api/whispers/{task['id']}", json={"done": True}).get_json()
    assert done["done"] is True and done["open"] == 1
    assert len(get("?filter=open")["items"]) == 1
    assert client.delete(f"/api/whispers/{task['id']}").status_code == 200
    assert task["id"] not in [w["id"] for w in get("")["items"]]
    assert client.post(f"/api/whispers/{task['id']}/restore").status_code == 200
    assert task["id"] in [w["id"] for w in get("")["items"]]
    assert client.post("/api/whispers", json={"items": [{"kind": "task", "title": "x"}], "transcript": "x",
                                              "audio_file": "../../etc/passwd"}).status_code == 400


def test_whispers_ignore_the_current_project(client, lib):
    save(client, [{"kind": "note", "title": "Заметка", "text": "заметка"}])
    other = lib.create_project("Другой")
    lib.set_current_project(other["id"])
    assert len(client.get("/api/whispers").get_json()["items"]) == 1


def test_patch_due_clears_notified(client, lib):
    [w] = save(client, [{"kind": "remind", "title": "Позвонить", "text": "позвонить", "due_at": 100.0}])
    lib.mark_whisper_notified(w["id"], 200.0)
    out = client.patch(f"/api/whispers/{w['id']}", json={"due_at": 300.0, "kind": "task", "title": "Позвонить Ирине"}).get_json()
    assert out["due_at"] == 300.0 and out["notified_at"] is None and out["kind"] == "task"


def test_whisper_reminder_scheduler(lib):
    [due, later, note, done] = lib.add_whispers([
        {"kind": "remind", "title": "Позвонить Ирине", "text": "позвонить", "due_at": 1000.0},
        {"kind": "task", "title": "Потом", "text": "потом", "due_at": 5000.0},
        {"kind": "note", "title": "Заметка", "text": "заметка", "due_at": 1000.0},
        {"kind": "task", "title": "Сделано", "text": "сделано", "due_at": 1000.0}], "сказано")
    lib.update_whisper(done["id"], done=True)
    shown = []
    sched = wm.ReminderScheduler(lib, lambda title, text: shown.append((title, text)), clock=lambda: 2000.0)
    assert [w["id"] for w in sched.tick()] == [due["id"]]
    assert shown == [("Dictum", "Позвонить Ирине")]
    assert lib.get_whisper(due["id"])["notified_at"] is not None
    assert sched.tick() == [] and len(shown) == 1                    # once
    assert lib.get_whisper(later["id"])["notified_at"] is None


def test_scheduler_thread_runs_and_stops(lib):
    lib.add_whispers([{"kind": "remind", "title": "Сейчас", "text": "сейчас", "due_at": 1.0}], "сейчас")
    fired = threading.Event()
    sched = wm.ReminderScheduler(lib, lambda t, x: fired.set(), interval=0.05).start()
    try:
        assert fired.wait(2)
    finally:
        sched.stop()


def test_whisper_to_question(client, lib):
    pid = lib.current_project()["id"]
    [w] = save(client, [{"kind": "task", "title": "Уточнить срок ответа дилеру", "text": "уточнить срок"}],
               transcript="надо уточнить у клиента срок ответа дилеру")
    out = client.post(f"/api/whispers/{w['id']}/to-question", json={}).get_json()
    atom = lib.get_atom(out["atom_id"])
    assert atom["type"] == "question" and atom["project_id"] == pid and out["label"].startswith("Q-")
    assert atom["statement"] == "Уточнить срок ответа дилеру?"
    [ev] = atom["evidence"]
    assert ev["quote"] == "надо уточнить у клиента срок ответа дилеру"
    source = lib.get_source(ev["source_id"])
    assert source["kind"] == "note" and source["title"] == "Шепнуть"
    assert source["id"] not in [s["id"] for s in lib.list_sources(pid)]          # hidden from Встречи
    assert lib.get_whisper(w["id"])["atom_id"] == out["atom_id"] and out["whisper"]["atom_id"] == out["atom_id"]
    # a second one goes into the same hidden source
    [w2] = save(client, [{"kind": "note", "title": "Кто утверждает статус", "text": "кто"}], transcript="кто утверждает")
    other = lib.create_project("Портал")
    out2 = client.post(f"/api/whispers/{w2['id']}/to-question", json={"project_id": other["id"]}).get_json()
    assert out2["project_id"] == other["id"] and out2["project_name"] == "Портал"
    out3 = client.post(f"/api/whispers/{w['id']}/to-question", json={}).get_json()
    assert lib.get_atom(out3["atom_id"])["evidence"][0]["source_id"] == source["id"]


def test_to_question_uses_the_linked_project(client, lib):
    linked = lib.create_project("Заявки")
    [w] = save(client, [{"kind": "task", "title": "Спросить про дубли", "text": "дубли", "project_id": linked["id"]}])
    out = client.post(f"/api/whispers/{w['id']}/to-question", json={}).get_json()
    assert out["project_id"] == linked["id"]


def test_whispers_absent_from_project_export_and_search(client, lib):
    pid = lib.current_project()["id"]
    save(client, [{"kind": "note", "title": "Секретная заметка про бюджет", "text": "бюджет", "project_id": pid}])
    data = lib.export_project(pid)
    assert "whispers" not in data["tables"]
    assert "бюджет" not in str(data)
    assert lib.search(pid, "бюджет") == [] or all(h["entity"] != "whisper" for h in lib.search(pid, "бюджет"))
    assert lib.list_atoms(pid) == [] and lib.list_sources(pid) == []


def test_soft_delete_keeps_the_audio(client, rec, lib, monkeypatch):
    monkeypatch.setattr(rec, "_whisper_final_text", lambda path, opts: "просто мысль")
    monkeypatch.setattr(rec, "_ai_prefs", lambda project: ({"llm_provider": "claude"}, "k", None))
    monkeypatch.setattr(rec, "_whisper_complete", lambda prefs, key: lambda s, u, schema: {"items": []})
    client.post("/api/whispers/record/start", json={})
    body = client.post("/api/whispers/record/stop").get_json()
    path = os.path.join(rec._whisper["capture"].root, body["audio_file"])
    size = os.path.getsize(path)
    [w] = save(client, body["items"], transcript=body["transcript"], audio=body["audio_file"])
    client.delete(f"/api/whispers/{w['id']}")
    assert lib.get_whisper(w["id"], include_deleted=True)["audio_file"] == body["audio_file"]
    assert os.path.getsize(path) == size
