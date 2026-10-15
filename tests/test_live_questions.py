"""The question card in a live session (5.0 C4.3): the detector, the score threshold, one card at a time (newest
wins), dismissal, expiry, the /live payload and the setting; failures never reach the recording."""
import threading

import pytest

from core import ask, index, live_questions, materials, settings
from core.live_questions import LiveQuestions, is_question
from core.store import Store
from tests import fake_embed


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


@pytest.fixture()
def pid(lib):
    return lib.ensure_default_project()["id"]


@pytest.fixture()
def indexed(lib, pid, monkeypatch):
    fake_embed.install(monkeypatch, index)
    materials.import_text(lib, lib.get_project(pid), "Кто утверждает изменение статуса заявки? Статус заявки утверждает "
                          "руководитель отдела или его заместитель.", "Регламент v2")
    off = materials.import_text(lib, lib.get_project(pid), "Кто утверждает изменение статуса заявки дилера в старом "
                                "регламенте: директор.", "Регламент v1")
    lib.update_material(off["id"], in_context=False)
    index.index_project(lib, pid)


@pytest.fixture()
def recording(lib, pid):
    return lib.create_source(pid, "recording", "Звонок", status="recording")


def say(lib, source_id, *texts):
    lib.append_provisional_segments(source_id, [{"speaker": "OTHER", "start": 1.0, "end": 2.0, "text": t} for t in texts])


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


SHORT = "Утверждает руководитель отдела или его заместитель [Источник 1]."


def model(reply=SHORT, calls=None):
    def generate(system, user, on_delta):
        if calls is not None:
            calls.append({"system": system, "user": user})
        return reply
    return generate


# ── the detector ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "Кто будет утверждать изменение статуса заявки?",
    "А мы успеем сделать это до конца квартала?",
    "Сколько заявок приходит от дилеров за день",
    "Какие поля обязательны в карточке клиента сейчас",
    "How many requests do the dealers send per day",
    "Which fields are required on the client card",
    "We need to know if this works for everyone?",
])
def test_questions_are_detected(text):
    assert is_question(text)


@pytest.mark.parametrize("text", [
    "Кто будет утверждать?",                          # too short
    "Давайте начнём с заявок дилеров сегодня утром",  # no interrogative, no "?"
    "Нам нужно, чтобы система проверяла VIN",
    "What?",
    "",
])
def test_other_lines_are_not(text):
    assert not is_question(text)


# ── the card ─────────────────────────────────────────────────────────────────

def test_a_question_close_to_a_material_in_context_gets_a_card(lib, pid, indexed, recording):
    calls = []
    lq = LiveQuestions(recording["id"], lib, live_questions.answerer(lib, pid, model(calls=calls)))
    say(lib, recording["id"], "Давайте начнём с заявок дилеров", "А кто утверждает изменение статуса заявки?")
    card = lq.run_pass()
    assert card["text"] == "А кто утверждает изменение статуса заявки?"
    assert card["answer"] == "Утверждает руководитель отдела или его заместитель."
    assert card["citation"]["entity"] == "material" and card["citation"]["title"] == "Регламент v2"
    assert ask.SHORT_CONTRACT.split()[0] in calls[0]["system"] and "Регламент v1" not in calls[0]["user"]
    assert lq.current()["id"] == card["id"]


def test_no_card_below_the_score_threshold(lib, pid, indexed, recording):
    calls = []
    lq = LiveQuestions(recording["id"], lib, live_questions.answerer(lib, pid, model(calls=calls)))
    say(lib, recording["id"], "Когда мы поедем в отпуск всей командой летом?")
    assert lq.run_pass() is None and lq.current() is None and calls == []


def test_no_card_without_the_index(lib, pid, recording, monkeypatch):
    monkeypatch.setattr(index, "available", lambda: False)
    materials.import_text(lib, lib.get_project(pid), "Статус заявки утверждает руководитель отдела.", "Регламент")
    lq = LiveQuestions(recording["id"], lib, live_questions.answerer(lib, pid, model(calls=[])))
    say(lib, recording["id"], "А кто утверждает изменение статуса заявки?")
    assert lq.run_pass() is None


def test_no_card_when_the_model_has_no_answer(lib, pid, indexed, recording):
    lq = LiveQuestions(recording["id"], lib, live_questions.answerer(lib, pid, model("—")))
    say(lib, recording["id"], "А кто утверждает изменение статуса заявки?")
    assert lq.run_pass() is None


