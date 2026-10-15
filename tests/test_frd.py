import io
import re
import zipfile

import pytest

from core import docx_export, frd
from core.desktop_api import DesktopApi
from core.store import Store
from tests.test_recorder import wait_for

PREFS = {"llm_provider": "claude", "claude_model": "claude-opus-5", "local_model": ""}


@pytest.fixture()
def store(tmp_path):
    return Store(root=str(tmp_path / "lib"), user="ba")


def seed(store, accept=True):
    pid = store.current_project()["id"]
    src = store.create_source(pid, "recording", "Созвон")
    store.save_transcript(src["id"], {"segments": [
        {"speaker": "SPEAKER_01", "start": i * 10.0, "end": i * 10 + 8, "text": t} for i, t in enumerate(
            ["карточка клиента при звонке", "открывается быстро", "маскировать номер карты", "кто переносит архив"])]})
    ev = lambda i, q: [{"source_id": src["id"], "segment_idx": i, "start": i * 10.0, "speaker": "SPEAKER_01", "quote": q}]
    ids = store.add_atoms(pid, [
        {"type": "functional", "statement": "Открывать карточку клиента при звонке", "evidence": ev(0, "карточка клиента")},
        {"type": "nfr", "statement": "Карточка открывается быстро", "evidence": ev(1, "открывается быстро")},
        {"type": "functional", "statement": "Маскировать номер карты", "evidence": ev(2, "маскировать номер")},
        {"type": "question", "statement": "Кто переносит архив обращений?", "evidence": ev(3, "кто переносит")}])
    if accept:
        for i in ids:
            store.update_atom(i, status="accepted")
    return pid, ids, src["id"]


def full_reply(groups=None, drop=()):
    items = {"FR-1": "Система должна открывать карточку клиента при входящем звонке.",
             "FR-2": "Система должна маскировать номер карты.",
             "NFR-1": "Карточка должна открываться быстро.",
             "Q-1": "Кто отвечает за перенос архива обращений?"}
    return {"purpose": "Документ описывает карточку клиента.", "context": "Операторы не видят историю.",
            "assumptions": ["Номер звонящего известен."],
            "groups": groups if groups is not None else [{"title": "Карточка", "ids": ["FR-1"]}, {"title": "Безопасность", "ids": ["FR-2"]}],
            "items": [{"id": k, "text": v} for k, v in items.items() if k not in drop],
            "out_of_scope": [], "issues": [{"id": "NFR-1", "rule": "not_measurable", "message": "Нет времени."},
                                            {"id": "FR-9", "rule": "vague", "message": "unknown id"}]}


def llm(*replies):
    calls, queue = [], list(replies)

    def complete(system, user, schema, prefs, api_key):
        calls.append({"system": system, "user": user, "schema": schema})
        return queue.pop(0)
    complete.calls = calls
    return complete


def blocks(store, pid, number=None):
    v = store.version(store.document(pid)["id"], number)
    return {b["id"]: (num, b) for num, _k, b in frd.req_blocks(v["content"])}, v


# ── building ─────────────────────────────────────────────────────────────────

def test_full_build_structure_ids_sources_and_quality(store):
    pid, ids, sid = seed(store)
    r = frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    assert (r["version"], r["atoms"], r["mode"]) == (1, 4, "full")
    by_id, v = blocks(store, pid)
    assert {k: n for k, (n, _b) in by_id.items()} == {"FR-1": "3.1", "FR-2": "3.2", "NFR-1": "4", "Q-1": "6"}
    fr1 = by_id["FR-1"][1]
    assert fr1["atom_id"] == ids[0] and fr1["sources"][0]["source_id"] == sid and fr1["sources"][0]["quote"] == "карточка клиента"
    assert [s["title"] for s in v["content"]["sections"]][:2] == ["Назначение документа", "Контекст и допущения"]
    assert {i["rule"] for i in by_id["NFR-1"][1]["issues"]} == {"not_measurable", "vague"}   # model + rule "быстро"
    assert v["content"]["language"] == "ru"


