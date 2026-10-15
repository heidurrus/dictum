"""Спросить (5.0 C6): retrieval across materials, meeting windows and atoms; the keyword fallback without the index;
citation markers in both languages; the create_question intent; the history; "Только локально" never calls Claude."""
import time

import pytest

from core import ask, index, local_llm, materials, skills, summarize as summarize_mod
from core.store import Store
from tests import fake_embed


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    monkeypatch.setattr(app_module, "schedule_index", lambda project_id, force_material=None: None)
    return store


@pytest.fixture()
def pid(lib):
    return lib.ensure_default_project()["id"]


@pytest.fixture()
def indexed(monkeypatch):
    fake_embed.install(monkeypatch, index)


def material(lib, pid, text, title, in_context=True):
    m = materials.import_text(lib, lib.get_project(pid), text, title)
    if not in_context:
        lib.update_material(m["id"], in_context=False)
    return m


def meeting(lib, pid, lines, title="Созвон с дилером"):
    s = lib.create_source(pid, "transcript", title)
    lib.save_transcript(s["id"], {"segments": [{"start": 10.0 * i, "end": 10.0 * i + 5, "speaker": "A", "text": t}
                                               for i, t in enumerate(lines)]})
    return s


@pytest.fixture()
def project(lib, pid, indexed):
    """A material in context, one out of context, a meeting and an accepted atom, all indexed."""
    sla = material(lib, pid, "Ответ дилеру по заявке даётся не позднее двух часов. Срок ответа дилеру фиксирован.",
                   "SLA для дилеров")
    hidden = material(lib, pid, "Ответ дилеру по заявке даётся за четыре часа, срок ответа дилеру по регламенту.",
                      "Старый регламент", in_context=False)
    meet = meeting(lib, pid, ["Срок ответа дилеру два часа, это важно", "Про отпуска поговорим потом"])
    [aid] = lib.add_atoms(pid, [{"type": "nfr", "statement": "Срок ответа дилеру не больше двух часов",
                                 "evidence": [{"source_id": meet["id"], "segment_idx": 0, "start": 0.0,
                                               "quote": "Срок ответа дилеру два часа"}]}])
    lib.update_atom(aid, status="accepted")
    index.index_project(lib, pid)
    return {"sla": sla["id"], "hidden": hidden["id"], "meeting": meet["id"], "atom": aid}


Q = "Какой срок ответа дилеру по заявке?"


# ── retrieval ────────────────────────────────────────────────────────────────

def test_retrieval_mixes_materials_meetings_and_atoms_and_numbers_them(lib, pid, project):
    found = ask.retrieve(lib, pid, Q, context_only=False)
    assert found["indexed"] is True and found["best"] > 0
    kinds = {s["entity"] for s in found["sources"]}
    assert kinds == {"material", "segment", "atom"}
    assert [s["n"] for s in found["sources"]] == list(range(1, len(found["sources"]) + 1))
    ids = {s["entity_id"] for s in found["sources"]}
    assert {project["sla"], project["hidden"], project["meeting"], project["atom"]} <= ids
    atom = next(s for s in found["sources"] if s["entity"] == "atom")
    assert atom["title"].startswith("NFR-") and atom["locator"] == 0
    seg = next(s for s in found["sources"] if s["entity"] == "segment")
    assert seg["locator"] == 0 and seg["start"] == 0.0 and seg["title"] == "Созвон с дилером"


def test_context_only_drops_materials_out_of_context_but_keeps_meetings_and_atoms(lib, pid, project):
    found = ask.retrieve(lib, pid, Q, context_only=True)
    ids = {s["entity_id"] for s in found["sources"]}
    assert project["hidden"] not in ids
    assert {project["sla"], project["meeting"], project["atom"]} <= ids


def test_retrieve_k_limits_the_vector_hits(lib, pid, project, monkeypatch):
    monkeypatch.setattr(index, "tuning", lambda: {"retrieve_k": 2, "label_assign": 0.45, "graph_edge": 0.3})
    found = ask.retrieve(lib, pid, Q, context_only=False)
    assert len([s for s in found["sources"] if s["score"] is not None]) == 2
    assert len([s for s in found["sources"] if s["score"] is None]) <= ask.FTS_EXTRA


