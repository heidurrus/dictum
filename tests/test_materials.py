"""Материалы (5.0 C5, first half): import of each kind, the offline rule, listing filters, delete / undo, labels."""
import io
import os
import sqlite3
import zipfile

import pytest

from core import materials
from core.store import LABEL_COLORS, Store, StoreError

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


@pytest.fixture()
def pid(lib):
    return lib.ensure_default_project()["id"]


def make_docx(paragraphs):
    body = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in paragraphs)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><w:document '
           'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           f"<w:body>{body}</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


EML = (b"From: Anna <anna@example.com>\r\nTo: ba@example.com\r\nSubject: SLA for dealers\r\n"
       b"Content-Type: text/plain; charset=utf-8\r\n\r\nResponse within 4 hours.\r\n\r\nResolution within 2 days.\r\n")
RTF = (rb"{\rtf1\ansi\ansicpg1251{\fonttbl{\f0 Arial;}}\f0 \'cf\'f0\'e8\'e2\'e5\'f2 regulation\par "
       rb"Second \u1076?\u1072? paragraph\par}")
HTML = ("<html><head><title>Регламент</title><style>p{}</style></head><body><nav>Меню сайта</nav>"
        "<h1>Порядок</h1><p>Заявка   принимается\nв течение дня.</p><script>x()</script><ul><li>Пункт</li></ul></body></html>")