def test_the_model_cannot_drop_or_invent_requirements(store):
    pid, *_ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply(groups=[{"title": "A", "ids": ["FR-1", "FR-77"]}], drop=("FR-2",))))
    by_id, v = blocks(store, pid)
    assert by_id["FR-2"][1]["text"] == "Маскировать номер карты"          # fell back to the atom's own words
    functional = v["content"]["sections"][2]
    assert [s["title"] for s in functional["subsections"]] == ["A", "Прочее"] and "FR-77" not in by_id


def test_ids_are_stable_and_never_reused(store):
    pid, ids, _ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    store.update_atom(ids[0], status="rejected")
    extra = store.add_atoms(pid, [{"type": "functional", "statement": "Новое требование",
                                   "evidence": [{"source_id": store.list_sources(pid)[0]["id"], "quote": "карточка"}]}])[0]
    store.update_atom(extra, status="accepted")
    rids = store.requirement_ids(pid, store.list_atoms(pid, status="accepted"))
    assert rids[ids[2]] == "FR-2" and rids[extra] == "FR-3", "FR-1 belonged to the rejected atom and is not reused"


def test_rebuild_rewrites_only_what_changed(store):
    pid, ids, _ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    store.update_atom(ids[1], statement="Карточка открывается не дольше 2 секунд")
    changed = llm({"items": [{"id": "NFR-1", "text": "Карточка клиента должна открываться не дольше 2 секунд.", "group": ""}],
                   "issues": []})
    r = frd.build(store, pid, PREFS, "k", mode="changed", complete=changed)
    assert r["mode"] == "changed" and r["version"] == 2
    to_write = changed.calls[0]["user"].split("To write:")[1]
    assert "NFR-1 [nfr]" in to_write and not re.search(r"(?<![A-Z])FR-\d", to_write)
    new, _ = blocks(store, pid)
    old, _ = blocks(store, pid, 1)
    assert new["FR-1"][1]["text"] == old["FR-1"][1]["text"] and new["FR-1"][0] == "3.1"   # untouched, same place
    assert new["NFR-1"][1]["text"].endswith("2 секунд.") and new["NFR-1"][1]["issues"] == []


def test_rebuild_places_a_new_requirement_in_a_group(store):
    pid, ids, _ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    new_atom = store.add_atoms(pid, [{"type": "functional", "statement": "Показывать последние заказы",
                                      "evidence": [{"source_id": store.list_sources(pid)[0]["id"], "quote": "карточка"}]}])[0]
    store.update_atom(new_atom, status="accepted")
    frd.build(store, pid, PREFS, "k", complete=llm(
        {"items": [{"id": "FR-3", "text": "Система должна показывать последние заказы.", "group": "Карточка"}], "issues": []}))
    by_id, _ = blocks(store, pid)
    assert by_id["FR-3"][0] == "3.1"


def test_rebuild_with_nothing_changed_is_refused(store):
    pid, *_ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    with pytest.raises(frd.BuildError, match="up to date"):
        frd.build(store, pid, PREFS, "k", complete=llm())


def test_removed_atom_leaves_the_document_without_an_llm_call(store):
    pid, ids, _ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    store.update_atom(ids[2], status="rejected")
    no_calls = llm()
    frd.build(store, pid, PREFS, "k", complete=no_calls)
    by_id, v = blocks(store, pid)
    assert "FR-2" not in by_id and no_calls.calls == []
    assert [s["title"] for s in v["content"]["sections"][2]["subsections"]] == ["Карточка"]


def test_no_accepted_atoms_refuses_to_build(store):
    pid, *_ = seed(store, accept=False)
    with pytest.raises(frd.BuildError, match="Review the atoms"):
        frd.build(store, pid, PREFS, "k", complete=llm())


def test_staleness_per_section_and_diff(store):
    pid, ids, _ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    doc = store.document(pid)
    assert frd.staleness(store, pid, store.version(doc["id"]))["stale"] is False
    store.update_atom(ids[2], statement="Маскировать номер карты, кроме 4 последних цифр")
    st = frd.staleness(store, pid, store.version(doc["id"]))
    assert st["stale"] and st["changed"] == 1 and st["sections"] == {"3.2": 1}
    frd.build(store, pid, PREFS, "k", complete=llm({"items": [{"id": "FR-2", "text": "Система должна маскировать номер карты, кроме последних 4 цифр.", "group": "Безопасность"}], "issues": []}))
    changes = frd.diff(store.version(doc["id"], 1), store.version(doc["id"], 2))
    assert [(c["id"], c["change"]) for c in changes] == [("FR-2", "changed")]


