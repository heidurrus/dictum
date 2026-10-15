import pytest

from core import atoms as atoms_mod
from core.atoms import chunk_segments, extract_atoms, normalize, segment_line, verify_evidence
from core.llm import LLMError
from core.store import Store, StoreError
from tests.test_recorder import wait_for

PREFS = {"llm_provider": "claude", "claude_model": "claude-opus-5", "local_model": ""}

CALL = {"diarized": True, "segments": [
    {"speaker": "SPEAKER_00", "start": 0.0, "end": 4.0, "text": "Добрый день, начнём."},
    {"speaker": "SPEAKER_01", "start": 4.5, "end": 9.0,
     "text": "Карточка клиента должна открываться до поднятия трубки, не дольше двух секунд."},
    {"speaker": "SPEAKER_01", "start": 9.5, "end": 14.0, "text": "И оператор видит историю заказов за год."},
]}


def fake_llm(*replies):
    """complete_json stub: returns the replies in order and records every call."""
    calls, queue = [], list(replies)

    def complete(system, user, schema, prefs, api_key):
        calls.append({"system": system, "user": user, "schema": schema, "prefs": prefs})
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    complete.calls = calls
    return complete


@pytest.fixture()
def store(tmp_path):
    return Store(root=str(tmp_path / "lib"), user="ba")


def make_source(store, result=CALL, project=None):
    pid = project or store.current_project()["id"]
    src = store.create_source(pid, "recording", "Звонок с Иваном")
    store.save_transcript(src["id"], result)
    return src["id"]


LATENCY = {"type": "nfr", "statement": "Карточка клиента открывается не дольше 2 секунд",
           "evidence": [{"segment": 1, "quote": "не дольше двух секунд"}]}
HISTORY = {"type": "functional", "statement": "Оператор видит историю заказов клиента за год",
           "evidence": [{"segment": 2, "quote": "оператор видит историю заказов за год"}]}


# ── helpers ──────────────────────────────────────────────────────────────────

def test_normalize_ignores_case_quotes_dashes_and_yo():
    assert normalize("  «Ещё» — ТАК, ") == normalize('"еще" - так')


def test_segment_line_labels_index_speaker_and_time():
    assert segment_line({"idx": 3, "speaker": "SPEAKER_01", "speaker_name": "Иван", "start": 65, "text": "Да"}) \
        == "[S3] [Иван, 01:05] Да"
    assert segment_line({"idx": 0, "speaker": None, "start": None, "text": "Абзац"}) == "[S0] Абзац"


def test_chunks_respect_the_size_limit_and_keep_order():
    segs = [{"idx": i, "speaker": None, "start": None, "text": "x" * 40} for i in range(10)]
    chunks = chunk_segments(segs, limit=100)
    assert [s["idx"] for c in chunks for s in c] == list(range(10))
    assert all(sum(len(segment_line(s)) + 1 for s in c) <= 100 for c in chunks)


def test_verify_drops_invented_quotes_and_fixes_wrong_line():
    chunk = [{"idx": 1, "speaker": "A", "start": 1.0, "text": "Нужен экспорт в Excel."},
             {"idx": 2, "speaker": "B", "start": 5.0, "text": "Только для руководителей."}]
    kept = verify_evidence([{"segment": 1, "quote": "только для руководителей"},   # wrong line → re-attached
                            {"segment": 1, "quote": "экспорт в PDF"},              # not said → dropped
                            {"segment": 2, "quote": "ok"}], chunk, "s")              # too short → dropped
    assert [(e["segment_idx"], e["speaker"], e["start"]) for e in kept] == [(2, "B", 5.0)]


# ── extraction ───────────────────────────────────────────────────────────────

