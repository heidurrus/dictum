"""Backlog → Jira Cloud through the Atlassian Remote MCP (spec increment 4b, FR-JIRA-*, D-05, D-08).

Deterministic, no LLM: the same backlog gives the same tool calls in the same order.
The preview only reads (searchJiraIssuesUsingJql); nothing is written before the
BA presses the button (BR-11). Every issue carries the label rw-<item uuid>, so a
retry after a failure finds what was already created instead of duplicating it
(BR-15). Only fields the workbench owns are written: summary, description, labels,
parent (FR-JIRA-04 AC2).
"""
import datetime
import hashlib
import json

from core.frd import decompose_documents, req_blocks, requirements_document
from core.llm import output_language

APP_LABEL = "requirements-workbench"
ORDER = {"epic": 0, "story": 1, "nfr": 2, "subtask": 3}
TEXT = {
    "ru": {"ac": "Критерии приёмки", "given": "Дано", "when": "когда", "then": "тогда", "source": "Источник",
           "section": "раздел", "goal": "Бизнес-цель", "made": "Создано в Dictum"},
    "en": {"ac": "Acceptance criteria", "given": "Given", "when": "when", "then": "then", "source": "Source",
           "section": "section", "goal": "Business goal", "made": "Created in Dictum"},
}


class JiraError(Exception):
    """A user-facing Jira problem."""


def label(item):
    return f"rw-{item['id']}"


# ── site, projects, issue types ──────────────────────────────────────────────

def sites(session):
    """Jira sites the account can use (deduplicated: the same site is listed once per product)."""
    out = {}
    for r in session.call("getAccessibleAtlassianResources") or []:
        if any("jira" in s for s in r.get("scopes") or []):
            out[r["id"]] = {"cloud_id": r["id"], "url": r.get("url"), "name": r.get("name")}
    return list(out.values())


def projects(session, cloud_id, search=None):
    args = {"cloudId": cloud_id, "maxResults": 50, "expandIssueTypes": True, "action": "create"}
    if search:
        args["searchString"] = search
    body = session.call("getVisibleJiraProjects", **args) or {}
    return [{"key": p["key"], "name": p.get("name"), "issue_types": [
        {"id": t["id"], "name": t["name"], "subtask": bool(t.get("subtask")), "level": t.get("hierarchyLevel", 0)}
        for t in p.get("issueTypes") or []]} for p in body.get("values") or []]


def suggest_types(issue_types):
    """Map backlog kinds to the project's issue types by what they are, not by name (types are often
    localised: Эпик / История / Задача / Подзадача)."""
    def find(pred, words=()):
        cands = [t for t in issue_types if pred(t)]
        for w in words:
            for t in cands:
                if w in t["name"].lower():
                    return t["name"]
        return cands[0]["name"] if cands else None
    standard = lambda t: not t["subtask"] and t.get("level", 0) == 0  # noqa: E731
    story = find(standard, ("story", "истори")) or find(lambda t: not t["subtask"])
    return {"epic": find(lambda t: t.get("level", 0) >= 1, ("epic", "эпик")),
            "story": story,
            "nfr": find(standard, ("task", "задач")) or story,
            "subtask": find(lambda t: t["subtask"], ("sub", "подзадач"))}


# ── what an item becomes in Jira ─────────────────────────────────────────────

def _sources(version):
    return {b["id"]: b.get("sources") or [] for _n, _k, b in req_blocks(version["content"])} if version else {}


def quote_policy(project):
    """What of the client's words goes into Jira (PM-04): full quotes, a link-like reference, or nothing.
    "auto": full, except for Local only projects, where only the reference goes."""
    p = (project or {}).get("jira_quotes") or "auto"
    if p == "auto":
        return "link" if (project or {}).get("local_only") else "full"
    return p