def test_conflicting_atoms_are_marked(store):
    pid, ids, _ = seed(store)
    store.add_conflict(pid, ids[0], ids[2], "Противоречие")
    r = frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    by_id, _ = blocks(store, pid)
    assert r["conflicts"] == 2 and by_id["FR-1"][1]["conflict"] == "Противоречие"


@pytest.mark.parametrize("text,kind,rules", [
    ("Карточка открывается быстро", "nfr", {"vague", "not_measurable"}),
    ("Карточка открывается не дольше 2 секунд", "nfr", set()),
    ("Интерфейс должен быть удобным", "functional", {"vague"}),
    ("Ответ не позднее пяти минут", "nfr", set()),
    ("Доступ только у операторов первой линии", "nfr", set()),     # access rule: no number needed
    ("Система должна выдерживать высокую нагрузку", "nfr", {"not_measurable"}),
])
def test_rule_checks(text, kind, rules):
    assert {i["rule"] for i in frd.rule_checks(text, kind, "ru")} == rules


def test_fix_suggestion(store):
    pid, ids, _ = seed(store)
    fake = llm({"statement": "Карточка открывается не дольше [уточнить: N секунд]"})
    r = frd.suggest_fix(store, pid, ids[1], "not_measurable", "Нет времени.", PREFS, "k", complete=fake)
    assert "[уточнить" in r["statement"] and "Карточка открывается быстро" in fake.calls[0]["user"]


# ── export ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("template", ["neutral", "gost"])
def test_docx_has_sections_footnotes_and_free_text(store, template):
    pid, *_ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    doc = store.document(pid)
    store.add_free_block(doc["id"], "purpose", "Согласовано с заказчиком.")
    data = docx_export.render(doc, store.version(doc["id"]), store.free_blocks(doc["id"]),
                              template=docx_export.starter(template), numbering="plain" if template == "gost" else "dot")
    z = zipfile.ZipFile(io.BytesIO(data))
    body = z.read("word/document.xml").decode()
    notes = z.read("word/footnotes.xml").decode()
    assert "Согласовано с заказчиком." in body and "FR-1." in body and "Функциональные требования" in body
    refs = set(re.findall(r'footnoteReference w:id="(\d+)"', body))
    assert refs == set(re.findall(r'<w:footnote w:id="(\d+)"', notes)) and len(refs) == 4
    assert "«карточка клиента»" in notes and "00:00" in notes
    assert "footnotes+xml" in z.read("[Content_Types].xml").decode()
    assert "TOC \\o" in body
    if template == "gost":
        assert "Times New Roman" in z.read("word/styles.xml").decode() and "ФУНКЦИОНАЛЬНЫЕ ТРЕБОВАНИЯ" in body
    import docx
    docx.Document(io.BytesIO(data))                 # reopens cleanly


def test_plural_in_export_meta():
    assert docx_export._plural(4, ("требование", "требования", "требований"), "ru") == "требования"
    assert docx_export._plural(11, ("требование", "требования", "требований"), "ru") == "требований"
    assert docx_export._plural(21, ("требование", "требования", "требований"), "ru") == "требование"


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    s = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", s)
    monkeypatch.setattr(app_module.settings, "load_settings", lambda: dict(PREFS))
    monkeypatch.setattr(app_module.settings, "secret", lambda name: "key")
    return s


