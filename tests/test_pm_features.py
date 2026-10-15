"""Features added after the PM review (docs/product/pm-review.md)."""
import io
import zipfile

import pytest

from core import backlog, exports, frd, suggest
from core.store import Store, StoreError
from tests.test_backlog import decomposition
from tests.test_frd import PREFS, full_reply, llm, seed


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DICTUM_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture()
def store(tmp_path):
    return Store(root=str(tmp_path / "lib"), user="ba")


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    s = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", s)
    return s


def built(store):
    pid, ids, sid = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    return pid, ids, sid


# ── traceability, Markdown, follow-up, review import ─────────────────────────

def test_traceability_matrix_is_a_real_xlsx_with_quotes_and_stories(store):
    pid, ids, sid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    rows, version = exports.traceability_rows(store, pid)
    assert rows[0][0] == "ID" and version["number"] == 1
    fr1 = next(r for r in rows if r[0] == "FR-1")
    assert fr1[6] == "карточка клиента" and fr1[7] == "Созвон" and "Карточка при звонке" in fr1[10]
    z = zipfile.ZipFile(io.BytesIO(exports.xlsx(rows)))
    assert "xl/worksheets/sheet1.xml" in z.namelist() and "FR-1" in z.read("xl/worksheets/sheet1.xml").decode()


def test_markdown_export(store):
    pid, ids, sid = built(store)
    doc = store.document(pid)
    md = exports.markdown(doc, store.version(doc["id"]), store.free_blocks(doc["id"]))
    assert md.startswith("# ") and "**FR-1**" in md and "## " in md


def test_followup_lists_open_questions_conflicts_and_actions(store):
    pid, ids, sid = seed(store, accept=False)
    store.add_actions(pid, sid, [{"text": "Прислать макеты", "owner": "Иван", "due": "пятница"}])
    cid = store.add_conflict(pid, ids[0], ids[2], "Что главнее?")
    q = store.resolve_conflict(cid, "question")["question_atom"]
    f = exports.followup(store, pid)
    assert "Кто переносит архив обращений?" in f["text"] and "Прислать макеты (Иван, срок: пятница)" in f["text"]
    assert "или" in f["text"] and q in f["question_ids"] and f["actions"] == 1
    store.answer_question(q, "Карточка")
    assert q not in exports.followup(store, pid)["question_ids"], "answered questions leave the letter"


def _docx_with_comment(text="FR-2. Система должна маскировать номер карты.", comment="Только последние 4 цифры"):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    doc = (f'<w:document {w}><w:body><w:p><w:r><w:t>Раздел 3</w:t></w:r></w:p>'
           f'<w:p><w:commentRangeStart w:id="0"/><w:r><w:t>{text}</w:t></w:r><w:commentRangeEnd w:id="0"/>'
           f'<w:r><w:commentReference w:id="0"/></w:r></w:p></w:body></w:document>')
    com = f'<w:comments {w}><w:comment w:id="0" w:author="Заказчик"><w:p><w:r><w:t>{comment}</w:t></w:r></w:p></w:comment></w:comments>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc)
        z.writestr("word/comments.xml", com)
    return buf.getvalue()


def test_review_comments_come_back_as_a_source_tied_to_requirements(client, lib):
    pid, ids, sid = built(lib)
    doc = lib.document(pid)
    assert exports.docx_comments(_docx_with_comment()) == [
        ("FR-2", "Заказчик", "Только последние 4 цифры", "FR-2. Система должна маскировать номер карты.")]
    r = client.post(f"/api/documents/{doc['id']}/review",
                    data={"file": (io.BytesIO(_docx_with_comment()), "FRD v1 (заказчик).docx")},
                    content_type="multipart/form-data").get_json()
    assert r["comments"] == 1 and r["linked"] == 1
    segs, _ = lib.transcript(r["source_id"])
    assert segs[0]["text"].startswith("[FR-2] Только последние 4 цифры") and segs[0]["speaker"] == "Заказчик"


# ── sign-off, change requests ────────────────────────────────────────────────

def test_approved_version_is_the_baseline_for_change_requests(client, lib):
    pid, ids, sid = built(lib)
    doc = lib.document(pid)
    r = client.post(f"/api/documents/{doc['id']}/versions/1/status", json={"status": "approved"}).get_json()
    assert r["baseline"] == 1 and r["versions"][0]["status"] == "approved"
    assert client.post(f"/api/documents/{doc['id']}/versions/1/status", json={"status": "signed"}).status_code == 400
    lib.update_atom(ids[2], statement="Маскировать номер карты, кроме последних 4 цифр")
    reply = full_reply()
    reply["items"] = [dict(i, text="Система должна маскировать номер карты, кроме последних 4 цифр.")
                      if i["id"] == "FR-2" else i for i in reply["items"]]
    frd.build(lib, pid, PREFS, "k", mode="full", complete=llm(reply))
    ch = client.get(f"/api/documents/{doc['id']}/changes").get_json()
    assert ch["baseline"] == 1 and ch["to"] == 2 and [c["id"] for c in ch["changes"]] == ["FR-2"]


# ── transcript corrections and highlights ────────────────────────────────────

