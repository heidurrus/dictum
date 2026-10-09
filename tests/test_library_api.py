import io
import os

import pytest

from core.store import Store
from tests.test_recorder import StreamingWavWriter, wait_for

import numpy as np


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    """A fresh library per test."""
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


def import_vtt(client, name="Встреча.vtt", project_id=None):
    vtt = ("WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v SPEAKER_00>Добрый день</v>\n\n"
           "00:00:04.000 --> 00:00:06.000\n<v SPEAKER_01>Нужна карточка клиента</v>\n").encode()
    data = {"audio": (io.BytesIO(vtt), name)}
    if project_id:
        data["project_id"] = project_id
    return client.post("/transcribe", data=data, content_type="multipart/form-data").get_json()


def test_projects_create_switch_rename_archive(client, lib):
    body = client.get("/api/projects").get_json()
    default = body["current_project_id"]
    assert [p["name"] for p in body["projects"]] == ["Мой проект"]

    crm = client.post("/api/projects", json={"name": "CRM для контакт-центра"}).get_json()
    assert client.post("/api/projects", json={"name": "crm для контакт-центра"}).status_code == 400
    assert client.post(f"/api/projects/{crm['id']}/current").status_code == 200
    assert client.get("/api/projects").get_json()["current_project_id"] == crm["id"]

    r = client.patch(f"/api/projects/{crm['id']}", json={"name": "CRM", "local_only": True}).get_json()
    assert r["name"] == "CRM" and r["local_only"] is True
    client.patch(f"/api/projects/{crm['id']}", json={"archived": True})
    body = client.get("/api/projects").get_json()
    assert [p["id"] for p in body["projects"]] == [default] and body["current_project_id"] == default
    assert client.patch("/api/projects/nope", json={"name": "x"}).status_code == 404


def test_imported_transcript_is_saved_in_the_right_project(client, lib):
    client.get("/api/projects")                       # the app always starts with "Мой проект"
    other = client.post("/api/projects", json={"name": "Other"}).get_json()
    a = import_vtt(client)
    b = import_vtt(client, "Второй.vtt", project_id=other["id"])
    current = client.get("/api/projects").get_json()["current_project_id"]
    mine = client.get(f"/api/projects/{current}/sources").get_json()["sources"]
    theirs = client.get(f"/api/projects/{other['id']}/sources").get_json()["sources"]
    assert [s["id"] for s in mine] == [a["source_id"]] and [s["id"] for s in theirs] == [b["source_id"]]
    src = client.get(f"/api/sources/{a['source_id']}").get_json()
    assert src["kind"] == "transcript" and src["import_format"] == "vtt" and src["speakers"] == 2
    assert os.path.exists(os.path.join(lib.source_dir(src), "Встреча.vtt"))