def description(item, doc_title, version, lang="ru", quotes="full", docs=None):
    """Markdown description with the document reference and (policy allowing) a verbatim quote (FR-JIRA-05).
    docs: {document id: (document, version)} when requirements come from several documents."""
    t = TEXT.get(lang, TEXT["ru"])
    parts = []
    if item["kind"] == "epic" and item.get("goal"):
        parts.append(f"**{t['goal']}:** {item['goal']}")
    if item.get("body"):
        parts.append(item["body"])
    elif item["kind"] == "nfr":
        parts.append(item["title"])
    if item.get("acceptance"):
        lines = []
        for a in item["acceptance"]:
            bits = [f"{t['given']} {a['given']}" if a.get("given") else "", f"{t['when']} {a['when']}" if a.get("when") else "",
                    f"{t['then']} {a['then']}" if a.get("then") else ""]
            lines.append("- " + ", ".join(b for b in bits if b))
        parts.append(f"**{t['ac']}**\n" + "\n".join(lines))
    refs = item.get("refs") or []
    if refs and version:
        by_doc = {}
        for r in refs:
            d, v = (docs or {}).get(r.get("doc_id")) or ({"title": doc_title}, version)
            by_doc.setdefault((d["title"], v["number"]), (v, []))[1].append(r)
        srcs = {}
        for v, _rs in by_doc.values():
            srcs.update(_sources(v))
        lines = [f"**{t['source']}:** " + "; ".join(
            f"{title} v{num} · " + ", ".join(f"{t['section']} {r['section']} · {r['id']}" for r in rs)
            for (title, num), (_v, rs) in by_doc.items())]
        for r in (refs[:3] if quotes != "none" else []):
            for s in (srcs.get(r["id"]) or [])[:1]:
                when = []
                if s.get("source_date"):
                    when.append(datetime.datetime.fromtimestamp(s["source_date"]).strftime("%d.%m.%Y"))
                if s.get("start") is not None:
                    m, sec = divmod(int(s["start"]), 60)
                    when.append(f"{m:02d}:{sec:02d}")
                who = s.get("speaker_name") or s.get("speaker") or ""
                meta = " · ".join(x for x in [who, " ".join(when), s.get("source_title") or ""] if x)
                if quotes == "full":
                    lines.append(f"> «{s['quote']}»" + (f" — {meta}" if meta else ""))
                elif meta:
                    lines.append(f"- {meta}")
        parts.append("\n".join(lines))
    parts.append(f"_{t['made']} · {label(item)}_")
    return "\n\n".join(parts)


def payload(item, target, doc_title, version, lang, parent_key=None, quotes="full", docs=None):
    """The fields the workbench owns, exactly as they will be sent."""
    kind_type = (target.get("types") or {}).get(item["kind"])
    labels = [APP_LABEL, label(item)] + ([f"moscow-{item['priority']}"] if item.get("priority") else [])
    return {"issueTypeName": kind_type, "summary": item["title"][:250],
            "description": description(item, doc_title, version, lang, quotes, docs),
            "labels": labels, "parent": parent_key}


def local_status(store, project_id):
    """Without calling Jira: how many included items would be created or updated (PM-03)."""
    target = store.jira_target(project_id)
    items = store.backlog(project_id)
    pushed = [i for i in items if i.get("jira_key")]
    if not target or not pushed:
        return {"pushed": len(pushed), "pending": None}
    doc = requirements_document(store, project_id)
    version = store.version(doc["id"])
    docs = {d["id"]: (d, v) for d, v in decompose_documents(store, project_id)}
    project = store.get_project(project_id)
    lang = output_language(project) or (version or {}).get("content", {}).get("language", "ru")
    by_id = {i["id"]: i for i in items}
    pending = 0
    for item in items:
        if not item["included"]:
            continue
        parent = by_id.get(item.get("parent_id"))
        p = payload(item, target, doc["title"], version, lang, parent.get("jira_key") if parent else None,
                    quote_policy(project), docs)
        if not item.get("jira_key") or fingerprint(p) != item.get("jira_hash"):
            pending += 1
    return {"pushed": len(pushed), "pending": pending}


