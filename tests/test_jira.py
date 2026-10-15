import io
import json
import urllib.error
import urllib.parse

import pytest

from core import backlog, frd, jira
from core.atlassian_auth import AtlassianAuth, AuthError, AuthRequired, FileStore, MemoryStore
from core.fake_jira import FakeJira
from core.mcp_client import McpError, McpSession, RateLimited
from core.store import Store
from tests.test_backlog import decomposition
from tests.test_frd import PREFS, full_reply, llm, seed
from tests.test_recorder import wait_for


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture()
def store(tmp_path):
    return Store(root=str(tmp_path / "lib"), user="ba")


def with_backlog(store):
    pid, *_ = seed(store)
    frd.build(store, pid, PREFS, "k", complete=llm(full_reply()))
    backlog.build(store, pid, PREFS, "k", complete=llm(decomposition()))
    return pid


def target(store, pid, fake):
    types = jira.suggest_types([{"name": t["name"], "subtask": t["subtask"], "level": t["hierarchyLevel"]}
                                for t in fake.types])
    return store.set_jira_target(pid, fake.cloud_id, fake.site, fake.project_key, "Sandbox", types)


def rows_by(plan, action):
    return [r for r in plan["rows"] if r["action"] == action]


# ── mapping ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("localized,expect", [
    (True, {"epic": "Эпик", "story": "История", "nfr": "Задача", "subtask": "Подзадача"}),
    (False, {"epic": "Epic", "story": "Story", "nfr": "Task", "subtask": "Sub-task"}),
])
def test_issue_types_are_mapped_by_meaning_not_name(localized, expect):
    fake = FakeJira(localized=localized)
    assert jira.suggest_types(jira.projects(fake, "c")[0]["issue_types"]) == expect


def test_sites_are_deduplicated_and_jira_only():
    assert jira.sites(FakeJira()) == [{"cloud_id": "cloud-1", "url": "https://sandbox.atlassian.net", "name": "sandbox"}]


# ── preview and push ─────────────────────────────────────────────────────────