def test_correcting_a_segment_keeps_the_original_and_flags_broken_quotes(client, lib):
    pid, ids, sid = seed(lib)
    body = client.get(f"/api/sources/{sid}").get_json()
    assert body["atom_marks"]["0"][0]["atom_id"] == ids[0]
    r = client.patch(f"/api/sources/{sid}/segments/0", json={"text": "карточка покупателя при звонке"}).get_json()
    assert r["broken"] == [ids[0]], "the quote «карточка клиента» is no longer in the line"
    seg = client.get(f"/api/sources/{sid}").get_json()["segments"][0]
    assert seg["corrected"] and seg["text"] == "карточка покупателя при звонке"
    assert any(e["action"] == "edit_segment" for e in lib.audit("source", sid))
    with pytest.raises(StoreError):
        lib.edit_segment(sid, 0, "  ")


# ── steer by review ──────────────────────────────────────────────────────────

def test_repeated_rejections_suggest_a_rule_that_goes_into_the_projects_own_skill(store):
    pid, ids, sid = seed(store, accept=False)
    for i in range(5):
        a = store.add_ba_atom(pid, "functional", f"Созвон по процессу номер {i}")
        store.update_atom(a["id"], status="rejected", reject_reason="not_requirement")
    [s] = suggest.suggestions(store, pid)
    assert s["count"] == 5 and "Созвон по процессу номер 0" in s["rule"]
    name = suggest.apply(store, pid, s["rule"])
    assert store.project_skills(pid)["extract"] == name
    from core import skills
    assert "Созвон по процессу номер 0" in skills.get(name).instructions


# ── activity, project file ───────────────────────────────────────────────────

def test_activity_feed_and_project_round_trip(client, lib, tmp_path, monkeypatch):
    pid, ids, sid = built(lib)
    lib.add_actions(pid, sid, [{"text": "Прислать макеты"}])
    feed = client.get(f"/api/projects/{pid}/activity").get_json()["entries"]
    assert {"accepted", "build"} <= {e["action"] for e in feed}
    data = client.get(f"/api/projects/{pid}/export.zip").data
    assert client.post("/api/projects/import", data={"file": (io.BytesIO(data), "p.zip")},
                       content_type="multipart/form-data").status_code == 400, "already in the library"
    other = Store(root=str(tmp_path / "other"), user="ba")
    import app as app_module
    monkeypatch.setattr(app_module, "library", other)
    r = client.post("/api/projects/import", data={"file": (io.BytesIO(data), "p.zip")}, content_type="multipart/form-data")
    assert r.status_code == 200
    assert len(other.list_atoms(pid)) == 4 and other.version(other.document(pid)["id"])["number"] == 1
    assert other.list_actions(pid)[0]["text"] == "Прислать макеты"


def test_status_flows_downstream_and_counts_open_items(client, lib):
    pid, ids, sid = built(lib)
    lib.add_actions(pid, sid, [{"text": "Прислать макеты"}])
    st = client.get(f"/api/projects/{pid}/status").get_json()
    assert st["open_items"] == {"questions": 1, "actions": 1} and not st["document"]["stale"]
    lib.update_atom(ids[0], statement="Открывать карточку клиента до ответа на звонок")
    st = client.get(f"/api/projects/{pid}/status").get_json()
    assert st["document"]["stale"] and st["document"]["changed"] == 1


def test_documents_api_lists_types_creates_and_switches_type(client, lib):
    pid, ids, sid = seed(lib)
    body = client.get(f"/api/projects/{pid}/documents?lang=en").get_json()
    names = {t["name"] for t in body["types"]}
    assert {"write-frd", "write-brd", "write-vision-scope", "write-risk-register", "write-as-is-to-be"} <= names
    assert next(t for t in body["types"] if t["name"] == "write-brd")["title"] == "BRD — business requirements"
    risk = next(t for t in body["types"] if t["name"] == "write-risk-register")
    assert risk["atom_types"] == ["risk", "question"] and not risk["decomposes"]
    assert next(t for t in body["types"] if t["name"] == "write-frd")["decomposes"]
    d = client.post(f"/api/projects/{pid}/documents?lang=ru", json={"kind": "write-vision-scope"}).get_json()
    assert d["short"] == "Vision & Scope" and d["title"].startswith("Vision & Scope — ")
    assert client.post(f"/api/projects/{pid}/documents", json={"kind": "extract-requirements"}).status_code == 400
    assert len(client.get(f"/api/projects/{pid}/documents").get_json()["documents"]) == 2
    got = client.get(f"/api/projects/{pid}/document?document={d['id']}").get_json()
    assert got["document"]["kind"] == "write-vision-scope"
    client.patch(f"/api/documents/{d['id']}", json={"kind": "write-brd"})
    assert client.get(f"/api/projects/{pid}/document?document={d['id']}").get_json()["document"]["kind"] == "write-brd"
    first = client.get(f"/api/projects/{pid}/documents").get_json()["documents"][0]
    assert client.delete(f"/api/documents/{first['id']}").status_code == 200, "any document can go…"
    assert client.delete(f"/api/documents/{d['id']}").status_code == 400, "…as long as one stays"
    assert client.patch(f"/api/documents/{d['id']}", json={"decompose": True}).get_json()["decompose"] == 1


def test_skills_come_in_the_interface_language(client, lib):
    en = {s["name"]: s["title"] for s in client.get("/api/skills?lang=en").get_json()["skills"]}
    ru = {s["name"]: s["title"] for s in client.get("/api/skills?lang=ru").get_json()["skills"]}
    assert en["extract-requirements"] == "Requirement extraction" and ru["extract-requirements"] == "Извлечение требований"
    one = client.get("/api/skills/house-rules?lang=en").get_json()
    assert one["title"] == "House rules" and one["description"].startswith("Rules added")