def test_the_newest_question_wins_and_old_lines_are_not_read_again(lib, recording):
    asked = []
    lq = LiveQuestions(recording["id"], lib,
                       lambda q: asked.append(q) or {"answer": "Ответ: " + q, "citation": {"n": 1}})
    say(lib, recording["id"], "А кто утверждает изменение статуса заявки?", "Сколько заявок приходит за один день?")
    assert lq.run_pass()["text"] == "Сколько заявок приходит за один день?"
    assert asked == ["Сколько заявок приходит за один день?"]
    assert lq.run_pass() is None and len(asked) == 1               # nothing new
    say(lib, recording["id"], "Где хранится история изменений заявки дилера?")
    assert lq.run_pass()["text"] == "Где хранится история изменений заявки дилера?"
    assert lq.current()["text"] == "Где хранится история изменений заявки дилера?"


def test_dismissal_and_expiry(lib, recording):
    clock = Clock()
    lq = LiveQuestions(recording["id"], lib, lambda q: {"answer": "Да.", "citation": {"n": 1}}, clock=clock)
    say(lib, recording["id"], "А кто утверждает изменение статуса заявки?")
    card = lq.run_pass()
    assert not lq.dismiss("another-card") and lq.current()
    assert lq.dismiss(card["id"]) and lq.current() is None and not lq.dismiss(card["id"])
    say(lib, recording["id"], "Сколько заявок приходит за один день?")
    lq.run_pass()
    clock.now += 59
    assert lq.current() is not None
    clock.now += 2
    assert lq.current() is None


def test_a_busy_pass_is_skipped_and_errors_are_logged_not_raised(lib, recording):
    gate, entered = threading.Event(), threading.Event()

    def slow(q):
        entered.set()
        gate.wait(2)
        raise RuntimeError("model down")
    lq = LiveQuestions(recording["id"], lib, slow)
    say(lib, recording["id"], "А кто утверждает изменение статуса заявки?")
    assert lq.tick() is True
    entered.wait(2)
    assert lq.busy and lq.tick() is False and lq.skipped == 1
    gate.set()
    for _ in range(100):
        if not lq.busy:
            break
        threading.Event().wait(0.02)
    assert lq.errors == 1 and lq.current() is None
    lq.stop()
    assert lq.tick() is False


# ── the app ──────────────────────────────────────────────────────────────────

def test_the_setting_is_off_by_default_and_round_trips(client, monkeypatch, tmp_path):
    monkeypatch.setenv("DICTUM_DATA_DIR", str(tmp_path))
    assert settings.DEFAULTS["live_questions"] is False
    assert client.get("/settings").get_json()["live_questions"] is False
    assert client.post("/settings", json={"live_questions": True}).get_json()["live_questions"] is True
    assert client.get("/settings").get_json()["live_questions"] is True
    assert settings.load_settings()["live_questions"] is True


def test_off_setting_starts_no_question_helper(app_module, lib, recording, monkeypatch):
    monkeypatch.setattr(app_module.settings, "load_settings", lambda: {**settings.DEFAULTS})
    assert app_module._start_live_questions(recording) is None


def test_the_live_payload_carries_the_card_and_dismiss_hides_it(client, app_module, lib, recording, monkeypatch):
    lq = LiveQuestions(recording["id"], lib, lambda q: {"answer": "Руководитель.", "citation": {"n": 1, "title": "R"}})
    say(lib, recording["id"], "А кто утверждает изменение статуса заявки?")
    lq.run_pass()

    class Rec:
        recording = True

        def status(self):
            return {"recording": True, "paused": False, "elapsed": 5}
    monkeypatch.setattr(app_module, "_recorder", Rec())
    monkeypatch.setitem(app_module._session, "source_id", recording["id"])
    monkeypatch.setitem(app_module._session, "questions", lq)
    monkeypatch.setitem(app_module._session, "live", None)
    body = client.get(f"/api/sources/{recording['id']}/live").get_json()
    assert body["question"]["text"] == "А кто утверждает изменение статуса заявки?"
    assert body["question"]["answer"] == "Руководитель." and body["question"]["citation"]["title"] == "R"
    r = client.post(f"/api/sources/{recording['id']}/live/question/dismiss", json={"id": body["question"]["id"]})
    assert r.get_json()["dismissed"] is True
    assert client.get(f"/api/sources/{recording['id']}/live").get_json()["question"] is None