def test_preview_is_read_only_and_follows_the_ticks(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    plan = jira.plan(store, pid, fake)
    assert fake.writes == [], "no write before the button (BR-11)"
    assert plan["counts"] == {"create": 4, "update": 0, "unchanged": 0, "skip": 3, "blocked": 0}
    kinds = [r["kind"] for r in rows_by(plan, "create")]
    assert kinds == ["epic", "epic", "story", "story"], "parents come first"
    assert {r["kind"] for r in rows_by(plan, "skip")} == {"subtask", "nfr"}, "generated sub-tasks and NFRs unticked"


def test_push_creates_parents_first_with_labels_quotes_and_links(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    ids = [r["item_id"] for r in rows_by(jira.plan(store, pid, fake), "create")]
    result = jira.push(store, pid, fake, ids)
    assert len(result["done"]) == 4 and result["failed"] == []
    creates = [a for t, a in fake.writes if t == "createJiraIssue"]
    assert [a["issueTypeName"] for a in creates] == ["Эпик", "Эпик", "История", "История"]
    story = next(i for i in fake.issues.values() if i["fields"]["issuetype"]["name"] == "История")
    assert story["fields"]["parent"]["key"].startswith("SBX-")
    desc = story["fields"]["description"]
    assert "Критерии приёмки" in desc and "Дано входящий звонок" in desc
    assert "раздел 3.1 · FR-1" in desc and "> «карточка клиента»" in desc, "FRD reference and a verbatim quote"
    assert any(lb.startswith("rw-") for lb in story["fields"]["labels"]) and "requirements-workbench" in story["fields"]["labels"]
    items = {i["id"]: i for i in store.backlog(pid)}
    assert all(items[d["item_id"]]["jira_key"] == d["key"] and d["url"].endswith(d["key"]) for d in result["done"])


def test_second_push_is_unchanged_then_update_after_an_edit(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    jira.push(store, pid, fake, [r["item_id"] for r in rows_by(jira.plan(store, pid, fake), "create")])
    plan = jira.plan(store, pid, fake)
    assert plan["counts"]["unchanged"] == 4 and plan["counts"]["create"] == 0
    story = next(i for i in store.backlog(pid) if i["kind"] == "story")
    store.update_backlog_item(story["id"], body="Как оператор, я хочу новое")
    plan = jira.plan(store, pid, fake)
    assert [r["item_id"] for r in rows_by(plan, "update")] == [story["id"]]
    before = len(fake.issues)
    jira.push(store, pid, fake, [story["id"]])
    assert len(fake.issues) == before, "update never creates"
    assert fake.issues[store.get_backlog_item(story["id"])["jira_key"]]["fields"]["description"].startswith("Как оператор, я хочу новое")


def test_retry_after_failure_does_not_duplicate(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    ids = [r["item_id"] for r in rows_by(jira.plan(store, pid, fake), "create")]
    real_create = fake.createJiraIssue
    count = {"n": 0}

    def flaky(**a):                                  # the 3rd create reaches Jira but the answer is lost
        count["n"] += 1
        out = real_create(**a)
        if count["n"] == 3:
            raise McpError("connection reset")
        return out
    fake.createJiraIssue = flaky
    first = jira.push(store, pid, fake, ids)
    assert len(first["done"]) == 3 and len(first["failed"]) == 1
    fake.createJiraIssue = real_create
    plan = jira.plan(store, pid, fake)
    lost = next(r for r in plan["rows"] if r["item_id"] == first["failed"][0]["item_id"])
    assert "found_by_label" in lost["flags"] and lost["action"] in ("update", "unchanged"), "found, not re-created"
    jira.push(store, pid, fake, [lost["item_id"]])
    assert len(fake.issues) == 4, "no duplicate issue after the retry (BR-15)"


def test_edited_in_jira_is_flagged(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    jira.push(store, pid, fake, [r["item_id"] for r in rows_by(jira.plan(store, pid, fake), "create")])
    story = next(i for i in store.backlog(pid) if i["kind"] == "story")
    fake.touch_in_jira(story["jira_key"], summary="Changed by the team")
    row = next(r for r in jira.plan(store, pid, fake)["rows"] if r["item_id"] == story["id"])
    assert "changed_in_jira" in row["flags"]


def test_subtask_needs_its_story(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    sub = next(i for i in store.backlog(pid) if i["kind"] == "subtask")
    store.set_backlog_included(pid, [sub["id"]], True)            # ticks its story and epic too
    plan = jira.plan(store, pid, fake)
    assert next(r for r in plan["rows"] if r["item_id"] == sub["id"])["action"] == "create"
    ids = [r["item_id"] for r in rows_by(plan, "create")]
    jira.push(store, pid, fake, ids)
    created_sub = next(i for i in fake.issues.values() if i["fields"]["issuetype"]["name"] == "Подзадача")
    assert created_sub["fields"]["parent"]["key"] == store.get_backlog_item(sub["parent_id"])["jira_key"]


def test_no_mapping_blocks_the_row(store):
    pid = with_backlog(store)
    fake = FakeJira()
    store.set_jira_target(pid, fake.cloud_id, fake.site, fake.project_key, "Sandbox",
                          {"epic": None, "story": "История", "nfr": "Задача", "subtask": "Подзадача"})
    plan = jira.plan(store, pid, fake)
    assert {r["kind"] for r in rows_by(plan, "blocked")} == {"epic"}
    assert all(r["reason"] == "no_type" for r in rows_by(plan, "blocked"))


def test_push_without_rows_is_refused(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    with pytest.raises(jira.JiraError):
        jira.push(store, pid, fake, [])
    assert fake.writes == []


# ── MCP transport ────────────────────────────────────────────────────────────

class Resp(io.BytesIO):
    def __init__(self, body, ctype="application/json", headers=None):
        super().__init__(body.encode())
        self.headers = {"Content-Type": ctype, **(headers or {})}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"{}"))


def test_mcp_session_handles_sse_session_ids_and_token_refresh():
    sent, tokens = [], []
    script = [
        lambda m: Resp(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {}}), headers={"Mcp-Session-Id": "S1"}),
        lambda m: Resp(""),                                                     # notifications/initialized
        lambda m: (_ for _ in ()).throw(http_error(401)),                        # expired token
        lambda m: Resp("event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {
            "content": [{"type": "text", "text": json.dumps({"key": "SBX-1"})}]}}) + "\n\n", "text/event-stream"),
    ]

    def opener(req, timeout=None):
        m = json.loads(req.data)
        sent.append((m.get("method"), req.headers.get("Mcp-session-id"), req.headers.get("Authorization")))
        return script.pop(0)(m)

    s = McpSession("https://mcp/x", lambda force_refresh=False: tokens.append(force_refresh) or ("new" if force_refresh else "old"),
                   opener=opener, sleep=lambda s: None)
    assert s.call("createJiraIssue", summary="x") == {"key": "SBX-1"}
    assert [x[0] for x in sent] == ["initialize", "notifications/initialized", "tools/call", "tools/call"]
    assert sent[2][1] == "S1" and sent[3][2] == "Bearer new", "session id kept, retried with a refreshed token"