def test_extract_saves_verified_atoms_with_evidence(store):
    sid = make_source(store)
    invented = {"type": "functional", "statement": "Экспорт в PDF", "evidence": [{"segment": 1, "quote": "экспорт в PDF"}]}
    llm = fake_llm({"atoms": [LATENCY, HISTORY, invented]}, {"duplicates": [], "conflicts": []})
    steps = []
    r = extract_atoms(store, sid, PREFS, "key", progress=lambda *a: steps.append(a), complete=llm)
    assert r["extracted"] == 2 and r["dropped"] == 1 and r["model"] == "claude-opus-5"
    assert len(llm.calls) == 2 and "N2 [functional]" in llm.calls[1]["user"]
    atoms = store.list_atoms(store.current_project()["id"])
    assert [(a["type"], a["status"]) for a in atoms] == [("nfr", "pending"), ("functional", "pending")]
    ev = atoms[0]["evidence"][0]
    assert (ev["source_id"], ev["segment_idx"], ev["start"], ev["source_title"]) == (sid, 1, 4.5, "Звонок с Иваном")
    assert "[S1] [SPEAKER_01, 00:04]" in llm.calls[0]["user"]
    assert steps[-1][0] == steps[-1][1]


def test_duplicates_fold_into_existing_atoms_and_conflicts_are_flagged(store):
    first = make_source(store)
    extract_atoms(store, first, PREFS, "k", complete=fake_llm({"atoms": [LATENCY]}))
    pid = store.current_project()["id"]
    existing = store.list_atoms(pid)[0]
    store.update_atom(existing["id"], status="accepted")

    second = make_source(store, {"segments": [
        {"speaker": "Олег", "start": 1.0, "end": 3.0, "text": "Карточка открывается за две секунды максимум."},
        {"speaker": "Олег", "start": 3.0, "end": 6.0, "text": "История заказов нужна за три года."}]})
    llm = fake_llm(
        {"atoms": [{"type": "nfr", "statement": "Карточка открывается не дольше 2 с",
                    "evidence": [{"segment": 0, "quote": "за две секунды максимум"}]},
                   {"type": "functional", "statement": "История заказов за три года",
                    "evidence": [{"segment": 1, "quote": "История заказов нужна за три года"}]}]},
        {"duplicates": [{"new": "N1", "same_as": "E1"}, {"new": "E1", "same_as": "N2"}],   # 2nd: not new → ignored
         "conflicts": [{"a": "N2", "b": "E1", "description": "Разный срок хранения истории"},
                       {"a": "N9", "b": "E1", "description": "unknown id"}]})
    r = extract_atoms(store, second, PREFS, "k", complete=llm)
    assert (r["extracted"], r["merged"], r["conflicts"]) == (1, 1, 1)
    assert "E1 [nfr]" in llm.calls[1]["user"] and "N2 [functional]" in llm.calls[1]["user"]

    merged = store.get_atom(existing["id"])
    assert merged["status"] == "accepted", "a reviewed atom keeps its decision"
    assert sorted(e["source_id"] for e in merged["evidence"]) == sorted([first, second])
    stats = store.atom_stats(pid)
    assert (stats["total"], stats["merged"], stats["open_conflicts"]) == (2, 1, 1)


def test_reextract_replaces_pending_but_keeps_reviewed(store):
    sid = make_source(store)
    extract_atoms(store, sid, PREFS, "k", complete=fake_llm({"atoms": [LATENCY, HISTORY]}, {"duplicates": [], "conflicts": []}))
    pid = store.current_project()["id"]
    kept = store.list_atoms(pid)[0]
    store.update_atom(kept["id"], status="accepted")
    r = extract_atoms(store, sid, PREFS, "k",
                      complete=fake_llm({"atoms": [HISTORY]}, {"duplicates": [], "conflicts": []}))
    assert r["replaced"] == 1
    assert sorted(a["status"] for a in store.list_atoms(pid)) == ["accepted", "pending"]


def test_action_items_and_other_are_set_aside(store):
    sid = make_source(store)
    llm = fake_llm({"atoms": [
        LATENCY,
        {"type": "action_item", "statement": "Иван пришлёт письмо", "evidence": [{"segment": 0, "quote": "начнём"}]},
        {"type": "other", "statement": "Приветствие", "evidence": []}]})
    r = extract_atoms(store, sid, PREFS, "k", complete=llm)
    assert (r["extracted"], r["skipped_actions"], r["skipped_other"], r["dropped"]) == (1, 1, 1, 0)
    assert [a["statement"] for a in store.list_atoms(store.current_project()["id"])] == [LATENCY["statement"]]
    schema_types = llm.calls[0]["schema"]["properties"]["atoms"]["items"]["properties"]["type"]["enum"]
    assert {"action_item", "other"} <= set(schema_types) and "action_item" in llm.calls[0]["system"]