def fingerprint(p):
    return hashlib.sha256(json.dumps(p, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


# ── preview (read-only) ──────────────────────────────────────────────────────

def _search(session, cloud_id, jql, fields):
    out, token = [], None
    for _ in range(20):
        args = {"cloudId": cloud_id, "jql": jql, "fields": fields, "maxResults": 100}
        if token:
            args["nextPageToken"] = token
        body = session.call("searchJiraIssuesUsingJql", **args) or {}
        out += body.get("issues") or body.get("values") or []
        token = body.get("nextPageToken")
        if not token or body.get("isLast"):
            break
    return out


def _chunks(seq, n=40):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def plan(store, project_id, session):
    """Preview rows: create / update / unchanged / skip / blocked, computed with read calls only."""
    target = store.jira_target(project_id)
    if not target:
        raise JiraError("Choose the Jira site and project first.")
    types = target.get("types") or {}
    doc = requirements_document(store, project_id)
    version = store.version(doc["id"])
    docs = {d["id"]: (d, v) for d, v in decompose_documents(store, project_id)}
    project = store.get_project(project_id)
    quotes = quote_policy(project)
    lang = output_language(project) or (version or {}).get("content", {}).get("language", "ru")
    items = store.backlog(project_id)
    by_id = {i["id"]: i for i in items}

    # Issues this app created before (by label) and the current state of linked ones.
    remote, by_label = {}, {}
    keys = [i["jira_key"] for i in items if i.get("jira_key")]
    for chunk in _chunks(keys):
        for issue in _search(session, target["cloud_id"], "key in (" + ",".join(chunk) + ")", ["summary", "updated", "labels", "status"]):
            remote[issue["key"]] = issue
    unlinked = [i for i in items if i["included"] and not i.get("jira_key")]
    for chunk in _chunks(unlinked):
        jql = f'project = "{target["project_key"]}" AND labels in (' + ",".join(f'"{label(i)}"' for i in chunk) + ")"
        for issue in _search(session, target["cloud_id"], jql, ["summary", "updated", "labels"]):
            for lb in (issue.get("fields") or {}).get("labels") or []:
                if lb.startswith("rw-"):
                    by_label[lb[3:]] = issue

    rows = []
    for item in sorted(items, key=lambda i: (ORDER[i["kind"]], i["position"])):
        parent = by_id.get(item.get("parent_id"))
        row = {"item_id": item["id"], "kind": item["kind"], "title": item["title"], "key": item.get("jira_key"),
               "url": item.get("jira_url"), "parent_id": item.get("parent_id"), "flags": [],
               "parent_title": parent["title"] if parent else None}
        adopted = by_label.get(item["id"])
        if not row["key"] and adopted:                       # created earlier but not recorded locally
            row["key"] = adopted["key"]
            row["url"] = f"{target['site_url']}/browse/{adopted['key']}"
            row["flags"].append("found_by_label")
        if not item["included"]:
            row["action"] = "skip"
        elif not types.get(item["kind"]):
            row["action"], row["reason"] = "blocked", "no_type"
        elif item["kind"] == "subtask" and not (parent and (parent.get("jira_key") or parent["included"])):
            row["action"], row["reason"] = "blocked", "no_parent"
        else:
            parent_key = parent.get("jira_key") if parent else None
            p = payload(item, target, doc["title"], version, lang, parent_key, quotes, docs)
            fp = fingerprint(p)
            if not row["key"]:
                row["action"] = "create"
            elif row["key"] not in remote and "found_by_label" not in row["flags"]:
                row["action"], row["flags"] = "create", row["flags"] + ["missing_in_jira"]
                row["key"] = None
            else:
                row["action"] = "unchanged" if fp == item.get("jira_hash") else "update"
                upd = _ts(((remote.get(row["key"]) or {}).get("fields") or {}).get("updated"))
                mine = _ts(item.get("jira_remote_updated"))
                if upd and mine and upd > mine:
                    row["flags"].append("changed_in_jira")      # FR-JIRA-06: confirm before overwriting
            row["fingerprint"] = fp
        rows.append(row)
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ("create", "update", "unchanged", "skip", "blocked")}
    return {"target": target, "rows": rows, "counts": counts, "orphans": store.jira_orphans(project_id), "quotes": quotes,
            "stale": _stale(store, project_id, version)}


def _stale(store, project_id, version):
    """Is what the preview pushes behind the latest decisions? (PM-03)"""
    from core import backlog, frd
    doc_stale = frd.staleness(store, project_id, version) if version else None
    return {"document": bool(doc_stale and doc_stale["stale"]), "backlog": backlog.stale(store, project_id)["stale"]}


# ── push ─────────────────────────────────────────────────────────────────────

def _key_of(result):
    if isinstance(result, dict):
        return result.get("key") or (result.get("issue") or {}).get("key")
    return None


def _updated_of(result):
    if isinstance(result, dict):
        return (result.get("fields") or {}).get("updated")
    return None


def push(store, project_id, session, item_ids, progress=None):
    """Create/update the chosen items, parents first. Successes are kept even if others fail (FR-JIRA-04 AC4)."""
    report = progress or (lambda pct, msg: None)
    preview = plan(store, project_id, session)             # recomputed right before writing: never stale
    target = preview["target"]
    chosen = set(item_ids or [])
    rows = [r for r in preview["rows"] if r["item_id"] in chosen and r["action"] in ("create", "update")]
    if not rows:
        raise JiraError("Nothing to push: tick at least one row to create or update.")
    doc = requirements_document(store, project_id)
    version = store.version(doc["id"])
    docs = {d["id"]: (d, v) for d, v in decompose_documents(store, project_id)}
    project = store.get_project(project_id)
    quotes = quote_policy(project)
    lang = output_language(project) or (version or {}).get("content", {}).get("language", "ru")
    keys = {i["id"]: i.get("jira_key") for i in store.backlog(project_id)}
    for r in preview["rows"]:
        if r.get("key"):
            keys[r["item_id"]] = r["key"]
    done, failed = [], []
    for n, row in enumerate(rows):
        item = store.get_backlog_item(row["item_id"])
        report(int(100 * n / len(rows)), item["title"][:60])
        parent_key = keys.get(item.get("parent_id")) if item.get("parent_id") else None
        if item["kind"] == "subtask" and not parent_key:
            failed.append({"item_id": item["id"], "title": item["title"], "error": "the parent story isn't in Jira yet"})
            continue
        p = payload(item, target, doc["title"], version, lang, parent_key, quotes, docs)
        try:
            key = keys.get(item["id"])
            if key:
                fields = {"summary": p["summary"], "description": p["description"], "labels": p["labels"]}
                result = session.call("editJiraIssue", cloudId=target["cloud_id"], issueIdOrKey=key, fields=fields,
                                      contentFormat="markdown")
                action = "updated"
            else:
                args = {"cloudId": target["cloud_id"], "projectKey": target["project_key"],
                        "issueTypeName": p["issueTypeName"], "summary": p["summary"], "description": p["description"],
                        "contentFormat": "markdown", "additional_fields": {"labels": p["labels"]}}
                if parent_key:
                    args["parent"] = parent_key
                result = session.call("createJiraIssue", **args)
                key = _key_of(result)
                if not key:
                    raise JiraError("Jira did not return the new issue's key")
                action = "created"
            keys[item["id"]] = key
            url = f"{target['site_url']}/browse/{key}"
            updated = _updated_of(result)
            if not updated:                                 # Jira's own clock, so later edits there are detected
                try:
                    updated = _updated_of(session.call("getJiraIssue", cloudId=target["cloud_id"], issueIdOrKey=key,
                                                       fields=["updated"]))
                except Exception:
                    updated = None
            store.mark_pushed(item["id"], key, url, fingerprint(p), updated)
            done.append({"item_id": item["id"], "title": item["title"], "key": key, "url": url, "action": action})
        except Exception as e:                              # keep going: one bad row must not stop the rest
            failed.append({"item_id": item["id"], "title": item["title"], "error": str(e)[:300]})
    report(100, "Done")
    return {"done": done, "failed": failed, "target": {"project_key": target["project_key"], "site_url": target["site_url"]}}


def _ts(value):
    """Jira timestamps ("2026-09-28T15:00:05.123+0300") → aware datetime; None if missing or unreadable."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