def test_keyword_hits_add_exact_terms_the_vectors_missed(lib, pid, indexed):
    material(lib, pid, "Интеграция с 1С через шину ESB-7731 раз в сутки.", "Интеграции")
    meeting(lib, pid, ["Ничего общего тут нет совсем"])
    index.index_project(lib, pid)
    found = ask.retrieve(lib, pid, "что с ESB-7731?", context_only=True, k=1)
    assert any(s["entity"] == "material" and "ESB-7731" in s["text"] for s in found["sources"])


def test_without_the_index_retrieval_uses_keywords_only(lib, pid, monkeypatch):
    material(lib, pid, "Ответ дилеру по заявке даётся не позднее двух часов.", "SLA для дилеров")
    meeting(lib, pid, ["Срок ответа дилеру два часа"])
    monkeypatch.setattr(index, "available", lambda: False)
    monkeypatch.setattr(index, "embed", lambda *a, **k: pytest.fail("no index model"))
    found = ask.retrieve(lib, pid, Q, context_only=True)
    assert found["indexed"] is False
    assert {s["entity"] for s in found["sources"]} == {"material", "segment"}
    assert all(s["score"] is None for s in found["sources"])


def test_the_keyword_fallback_honours_context_only(lib, pid, monkeypatch):
    material(lib, pid, "Ответ дилеру по заявке даётся за четыре часа.", "Старый регламент", in_context=False)
    monkeypatch.setattr(index, "available", lambda: False)
    assert ask.retrieve(lib, pid, Q, context_only=True)["sources"] == []
    assert len(ask.retrieve(lib, pid, Q, context_only=False)["sources"]) == 1


# ── citations ────────────────────────────────────────────────────────────────

SOURCES = [{"n": 1, "entity": "material", "entity_id": "m1", "locator": 0, "title": "SLA", "text": "a", "start": None},
           {"n": 2, "entity": "segment", "entity_id": "s1", "locator": 4, "title": "Звонок", "text": "b", "start": 65.0},
           {"n": 3, "entity": "atom", "entity_id": "a1", "locator": 0, "title": "NFR-4", "text": "c", "start": None}]


def test_citation_markers_in_russian_become_citations_in_order():
    text, cites = ask.parse_citations("Два часа [Источник 2]. Так и в SLA [Источник 1] [Источник 2].", SOURCES)
    assert [c["n"] for c in cites] == [2, 1]
    assert cites[0] == {"n": 2, "entity": "segment", "entity_id": "s1", "locator": 4, "title": "Звонок", "start": 65.0}
    assert cites[1] == {"n": 1, "entity": "material", "entity_id": "m1", "locator": 0, "title": "SLA"}
    assert text == "Два часа [Источник 2]. Так и в SLA [Источник 1] [Источник 2]."


def test_citation_markers_in_english_lists_and_missing_numbers():
    text, cites = ask.parse_citations("Two hours [Source 3, 9]. Also [Sources 1 and 2]. Nope [Source 7].", SOURCES)
    assert [c["n"] for c in cites] == [3, 1, 2]
    assert "[Source 9]" not in text and "[Source 7]" not in text
    assert "[Source 3]" in text and "[Source 1][Source 2]" in text and text.endswith("Nope.")


def test_intent_is_parsed_and_cut_from_the_answer():
    raw = 'Готово [Источник 1].\n<intent>{"create_question": {"statement": "Какой срок?", "source_ns": [1, 2]}}</intent>'
    body, intent = ask.parse_intent(raw)
    assert body == "Готово [Источник 1]." and intent == {"statement": "Какой срок?", "source_ns": [1, 2]}
    assert ask.parse_intent("Нет намерения")[1] is None
    assert ask.parse_intent("<intent>{broken</intent>")[1] is None


def test_the_stream_never_shows_the_intent():
    shown = []
    f = ask.StreamFilter(shown.append)
    for piece in ["Ответ [Ист", "очник 1]. <in", "tent>{\"create_question\": {}}", "</intent>"]:
        f.feed(piece)
    assert "".join(shown) == "Ответ [Источник 1]. "


# ── the answer ───────────────────────────────────────────────────────────────

