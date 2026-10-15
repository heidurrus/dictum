"""Backlog: FRD → epics, stories with acceptance criteria, sub-tasks (spec increment 4, FR-DEC-*).

The *decompose* skill says how to slice and word stories; the app's contract
keeps them tied to the document: every functional requirement is covered by a
story, stories reference FR IDs that exist, nothing is invented. Generated
sub-tasks and standalone NFR items start unticked (BR-09). BA edits pin items,
so rebuilding never overwrites them (FR-DEC-05).
"""
import uuid

from core import skills
from core.frd import _lang_name, decompose_documents, req_blocks, requirements_document
from core.llm import complete_json, for_project, model_name, output_language

DECOMPOSE_CONTRACT = """- Use only the requirements listed; never invent features. Every FR and BR ID must appear in the refs of at least one story.
- epics: title and goal; stories inside epics: title (short), story (the user-story sentence), refs (FR / BR IDs it implements), acceptance (list of given / when / then), subtasks (short titles, may be empty).
- nfr_links: for each NFR ID, the FR IDs whose stories it constrains (empty if none)."""

INVEST_CONTRACT = """Stories are listed as S1, S2… with their criteria. For each real problem return: id (the S number), letter (I, N, V, E, S or T), reason (one sentence) and fix (the concrete change: a rewritten story, a split, or criteria to add). Return an empty list when all stories are fine."""

GIVEN_WHEN_THEN = {"type": "object", "properties": {"given": {"type": "string"}, "when": {"type": "string"},
                                                     "then": {"type": "string"}},
                   "required": ["given", "when", "then"], "additionalProperties": False}
STRINGS = {"type": "array", "items": {"type": "string"}}
DECOMPOSE_SCHEMA = {
    "type": "object",
    "properties": {
        "epics": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "goal": {"type": "string"},
                "stories": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"title": {"type": "string"}, "story": {"type": "string"}, "refs": STRINGS,
                                   "acceptance": {"type": "array", "items": GIVEN_WHEN_THEN}, "subtasks": STRINGS},
                    "required": ["title", "story", "refs", "acceptance", "subtasks"], "additionalProperties": False}},
            },
            "required": ["title", "goal", "stories"], "additionalProperties": False}},
        "nfr_links": {"type": "array", "items": {
            "type": "object", "properties": {"id": {"type": "string"}, "stories_for": STRINGS},
            "required": ["id", "stories_for"], "additionalProperties": False}},
    },
    "required": ["epics", "nfr_links"],
    "additionalProperties": False,
}
INVEST_SCHEMA = {
    "type": "object",
    "properties": {"findings": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"},
                                         "letter": {"type": "string", "enum": list("INVEST")},
                                         "reason": {"type": "string"}, "fix": {"type": "string"}},
        "required": ["id", "letter", "reason", "fix"], "additionalProperties": False}}},
    "required": ["findings"],
    "additionalProperties": False,
}
TEXT = {
    "ru": {"other": "Прочее", "nfr_value": "Не несёт ценности сама по себе — это ограничение для историй.",
           "nfr_move": "Перенести в критерии: {ids}", "uncovered": "Требование {id} не попало ни в одну историю"},
    "en": {"other": "Other", "nfr_value": "Carries no value on its own: it constrains stories.",
           "nfr_move": "Move into the criteria of: {ids}", "uncovered": "{id} was not covered by any story"},
}


class BacklogError(Exception):
    """A user-facing reason the backlog can't be built."""


def _requirements(version):
    """{id: {text, section, type}} from an FRD version."""
    out = {}
    for num, _key, b in req_blocks(version["content"]):
        out[b["id"]] = {"text": b["text"], "section": num, "type": b["type"], "atom_id": b["atom_id"]}
    return out


def _ref(rid, reqs):
    r = reqs[rid]
    return {"id": rid, "section": r["section"], "atom_id": r["atom_id"], "doc_id": r.get("doc_id")}


STORY_PREFIXES = ("FR-", "BR-")              # what becomes a story; NFRs stay constraints


def sources(store, project_id):
    """The requirements of every document marked for decomposition, the first document winning an ID
    that appears in two (an SRS and a GOST spec of the same atoms)."""
    docs = decompose_documents(store, project_id)
    reqs = {}
    for d, v in docs:
        for rid, r in _requirements(v).items():
            reqs.setdefault(rid, {**r, "doc_id": d["id"]})
    return docs, reqs