def test_local_only_project_uses_the_local_model(store):
    p = store.create_project("Банк", local_only=True)
    sid = make_source(store, project=p["id"])
    llm = fake_llm({"atoms": []})
    r = extract_atoms(store, sid, PREFS, "k", complete=llm)
    assert llm.calls[0]["prefs"]["llm_provider"] == "local" and r["provider"] == "local"


def test_failed_dedup_keeps_the_atoms(store):
    sid = make_source(store)
    r = extract_atoms(store, sid, PREFS, "k", complete=fake_llm({"atoms": [LATENCY, HISTORY]}, LLMError("down")))
    assert r["extracted"] == 2


def test_source_without_text_is_an_error(store):
    src = store.create_source(store.current_project()["id"], "recording", "empty", status="recorded")
    with pytest.raises(LLMError):
        extract_atoms(store, src["id"], PREFS, "k", complete=fake_llm())


def test_long_sources_are_read_in_parts(store, monkeypatch):
    monkeypatch.setattr(atoms_mod, "CHUNK_CHARS", 90)
    sid = make_source(store)
    llm = fake_llm({"atoms": []}, {"atoms": []}, {"atoms": []})
    extract_atoms(store, sid, PREFS, "k", complete=llm)
    assert len(llm.calls) == 3


# ── review & conflicts in the store ──────────────────────────────────────────

def _two_atoms(store):
    sid = make_source(store)
    pid = store.current_project()["id"]
    a, b = store.add_atoms(pid, [
        {"type": "nfr", "statement": "2 секунды", "evidence": [{"source_id": sid, "segment_idx": 1, "quote": "двух секунд"}]},
        {"type": "nfr", "statement": "5 секунд", "evidence": [{"source_id": sid, "segment_idx": 2, "quote": "историю"}]}])
    return pid, a, b


def test_edits_keep_the_original_and_are_audited(store):
    pid, a, _ = _two_atoms(store)
    atom = store.update_atom(a, statement="Карточка ≤ 2 с")
    assert (atom["statement"], atom["original_statement"]) == ("Карточка ≤ 2 с", "2 секунды")
    store.update_atom(a, status="rejected")
    store.update_atom(a, status="pending")                 # undo
    actions = [e["action"] for e in store.audit("atom", a)]
    assert {"create", "edit", "rejected", "pending"} <= set(actions)
    with pytest.raises(StoreError):
        store.update_atom(a, status="merged")
    with pytest.raises(StoreError):
        store.update_atom(a, statement="  ")


def test_bulk_update_in_one_go_with_audit(store):
    pid, a, b = _two_atoms(store)
    other = store.create_project("Чужой")
    sid = make_source(store, project=other["id"])
    foreign = store.add_atoms(other["id"], [{"type": "nfr", "statement": "x",
                                             "evidence": [{"source_id": sid, "quote": "двух секунд"}]}])[0]
    changed = store.bulk_update_atoms(pid, [{"id": a, "status": "accepted"}, {"id": b, "status": "accepted"},
                                            {"id": foreign, "status": "accepted"}, {"id": "nope", "status": "accepted"}])
    assert changed == [a, b], "other projects' and unknown atoms are skipped"
    assert store.get_atom(foreign)["status"] == "pending"
    assert store.atom_stats(pid)["accepted"] == 2
    entry = store.audit("atom", a)[0]
    assert entry["action"] == "accepted" and entry["after"]["bulk"] is True
    assert store.bulk_update_atoms(pid, [{"id": a, "status": "accepted"}]) == [], "no-op changes are not counted"
    assert store.bulk_update_atoms(pid, [{"id": a, "type": "question"}]) == [a]
    assert store.get_atom(a)["type"] == "question"


@pytest.mark.parametrize("items,match", [
    ([], "nothing"), ([{"id": "x"}], "status, type or priority"), ([{"id": "x", "status": "merged"}], "status"),
    ([{"id": "x", "type": "epic"}], "type"), ([{"id": "x", "status": "accepted", "statement": "y"}], "only status, type"),
])
def test_bulk_update_validates(store, items, match):
    pid, *_ = _two_atoms(store)
    with pytest.raises(StoreError, match=match):
        store.bulk_update_atoms(pid, items)