def upload(client, pid, name, data):
    return client.post(f"/api/projects/{pid}/materials", data={"files": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


@pytest.mark.parametrize("name, data, fmt, expect", [
    ("Регламент.docx", make_docx(["1. Общие положения", "", "Порядок приёма заявок"]), "docx",
     ["1. Общие положения", "Порядок приёма заявок"]),
    ("Схема.md", "# Схема\n\nПервый абзац\nпродолжение.\n\nВторой.".encode(), "md",
     ["# Схема", "Первый абзац продолжение.", "Второй."]),
    ("Заметки.txt", "Одна строка.".encode("cp1251"), "txt", ["Одна строка."]),
    ("Old.rtf", RTF, "rtf", ["Привет regulation", "Second да paragraph"]),
    ("Page.html", HTML.encode(), "html", ["Порядок", "Заявка принимается в течение дня.", "Пункт"]),
    ("Письмо.eml", EML, "eml", ["Response within 4 hours.", "Resolution within 2 days."]),
])
def test_import_each_file_type(client, lib, pid, name, data, fmt, expect):
    res = upload(client, pid, name, data)
    assert res.status_code == 200, res.get_json()
    [m] = res.get_json()["materials"]
    assert m["kind"] == "material" and m["material_kind"] == "file" and m["import_format"] == fmt
    assert m["status"] == "ready" and m["in_context"] is True and m["size"] == len(data)
    segs, _ = lib.transcript(m["id"])
    assert [s["text"] for s in segs] == expect
    assert all(s["start"] is None for s in segs) and [s["idx"] for s in segs] == list(range(len(expect)))
    # The bytes are copied to <data>/library/<project>/materials/<id>.<ext>
    ext = os.path.splitext(name)[1]
    assert m["path"] == os.path.join(lib.root, pid, "materials", m["id"] + ext)
    with open(m["path"], "rb") as f:
        assert f.read() == data
    if fmt == "eml":
        assert m["title"] == "SLA for dealers"
    if fmt == "html":
        assert m["title"] == "Регламент"


def test_import_pdf_and_the_original_stays_untouched(client, lib, pid, tmp_path):
    src = os.path.join(FIXTURES, "two_pages_footer.pdf")
    with open(src, "rb") as f:
        data = f.read()
    before = os.stat(src).st_mtime
    [m] = upload(client, pid, "two_pages_footer.pdf", data).get_json()["materials"]
    assert m["import_format"] == "pdf" and m["ext"] == "pdf"
    assert "caller card must open" in lib.get_material(m["id"])["text"]
    assert os.stat(src).st_mtime == before


def test_unsupported_and_empty_files_are_refused(client, pid):
    res = upload(client, pid, "song.mp3", b"ID3")
    assert res.status_code == 400 and "unsupported" in res.get_json()["error"]
    assert upload(client, pid, "empty.txt", b"  \n ").status_code == 400


def test_pasted_text_becomes_a_note(client, lib, pid):
    res = client.post(f"/api/projects/{pid}/materials", json={"text": "Первый.\n\nВторой абзац.", "title": "  Воркшоп  8 окт "})
    [m] = res.get_json()["materials"]
    assert m["material_kind"] == "note" and m["ext"] == "md" and m["title"] == "Воркшоп 8 окт"
    assert [s["text"] for s in lib.transcript(m["id"])[0]] == ["Первый.", "Второй абзац."]
    # without a title the first paragraph names it
    [m2] = client.post(f"/api/projects/{pid}/materials", json={"text": "Только текст"}).get_json()["materials"]
    assert m2["title"] == "Только текст"
    assert client.post(f"/api/projects/{pid}/materials", json={"text": "  "}).status_code == 400


class FakeResponse(io.BytesIO):
    def __init__(self, body, ctype="text/html; charset=utf-8"):
        super().__init__(body)
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_url_is_fetched_once_with_a_timeout_and_a_user_agent(client, lib, pid, monkeypatch):
    calls = []

    def opener(req, timeout):
        calls.append((req.full_url, req.get_header("User-agent"), timeout))
        return FakeResponse(HTML.encode())
    monkeypatch.setattr(materials.urllib.request, "urlopen", opener)
    res = client.post(f"/api/projects/{pid}/materials", json={"url": "https://wiki.example.com/portal"})
    [m] = res.get_json()["materials"]
    assert calls == [("https://wiki.example.com/portal", materials.USER_AGENT, 10)]
    assert m["material_kind"] == "url" and m["url"] == "https://wiki.example.com/portal" and m["ext"] == "url"
    assert m["title"] == "Регламент" and m["synced_at"] and m["error"] is None
    assert "Меню сайта" not in m["preview"] and "Заявка принимается в течение дня." in m["preview"]
    res = client.post(f"/api/materials/{m['id']}/resync")                 # fetches again
    assert res.status_code == 200 and len(calls) == 2
    note = materials.import_text(lib, lib.get_project(pid), "Заметка")
    assert client.post(f"/api/materials/{note['id']}/resync").status_code == 400


def test_url_fetch_failure_is_kept_as_the_error(client, lib, pid, monkeypatch):
    def boom(req, timeout):
        raise TimeoutError("timed out")
    monkeypatch.setattr(materials.urllib.request, "urlopen", boom)
    [m] = client.post(f"/api/projects/{pid}/materials", json={"url": "http://intranet/x"}).get_json()["materials"]
    assert m["error"] == "could not fetch the page (timed out)" and m["status"] == "ready" and m["title"] == "intranet/x"
    assert client.post(f"/api/projects/{pid}/materials", json={"url": "ftp://x"}).status_code == 400


def test_local_only_project_never_fetches_a_url(client, lib, monkeypatch):
    project = lib.create_project("Секретно", local_only=True)

    def no_network(*a, **k):
        raise AssertionError("a local-only project must not fetch")
    monkeypatch.setattr(materials.urllib.request, "urlopen", no_network)
    res = client.post(f"/api/projects/{project['id']}/materials", json={"url": "https://example.com/a"})
    [m] = res.get_json()["materials"]
    assert m["error"] == "offline" and m["url"] == "https://example.com/a" and m["synced_at"] is None
    res = client.post(f"/api/materials/{m['id']}/resync")
    assert res.status_code == 200 and res.get_json()["error"] == "offline"


def test_folder_import_is_a_job_skips_hidden_and_stops_at_the_limit(client, lib, pid, tmp_path, monkeypatch):
    folder = tmp_path / "docs"
    (folder / "sub").mkdir(parents=True)
    (folder / ".git").mkdir()
    (folder / "a.txt").write_text("Альфа")
    (folder / "sub" / "b.md").write_text("Бета")
    (folder / ".hidden.txt").write_text("скрыто")
    (folder / ".git" / "c.txt").write_text("служебное")
    (folder / "song.mp3").write_bytes(b"ID3")
    (folder / "bad.docx").write_bytes(b"not a zip")
    res = client.post(f"/api/projects/{pid}/materials", json={"folder": str(folder)})
    job_id = res.get_json()["job_id"]
    import time
    for _ in range(100):
        job = client.get(f"/job/{job_id}").get_json()
        if job["status"] != "processing":
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert len(job["result"]["imported"]) == 2 and len(job["result"]["failed"]) == 1
    assert sorted(m["title"] for m in lib.list_materials(pid)) == ["a", "b"]
    assert client.post(f"/api/projects/{pid}/materials", json={"folder": str(tmp_path / "nope")}).status_code == 400
    monkeypatch.setattr(materials, "FOLDER_LIMIT", 1)
    files, more = materials.folder_files(str(folder))
    assert len(files) == 1 and more


def test_listing_filters_and_sources_list_excludes_materials(client, lib, pid):
    note = client.post(f"/api/projects/{pid}/materials", json={"text": "Про SLA дилеров", "title": "SLA"}).get_json()["materials"][0]
    doc = upload(client, pid, "Схема.md", "Схема процесса".encode()).get_json()["materials"][0]
    meeting = client.post("/transcribe", data={"audio": (io.BytesIO("Просто текст встречи".encode()), "Встреча.txt")},
                          content_type="multipart/form-data").get_json()["source_id"]
    label = lib.create_label(pid, "процесс")
    lib.assign_label(doc["id"], label["id"])

    def titles(**q):
        return [m["title"] for m in client.get(f"/api/projects/{pid}/materials", query_string=q).get_json()["materials"]]
    assert titles() == ["Схема", "SLA"]
    assert titles(kind="note") == ["SLA"] and titles(kind="file") == ["Схема"] and titles(kind="url") == []
    assert titles(label=label["id"]) == ["Схема"]
    assert titles(q="дилер") == ["SLA"] and titles(q="схем") == ["Схема"]
    assert client.get(f"/api/projects/{pid}/materials?kind=video").status_code == 400
    rows = client.get(f"/api/projects/{pid}/materials").get_json()["materials"]
    assert rows[0]["labels"] == [{"id": label["id"], "name": "процесс", "color": LABEL_COLORS[0],
                                  "assigned_by": "user", "score": None}]
    assert "text" not in rows[0]
    # Встречи never shows materials; the status counts only meetings
    srcs = client.get(f"/api/projects/{pid}/sources").get_json()["sources"]
    assert [s["id"] for s in srcs] == [meeting]
    assert client.get(f"/api/projects/{pid}/status").get_json()["sources"] == 1
    assert note["id"] in {s["id"] for s in lib.list_sources(pid, include_materials=True)}


def test_get_patch_preview_and_in_context(client, lib, pid):
    long = "\n\n".join(f"Абзац {i} " + "слово " * 30 for i in range(20))
    m = client.post(f"/api/projects/{pid}/materials", json={"text": long, "title": "Длинный"}).get_json()["materials"][0]
    got = client.get(f"/api/materials/{m['id']}").get_json()
    assert len(got["preview"]) == 1200 and got["preview"] == lib.get_material(m["id"])["text"][:1200]
    assert "text" not in got and got["in_context"] is True and got["labels"] == []
    assert client.get(f"/api/materials/{m['id']}?full=1").get_json()["text"].startswith("Абзац 0")
    res = client.patch(f"/api/materials/{m['id']}", json={"in_context": False, "title": "Короче"})
    assert res.status_code == 200 and res.get_json()["in_context"] is False and res.get_json()["title"] == "Короче"
    assert client.patch(f"/api/materials/{m['id']}", json={"url": "x"}).status_code == 400
    assert client.get("/api/materials/nope").status_code == 404
    # a meeting is not a material
    sid = lib.create_source(pid, "document", "Док")["id"]
    assert client.get(f"/api/materials/{sid}").status_code == 404


def test_delete_and_undo_like_sources(client, lib, pid):
    m = client.post(f"/api/projects/{pid}/materials", json={"text": "Удаляемое"}).get_json()["materials"][0]
    assert client.delete(f"/api/materials/{m['id']}").status_code == 200
    assert client.get(f"/api/projects/{pid}/materials").get_json()["materials"] == []
    assert client.get(f"/api/materials/{m['id']}").status_code == 404
    assert os.path.exists(lib.db_path)
    assert client.post(f"/api/sources/{m['id']}/restore").status_code == 200      # the sources' undo path
    assert [x["id"] for x in client.get(f"/api/projects/{pid}/materials").get_json()["materials"]] == [m["id"]]
    client.delete(f"/api/materials/{m['id']}")
    assert client.post(f"/api/materials/{m['id']}/restore").status_code == 200
    assert client.delete("/api/materials/nope").status_code == 404


def test_extraction_reads_a_material_like_any_source(lib, pid):
    m = materials.import_text(lib, lib.get_project(pid), "Система должна открывать карточку.\n\nВторое.")
    assert lib.transcript_text(m["id"]) == "Система должна открывать карточку.\nВторое."


def test_labels_palette_assign_and_tombstone(client, lib, pid):
    names = [f"m{i}" for i in range(10)]
    colors = [client.post(f"/api/projects/{pid}/labels", json={"name": n}).get_json()["label"]["color"] for n in names]
    assert colors == list(LABEL_COLORS) + list(LABEL_COLORS[:2])
    assert client.post(f"/api/projects/{pid}/labels", json={"name": "M1"}).status_code == 400     # same name
    assert client.post(f"/api/projects/{pid}/labels", json={"name": " "}).status_code == 400
    m = client.post(f"/api/projects/{pid}/materials", json={"text": "Текст"}).get_json()["materials"][0]
    res = client.post(f"/api/projects/{pid}/labels", json={"name": "регламент", "seed_material_id": m["id"]}).get_json()
    lab = res["label"]
    assert res["assigned"] == [m["id"]] and lab["count"] == 1
    assert [x["name"] for x in client.get(f"/api/materials/{m['id']}").get_json()["labels"]] == ["регламент"]
    listed = {x["name"]: x["count"] for x in client.get(f"/api/projects/{pid}/labels").get_json()["labels"]}
    assert listed["регламент"] == 1 and listed["m0"] == 0
    # manual unassign deletes the row
    res = client.delete(f"/api/materials/{m['id']}/labels/{lab['id']}")
    assert res.status_code == 200 and res.get_json()["labels"] == []
    assert client.delete(f"/api/materials/{m['id']}/labels/{lab['id']}").status_code == 400
    # an automatic label leaves a tombstone, and auto never puts it back nor overrides a user's row
    assert lib.assign_label(m["id"], lab["id"], by="auto", score=0.72)
    assert client.get(f"/api/materials/{m['id']}").get_json()["labels"][0]["assigned_by"] == "auto"
    client.delete(f"/api/materials/{m['id']}/labels/{lab['id']}")
    with sqlite3.connect(lib.db_path) as c:
        assert c.execute("SELECT assigned_by FROM material_labels").fetchall() == [("removed",)]
    assert lib.assign_label(m["id"], lab["id"], by="auto") is False
    assert client.get(f"/api/materials/{m['id']}").get_json()["labels"] == []
    assert client.post(f"/api/materials/{m['id']}/labels/{lab['id']}").status_code == 200       # the BA can
    assert lib.assign_label(m["id"], lab["id"], by="auto") is False
    assert client.get(f"/api/materials/{m['id']}").get_json()["labels"][0]["assigned_by"] == "user"
    # deleting a label takes it off every material
    assert client.delete(f"/api/labels/{lab['id']}").status_code == 200
    assert client.get(f"/api/materials/{m['id']}").get_json()["labels"] == []
    assert client.delete(f"/api/labels/{lab['id']}").status_code == 404


def test_labels_stay_in_their_project(client, lib, pid):
    other = lib.create_project("Другой")
    lab = lib.create_label(other["id"], "чужая")
    m = materials.import_text(lib, lib.get_project(pid), "Текст")
    assert client.post(f"/api/materials/{m['id']}/labels/{lab['id']}").status_code == 400
    assert client.post(f"/api/projects/{other['id']}/labels", json={"name": "x", "seed_material_id": m["id"]}).status_code == 400
    with pytest.raises(StoreError):
        lib.assign_label(m["id"], lab["id"], by="sometimes")


def test_export_import_keeps_materials_and_labels(lib, pid, tmp_path):
    m = materials.import_text(lib, lib.get_project(pid), "Перенос", title="Перенос")
    lab = lib.create_label(pid, "перенос")
    lib.assign_label(m["id"], lab["id"])
    data = lib.export_project(pid)
    other = Store(root=str(tmp_path / "other"), user="ba")
    p2 = other.import_project(data)
    [got] = other.list_materials(p2["id"])
    assert got["title"] == "Перенос" and [x["name"] for x in got["labels"]] == ["перенос"]
    assert [h["id"] for h in other.search(p2["id"], "перенос")] == [m["id"]]
