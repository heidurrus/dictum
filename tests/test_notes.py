"""Meeting notes (spec 5.0 C3): save, append, audit, and the routes."""
import pytest

from core import notes
from core.store import Store, StoreError
from tests.test_library_api import import_vtt, lib  # noqa: F401  (fixture)


@pytest.fixture()
def store(tmp_path):
    t = [1000.0]

    def clock():
        t[0] += 1
        return t[0]
    s = Store(root=str(tmp_path / "lib"), user="ba", clock=clock)
    s.clock = t
    return s


@pytest.fixture()
def source(store):
    p = store.create_project("P")
    return store.create_source(p["id"], "transcript", "Звонок")


def test_save_returns_text_and_time(store, source):
    r = notes.save_notes(store, source["id"], "# Итоги\n- SLA 2 часа")
    assert r["text"] == "# Итоги\n- SLA 2 часа" and r["saved_at"] > 1000
    assert store.notes(source["id"]) == ("# Итоги\n- SLA 2 часа", None)
    with pytest.raises(ValueError):
        notes.save_notes(store, source["id"], None)
    with pytest.raises(StoreError, match="not found"):
        notes.save_notes(store, "nope", "x")


def test_append_to_empty_notes(store, source):
    r = notes.append_note(store, source["id"], "Утверждает руководитель")
    assert r["text"] == "- Утверждает руководитель"
    with pytest.raises(ValueError):
        notes.append_note(store, source["id"], "   ")


def test_append_keeps_existing_text(store, source):
    notes.save_notes(store, source["id"], "- Дубли заявок\n")
    r = notes.append_note(store, source["id"], "- уже пункт")
    assert r["text"] == "- Дубли заявок\n- уже пункт"
    r = notes.append_note(store, source["id"], "SLA  2\nчаса")
    assert r["text"] == "- Дубли заявок\n- уже пункт\n- SLA 2 часа"
    assert notes.bullet("1. первый") == "1. первый" and notes.bullet("## Тема") == "## Тема"


def test_notes_edits_are_audited_and_autosaves_coalesce(store, source):
    sid = source["id"]
    notes.save_notes(store, sid, "a")
    notes.save_notes(store, sid, "ab")                         # a second later: same audit entry
    log = [e for e in store.audit("source", sid) if e["action"] == "notes"]
    assert len(log) == 1 and log[0]["before"] == {"notes": ""} and log[0]["after"] == {"notes": "ab"}
    store.clock[0] += 120                                       # two minutes later: a new entry
    notes.save_notes(store, sid, "abc")
    assert len([e for e in store.audit("source", sid) if e["action"] == "notes"]) == 2
    notes.append_note(store, sid, "d")
    appended = [e for e in store.audit("source", sid) if e["action"] == "notes_append"]
    assert len(appended) == 1 and appended[0]["after"] == {"notes": "abc\n- d"}


def test_notes_routes(client, lib):  # noqa: F811
    sid = import_vtt(client)["source_id"]
    assert client.get(f"/api/sources/{sid}").get_json()["notes"] == ""
    r = client.put(f"/api/sources/{sid}/notes", json={"text": "- SLA"})
    assert r.status_code == 200 and r.get_json()["text"] == "- SLA" and r.get_json()["saved_at"]
    r = client.post(f"/api/sources/{sid}/notes/append", json={"line": "Кто утверждает?"}).get_json()
    assert r["text"] == "- SLA\n- Кто утверждает?"
    body = client.get(f"/api/sources/{sid}").get_json()
    assert body["notes"] == "- SLA\n- Кто утверждает?" and body["recap_style"] is None
    assert client.put(f"/api/sources/{sid}/notes", json={"text": 5}).status_code == 400
    assert client.post(f"/api/sources/{sid}/notes/append", json={"line": ""}).status_code == 400
    assert client.put("/api/sources/nope/notes", json={"text": "x"}).status_code == 404