def test_bulk_accepting_a_conflict_question_keeps_the_conflict_open(store):
    pid, a, b = _two_atoms(store)
    q = store.resolve_conflict(store.add_conflict(pid, a, b, "2 или 5?"), "question")["question_atom"]
    store.bulk_update_atoms(pid, [{"id": q, "status": "accepted"}])
    assert store.list_conflicts(pid)[0]["status"] == "awaiting_answer", "only a recorded answer settles it (PM-21)"


@pytest.mark.parametrize("action,expect", [
    ("keep_a", {"a": "pending", "b": "rejected"}),
    ("keep_b", {"a": "rejected", "b": "pending"}),
])
def test_conflict_keep_one(store, action, expect):
    pid, a, b = _two_atoms(store)
    cid = store.add_conflict(pid, a, b, "Разные сроки")
    assert store.resolve_conflict(cid, action)["status"] == "resolved"
    assert {"a": store.get_atom(a)["status"], "b": store.get_atom(b)["status"]} == expect
    assert store.list_conflicts(pid) == []


def test_conflict_merge_combines_statement_and_evidence(store):
    pid, a, b = _two_atoms(store)
    cid = store.add_conflict(pid, a, b, "Разные сроки")
    with pytest.raises(StoreError):
        store.resolve_conflict(cid, "merge")
    store.resolve_conflict(cid, "merge", "Не дольше 3 секунд")
    atom = store.get_atom(a)
    assert atom["statement"] == "Не дольше 3 секунд" and len(atom["evidence"]) == 2
    assert store.get_atom(b)["status"] == "merged"


def test_conflict_question_waits_for_the_answer(store):
    pid, a, b = _two_atoms(store)
    cid = store.add_conflict(pid, a, b, "2 или 5 секунд?")
    q = store.resolve_conflict(cid, "question")
    assert q["status"] == "awaiting_answer"
    question = store.get_atom(q["question_atom"])
    assert question["type"] == "question" and "2 или 5 секунд?" in question["statement"]
    assert len(question["evidence"]) == 2
    assert store.list_conflicts(pid)[0]["status"] == "awaiting_answer"
    store.update_atom(q["question_atom"], status="accepted")
    assert store.list_conflicts(pid)[0]["status"] == "awaiting_answer", "accepting a question answers nothing"
    store.answer_question(q["question_atom"], "Пять секунд", source="письмо от 12.03")
    assert store.list_conflicts(pid)[0]["status"] == "awaiting_answer", "an answer alone doesn't pick a side"
    answered = store.answer_question(q["question_atom"], "Пять секунд", source="письмо от 12.03", resolution="keep_b")
    assert answered["q_state"] == "answered" and answered["answer"] == "Пять секунд"
    assert store.list_conflicts(pid) == [] and store.get_atom(a)["status"] == "rejected"
    assert store.list_conflicts(pid, include_resolved=True)[0]["question_atom"] == q["question_atom"]


def test_ba_can_add_an_atom_and_action_items_are_kept(store):
    pid, a, b = _two_atoms(store)
    own = store.add_ba_atom(pid, "functional", "Экспорт в CSV", note="из чата с заказчиком")
    assert own["status"] == "accepted" and own["origin"] == "ba" and own["evidence"] == []
    store.add_actions(pid, None, [{"text": "Отправить макеты", "owner": "Иван"}, {"text": " "}])
    [act] = store.list_actions(pid)
    assert act["text"] == "Отправить макеты" and act["status"] == "open"
    store.update_action(act["id"], status="done")
    assert store.list_actions(pid)[0]["status"] == "done"


def test_reject_reason_and_priority(store):
    pid, a, b = _two_atoms(store)
    with pytest.raises(StoreError):
        store.update_atom(a, status="rejected", reject_reason="nope")
    assert store.update_atom(a, status="rejected", reject_reason="out_of_scope")["reject_reason"] == "out_of_scope"
    assert store.update_atom(a, status="accepted")["reject_reason"] is None, "a reason only lives on rejected atoms"
    store.bulk_update_atoms(pid, [{"id": a, "priority": "must"}, {"id": b, "priority": "could"}])
    assert (store.get_atom(a)["priority"], store.get_atom(b)["priority"]) == ("must", "could")