def test_api_build_view_export_free_blocks_and_findings(client, app_module, lib, monkeypatch):
    pid, ids, _ = seed(lib)
    fake = llm(full_reply(), {"statement": "Карточка открывается не дольше [уточнить: N секунд]"})
    monkeypatch.setattr(app_module.frd, "complete_json", fake)
    real_build, real_fix = frd.build, frd.suggest_fix
    monkeypatch.setattr(app_module.frd, "build", lambda *a, **k: real_build(*a, **k, complete=fake))
    monkeypatch.setattr(app_module.frd, "suggest_fix", lambda *a, **k: real_fix(*a, **k, complete=fake))

    body = client.get(f"/api/projects/{pid}/document").get_json()
    assert body["version"] is None and body["stats"]["accepted"] == 4
    job = client.post(f"/api/projects/{pid}/document/build", json={"mode": "full"}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    body = client.get(f"/api/projects/{pid}/document").get_json()
    doc_id = body["document"]["id"]
    assert body["version"]["number"] == 1 and body["stale"]["stale"] is False and "snapshot" not in body["version"]

    r = client.get(f"/api/documents/{doc_id}/export.docx?template=gost")
    assert r.status_code == 200 and r.data[:2] == b"PK" and "v1.docx" in r.headers["Content-Disposition"]

    fb = client.post(f"/api/documents/{doc_id}/free-blocks", json={"section": "purpose", "text": "Моё"}).get_json()
    assert client.patch(f"/api/free-blocks/{fb['id']}", json={"text": "Моё, исправлено"}).status_code == 200
    assert client.delete(f"/api/free-blocks/{fb['id']}").status_code == 200
    assert client.post(f"/api/free-blocks/{fb['id']}/restore").status_code == 200
    assert [f["text"] for f in client.get(f"/api/projects/{pid}/document").get_json()["free_blocks"]] == ["Моё, исправлено"]

    def nfr_issues():
        v = client.get(f"/api/projects/{pid}/document").get_json()["version"]
        return {i["rule"] for _n, _k, b in frd.req_blocks(v["content"]) if b["id"] == "NFR-1" for i in b["issues"]}
    assert nfr_issues() == {"not_measurable", "vague"}
    client.post(f"/api/documents/{doc_id}/dismiss", json={"atom_id": ids[1], "rule": "vague"})
    assert nfr_issues() == {"not_measurable"}

    job = client.post(f"/api/documents/{doc_id}/fix", json={"atom_id": ids[1], "rule": "not_measurable", "message": "x"}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    assert "[уточнить" in client.get(f"/job/{job}").get_json()["result"]["statement"]

    client.patch(f"/api/atoms/{ids[1]}", json={"statement": "Карточка открывается не дольше 2 секунд"})
    body = client.get(f"/api/projects/{pid}/document").get_json()
    assert body["stale"]["stale"] and body["stale"]["sections"] == {"4": 1}
    assert client.get(f"/api/documents/{doc_id}/diff").status_code == 400        # only one version so far


def test_api_build_needs_accepted_atoms(client, lib):
    pid, *_ = seed(lib, accept=False)
    r = client.post(f"/api/projects/{pid}/document/build", json={})
    assert r.status_code == 400 and "Review the atoms" in r.get_json()["error"]


def test_api_document_template_and_title(client, lib):
    pid, *_ = seed(lib)
    doc_id = client.get(f"/api/projects/{pid}/document").get_json()["document"]["id"]
    assert client.get(f"/api/projects/{pid}/document").get_json()["document"]["template"] == "export-standard"
    assert client.patch(f"/api/documents/{doc_id}", json={"template": "export-gost"}).get_json()["template"] == "export-gost"
    assert client.patch(f"/api/documents/{doc_id}", json={"template": "Not A Skill!"}).status_code == 400
    assert client.patch(f"/api/documents/{doc_id}", json={"title": "ФТ — Карточка"}).get_json()["title"] == "ФТ — Карточка"


# ── saving files in the desktop window ───────────────────────────────────────

def test_desktop_save_file_and_text(tmp_path):
    fetched = []

    def opener(url, timeout=None):
        fetched.append(url)
        return io.BytesIO(b"DOCX")
    target = tmp_path / "out.docx"
    api = DesktopApi("http://127.0.0.1:47823", lambda name: str(target), opener=opener)
    assert api.save_file("/api/documents/x/export.docx?version=1", "FRD.docx") == {"saved": str(target)}
    assert target.read_bytes() == b"DOCX" and fetched == ["http://127.0.0.1:47823/api/documents/x/export.docx?version=1"]
    assert api.save_file("https://evil.example/x", "a") == {"error": "invalid path"}
    assert api.save_file("//evil.example/x", "a") == {"error": "invalid path"}
    assert DesktopApi("http://x", lambda n: None).save_text("a.txt", "t") == {"cancelled": True}
    api.save_text("a.txt", "привет")
    assert target.read_text(encoding="utf-8") == "привет"


# ── output language (per project) ────────────────────────────────────────────

def test_project_language_switches_the_document_and_forces_a_full_rebuild(store):
    pid, ids, _ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))          # Russian sources → Russian doc
    assert store.version(store.document(pid)["id"])["content"]["language"] == "ru"
    store.update_project(pid, language="en")
    fake = llm(full_reply())
    r = frd.build(store, pid, PREFS, "k", mode="changed", complete=fake)
    v = store.version(store.document(pid)["id"])
    assert r["mode"] == "full", "a language switch rewrites everything"
    assert v["content"]["language"] == "en" and v["content"]["sections"][0]["title"] == "Purpose"
    assert "Write everything in English" in fake.calls[0]["system"]


