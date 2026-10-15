"""5.0.4: business analysis can be switched off per project. The column arrives on old databases switched on, the
switch round-trips through PATCH, a notes-only project never starts extraction by itself, and the whisper inbox
refuses to make a question in it."""
import sqlite3

import pytest

from core import whisper as wm
from core.store import Store, StoreError

OLD_SCHEMA = """
  CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, local_only INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, created_by TEXT NOT NULL,
    updated_at REAL NOT NULL, updated_by TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'auto', jira_quotes TEXT NOT NULL DEFAULT 'auto',
    auto_extract INTEGER NOT NULL DEFAULT 1);
  INSERT INTO projects (id, name, local_only, archived, created_at, created_by, updated_at, updated_by)
    VALUES ('p1', 'Портал дилера', 0, 0, 1, 'ba', 1, 'ba');
"""


def test_old_database_gets_analysis_on(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    db = sqlite3.connect(root / "workbench.db")             # 5.0.3: projects without the analysis column
    db.executescript(OLD_SCHEMA)
    db.commit()
    db.close()
    store = Store(root=str(root), user="ba")
    p = store.get_project("p1")
    assert p["analysis"] is True and p["auto_extract"] is True
    with sqlite3.connect(root / "workbench.db") as c:
        col = {r[1]: r for r in c.execute("PRAGMA table_info(projects)")}["analysis"]
    assert col[3] == 1 and col[4] == "1"                     # NOT NULL DEFAULT 1
    Store(root=str(root), user="ba")                         # a second open does not migrate twice
    assert store.get_project("p1")["analysis"] is True


def test_new_projects_default_on_and_can_start_off(tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    assert store.create_project("Портал")["analysis"] is True
    assert store.create_project("Заметки", analysis=False)["analysis"] is False


def test_switch_is_stored_coerced_and_audited(tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    pid = store.create_project("Портал")["id"]
    assert store.update_project(pid, analysis=0)["analysis"] is False
    assert store.update_project(pid, analysis="yes")["analysis"] is True
    with sqlite3.connect(tmp_path / "lib" / "workbench.db") as c:
        actions = [r[0] for r in c.execute("SELECT action FROM audit_log WHERE entity = 'project' AND entity_id = ?",
                                           (pid,))]
    assert actions == ["create", "update", "update"]


# ── routes ───────────────────────────────────────────────────────────────────
@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    monkeypatch.setattr(app_module, "schedule_index", lambda project_id, force_material=None: None)
    store.ensure_default_project()
    return store


def test_patch_round_trip(client, lib):
    pid = lib.current_project()["id"]
    r = client.patch(f"/api/projects/{pid}", json={"analysis": False})
    assert r.status_code == 200 and r.get_json()["analysis"] is False
    listed = {p["id"]: p for p in client.get("/api/projects").get_json()["projects"]}
    assert listed[pid]["analysis"] is False
    assert client.patch(f"/api/projects/{pid}", json={"analysis": True}).get_json()["analysis"] is True
    created = client.post("/api/projects", json={"name": "Только запись", "analysis": False}).get_json()
    assert created["analysis"] is False
    assert client.post("/api/projects", json={"name": "Анализ"}).get_json()["analysis"] is True


def test_auto_extract_skipped_when_analysis_is_off(app_module, lib, monkeypatch):
    started = []
    monkeypatch.setattr(app_module, "_ai_prefs", lambda project: ({"llm_provider": "claude"}, "k", None))
    monkeypatch.setattr(app_module, "_start_extraction",
                        lambda source_id, prefs, api_key: started.append(source_id) or {"job_id": "j1"})
    pid = lib.current_project()["id"]
    sid = lib.create_source(pid, "audio", "Созвон", status="ready")["id"]
    assert app_module._after_transcription(sid) == "j1" and started == [sid]   # on (the default): it goes on
    lib.update_project(pid, analysis=False)
    assert app_module._after_transcription(sid) is None and started == [sid]  # off: never by itself
    assert lib.get_project(pid)["auto_extract"] is True                       # the other setting is kept as it was


def test_whisper_to_question_refused_when_analysis_is_off(client, lib):
    notes = lib.create_project("Заметки", analysis=False)
    r = client.post("/api/whispers", json={"items": [{"kind": "task", "title": "Уточнить срок", "text": "срок"}],
                                           "transcript": "уточнить срок", "audio_file": None})
    [w] = r.get_json()["items"]
    r = client.post(f"/api/whispers/{w['id']}/to-question", json={"project_id": notes["id"]})
    assert r.status_code == 409 and "business analysis is off" in r.get_json()["error"]
    assert lib.list_atoms(notes["id"]) == [] and lib.get_whisper(w["id"])["atom_id"] is None
    with pytest.raises(StoreError):
        wm.to_question(lib, lib.get_whisper(w["id"]), notes["id"])
    on = client.post(f"/api/whispers/{w['id']}/to-question", json={})          # the current project still works
    assert on.status_code == 200 and on.get_json()["project_id"] == lib.current_project()["id"]
