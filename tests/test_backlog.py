import pytest

from core import backlog, frd, skills
from core.store import Store, StoreError
from tests.test_frd import PREFS, full_reply, llm, seed
from tests.test_recorder import wait_for


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture()
def store(tmp_path):
    return Store(root=str(tmp_path / "lib"), user="ba")


def built(store):
    pid, ids, sid = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    return pid


def decomposition(**over):
    reply = {"epics": [{"title": "Карточка клиента", "goal": "Сократить время обработки звонка", "stories": [
        {"title": "Карточка при звонке", "story": "Как оператор, я хочу видеть карточку при звонке, чтобы не переспрашивать",
         "refs": ["FR-1", "FR-99"], "acceptance": [
             {"given": "входящий звонок с известного номера", "when": "звонок поступает", "then": "карточка открыта"},
             {"given": "номер неизвестен", "when": "звонок поступает", "then": "пустая карточка с поиском"}],
         "subtasks": ["API карточки", "Компонент карточки"]},
        {"title": "Выдуманная", "story": "…", "refs": ["FR-77"], "acceptance": [], "subtasks": []}]}],
        "nfr_links": [{"id": "NFR-1", "stories_for": ["FR-1"]}]}
    reply.update(over)
    return reply


def by_kind(items, kind):
    return [i for i in items if i["kind"] == kind]


# ── building ─────────────────────────────────────────────────────────────────

def test_build_tree_links_defaults_and_coverage(store):
    pid = built(store)
    fake = llm(decomposition())
    r = backlog.build(store, pid, PREFS, "k", complete=fake)
    items = store.backlog(pid)
    epics, stories, subtasks, nfrs = (by_kind(items, k) for k in ("epic", "story", "subtask", "nfr"))
    assert (len(epics), r["frd_version"]) == (2, 1)                       # + "Прочее" for the uncovered FR-2
    first = stories[0]
    assert first["refs"] == [{"id": "FR-1", "section": "3.1", "atom_id": first["refs"][0]["atom_id"],
                              "doc_id": store.document(pid)["id"]}], "unknown refs dropped"
    assert len(first["acceptance"]) == 2 and epics[0]["goal"] == "Сократить время обработки звонка"
    assert all(s["generated"] and not s["included"] for s in subtasks), "generated sub-tasks start unticked"
    assert not any(s["title"] == "Выдуманная" for s in stories), "a story with no real requirement is dropped"
    assert r["uncovered"] == ["FR-2"] and stories[-1]["refs"][0]["id"] == "FR-2"
    nfr = nfrs[0]
    assert not nfr["included"] and nfr["invest"][0]["letter"] == "V" and nfr["invest"][0]["move_to"] == [first["id"]]
    assert [i["kind"] for i in items][:4] == ["epic", "story", "subtask", "subtask"], "tree order"
    assert "Every FR and BR ID must appear" in fake.calls[0]["system"] and "FR-1 (section 3.1)" in fake.calls[0]["user"]


def test_rebuild_keeps_pinned_items(store):
    pid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    story = by_kind(store.backlog(pid), "story")[0]
    store.update_backlog_item(story["id"], body="Отредактировано аналитиком")
    mine = store.add_backlog_item(pid, {"kind": "story", "title": "Своя история"})
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    titles = [i["title"] for i in store.backlog(pid)]
    assert "Своя история" in titles
    assert any(i["body"] == "Отредактировано аналитиком" for i in store.backlog(pid))
    assert sum(t == "Карточка при звонке" for t in titles) == 1, "the edited story stands in for the regenerated one"
    assert store.get_backlog_item(mine["id"])["pinned"]


def test_build_needs_a_document(store):
    pid, *_ = seed(store)
    with pytest.raises(backlog.BacklogError, match="marked for decomposition"):
        backlog.build(store, pid, PREFS, "k", complete=llm())


def test_decompose_skill_is_used(store):
    pid = built(store)
    s = skills.create("split-into-stories")
    skills.save(s.name, instructions="ИСТОРИИ ТОЛЬКО ДЛЯ СТАРШЕГО СМЕНЫ. {language}")
    fake = llm(decomposition())
    backlog.build(store, pid, PREFS, "k", complete=fake, skillset=skills.resolve({"decompose": s.name}))
    assert fake.calls[0]["system"].startswith("ИСТОРИИ ТОЛЬКО ДЛЯ СТАРШЕГО СМЕНЫ. Russian")


# ── editing ──────────────────────────────────────────────────────────────────

def test_include_cascades_down_and_up(store):
    pid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    items = store.backlog(pid)
    epic, story, sub = by_kind(items, "epic")[0], by_kind(items, "story")[0], by_kind(items, "subtask")[0]
    store.set_backlog_included(pid, [epic["id"]], False)
    assert not store.get_backlog_item(story["id"])["included"], "unticking a parent unticks its children"
    store.set_backlog_included(pid, [sub["id"]], True)
    assert store.get_backlog_item(epic["id"])["included"] and store.get_backlog_item(story["id"])["included"]
    assert not store.get_backlog_item(story["id"])["pinned"], "ticking doesn't pin"