def test_language_rule_reaches_extraction_and_jira(store):
    from core import atoms, jira
    from core.fake_jira import FakeJira
    from core.llm import language_rule
    pid, ids, sid = seed(store, accept=False)
    store.update_project(pid, language="en")
    assert "in English" in language_rule(store.get_project(pid))
    fake = llm({"atoms": []})
    atoms.extract_candidates(store, sid, PREFS, "k", complete=fake)
    assert "Write everything you produce" in fake.calls[0]["system"] and "Quotes and evidence stay" in fake.calls[0]["system"]
    for i in ids:
        store.update_atom(i, status="accepted")
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    from core import backlog as bl
    from tests.test_backlog import decomposition
    bl.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    j = FakeJira(localized=False)
    types = jira.suggest_types(jira.projects(j, "c")[0]["issue_types"])
    store.set_jira_target(pid, j.cloud_id, j.site, j.project_key, "S", types)
    rows = [r["item_id"] for r in jira.plan(store, pid, j)["rows"] if r["action"] == "create"]
    jira.push(store, pid, j, rows)
    story = next(i for i in j.issues.values() if i["fields"]["issuetype"]["name"] == "Story")
    assert "**Acceptance criteria**" in story["fields"]["description"] and "Created in Dictum" in story["fields"]["description"]


def test_project_language_is_validated(store):
    pid = store.current_project()["id"]
    with pytest.raises(Exception):
        store.update_project(pid, language="de")
    assert store.update_project(pid, language="ru")["language"] == "ru"


def test_atoms_rejected_as_out_of_scope_are_listed_in_that_section(store):
    pid, a1, a2, *_ = seed(store)
    extra = store.add_ba_atom(pid, "functional", "Мобильное приложение для клиентов")
    store.update_atom(extra["id"], status="rejected", reject_reason="out_of_scope")
    r = frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    content = store.version(r["document_id"])["content"]
    sec = next(x for x in content["sections"] if x["key"] == "out_of_scope")
    assert any("Мобильное приложение для клиентов" in b.get("items", []) for b in sec["blocks"])