RANK = {"must": 0, "should": 1, "could": 2, "wont": 3}


def _priority(store, refs, reqs):
    """A story is as important as the most important requirement it implements (MoSCoW)."""
    found = []
    for r in refs:
        try:
            p = store.get_atom(reqs[r]["atom_id"]).get("priority")
        except Exception:
            p = None
        if p:
            found.append(p)
    return min(found, key=RANK.get) if found else None


def build(store, project_id, prefs, api_key, progress=None, complete=complete_json, skillset=None, note=None):
    """Rebuild the backlog from the latest FRD version (pinned items are kept)."""
    report = progress or (lambda pct, msg: None)
    project = store.get_project(project_id)
    docs, reqs = sources(store, project_id)
    if not docs:
        raise BacklogError("No built document is marked for decomposition. Build an SRS, or mark a document "
                           "“В декомпозицию” on the Documents screen.")
    doc, version = docs[0]
    frs = [r for r in reqs if r.startswith(STORY_PREFIXES)]
    nfrs = [r for r in reqs if r.startswith("NFR-")]
    if not frs:
        raise BacklogError("The documents marked for decomposition have no functional or business requirements.")
    prefs = for_project(prefs, project)
    skillset = skillset or skills.resolve()
    lang = output_language(project) or version["content"].get("language", "ru")
    t = TEXT[lang]
    sections = {s["key"]: s for s in version["content"]["sections"]}
    purpose = next((b["text"] for b in sections.get("purpose", {}).get("blocks", []) if b["kind"] == "text"), "")
    context = next((b["text"] for b in sections.get("context", {}).get("blocks", []) if b["kind"] == "text"), "")
    user = (f"Project: {project['name']}\nPurpose: {purpose}\nContext: {context}\n\nRequirements:\n" +
            "\n".join(f"{rid} (section {r['section']}): {r['text']}" for rid, r in reqs.items() if not rid.startswith("Q-")))
    if (note or "").strip():
        user += "\n\nThe analyst's instruction for this run (follow it): " + note.strip()
    report(5, "Writing stories…")
    system = skills.compose(skillset, "decompose", DECOMPOSE_CONTRACT, language=_lang_name(lang))
    reply = complete(system, user, DECOMPOSE_SCHEMA, prefs, api_key)
    report(80, "Checking coverage…")

    tree, covered, story_by_fr = [], set(), {}
    for e in reply.get("epics") or []:
        stories = []
        for s in e.get("stories") or []:
            refs = [r.strip() for r in s.get("refs") or [] if r.strip() in reqs and r.strip().startswith(STORY_PREFIXES)]
            title = str(s.get("title") or "").strip()
            if not refs or not title:
                continue                                # a story must implement a real requirement
            sid = str(uuid.uuid4())
            covered.update(refs)
            for r in refs:
                story_by_fr.setdefault(r, sid)
            stories.append({"id": sid, "kind": "story", "title": title, "body": str(s.get("story") or "").strip(),
                            "priority": _priority(store, refs, reqs),
                            "refs": [_ref(r, reqs) for r in refs],
                            "acceptance": [{k: str(a.get(k) or "").strip() for k in ("given", "when", "then")}
                                           for a in s.get("acceptance") or []],
                            "children": [{"kind": "subtask", "title": str(x).strip(), "generated": True, "included": False}
                                         for x in s.get("subtasks") or [] if str(x).strip()]})
        if stories:
            tree.append({"kind": "epic", "title": str(e.get("title") or "").strip() or t["other"],
                         "goal": str(e.get("goal") or "").strip(), "children": stories})
    missing = [r for r in frs if r not in covered]
    if missing:                                          # never lose a requirement
        extra = []
        for r in missing:
            sid = str(uuid.uuid4())
            story_by_fr[r] = sid
            extra.append({"id": sid, "kind": "story", "title": reqs[r]["text"][:120], "body": reqs[r]["text"],
                          "priority": _priority(store, [r], reqs),
                          "refs": [_ref(r, reqs)], "acceptance": [],
                          "invest": [{"letter": "T", "reason": t["uncovered"].format(id=r), "fix": ""}]})
        tree.append({"kind": "epic", "title": t["other"], "goal": "", "children": extra})

    links = {str(n.get("id", "")).strip(): [x.strip() for x in n.get("stories_for") or []] for n in reply.get("nfr_links") or []}
    for n in nfrs:
        targets = [story_by_fr[f] for f in links.get(n, []) if f in story_by_fr]
        tree.append({"kind": "nfr", "title": reqs[n]["text"], "refs": [_ref(n, reqs)], "included": False,
                     "invest": [{"letter": "V", "reason": t["nfr_value"],
                                 "fix": t["nfr_move"].format(ids=", ".join(links.get(n, []))) if targets else "",
                                 "move_to": sorted(set(targets))}]})
    kept = store.replace_backlog(project_id, tree, version["number"],
                                 sources={d["id"]: v["number"] for d, v in docs})
    report(100, "Done")
    items = store.backlog(project_id)
    return {"frd_version": version["number"], "matched": kept["matched"], "orphans": kept["orphans"], "epics": sum(i["kind"] == "epic" for i in items),
            "stories": sum(i["kind"] == "story" for i in items), "subtasks": sum(i["kind"] == "subtask" for i in items),
            "model": model_name(prefs), "uncovered": missing}