def scripted(reply, seen=None):
    def generate(system, user, on_delta):
        if seen is not None:
            seen.append({"system": system, "user": user})
        on_delta(reply)
        return reply
    return generate


def test_answer_cites_saves_history_and_says_how_many_sources(lib, pid, project):
    seen = []
    out = ask.answer(lib, pid, Q, True, scripted("Два часа [Источник 1], так и на встрече [Источник 2].", seen),
                     model="fake")
    assert "[Источник N]" in seen[0]["system"] and "Не нашёл в материалах проекта" in seen[0]["system"]
    assert "[Источник 1]" in seen[0]["user"] and Q in seen[0]["user"]
    assert len(out["citations"]) == 2 and out["sources_used"] == 2 and out["created"] is None
    assert out["indexed"] is True and out["elapsed"] >= 0
    [row] = lib.ask_history(pid)
    assert row["question"] == Q and row["answer"] == out["answer"] and row["citations"] == out["citations"]
    assert row["context_only"] is True and row["model"] == "fake" and row["sources_used"] == 2


def test_nothing_to_search_answers_not_found_without_a_model_call(lib, pid, indexed):
    out = ask.answer(lib, pid, "Кто такой Мюнхгаузен?", True, lambda *a: pytest.fail("no sources, no call"))
    assert out["answer"] == ask.NOT_FOUND["ru"] and out["citations"] == []


def test_the_intent_creates_a_question_atom_quoting_the_cited_sources(lib, pid, project):
    found = ask.retrieve(lib, pid, Q, context_only=True)
    n_mat = next(s["n"] for s in found["sources"] if s["entity_id"] == project["sla"])
    n_seg = next(s["n"] for s in found["sources"] if s["entity"] == "segment")
    reply = (f"Сделал вопрос [Источник {n_mat}] [Источник {n_seg}].\n<intent>{{\"create_question\": {{\"statement\": "
             f"\"Какой срок ответа дилеру считать целевым?\", \"source_ns\": [{n_mat}, {n_seg}]}}}}</intent>")
    out = ask.answer(lib, pid, "Сделай из этого вопрос для клиента: " + Q, True, scripted(reply))
    created = out["created"]
    assert created and created["label"].startswith("Q-") and "<intent>" not in out["answer"]
    atom = lib.get_atom(created["atom_id"])
    assert atom["type"] == "question" and atom["statement"] == "Какой срок ответа дилеру считать целевым?"
    quotes = {(e["source_id"], e["quote"]) for e in atom["evidence"]}
    assert (project["meeting"], "Срок ответа дилеру два часа, это важно") in quotes
    mat = next(e for e in atom["evidence"] if e["source_id"] == project["sla"])
    assert mat["quote"] == "Ответ дилеру по заявке даётся не позднее двух часов." and mat["segment_idx"] == 0
    assert lib.ask_history(pid)[0]["created"] == created


def test_the_intent_creates_nothing_when_business_analysis_is_off(lib, pid, project):
    lib.update_project(pid, analysis=False)
    before = len(lib.list_atoms(pid))
    reply = ("Сделал вопрос [Источник 1].\n<intent>{\"create_question\": {\"statement\": \"Какой срок?\", "
             "\"source_ns\": [1]}}</intent>")
    out = ask.answer(lib, pid, "Сделай из этого вопрос для клиента: " + Q, True, scripted(reply))
    assert out["created"] is None and "<intent>" not in out["answer"] and len(lib.list_atoms(pid)) == before


def test_history_route_lists_newest_first_and_delete_removes_one(client, lib, pid, project):
    a = ask.answer(lib, pid, "Первый вопрос про срок ответа дилеру?", False, scripted("Да [Источник 1]."))
    time.sleep(0.01)
    b = ask.answer(lib, pid, "Второй вопрос про срок ответа дилеру?", False, scripted("Нет [Источник 1]."))
    body = client.get(f"/api/projects/{pid}/ask/history?limit=50").get_json()
    assert [i["id"] for i in body["items"]] == [b["id"], a["id"]]
    assert body["searchable"] is True and body["items"][1]["context_only"] is False
    assert client.delete(f"/api/ask/{a['id']}").status_code == 200
    assert [i["id"] for i in client.get(f"/api/projects/{pid}/ask/history").get_json()["items"]] == [b["id"]]
    assert client.delete(f"/api/ask/{a['id']}").status_code == 404