def test_risk_register_document_has_a_table_with_ids_and_a_heat_map(store):
    from core import docx_export, exports, skills as sk
    pid, ids, sid = seed(store)
    r1 = store.add_ba_atom(pid, "risk", "Заказчик может не согласовать сроки")
    r2 = store.add_ba_atom(pid, "risk", "У CRM может не быть API")
    doc = store.create_document(pid, "write-risk-register", "Риски — проект")
    rid = store.requirement_ids(pid, [store.get_atom(r1["id"]), store.get_atom(r2["id"])])
    reply = full_reply()
    reply["items"] = []
    reply["tables"] = [{"key": "risks", "rows": [
        [rid[r1["id"]], "Сроки не согласованы", "конфликт требований", "высокая", "высокое", "снизить: созвон", "BA", "FR-1"],
        ["RSK-99", "выдуманный", "", "низкая", "низкое", "", "", ""]]}]
    fake = llm(reply)
    r = frd.build(store, pid, PREFS, "k", mode="full", complete=fake, document_id=doc["id"])
    assert "RSK-" in fake.calls[0]["user"] and "Related atoms (context only" in fake.calls[0]["user"]
    content = store.version(doc["id"], r["version"])["content"]
    sec = next(s for s in content["sections"] if s["key"] == "risks")
    table, heat = sec["blocks"]
    assert [row[0] for row in table["rows"]] == [rid[r1["id"]], rid[r2["id"]]], "one row per risk atom, nothing invented"
    assert table["rows"][1][1] == "У CRM может не быть API", "a risk the model skipped keeps its own wording"
    assert heat["heatmap"] and heat["rows"][0][3] == rid[r1["id"]]
    assert not any(b["id"].startswith("FR-") for _n, _k, b in frd.req_blocks(content)), "a register places no FRs"
    md = exports.markdown(store.get_document(doc["id"]), store.version(doc["id"]), [], "ru")
    assert f"| {rid[r1['id']]} | Сроки не согласованы |" in md
    data = docx_export.render(store.get_document(doc["id"]), store.version(doc["id"]), [], template=None)
    import io, docx
    d = docx.Document(io.BytesIO(data))
    assert any(t.rows[1].cells[0].text == rid[r1["id"]] for t in d.tables)
    assert sk.doc_atom_types(sk.get("write-risk-register").meta)[0] == ["risk", "question"]


def test_each_document_takes_only_its_own_atom_types(store):
    pid, ids, sid = seed(store)
    br = store.add_ba_atom(pid, "business", "Сократить время обслуживания звонка на 20%")
    srs = store.document(pid)                                  # the project's first document (SRS)
    brd = store.create_document(pid, "write-brd", "BRD")
    fake = llm(full_reply())
    frd.build(store, pid, PREFS, "k", complete=fake, document_id=brd["id"])
    content = store.version(brd["id"])["content"]
    placed = {b["id"] for _n, _k, b in frd.req_blocks(content)}
    assert any(x.startswith("BR-") for x in placed) and not any(x.startswith("FR-") for x in placed)
    assert "BR-1 [business]" in fake.calls[0]["user"].split("Related atoms")[0]
    assert "FR-1 [functional]" in fake.calls[0]["user"].split("Related atoms")[1], "FRs are context in a BRD"
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()), document_id=srs["id"])
    srs_ids = {b["id"] for _n, _k, b in frd.req_blocks(store.version(srs["id"])["content"])}
    assert "BR-1" not in srs_ids and "FR-1" in srs_ids
    store.update_atom(br["id"], statement="Сократить время обслуживания звонка на 30%")
    assert frd.staleness(store, pid, store.version(brd["id"]))["stale"]
    assert not frd.staleness(store, pid, store.version(srs["id"]))["stale"], "a BR change doesn't touch the SRS"
    assert [d["id"] for d, _v in frd.decompose_documents(store, pid)] == [srs["id"]]
    store.update_document(brd["id"], decompose=True)
    assert [d["id"] for d, _v in frd.decompose_documents(store, pid)] == [srs["id"], brd["id"]]


def test_each_document_keeps_its_own_type_and_versions(store):
    pid, ids, sid = seed(store)
    srs = store.document(pid)
    brd = store.create_document(pid, "write-brd", "BRD — проект")
    reply = full_reply()
    reply["extra"] = [{"key": "business_context", "text": "Операторы теряют время."}]
    frd.build(store, pid, PREFS, "k", complete=llm(reply), document_id=brd["id"])
    assert store.version(srs["id"]) is None and store.version(brd["id"])["number"] == 1
    content = store.version(brd["id"])["content"]
    assert content["skills"]["frd"] == "write-brd"
    assert next(s for s in content["sections"] if s["key"] == "business_context")["blocks"][0]["text"] == "Операторы теряют время."
    assert [d["id"] for d in store.documents(pid)] == [srs["id"], brd["id"]]
    assert frd.decompose_documents(store, pid) == [], "a BRD doesn't go into the backlog by default"