def test_edit_pins_and_validates_criteria(store):
    pid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    story = by_kind(store.backlog(pid), "story")[0]
    out = store.update_backlog_item(story["id"], acceptance=[{"given": "a", "when": "b", "then": "c"}, {"given": " "}])
    assert out["acceptance"] == [{"given": "a", "when": "b", "then": "c"}] and out["pinned"]
    with pytest.raises(StoreError):
        store.update_backlog_item(story["id"], title="  ")
    with pytest.raises(StoreError):
        store.update_backlog_item(story["id"], jira_key="X-1")


def test_delete_subtree_and_restore(store):
    pid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    story = by_kind(store.backlog(pid), "story")[0]
    gone = store.delete_backlog_item(story["id"])
    assert len(gone) == 3 and story["id"] not in {i["id"] for i in store.backlog(pid)}
    store.delete_backlog_item(story["id"], restore=True)
    assert len([i for i in store.backlog(pid) if i["parent_id"] == story["id"]]) == 2


def test_move_nfr_into_story_criteria(store):
    pid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    items = store.backlog(pid)
    nfr, story = by_kind(items, "nfr")[0], by_kind(items, "story")[0]
    out = backlog.move_nfr_into(store, nfr["id"], story["id"])
    assert out["acceptance"][-1] == {"given": "", "when": "", "then": nfr["title"]}
    assert {r["id"] for r in out["refs"]} == {"FR-1", "NFR-1"}
    assert not by_kind(store.backlog(pid), "nfr")


def test_invest_findings_are_stored_per_story(store):
    pid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    fake = llm({"findings": [{"id": "S1", "letter": "S", "reason": "Слишком большая", "fix": "Разделить на две"},
                             {"id": "S9", "letter": "I", "reason": "нет такой", "fix": ""}]})
    r = backlog.invest(store, pid, PREFS, "k", complete=fake)
    stories = by_kind(store.backlog(pid), "story")
    assert r == {"checked": 2, "with_findings": 1, "model": "claude-opus-5"}
    assert stories[0]["invest"] == [{"letter": "S", "reason": "Слишком большая", "fix": "Разделить на две"}]
    assert "S1: Карточка при звонке" in fake.calls[0]["user"] and not stories[0]["pinned"]


def test_stale_when_the_document_changes(store):
    pid = built(store)
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    assert backlog.stale(store, pid) == {"built_from": 1, "latest": 1, "stale": False}
    frd.build(store, pid, PREFS, "k", mode="full", complete=llm(full_reply()))
    assert backlog.stale(store, pid)["stale"] is True


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    s = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", s)
    monkeypatch.setattr(app_module.settings, "load_settings", lambda: dict(PREFS))
    monkeypatch.setattr(app_module.settings, "secret", lambda name: "key")
    return s


def test_api_backlog_flow(client, app_module, lib, monkeypatch):
    pid = built(lib)
    fake = llm(decomposition(), {"findings": []})
    real_build, real_invest = backlog.build, backlog.invest
    monkeypatch.setattr(app_module.backlog, "build", lambda *a, **k: real_build(*a, **k, complete=fake))
    monkeypatch.setattr(app_module.backlog, "invest", lambda *a, **k: real_invest(*a, **k, complete=fake))
    assert client.get(f"/api/projects/{pid}/backlog").get_json()["counts"]["story"] == 0
    job = client.post(f"/api/projects/{pid}/backlog/build").get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    body = client.get(f"/api/projects/{pid}/backlog").get_json()
    assert body["counts"] == {"epic": 2, "story": 2, "subtask": 2, "nfr": 1} and body["built_from"] == 1
    story = next(i for i in body["items"] if i["kind"] == "story")
    assert client.patch(f"/api/backlog/{story['id']}", json={"title": "Новое имя"}).get_json()["pinned"]
    added = client.post(f"/api/projects/{pid}/backlog", json={"kind": "subtask", "title": "Миграция", "parent_id": story["id"]})
    assert added.status_code == 200 and added.get_json()["parent_id"] == story["id"]
    epic = next(i for i in body["items"] if i["kind"] == "epic")
    moved = client.post(f"/api/backlog/{epic['id']}/move", json={"direction": "down"}).get_json()
    assert [i["id"] for i in moved["items"] if i["kind"] == "epic"][1] == epic["id"]
    assert moved["items"][-1]["id"] != epic["id"], "children move with their epic"
    job = client.post(f"/api/projects/{pid}/backlog/invest").get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    inc = client.post(f"/api/projects/{pid}/backlog/include", json={"ids": [story["id"]], "included": False}).get_json()
    assert story["id"] in inc["ids"]
    assert client.delete(f"/api/backlog/{story['id']}").status_code == 200


def test_api_backlog_needs_a_document(client, lib):
    pid, *_ = seed(lib)
    r = client.post(f"/api/projects/{pid}/backlog/build")
    assert r.status_code == 400 and "document first" in r.get_json()["error"]
    assert client.post(f"/api/projects/{pid}/backlog/invest").status_code == 400