def test_history_survives_a_restart(lib, pid, project, tmp_path):
    ask.answer(lib, pid, Q, True, scripted("Два часа [Источник 1]."))
    again = Store(root=lib.root, user="ba")
    assert [r["question"] for r in again.ask_history(pid)] == [Q]


def wait_job(client, job_id):
    for _ in range(200):
        job = client.get(f"/job/{job_id}").get_json()
        if job["status"] != "processing":
            return job
        time.sleep(0.02)
    raise AssertionError("the job did not finish")


def test_ask_route_streams_into_the_job_and_returns_the_result(client, app_module, lib, pid, project, monkeypatch):
    monkeypatch.setattr(app_module.settings, "secret", lambda name: "sk-test")
    monkeypatch.setattr(app_module, "_ask_generate", lambda prefs, key: scripted("Два часа [Источник 1]."))
    r = client.post(f"/api/projects/{pid}/ask", json={"question": Q, "context_only": True})
    assert r.status_code == 200
    job = wait_job(client, r.get_json()["job"])
    assert job["status"] == "done", job
    res = job["result"]
    assert set(res) >= {"answer", "citations", "created", "sources_used", "elapsed"}
    assert job["partial"] == "Два часа [Источник 1]." and res["citations"][0]["n"] == 1
    assert client.post(f"/api/projects/{pid}/ask", json={"question": "  "}).status_code == 400
    assert client.post("/api/projects/nope/ask", json={"question": Q}).status_code == 404


def test_ask_without_a_ready_provider_returns_the_summary_setup_error(client, app_module, lib, pid, monkeypatch):
    monkeypatch.setattr(app_module.settings, "secret", lambda name: None)
    monkeypatch.setattr(app_module.settings, "load_settings",
                        lambda: {**app_module.settings.DEFAULTS, "llm_provider": "claude"})
    r = client.post(f"/api/projects/{pid}/ask", json={"question": Q})
    s = client.post("/summarize", json={"text": "x"})
    assert r.status_code == s.status_code == 400 and r.get_json() == s.get_json()
    assert r.get_json()["needs_setup"] is True


def test_a_local_only_project_never_calls_claude(client, app_module, lib, pid, project, monkeypatch):
    lib.update_project(pid, local_only=True)
    monkeypatch.setattr(app_module.settings, "secret", lambda name: "sk-test")
    monkeypatch.setattr(app_module.settings, "load_settings",
                        lambda: {**app_module.settings.DEFAULTS, "llm_provider": "claude"})
    monkeypatch.setattr(local_llm, "ready", lambda: True)
    monkeypatch.setattr(summarize_mod, "local_model_id", lambda prefs: "local-x")

    def no_claude(*a, **k):
        raise AssertionError("Claude was called for a local-only project")
    monkeypatch.setattr(summarize_mod, "summarize_with_claude", no_claude)
    monkeypatch.setattr(summarize_mod.anthropic, "Anthropic", no_claude)
    local = []

    def fake_local(transcript, model_id, on_delta, title=None, opener=None, system=None, user=None):
        local.append(model_id)
        on_delta("Два часа [Источник 1].")
        return "Два часа [Источник 1]."
    monkeypatch.setattr(summarize_mod, "summarize_with_local", fake_local)
    r = client.post(f"/api/projects/{pid}/ask", json={"question": Q})
    job = wait_job(client, r.get_json()["job"])
    assert job["status"] == "done", job
    assert local == ["local-x"] and job["result"]["citations"]


def test_the_ask_skill_is_built_in_and_editable_like_the_recaps(monkeypatch, tmp_path):
    monkeypatch.setenv("DICTUM_DATA_DIR", str(tmp_path))
    s = skills.resolve()["ask"]
    assert s.name == "ask" and s.builtin and s.error is None
    copy = skills.create("ask", title="Мой Спросить")
    skills.save(copy.name, instructions="Отвечай очень коротко.")
    skills.set_global("ask", copy.name)
    system = ask.system_prompt(skills.resolve())
    assert system.startswith("Отвечай очень коротко.") and "[Источник N]" in system
