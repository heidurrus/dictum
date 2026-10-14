"""GET /api/projects/<id>/sources: search, sort and the Встречи row fields (people, atoms, tags)."""
import io

import pytest

from core.store import Store


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


def upload(client, name, body):
    data = {"audio": (io.BytesIO(body.encode()), name)}
    return client.post("/transcribe", data=data, content_type="multipart/form-data").get_json()["source_id"]


def vtt(*lines):
    cues = [f"00:00:{2 * i + 1:02d}.000 --> 00:00:{2 * i + 2:02d}.000\n<v {spk}>{text}</v>\n" for i, (spk, text) in enumerate(lines)]
    return "WEBVTT\n\n" + "\n".join(cues)


def listing(client, **params):
    pid = client.get("/api/projects").get_json()["current_project_id"]
    return client.get(f"/api/projects/{pid}/sources", query_string=params)


def titles(client, **params):
    return [s["title"] for s in listing(client, **params).get_json()["sources"]]


def test_search_finds_a_word_that_only_exists_in_a_segment(client, lib):
    upload(client, "Созвон по карточке.vtt", vtt(("SPEAKER_00", "Добрый день"), ("SPEAKER_01", "Нужен ЭКСПОРТ в Excel")))
    upload(client, "Письмо.txt", "Просим ускорить карточку клиента.")
    assert titles(client, q="экспорт") == ["Созвон по карточке"]      # case-insensitive, Cyrillic
    assert titles(client, q="ускорить") == ["Письмо"]                  # the source text of a document
    assert titles(client, q="созвон") == ["Созвон по карточке"]        # the title
    assert sorted(titles(client, q="карточк")) == ["Письмо", "Созвон по карточке"]
    assert titles(client, q="нет такого слова") == []
    assert len(titles(client, q="  ")) == 2                            # blank: everything


def test_sort_orders(client, lib):
    for name in ("Бета.txt", "альфа.txt", "Гамма.txt"):
        upload(client, name, "текст " + name)
    assert titles(client) == ["Гамма", "альфа", "Бета"]                # newest first by default
    assert titles(client, sort="new") == ["Гамма", "альфа", "Бета"]
    assert titles(client, sort="old") == ["Бета", "альфа", "Гамма"]
    assert titles(client, sort="az") == ["альфа", "Бета", "Гамма"]     # case-insensitive in any script
    assert listing(client, sort="size").status_code == 400


def test_people_atoms_and_tags(client, lib):
    sid = upload(client, "Встреча.vtt", vtt(("SPEAKER_00", "Привет"), ("SPEAKER_01", "Карточка за две секунды"),
                                             ("SPEAKER_02", "Да"), ("SPEAKER_03", "Нет"), ("SPEAKER_04", "Может быть")))
    doc = upload(client, "Заметки.txt", "Просто текст без спикеров.")
    lib.rename_speaker(sid, "SPEAKER_03", "Ирина")
    lib.rename_speaker(sid, "SPEAKER_01", "Олег")
    pid = lib.current_project()["id"]
    a, b, c = lib.add_atoms(pid, [
        {"type": "nfr", "statement": "2 секунды", "evidence": [{"source_id": sid, "segment_idx": 1, "quote": "две секунды"}]},
        {"type": "functional", "statement": "Карточка", "evidence": [{"source_id": sid, "segment_idx": 1, "quote": "Карточка"}]},
        {"type": "question", "statement": "Может?", "evidence": [{"source_id": sid, "segment_idx": 4, "quote": "Может"}]}])
    lib.update_atom(c, status="rejected")

    rows = {s["id"]: s for s in listing(client).get_json()["sources"]}
    meet = rows[sid]
    assert meet["people"] == "Олег, Ирина, SPEAKER_00, SPEAKER_02"      # renamed first, at most 4
    assert meet["atoms"] == 2                                            # the rejected one is not counted
    assert meet["atom_count"] == 3 and meet["title"] == "Встреча"       # what the list returned before stays
    assert meet["tags"] == "import"                                      # a timed Teams/Zoom transcript
    assert rows[doc]["tags"] == "text" and rows[doc]["people"] == "" and rows[doc]["atoms"] == 0


def test_source_tag_mapping():
    tag = Store.source_tag
    assert tag("recording", None) == "recording"
    assert tag("audio", None) == "import"
    assert tag("transcript", "srt") == "import"
    assert tag("transcript", "txt") == "text"
    assert tag("document", "docx") == "text" and tag("email", "eml") == "text"