def test_mcp_session_retries_rate_limits_then_gives_up():
    attempts = []

    def opener(req, timeout=None):
        m = json.loads(req.data)
        if m.get("method") == "initialize":
            return Resp(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {}}))
        if m.get("method") == "notifications/initialized":
            return Resp("")
        attempts.append(1)
        raise http_error(429)
    s = McpSession("https://mcp/x", lambda force_refresh=False: "t", opener=opener, sleep=lambda s: None, retries=3)
    with pytest.raises(RateLimited):
        s.call("searchJiraIssuesUsingJql", jql="x")
    assert len(attempts) == 4


def test_tool_error_is_reported():
    def opener(req, timeout=None):
        m = json.loads(req.data)
        if m.get("method") == "notifications/initialized":
            return Resp("")
        result = {} if m["method"] == "initialize" else {"isError": True, "content": [{"type": "text", "text": "Field 'x' is required"}]}
        return Resp(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": result}))
    with pytest.raises(McpError, match="required"):
        McpSession("https://mcp/x", lambda force_refresh=False: "t", opener=opener).call("createJiraIssue")


# ── sign-in ──────────────────────────────────────────────────────────────────

class FakeAtlassian:
    def __init__(self):
        self.requests = []
        self.clients = 0

    def __call__(self, req, timeout=None):
        url = req.full_url
        body = req.data.decode() if req.data else ""
        self.requests.append((url, body))
        if url.endswith("/.well-known/oauth-authorization-server"):
            return Resp(json.dumps({"authorization_endpoint": "https://mcp/authorize", "token_endpoint": "https://mcp/token",
                                    "registration_endpoint": "https://mcp/register", "revocation_endpoint": "https://mcp/token"}))
        if url.endswith("/register"):
            self.clients += 1
            return Resp(json.dumps({"client_id": f"client-{self.clients}"}))
        if url.endswith("/token"):
            form = dict(urllib.parse.parse_qsl(body))
            if form.get("grant_type") == "authorization_code":
                assert form["code_verifier"] and form["code"] == "CODE"
                return Resp(json.dumps({"access_token": "A1", "refresh_token": "R1", "expires_in": 3600}))
            if form.get("grant_type") == "refresh_token":
                return Resp(json.dumps({"access_token": "A2", "expires_in": 3600}))
            return Resp("{}")
        raise AssertionError(url)


def test_oauth_register_pkce_exchange_refresh_disconnect():
    clock = [1000.0]
    atl = FakeAtlassian()
    auth = AtlassianAuth(store=MemoryStore(), opener=atl, clock=lambda: clock[0], base="https://mcp")
    url = auth.start("http://127.0.0.1:47823/api/jira/callback")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["code_challenge_method"] == "S256" and q["client_id"] == "client-1" and q["redirect_uri"].endswith("/callback")
    auth.start("http://127.0.0.1:47823/api/jira/callback")
    assert atl.clients == 1, "the app registers once per redirect address"
    with pytest.raises(AuthError, match="expired"):
        auth.finish("wrong-state", "CODE")
    auth.finish(q["state"], "CODE")
    assert auth.connected() and auth.access_token() == "A1"
    clock[0] += 4000                                              # past expiry → refresh, keeps the refresh token
    assert auth.access_token() == "A2" and auth.store.get("tokens")["refresh_token"] == "R1"
    auth.disconnect()
    assert not auth.connected()
    with pytest.raises(AuthRequired):
        auth.access_token()


def test_requests_carry_the_app_user_agent():
    """Cloudflare in front of Atlassian blocks Python's default user agent (error 1010)."""
    seen = []

    def opener(req, timeout=None):
        seen.append(req.headers.get("User-agent"))
        m = json.loads(req.data) if req.data else {}
        if m.get("method") == "notifications/initialized":
            return Resp("")
        return Resp(json.dumps({"jsonrpc": "2.0", "id": m.get("id"), "result": {"content": []}}))
    McpSession("https://mcp/x", lambda force_refresh=False: "t", opener=opener).call("getAccessibleAtlassianResources")
    atl = FakeAtlassian()
    AtlassianAuth(store=MemoryStore(), opener=lambda req, timeout=None: seen.append(req.headers.get("User-agent")) or atl(req),
                  base="https://mcp").metadata()
    assert seen and all(ua and ua.startswith("RequirementsWorkbench/") for ua in seen)


def test_tokens_are_kept_in_a_private_file_not_the_keychain(tmp_path, monkeypatch):
    import os
    import stat
    import sys
    monkeypatch.setitem(sys.modules, "keyring", None)            # importing keyring would fail loudly
    store = FileStore(str(tmp_path / "jira-auth.json"))
    value = {"access_token": "x" * 4500, "refresh_token": "r"}
    store.set("tokens", value)
    store.set("clients", {"http://127.0.0.1/cb": "c1"})
    assert store.get("tokens") == value and store.get("clients") == {"http://127.0.0.1/cb": "c1"}
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(tmp_path / "jira-auth.json").st_mode) == 0o600
    store.delete("tokens")
    assert store.get("tokens") is None and store.get("clients")
    assert AtlassianAuth().store.__class__.__name__ == "FileStore"


# ── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    s = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", s)
    return s


def test_api_preview_and_push_need_the_project_key(client, app_module, lib, monkeypatch):
    pid = with_backlog(lib)
    fake = FakeJira()
    monkeypatch.setattr(app_module, "_jira_session", lambda: fake)
    sites = client.get("/api/jira/sites").get_json()["sites"]
    projects = client.get(f"/api/jira/projects?cloud_id={sites[0]['cloud_id']}").get_json()["projects"]
    assert projects[0]["suggested_types"]["story"] == "История"
    client.put(f"/api/projects/{pid}/jira/target", json={"cloud_id": sites[0]["cloud_id"], "site_url": sites[0]["url"],
                                                          "project_key": "SBX", "types": projects[0]["suggested_types"]})
    job = client.post(f"/api/projects/{pid}/jira/preview").get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    plan = client.get(f"/job/{job}").get_json()["result"]
    ids = [r["item_id"] for r in plan["rows"] if r["action"] == "create"]
    assert fake.writes == []
    r = client.post(f"/api/projects/{pid}/jira/push", json={"item_ids": ids, "confirm_project_key": "QAAP"})
    assert r.status_code == 400 and fake.writes == [], "a push naming another project is refused"
    job = client.post(f"/api/projects/{pid}/jira/push", json={"item_ids": ids, "confirm_project_key": "SBX"}).get_json()["job_id"]
    assert wait_for(lambda: client.get(f"/job/{job}").get_json()["status"] == "done")
    assert len(client.get(f"/job/{job}").get_json()["result"]["done"]) == 4


def test_api_not_connected(client, app_module, lib, monkeypatch):
    def not_connected():
        raise AuthRequired("Jira is not connected.")
    monkeypatch.setattr(app_module, "_jira_session", lambda: type("S", (), {"call": lambda self, *a, **k: not_connected()})())
    r = client.get("/api/jira/sites")
    assert r.status_code == 401 and r.get_json()["needs_connect"]


# ── private sign-in window ───────────────────────────────────────────────────

def test_private_window_prefers_installed_browsers():
    from core.private_browser import find_browser, open_private
    mac = find_browser("darwin", exists=lambda p: p == "/Applications/Firefox.app")
    assert mac == (["open", "-na", "Firefox", "--args"], "-private-window", "Firefox")
    win = find_browser("win32", exists=lambda p: p.endswith("msedge.exe"), env={"PROGRAMFILES": r"C:\PF"})
    assert win[1] == "--inprivate" and win[0][0].endswith("msedge.exe")
    assert find_browser("darwin", exists=lambda p: False) is None
    ran = []
    name = open_private("https://mcp.atlassian.com/x", run=lambda cmd, **k: ran.append(cmd),
                        platform="darwin", exists=lambda p: p == "/Applications/Google Chrome.app")
    assert name == "Google Chrome" and ran == [["open", "-na", "Google Chrome", "--args", "--incognito", "https://mcp.atlassian.com/x"]]