def test_rename_speaker_shows_everywhere_and_feeds_summaries(client, app_module, lib, monkeypatch):
    sid = import_vtt(client)["source_id"]
    r = client.put(f"/api/sources/{sid}/speakers/SPEAKER_00", json={"name": "Иван Петров"}).get_json()
    assert r["speaker_names"] == {"SPEAKER_00": "Иван Петров"}
    src = client.get(f"/api/sources/{sid}").get_json()
    assert src["segments"][0]["speaker_name"] == "Иван Петров"
    assert src["text"].startswith("[Иван Петров] [00:01 - 00:03] Добрый день")

    seen = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    monkeypatch.setattr(app_module, "summarize", lambda text, prefs, key, url, on_delta, title=None, skillset=None, language_rule="":
                        seen.update(text=text, title=title, provider=prefs["llm_provider"]) or "## Итоги")
    job = client.post("/summarize", json={"source_id": sid}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    assert "[Иван Петров]" in seen["text"] and seen["title"] == "Call or meeting — Встреча"
    assert client.get(f"/api/sources/{sid}").get_json()["summary"]["text"] == "## Итоги"
    assert client.get(f"/api/projects/{lib.current_project()['id']}/sources").get_json()["sources"][0]["has_summary"]


def test_local_only_project_never_uses_the_cloud(client, app_module, lib, monkeypatch):
    p = lib.current_project()
    lib.update_project(p["id"], local_only=True)
    sid = import_vtt(client)["source_id"]
    seen = {}
    monkeypatch.setattr(app_module.settings, "load_settings",
                        lambda: {"llm_provider": "claude", "claude_model": "claude-opus-5", "ollama_model": "qwen3:8b",
                                 "local_model": ""})
    monkeypatch.setattr(app_module, "summarize", lambda text, prefs, key, url, on_delta, title=None, skillset=None, language_rule="":
                        seen.update(provider=prefs["llm_provider"]) or "ok")
    monkeypatch.setattr(app_module.local_llm, "ready", lambda: False)
    r = client.post("/summarize", json={"source_id": sid})
    assert r.status_code == 400 and r.get_json()["needs_setup"] and "Local only" in r.get_json()["error"]

    monkeypatch.setattr(app_module.local_llm, "ready", lambda: True)
    job = client.post("/summarize", json={"source_id": sid}).get_json()["job_id"]   # no Anthropic key needed
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    assert seen["provider"] == "local"
    assert client.get(f"/job/{job}").get_json()["result"]["provider"] == "local"


def test_local_only_project_keeps_ollama_if_chosen(app_module):
    prefs = {"llm_provider": "ollama", "claude_model": "claude-opus-5", "ollama_model": "qwen3:8b", "local_model": ""}
    assert app_module.for_project(prefs, {"local_only": True})["llm_provider"] == "ollama"
    assert app_module.for_project({**prefs, "llm_provider": "claude"}, {"local_only": False})["llm_provider"] == "claude"


def test_rename_delete_restore_source(client, lib):
    sid = import_vtt(client)["source_id"]
    assert client.patch(f"/api/sources/{sid}", json={"title": "Созвон с заказчиком"}).get_json()["title"] == "Созвон с заказчиком"
    assert client.patch(f"/api/sources/{sid}", json={"status": "ready"}).status_code == 400
    assert client.delete(f"/api/sources/{sid}").status_code == 200
    assert client.get(f"/api/sources/{sid}").status_code == 404
    assert client.post(f"/api/sources/{sid}/restore").status_code == 200
    assert client.get(f"/api/sources/{sid}").status_code == 200
    actions = [e["action"] for e in client.get(f"/api/audit?entity=source&entity_id={sid}").get_json()["entries"]]
    assert actions == ["restore", "delete", "update", "update", "create"]


def _wav_source(lib, seconds=1.0):
    src = lib.create_source(lib.current_project()["id"], "recording", "Recording", status="recorded")
    path = os.path.join(lib.source_dir(src), "mixed.wav")
    w = StreamingWavWriter(path)
    w.write(np.zeros(int(16000 * seconds), np.int16))
    w.close()
    lib.update_source(src["id"], audio_file="mixed.wav")
    return src, path


def test_audio_supports_range_requests_for_seeking(client, lib):
    src, path = _wav_source(lib)
    full = client.get(f"/api/sources/{src['id']}/audio")
    assert full.status_code == 200 and len(full.data) == os.path.getsize(path)
    part = client.get(f"/api/sources/{src['id']}/audio", headers={"Range": "bytes=100-199"})
    assert part.status_code == 206 and len(part.data) == 100


def test_transcribe_a_saved_recording(client, app_module, lib, monkeypatch):
    src, path = _wav_source(lib)
    seen = {}

    def fake(job_id, audio_path, *a):
        seen["path"] = audio_path
        return {"text": "ok", "segments": [{"start": 0, "end": 1, "text": "ok"}]}
    monkeypatch.setattr(app_module, "_transcribe", fake)
    body = client.post(f"/api/sources/{src['id']}/transcribe", json={"model": "v3_e2e_rnnt"}).get_json()
    assert wait_for(lambda: client.get(f"/job/{body['job_id']}").get_json()["status"] == "done")
    assert seen["path"] == path and os.path.exists(path), "recording is kept after transcription"
    assert client.get(f"/api/sources/{src['id']}").get_json()["status"] == "ready"
    assert client.post(f"/api/sources/{src['id']}/transcribe", json={"model": "gpt"}).status_code == 400


def test_failed_transcription_marks_the_source(client, app_module, lib, monkeypatch):
    src, _ = _wav_source(lib)

    def boom(*a):
        raise RuntimeError("model exploded")
    monkeypatch.setattr(app_module, "_transcribe", boom)
    job = client.post(f"/api/sources/{src['id']}/transcribe", json={}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "error")
    s = client.get(f"/api/sources/{src['id']}").get_json()
    assert s["status"] == "failed" and s["error"] == "model exploded"


def test_unknown_ids(client, lib):
    assert client.get("/api/sources/nope").status_code == 404
    assert client.get("/api/projects/nope/sources").status_code == 404
    assert client.post("/summarize", json={"source_id": "nope"}).status_code == 404


def test_email_import_becomes_an_email_source(client, lib):
    from tests.test_emails import EML
    body = client.post("/transcribe", data={"audio": (io.BytesIO(EML), "letter.eml")},
                       content_type="multipart/form-data").get_json()
    src = client.get(f"/api/sources/{body['source_id']}").get_json()
    assert src["kind"] == "email" and src["title"] == "Требования к карточке"
    assert src["meta"]["email"]["from"] == "Иван Петров"
    assert src["segments"][0]["speaker_name"] == "Иван Петров"


def test_prose_import_becomes_a_document(client, lib):
    text = "Требования заказчика.\n\nСистема должна показывать историю обращений.\n".encode()
    body = client.post("/transcribe", data={"audio": (io.BytesIO(text), "Требования v2.txt")},
                       content_type="multipart/form-data").get_json()
    src = client.get(f"/api/sources/{body['source_id']}").get_json()
    assert src["kind"] == "document" and src["title"] == "Требования v2"
    assert [s["text"] for s in src["segments"]] == ["Требования заказчика.", "Система должна показывать историю обращений."]


def test_project_status_counts_for_the_sidebar(client, lib):
    pid = client.get("/api/projects").get_json()["current_project_id"]
    empty = client.get(f"/api/projects/{pid}/status").get_json()
    assert empty["sources"] == 0 and empty["atoms"] == {"review": 0, "total": 0, "accepted": 0, "conflicts": 0}
    assert empty["document"]["version"] is None and not empty["document"]["stale"]
    assert empty["open_items"] == {"questions": 0, "actions": 0}
    assert empty["backlog"]["items"] == 0 and empty["export"]["pushed"] == 0
    import_vtt(client, project_id=pid)
    assert client.get(f"/api/projects/{pid}/status").get_json()["sources"] == 1
    assert client.get("/api/projects/nope/status").status_code == 404


def test_audio_files_are_listed_and_downloadable(client, lib):
    src, path = _wav_source(lib)
    with open(path, "rb") as f, open(os.path.join(lib.source_dir(src), "mic.wav"), "wb") as m:
        m.write(f.read())
    files = client.get(f"/api/sources/{src['id']}").get_json()["audio_files"]
    assert [f["id"] for f in files] == ["mixed", "mic"], "a recording lists each channel it kept"
    assert all(f["size"] == os.path.getsize(path) for f in files)
    r = client.get(f"/api/sources/{src['id']}/audio/download/mic")
    assert r.status_code == 200 and len(r.data) == os.path.getsize(path)
    assert "attachment" in r.headers["Content-Disposition"] and "Recording.wav" in r.headers["Content-Disposition"]
    assert client.get(f"/api/sources/{src['id']}/audio/download/sys").status_code == 404
    assert client.get(f"/api/sources/{src['id']}/audio/download/../../x").status_code == 404


def test_imported_audio_downloads_as_the_original_file(client, lib):
    src = lib.create_source(lib.current_project()["id"], "audio", "Call", original_filename="call recording.m4a")
    os.makedirs(lib.source_dir(src), exist_ok=True)
    with open(os.path.join(lib.source_dir(src), "original.m4a"), "wb") as f:
        f.write(b"m4a-bytes")
    with open(os.path.join(lib.source_dir(src), "audio.wav"), "wb") as f:
        f.write(b"wav-bytes")
    lib.update_source(src["id"], audio_file="audio.wav")
    files = client.get(f"/api/sources/{src['id']}").get_json()["audio_files"]
    assert files == [{"id": "original", "name": "original.m4a", "size": 9, "filename": "call recording.m4a"}]
    r = client.get(f"/api/sources/{src['id']}/audio/download/original")
    assert r.data == b"m4a-bytes" and "call recording.m4a" in r.headers["Content-Disposition"]


def test_audio_download_uses_the_name_the_page_asks_for(client, lib):
    src, path = _wav_source(lib)
    r = client.get(f"/api/sources/{src['id']}/audio/download/mixed?name=Звонок — микрофон.wav")
    from urllib.parse import unquote
    assert "Звонок — микрофон.wav" in unquote(r.headers["Content-Disposition"])
    r = client.get(f"/api/sources/{src['id']}/audio/download/mixed?name=../evil.exe")
    assert "Recording.wav" in r.headers["Content-Disposition"], "wrong extension or path → the default name"