def test_migrates_a_v2_library(tmp_path):
    root = tmp_path / "lib"
    Store(root=str(root), user="ba")
    import sqlite3
    db = sqlite3.connect(root / "workbench.db")
    db.executescript("DROP TABLE atoms; DROP TABLE evidence; DROP TABLE conflicts; PRAGMA user_version = 2;")
    db.close()
    store = Store(root=str(root), user="ba")
    assert store.atom_stats(store.current_project()["id"])["total"] == 0


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    monkeypatch.setattr(app_module.settings, "load_settings", lambda: dict(PREFS))
    monkeypatch.setattr(app_module.settings, "secret", lambda name: "key")
    return store


def test_api_extract_review_and_resolve(client, app_module, lib, monkeypatch):
    sid = make_source(lib)
    pid = lib.current_project()["id"]
    llm = fake_llm({"atoms": [LATENCY, HISTORY]},
                   {"duplicates": [], "conflicts": [{"a": "N1", "b": "N2", "description": "тест"}]})
    monkeypatch.setattr(atoms_mod, "complete_json", llm)
    monkeypatch.setattr(app_module, "extract_atoms",
                        lambda *a, **k: atoms_mod.extract_atoms(*a, **k, complete=llm))
    job = client.post(f"/api/sources/{sid}/atoms/extract").get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    assert client.get(f"/job/{job}").get_json()["result"]["extracted"] == 2

    body = client.get(f"/api/projects/{pid}/atoms").get_json()
    assert body["stats"]["pending"] == 2 and body["stats"]["open_conflicts"] == 1
    a = body["atoms"][0]
    assert a["conflicts"][0]["description"] == "тест"
    assert client.get(f"/api/projects/{pid}/atoms?type=nfr").get_json()["atoms"][0]["id"] == a["id"]

    r = client.patch(f"/api/atoms/{a['id']}", json={"status": "accepted"}).get_json()
    assert r["status"] == "accepted" and r["stats"]["accepted"] == 1
    assert client.patch(f"/api/atoms/{a['id']}", json={"project_id": "x"}).status_code == 400

    conflict = client.get(f"/api/projects/{pid}/conflicts").get_json()["conflicts"][0]
    assert conflict["a"]["statement"] and conflict["b"]["statement"]
    r = client.post(f"/api/conflicts/{conflict['id']}/resolve", json={"action": "question"}).get_json()
    assert r["status"] == "awaiting_answer"
    client.patch(f"/api/atoms/{r['question_atom']}", json={"status": "accepted"})
    assert client.get(f"/api/projects/{pid}/conflicts").get_json()["conflicts"][0]["status"] == "awaiting_answer"
    ans = client.post(f"/api/atoms/{r['question_atom']}/answer", json={"answer": "Да", "resolution": "keep_a"}).get_json()
    assert ans["q_state"] == "answered" and ans["stats"]["open_conflicts"] == 0
    assert client.get(f"/api/projects/{pid}/conflicts").get_json()["conflicts"] == []
    own = client.post(f"/api/projects/{pid}/atoms", json={"statement": "Своё требование"}).get_json()
    assert own["origin"] == "ba" and own["status"] == "accepted"
    assert any(e["action"] == "extract_atoms" for e in lib.audit("source", sid))


def test_api_bulk(client, lib):
    pid, a, b = _two_atoms(lib)
    r = client.post(f"/api/projects/{pid}/atoms/bulk", json={"items": [{"id": a, "status": "rejected"},
                                                                       {"id": b, "status": "rejected"}]})
    body = r.get_json()
    assert r.status_code == 200 and body["changed"] == [a, b] and body["stats"]["rejected"] == 2
    undo = client.post(f"/api/projects/{pid}/atoms/bulk", json={"items": [{"id": a, "status": "pending"},
                                                                          {"id": b, "status": "pending"}]})
    assert undo.get_json()["stats"]["pending"] == 2
    assert client.post(f"/api/projects/{pid}/atoms/bulk", json={"items": []}).status_code == 400
    assert client.post(f"/api/projects/{pid}/atoms/bulk", json={}).status_code == 400