def test_connect_opens_a_private_window_by_default(client, app_module, lib, monkeypatch):
    import core.private_browser as pb
    opened = []
    monkeypatch.setattr(pb, "open_private", lambda url, **k: opened.append(url) or "Google Chrome")
    monkeypatch.setattr(app_module.jira_auth, "start", lambda redirect: "https://mcp.atlassian.com/v1/authorize?x=1")
    r = client.post("/api/jira/connect", json={}).get_json()
    assert r["opened_private"] == "Google Chrome" and opened == ["https://mcp.atlassian.com/v1/authorize?x=1"]
    r = client.post("/api/jira/connect", json={"private": False}).get_json()
    assert r["opened_private"] is None and len(opened) == 1


# ── rebuild keeps Jira identity (PM-07) ──────────────────────────────────────

def test_rebuilt_backlog_updates_the_same_issues_instead_of_duplicating(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    first = jira.push(store, pid, fake, [r["item_id"] for r in rows_by(jira.plan(store, pid, fake), "create")])
    keys = {d["key"] for d in first["done"]}
    sub = next(i for i in store.backlog(pid) if i["kind"] == "subtask")
    store.set_backlog_included(pid, [sub["id"]], True)
    reply = decomposition()
    reply["epics"][0]["stories"][0]["story"] = "Как старший оператор, я хочу видеть карточку сразу"
    r = backlog.build(store, pid, PREFS, "k", complete=llm(reply))
    assert r["matched"] >= 4 and r["orphans"] == []
    items = store.backlog(pid)
    assert {i["jira_key"] for i in items if i.get("jira_key")} == keys, "Jira links survive the rebuild"
    assert next(i for i in items if i["id"] == sub["id"])["included"], "the BA's tick survives too"
    plan = jira.plan(store, pid, fake)
    assert plan["counts"]["create"] == 1, "only the sub-task that was never pushed"
    assert [r["kind"] for r in rows_by(plan, "update")] == ["story"]
    jira.push(store, pid, fake, [r["item_id"] for r in rows_by(plan, "update")])
    assert len(fake.issues) == len(keys), "no duplicates"


def test_requirement_removed_on_rebuild_leaves_an_orphan_to_handle(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    jira.push(store, pid, fake, [r["item_id"] for r in rows_by(jira.plan(store, pid, fake), "create")])
    reply = decomposition()
    reply["epics"][0]["title"] = "Совсем другой эпик"
    reply["epics"][0]["stories"] = [reply["epics"][0]["stories"][1]]          # FR-1 story gone (FR-77 is fake)
    r = backlog.build(store, pid, PREFS, "k", complete=llm(reply))
    orphan_keys = {o["key"] for o in r["orphans"]}
    assert orphan_keys and orphan_keys == {o["key"] for o in store.jira_orphans(pid)}
    plan = jira.plan(store, pid, fake)
    assert {o["key"] for o in plan["orphans"]} == orphan_keys
    store.forget_jira_orphan(pid, sorted(orphan_keys)[0])
    assert len(store.jira_orphans(pid)) == len(orphan_keys) - 1


def test_local_only_projects_keep_client_quotes_out_of_jira(store):
    pid = with_backlog(store)
    fake = FakeJira()
    target(store, pid, fake)
    store.update_project(pid, local_only=True)
    story = next(i for i in store.backlog(pid) if i["kind"] == "story")
    store.update_backlog_item(story["id"], priority="must")
    jira.push(store, pid, fake, [r["item_id"] for r in rows_by(jira.plan(store, pid, fake), "create")])
    issue = fake.issues[store.get_backlog_item(story["id"])["jira_key"]]
    desc = issue["fields"]["description"]
    assert "FR-1" in desc and "«карточка клиента»" not in desc, "reference only, no verbatim quote"
    assert "moscow-must" in issue["fields"]["labels"]
    store.update_project(pid, jira_quotes="full")
    assert jira.plan(store, pid, fake)["quotes"] == "full"
    assert jira.local_status(store, pid)["pending"] >= 1, "the policy change shows as work to push"
