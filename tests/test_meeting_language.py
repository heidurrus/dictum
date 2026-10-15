"""5.0.5: a meeting is in Russian or Multilingual instead of naming a speech model. The language is kept per project
(arrives as Russian on old databases, round-trips through PATCH), Settings → Models maps each language to a model
(the one model of earlier versions is carried over), and the record and import routes get the mapped model."""
import io
import sqlite3

import pytest

from core import settings
from core.store import Store, StoreError
from tests.test_live import recording_app  # noqa: F401  (fixture)
from tests.test_recorder import wait_for

OLD_SCHEMA = """
  CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, local_only INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, created_by TEXT NOT NULL,
    updated_at REAL NOT NULL, updated_by TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'auto', jira_quotes TEXT NOT NULL DEFAULT 'auto',
    auto_extract INTEGER NOT NULL DEFAULT 1, analysis INTEGER NOT NULL DEFAULT 1);
  INSERT INTO projects (id, name, local_only, archived, created_at, created_by, updated_at, updated_by)
    VALUES ('p1', 'Портал дилера', 0, 0, 1, 'ba', 1, 'ba');
"""


# ── the project's language ───────────────────────────────────────────────────

def test_old_database_gets_russian(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    db = sqlite3.connect(root / "workbench.db")             # 5.0.4: projects without asr_lang
    db.executescript(OLD_SCHEMA)
    db.commit()
    db.close()
    store = Store(root=str(root), user="ba")
    assert store.get_project("p1")["asr_lang"] == "ru"
    with sqlite3.connect(root / "workbench.db") as c:
        col = {r[1]: r for r in c.execute("PRAGMA table_info(projects)")}["asr_lang"]
    assert col[3] == 1 and col[4] == "'ru'"                  # NOT NULL DEFAULT 'ru'
    Store(root=str(root), user="ba")                         # a second open does not migrate twice
    assert store.create_project("Новый")["asr_lang"] == "ru"


def test_language_is_validated_and_audited(tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    pid = store.create_project("Портал")["id"]
    assert store.update_project(pid, asr_lang="multi")["asr_lang"] == "multi"
    with pytest.raises(StoreError):
        store.update_project(pid, asr_lang="en")
    assert store.get_project(pid)["asr_lang"] == "multi"
    with sqlite3.connect(tmp_path / "lib" / "workbench.db") as c:
        actions = [r[0] for r in c.execute("SELECT action FROM audit_log WHERE entity = 'project' AND entity_id = ?", (pid,))]
    assert actions == ["create", "update"]


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    monkeypatch.setattr(app_module, "schedule_index", lambda project_id, force_material=None: None)
    store.ensure_default_project()
    return store


@pytest.fixture()
def prefs(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "settings_file", lambda: str(tmp_path / "settings.json"))


def test_patch_round_trip(client, lib):
    pid = lib.current_project()["id"]
    other = client.post("/api/projects", json={"name": "Английский заказчик"}).get_json()
    assert other["asr_lang"] == "ru"
    r = client.patch(f"/api/projects/{other['id']}", json={"asr_lang": "multi"})
    assert r.status_code == 200 and r.get_json()["asr_lang"] == "multi"
    listed = {p["id"]: p for p in client.get("/api/projects").get_json()["projects"]}
    assert listed[other["id"]]["asr_lang"] == "multi" and listed[pid]["asr_lang"] == "ru"   # each project its own
    assert client.patch(f"/api/projects/{pid}", json={"asr_lang": "de"}).status_code == 400


# ── language → model ─────────────────────────────────────────────────────────

def test_mapping_defaults_and_choices(prefs):
    assert settings.asr_model_for("ru") == "v3_e2e_rnnt"
    assert settings.asr_model_for("multi") == "multilingual_ctc"
    assert settings.asr_model_for("xx") == "v3_e2e_rnnt"                # anything else is Russian
    settings.save_settings({"asr_model_ru": "v3_e2e_ctc", "asr_model_multi": "multilingual_large_ctc"})
    assert settings.asr_model_for("ru") == "v3_e2e_ctc"
    assert settings.asr_model_for("multi") == "multilingual_large_ctc"
    for key, value in (("asr_model_ru", "multilingual_ctc"), ("asr_model_multi", "v3_e2e_rnnt"), ("asr_model_ru", "gpt")):
        with pytest.raises(ValueError):
            settings.save_settings({key: value})
    assert settings.save_settings({"asr_model_multi": ""})["asr_model_multi"] == ""        # back to the default
    assert settings.asr_model_for("multi") == "multilingual_ctc"


def test_the_one_model_of_earlier_versions_is_carried_over_once(prefs):
    data = settings.save_settings({"model": "multilingual_large_ctc"})
    assert data["asr_model_multi"] == "multilingual_large_ctc" and data["asr_model_ru"] == ""
    assert "model" not in data
    data = settings.save_settings({"model": "v3_ctc"})                   # a choice exists: nothing changes
    assert data["asr_model_ru"] == "" and data["asr_model_multi"] == "multilingual_large_ctc"


def test_a_russian_model_is_carried_over_and_unknown_ones_are_ignored(prefs):
    assert settings.save_settings({"model": "nope"})["asr_model_ru"] == ""
    assert settings.save_settings({"model": "v3_ctc"})["asr_model_ru"] == "v3_ctc"
    assert settings.asr_model_for("ru") == "v3_ctc"


def test_settings_and_models_routes_show_the_mapping(client, prefs):
    got = client.get("/settings").get_json()
    assert got["asr_langs"] == {"ru": "v3_e2e_rnnt", "multi": "multilingual_ctc"} and got["asr_model_ru"] == ""
    body = client.post("/settings", json={"model": "v2_rnnt"}).get_json()
    assert body["asr_model_ru"] == "v2_rnnt" and body["asr_langs"]["ru"] == "v2_rnnt"
    body = client.post("/settings", json={"asr_model_multi": "multilingual_large_ctc"}).get_json()
    assert body["asr_langs"]["multi"] == "multilingual_large_ctc"
    assert client.post("/settings", json={"asr_model_multi": "v1_ctc"}).status_code == 400
    assert client.get("/api/asr/models").get_json()["langs"] == {"ru": "v2_rnnt", "multi": "multilingual_large_ctc"}


# ── the routes get the meeting's model ───────────────────────────────────────

@pytest.fixture()
def spied(recording_app, monkeypatch, lib, prefs):  # noqa: F811
    a = recording_app
    seen = {"live": [], "jobs": []}
    monkeypatch.setattr(a, "_start_live", lambda source, folder, opts, recorder: seen["live"].append(opts))
    monkeypatch.setattr(a, "_start_live_questions", lambda source: None)
    monkeypatch.setattr(a, "_start_silence_watch", lambda source, folder, recorder: None)
    monkeypatch.setattr(a, "_start_transcription", lambda source, path, opts: seen["jobs"].append(opts) or "job-1")
    a.seen = seen
    return a


def _wait_audio(client):
    assert wait_for(lambda: all(c["frames"] >= 2048 for c in client.get("/desktop-record/status").get_json()["channels"].values()))


def test_a_multilingual_meeting_records_and_transcribes_with_the_multilingual_model(client, spied):
    a = spied
    sid = client.post("/desktop-record/start", json={"model": "multilingual_ctc", "device": "cpu"}).get_json()["source_id"]
    assert a.seen["live"][-1]["model_name"] == "multilingual_ctc"         # the live pass
    _wait_audio(client)
    r = client.post("/desktop-record/stop", json={"model": "multilingual_ctc", "device": "cpu"})
    assert r.status_code == 200
    assert a.seen["jobs"][-1]["model_name"] == "multilingual_ctc"         # the full pass
    assert a.library.get_source(sid)["asr_model"] == "multilingual_ctc"   # the meeting remembers it


def test_a_client_that_sends_only_the_language_gets_the_mapped_model(client, spied):
    a = spied
    settings.save_settings({"asr_model_multi": "multilingual_large_ctc"})
    client.post("/desktop-record/start", json={"asr_lang": "multi"})
    assert a.seen["live"][-1]["model_name"] == "multilingual_large_ctc"
    _wait_audio(client)
    client.post("/desktop-record/stop", json={})


def test_import_transcribes_with_the_chosen_model(client, spied, monkeypatch):
    a = spied
    for form, expected in (({"model": "multilingual_ctc"}, "multilingual_ctc"), ({"asr_lang": "multi"}, "multilingual_ctc"),
                           ({"asr_lang": "ru"}, "v3_e2e_rnnt")):
        body = client.post("/transcribe", data={"audio": (io.BytesIO(b"RIFF"), "Call.wav"), **form},
                           content_type="multipart/form-data").get_json()
        assert a.seen["jobs"][-1]["model_name"] == expected
        assert a.library.get_source(body["source_id"])["asr_model"] == expected