def test_api_extract_needs_text_and_a_key(client, app_module, lib, monkeypatch):
    src = lib.create_source(lib.current_project()["id"], "recording", "r", status="recorded")
    assert client.post(f"/api/sources/{src['id']}/atoms/extract").status_code == 400
    sid = make_source(lib)
    monkeypatch.setattr(app_module.settings, "secret", lambda name: None)
    r = client.post(f"/api/sources/{sid}/atoms/extract")
    assert r.status_code == 400 and r.get_json()["needs_setup"]
    assert client.post("/api/sources/nope/atoms/extract").status_code == 404


def test_api_merge(client, lib):
    pid, a, b = _two_atoms(lib)
    r = client.post(f"/api/atoms/{b}/merge", json={"into": a})
    assert r.status_code == 200 and len(r.get_json()["evidence"]) == 2
    assert [x["id"] for x in client.get(f"/api/projects/{pid}/atoms").get_json()["atoms"]] == [a]


def test_delete_hides_atoms_closes_conflicts_and_undo_restores(store):
    pid, a, b = _two_atoms(store)
    store.add_conflict(pid, a, b, "2 или 5?")
    assert store.delete_atoms(pid, [a, "nope"]) == [a]
    assert [x["id"] for x in store.list_atoms(pid)] == [b]
    assert store.atom_stats(pid)["total"] == 1 and store.atom_stats(pid)["open_conflicts"] == 0
    assert store.list_sources(pid)[0]["atom_count"] == 1
    import pytest as _p
    with _p.raises(StoreError, match="deleted"):
        store.update_atom(a, status="accepted")
    assert store.bulk_update_atoms(pid, [{"id": a, "status": "accepted"}]) == []
    assert store.audit("atom", a)[0]["action"] == "delete"
    assert store.restore_atoms(pid, [a]) == [a]
    assert len(store.list_atoms(pid)) == 2 and store.atom_stats(pid)["open_conflicts"] == 1, "the conflict is back"


def test_deleted_accepted_atom_leaves_the_document(store):
    from core import frd
    from tests.test_frd import full_reply, llm as frd_llm, seed as frd_seed
    pid, ids, _ = frd_seed(store)
    frd.build(store, pid, PREFS, "k", complete=frd_llm(full_reply()))
    store.delete_atoms(pid, [ids[2]])
    doc = store.document(pid)
    assert frd.staleness(store, pid, store.version(doc["id"]))["removed"] == 1


def test_api_delete_and_restore(client, lib):
    pid, a, b = _two_atoms(lib)
    r = client.post(f"/api/projects/{pid}/atoms/delete", json={"ids": [a, b]}).get_json()
    assert r["deleted"] == [a, b] and r["stats"]["total"] == 0
    assert client.post(f"/api/projects/{pid}/atoms/delete", json={"ids": []}).status_code == 400
    r = client.post(f"/api/projects/{pid}/atoms/restore", json={"ids": [a, b]}).get_json()
    assert r["restored"] == [a, b] and r["stats"]["total"] == 2


def test_reclassify_suggests_new_types_and_applies_them(client, app_module, tmp_path, monkeypatch):
    lib = Store(root=str(tmp_path / "lib2"), user="ba")
    monkeypatch.setattr(app_module, "library", lib)
    pid, a, b = _two_atoms(lib)
    fake = fake_llm({"items": [{"id": "A1", "type": "business"}, {"id": "A2", "type": "nfr"}, {"id": "A9", "type": "risk"}]})
    changes = atoms_mod.reclassify(lib, pid, PREFS, "k", complete=fake)
    assert [(c["id"], c["to"]) for c in changes] == [(a, "business")], "unchanged and unknown IDs are ignored"
    assert "[nfr]" not in fake.calls[0]["user"], "the old type would anchor the model"
    assert "business" in str(fake.calls[0]["schema"])
    rid = lib.requirement_ids(pid, [dict(lib.get_atom(a), type="business")])[a]
    assert rid.startswith("BR-")


def test_atom_marks_list_an_atom_once_per_line_even_with_two_quotes(store):
    sid = make_source(store)
    pid = store.current_project()["id"]
    [a] = store.add_atoms(pid, [{"type": "nfr", "statement": "2 секунды", "evidence": [
        {"source_id": sid, "segment_idx": 1, "quote": "двух секунд"},
        {"source_id": sid, "segment_idx": 1, "quote": "не дольше"}]}])   # two quotes on one line
    marks = store.atom_marks(sid)
    assert [m["atom_id"] for m in marks[1]].count(a) == 1