def invest(store, project_id, prefs, api_key, progress=None, complete=complete_json, skillset=None):
    """Check every story against INVEST (FR-DEC-04); results are stored on each story."""
    report = progress or (lambda pct, msg: None)
    project = store.get_project(project_id)
    stories = [i for i in store.backlog(project_id) if i["kind"] == "story"]
    if not stories:
        raise BacklogError("There are no stories to check yet.")
    prefs = for_project(prefs, project)
    doc = requirements_document(store, project_id)
    version = store.version(doc["id"])
    lang = output_language(project) or (version or {}).get("content", {}).get("language", "ru")
    labels = {f"S{i + 1}": s for i, s in enumerate(stories)}

    def describe(key, s):
        ac = "; ".join(f"Given {a['given']} when {a['when']} then {a['then']}" for a in s["acceptance"]) or "(none)"
        return f"{key}: {s['title']} — {s['body']}\n  Criteria: {ac}"
    report(10, "Checking stories…")
    system = skills.compose(skillset or skills.resolve(), "invest", INVEST_CONTRACT, language=_lang_name(lang))
    reply = complete(system, "\n".join(describe(k, s) for k, s in labels.items()), INVEST_SCHEMA, prefs, api_key)
    found = {}
    for f in reply.get("findings") or []:
        s = labels.get(str(f.get("id", "")).strip())
        if s and f.get("letter") in "INVEST" and str(f.get("reason") or "").strip():
            found.setdefault(s["id"], []).append({"letter": f["letter"], "reason": f["reason"].strip(),
                                                  "fix": str(f.get("fix") or "").strip()})
    for s in stories:
        store.update_backlog_item(s["id"], pin=False, invest=found.get(s["id"], []))
    report(100, "Done")
    return {"checked": len(stories), "with_findings": len(found), "model": model_name(prefs)}


def move_nfr_into(store, nfr_id, story_id):
    """Accept the suggestion "move this NFR into the criteria of story X" (FR-DEC-04 AC2)."""
    nfr, story = store.get_backlog_item(nfr_id), store.get_backlog_item(story_id)
    if nfr["kind"] != "nfr" or story["kind"] != "story":
        raise BacklogError("only a non-functional item can be moved into a story's criteria")
    store.update_backlog_item(story_id, acceptance=story["acceptance"] + [{"given": "", "when": "", "then": nfr["title"]}],
                              refs=story["refs"] + [r for r in nfr["refs"] if r not in story["refs"]])
    store.delete_backlog_item(nfr_id)
    return store.get_backlog_item(story_id)


def stale(store, project_id):
    """Is the backlog behind its documents? It is when a document marked for decomposition has a newer
    version than the one the backlog was built from, or when the set of those documents changed."""
    items = store.backlog(project_id)
    docs = decompose_documents(store, project_id)
    now = {d["id"]: v["number"] for d, v in docs}
    first = docs[0][1]["number"] if docs else None
    built = max((i["frd_version"] or 0 for i in items), default=0) or None
    last = next((e for e in store.audit("project", project_id, limit=500) if e["action"] == "backlog_build"), None)
    before = ((last or {}).get("after") or {}).get("sources")
    if before is None:                                   # built before 3.3: compare the first document only
        doc = requirements_document(store, project_id)
        latest = store.version(doc["id"])
        return {"built_from": built, "latest": latest["number"] if latest else None,
                "stale": bool(latest and built and latest["number"] > built)}
    return {"built_from": built, "latest": first, "stale": bool(items) and before != now}
