"""First-run discovery (5.0 C8): which files are offered, and importing them as meetings and materials."""
import os

import pytest

from core import discover
from core.store import Store

AUDIO = {".wav", ".m4a", ".mp4"}


def make(path, size=10, mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_lists_audio_and_documents_newest_first_skipping_the_rest(tmp_path):
    root = tmp_path / "Downloads"
    make(str(root / "Звонок.m4a"), mtime=1000)
    make(str(root / "Регламент.docx"), mtime=3000)
    make(str(root / "notes" / "Заметки.md"), mtime=2000)            # one level down is still found
    make(str(root / "photo.jpg"), mtime=4000)                          # not a candidate kind
    make(str(root / ".hidden.txt"), mtime=5000)                        # hidden file
    make(str(root / ".cache" / "inside.txt"), mtime=5000)              # hidden folder
    make(str(root / "a" / "b" / "c" / "deep.txt"), mtime=5000)         # deeper than MAX_DEPTH
    make(str(root / "empty.txt"), size=0)
    found = discover.candidates([str(root), str(tmp_path / "missing")], AUDIO)
    assert [c["name"] for c in found] == ["Регламент.docx", "Заметки.md", "Звонок.m4a"]
    assert [c["kind"] for c in found] == ["document", "document", "audio"]
    assert found[0]["size"] == 10 and found[0]["folder"] == "Downloads" and found[0]["path"].endswith("Регламент.docx")


def test_limit_and_size_cap(tmp_path, monkeypatch):
    root = tmp_path / "Documents"
    for i in range(60):
        make(str(root / f"note{i:02d}.txt"), mtime=1000 + i)
    found = discover.candidates([str(root)], AUDIO)
    assert len(found) == discover.LIMIT == 50 and found[0]["name"] == "note59.txt"
    monkeypatch.setattr(discover, "MAX_SIZE", 5)
    assert discover.candidates([str(root)], AUDIO) == []


def test_already_imported_files_are_left_out(tmp_path):
    root = tmp_path / "Desktop"
    make(str(root / "Регламент.docx"), size=10)
    make(str(root / "Другой.docx"), size=12)
    found = discover.candidates([str(root)], AUDIO, imported={("Регламент.docx", 10), ("Другой.docx", 99)})
    assert [c["name"] for c in found] == ["Другой.docx"]           # same name, other size: a different file


def test_roots_follow_the_env_override(tmp_path):
    assert discover.default_roots(home="/Users/a", env={}) == ["/Users/a/Downloads", "/Users/a/Documents", "/Users/a/Desktop"]
    env = {"DICTUM_DISCOVER_ROOTS": os.pathsep.join(["/x", "/y"])}
    assert discover.default_roots(env=env) == ["/x", "/y"]


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


def test_store_knows_imported_files_by_name_and_size(client, lib, tmp_path):
    pid = client.get("/api/projects").get_json()["current_project_id"]
    project = lib.get_project(pid)
    from core import materials
    materials.import_file(lib, project, "Регламент.md", "# Регламент\n\nТекст регламента".encode())
    src = lib.create_source(pid, "audio", "Звонок", original_filename="Звонок.m4a")
    make(os.path.join(lib.source_dir(src), "original.m4a"), size=7)
    assert lib.imported_files() == {("Регламент.md", len("# Регламент\n\nТекст регламента".encode())), ("Звонок.m4a", 7)}


def test_discover_route_and_import(client, app_module, lib, tmp_path, monkeypatch):
    root = tmp_path / "Downloads"
    call = make(str(root / "Звонок с дилером.wav"), size=64, mtime=2000)
    doc = str(root / "Регламент.md")
    os.makedirs(root, exist_ok=True)
    with open(doc, "w", encoding="utf-8") as f:
        f.write("# Регламент\n\nОтвет дилеру не позднее двух часов.")
    monkeypatch.setenv("DICTUM_DISCOVER_ROOTS", str(root))
    started = []
    monkeypatch.setattr(app_module, "_start_transcription",
                        lambda source, audio_path, opts: started.append((source["id"], audio_path, opts["model_name"])) or "job-1")
    monkeypatch.setattr(app_module, "_index_after", lambda *a, **k: None)

    body = client.get("/api/discover").get_json()
    assert [c["name"] for c in body["candidates"]] == ["Регламент.md", "Звонок с дилером.wav"]
    assert {c["kind"] for c in body["candidates"]} == {"audio", "document"}

    pid = client.get("/api/projects").get_json()["current_project_id"]
    r = client.post("/api/discover/import", json={"paths": [call, doc, str(root / "nope.txt")], "project_id": pid}).get_json()
    assert len(r["meetings"]) == 1 and r["meetings"][0]["job_id"] == "job-1" and len(r["materials"]) == 1
    assert r["failed"] == ["nope.txt: file not found"]
    meeting = lib.get_source(r["meetings"][0]["source_id"])
    assert meeting["kind"] == "audio" and meeting["title"] == "Звонок с дилером" and meeting["original_filename"] == "Звонок с дилером.wav"
    kept = os.path.join(lib.source_dir(meeting), "original.wav")
    assert started == [(meeting["id"], kept, "v3_e2e_rnnt")] and os.path.getsize(kept) == 64
    assert os.path.exists(call)                                   # the original stays where it was
    assert lib.get_material(r["materials"][0])["title"]

    # Imported now, so discovery no longer offers them.
    assert client.get("/api/discover").get_json()["candidates"] == []
    assert client.get("/api/discover?folder=" + str(tmp_path / "missing")).status_code == 400


def test_import_waits_for_a_running_speech_model_download(app_module, monkeypatch):
    busy = [True, True, False]
    progress = []
    monkeypatch.setattr(app_module.asr_downloads, "busy", lambda: busy.pop(0))
    monkeypatch.setattr(app_module, "set_progress", lambda job, pct, msg: progress.append(msg))
    app_module._wait_for_speech_model("j", poll=0)
    assert progress == ["Waiting for the speech model download…"] * 2
