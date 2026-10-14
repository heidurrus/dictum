"""Recap styles with incremental update (spec 5.0 C3)."""
import pytest

from core import notes, skills
from core.store import Store
from tests.test_library_api import import_vtt, lib  # noqa: F401  (fixture)
from tests.test_recorder import wait_for

FIRST = ["Дилер заводит заявки вручную", "Нужна проверка по VIN", "Ответ дилеру за два часа"]
LATER = ["Интеграцию с 1С обсудим отдельно", "Историю изменений хранить год"]


@pytest.fixture()
def store(tmp_path):
    return Store(root=str(tmp_path / "lib"), user="ba")


def _segments(lines):
    return {"segments": [{"start": 10.0 * i, "end": 10.0 * i + 5, "speaker": "SPEAKER_00", "text": t}
                         for i, t in enumerate(lines)], "text": " ".join(lines)}


@pytest.fixture()
def source(store):
    p = store.create_project("P")
    s = store.create_source(p["id"], "transcript", "Звонок с дилером")
    store.save_transcript(s["id"], _segments(FIRST))
    return s


class Model:
    def __init__(self):
        self.calls = []

    def __call__(self, system, user, on_delta):
        self.calls.append((system, user))
        on_delta("…")
        return f"## Главное\n- версия {len(self.calls)}"


def run(store, sid, style, incremental, model):
    return notes.recap(store, sid, style, incremental, model, skills.resolve(), "claude", "claude-opus-5")


def test_full_recap_sends_everything_and_records_through_idx(store, source):
    model = Model()
    row = run(store, source["id"], "brief", False, model)
    system, user = model.calls[0]
    assert all(t in user for t in FIRST) and "Звонок с дилером" in user
    assert "Previous recap" not in user and "updating an existing recap" not in system
    assert "Главное" in system                                      # the recap-brief skill
    assert row["through_idx"] == 2 and row["incremental"] is False and row["style"] == "brief"
    assert store.notes(source["id"])[1] == "brief"


def test_incremental_recap_sends_only_new_lines_and_the_old_recap(store, source):
    model = Model()
    run(store, source["id"], "brief", False, model)
    store.save_transcript(source["id"], _segments(FIRST + LATER))        # the meeting went on
    row = run(store, source["id"], "brief", True, model)
    system, user = model.calls[1]
    assert all(t in user for t in LATER) and not any(t in user for t in FIRST)
    assert "## Главное\n- версия 1" in user                             # the previous recap
    assert "updating an existing recap" in system and "not writing a new one" in system
    assert row["through_idx"] == 4 and row["incremental"] is True and row["text"].endswith("версия 2")


def test_incremental_with_nothing_new_does_not_call_the_model(store, source):
    model = Model()
    run(store, source["id"], "brief", False, model)
    row = run(store, source["id"], "brief", True, model)
    assert len(model.calls) == 1 and row["unchanged"] is True and row["text"].endswith("версия 1")


def test_a_style_without_a_recap_gets_a_full_one(store, source):
    model = Model()
    run(store, source["id"], "brief", False, model)
    run(store, source["id"], "actions", True, model)                     # incremental asked, no 'actions' row yet
    system, user = model.calls[1]
    assert all(t in user for t in FIRST) and "Previous recap" not in user
    assert "## Задачи" in system                                        # the recap-actions skill
    assert set(store.summaries(source["id"])) == {"brief", "actions"}
    assert store.notes(source["id"])[1] == "actions"


def test_recap_route_and_legacy_summary_field(client, app_module, lib, monkeypatch):  # noqa: F811
    sid = import_vtt(client)["source_id"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    seen = []
    monkeypatch.setattr(app_module, "_recap_generate",
                        lambda prefs, key: lambda system, user, on_delta: seen.append(user) or f"recap {len(seen)}")

    def recap(style, incremental=False):
        job = client.post(f"/api/sources/{sid}/recap", json={"style": style, "incremental": incremental}).get_json()["job_id"]
        assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
        return client.get(f"/job/{job}").get_json()

    job = recap("bullets")
    assert job["result"]["style"] == "bullets" and job["result"]["through_idx"] == 1
    assert job["kind"] == "summarize" and job["label"] == "Встреча"
    recap("actions")
    body = client.get(f"/api/sources/{sid}").get_json()
    assert set(body["summaries"]) == {"bullets", "actions"} and body["recap_style"] == "actions"
    assert body["summaries"]["bullets"] == {"text": "recap 1", "model": body["summaries"]["bullets"]["model"],
                                            "created_at": body["summaries"]["bullets"]["created_at"], "through_idx": 1}
    assert body["summary"]["text"] == "recap 2"                          # legacy field: the current style
    assert recap("actions", True)["result"]["unchanged"] is True and len(seen) == 2
    assert client.post(f"/api/sources/{sid}/recap", json={"style": "poem"}).status_code == 400

    # The old /summarize route keeps working and writes the 'brief' row.
    monkeypatch.setattr(app_module, "summarize", lambda *a, **k: "## Кратко")
    job = client.post("/summarize", json={"source_id": sid}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    body = client.get(f"/api/sources/{sid}").get_json()
    assert body["summaries"]["brief"]["text"] == "## Кратко" and body["summaries"]["brief"]["through_idx"] == 1
