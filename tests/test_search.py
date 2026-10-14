"""Keyword search (5.0 C5): one FTS5 index over meeting lines, notes, materials and atoms."""
import io
import sqlite3

import pytest

from core import materials
from core.store import SNIPPET_CLOSE, SNIPPET_OPEN, Store


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


@pytest.fixture()
def pid(lib):
    return lib.ensure_default_project()["id"]


def meeting(lib, pid, title, *lines):
    sid = lib.create_source(pid, "transcript", title)["id"]
    lib.save_transcript(sid, {"text": " ".join(lines),
                              "segments": [{"speaker": "SPEAKER_00", "start": float(i), "end": i + 1.0, "text": t}
                                           for i, t in enumerate(lines)]})
    return sid


def hits(client, pid, q):
    return client.get(f"/api/projects/{pid}/search", query_string={"q": q}).get_json()["hits"]


def test_search_spans_a_meeting_line_a_note_and_a_material(client, lib, pid):
    sid = meeting(lib, pid, "Звонок с дилером", "Добрый день", "Заявки дилеров приходят по почте")
    lib.update_notes(sid, lambda _: "- спросить про заявки на гарантию")
    m = materials.import_text(lib, lib.get_project(pid), "Регламент: заявки дилеров v2", title="Регламент")
    got = hits(client, pid, "заявк")
    by = {h["entity"]: h for h in got}
    assert set(by) == {"segment", "note", "material"}
    seg = by["segment"]
    assert seg["source_id"] == sid and seg["idx"] == 1 and seg["start"] == 1.0 and seg["title"] == "Звонок с дилером"
    assert SNIPPET_OPEN + "Заявки" + SNIPPET_CLOSE in seg["snippet"]
    assert by["note"]["id"] == sid and by["note"]["source_id"] == sid
    assert by["material"]["id"] == m["id"] and by["material"]["ext"] == "md" and by["material"]["material_kind"] == "note"
    # every word must match, each as a prefix; case and script do not matter
    assert {h["entity"] for h in hits(client, pid, "ДИЛЕР почт")} == {"segment"}
    assert hits(client, pid, "нет-такого") == []
    assert hits(client, pid, "   ") == []
    assert len(hits(client, pid, '"заявки* (')) == 3                  # FTS syntax in the query is just words
    assert hits(client, pid, "заявки OR почта") == []                  # "or" is a word to find, not an operator


def test_material_lines_are_one_material_hit_not_segments(client, lib, pid):
    materials.import_text(lib, lib.get_project(pid), "Первый абзац про SLA.\n\nВторой абзац про SLA.", title="SLA")
    got = hits(client, pid, "sla")
    assert [h["entity"] for h in got] == ["material"]


def test_atoms_are_found_and_follow_edits(client, lib, pid):
    sid = meeting(lib, pid, "Встреча", "Карточка клиента должна открываться быстро")
    [aid] = lib.add_atoms(pid, [{"type": "functional", "statement": "Карточка открывается за 2 секунды",
                                 "evidence": [{"source_id": sid, "segment_idx": 0, "quote": "Карточка клиента"}]}])
    h = [x for x in hits(client, pid, "секунд") if x["entity"] == "atom"]
    assert h and h[0]["id"] == aid and h[0]["type"] == "functional"
    lib.update_atom(aid, statement="Карточка открывается мгновенно")
    assert hits(client, pid, "секунд") == []
    assert [x["id"] for x in hits(client, pid, "мгновенно")] == [aid]
    ba = lib.add_ba_atom(pid, "question", "Кто утверждает статус?")
    assert [x["id"] for x in hits(client, pid, "утверждает")] == [ba["id"]]
    lib.answer_question(ba["id"], "Руководитель отдела")
    assert [x["id"] for x in hits(client, pid, "руководитель")] == [ba["id"]]
    lib.delete_atoms(pid, [aid])
    assert hits(client, pid, "мгновенно") == []


def test_deleted_sources_drop_out_and_come_back(client, lib, pid):
    sid = meeting(lib, pid, "Встреча", "Экспорт в Excel")
    lib.delete_source(sid)
    assert hits(client, pid, "excel") == []
    lib.restore_source(sid)
    assert len(hits(client, pid, "excel")) == 1


def test_edits_and_retranscription_reindex(client, lib, pid):
    sid = meeting(lib, pid, "Встреча", "Старое слово")
    lib.edit_segment(sid, 0, "Новое слово")
    assert hits(client, pid, "старое") == [] and len(hits(client, pid, "новое")) == 1
    lib.save_transcript(sid, {"segments": [{"text": "Совсем другое"}]})
    assert hits(client, pid, "новое") == [] and len(hits(client, pid, "другое")) == 1
    m = materials.import_text(lib, lib.get_project(pid), "Текст", title="Заголовок")
    lib.update_material(m["id"], title="Переименован")
    assert hits(client, pid, "заголовок") == [] and hits(client, pid, "переименован")[0]["id"] == m["id"]


def test_projects_do_not_see_each_other(client, lib, pid):
    other = lib.create_project("Другой")
    meeting(lib, other["id"], "Чужая", "Секретный проект")
    assert hits(client, pid, "секретный") == []
    assert len(hits(client, other["id"], "секретный")) == 1
    assert client.get("/api/projects/nope/search?q=x").status_code == 404


def test_migration_backfills_an_older_database(tmp_path):
    lib = Store(root=str(tmp_path / "lib"), user="ba")
    pid = lib.ensure_default_project()["id"]
    sid = meeting(lib, pid, "Встреча", "Ранняя запись про склад")
    lib.update_notes(sid, lambda _: "заметка про склад")
    [aid] = lib.add_atoms(pid, [{"type": "risk", "statement": "Склад может не успеть",
                                 "evidence": [{"source_id": sid, "segment_idx": 0, "quote": "склад"}]}])
    with sqlite3.connect(lib.db_path) as c:              # a v9 database from before the index
        c.execute("DROP TABLE search")
    again = Store(root=str(tmp_path / "lib"), user="ba")
    assert sorted(h["entity"] for h in again.search(pid, "склад")) == ["atom", "note", "segment"]
    Store(root=str(tmp_path / "lib"), user="ba")         # idempotent: a second start does not index twice
    assert len(again.search(pid, "склад")) == 3


def test_search_limit(client, lib, pid):
    meeting(lib, pid, "Много", *[f"строка про отчёт {i}" for i in range(40)])
    assert len(hits(client, pid, "отчёт")) == 30
    assert len(client.get(f"/api/projects/{pid}/search?q=отчёт&limit=5").get_json()["hits"]) == 5
    assert client.get(f"/api/projects/{pid}/search?q=x&limit=abc").status_code == 400


def test_upload_of_a_text_source_is_searchable(client, lib, pid):
    client.post("/transcribe", data={"audio": (io.BytesIO("Письмо про интеграцию с 1С".encode()), "Письмо.txt"),
                                     "project_id": pid}, content_type="multipart/form-data")
    assert [h["entity"] for h in hits(client, pid, "интеграц")] == ["segment"]
