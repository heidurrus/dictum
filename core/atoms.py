"""Requirement atoms: extract, verify, de-duplicate (spec increment 2, FR-ATM-*).

A source's segments are sent in chunks, each line labelled `[S<idx>]`, so the
model can cite where every atom came from. Quotes are then checked against the
real segment text: an atom with no verifiable quote is dropped (BR-02, "no
evidence, no atom"). A final pass compares the new atoms with the project's
existing ones to fold duplicates in and flag contradictions (BR-03, D-06).
"""
import re
import unicodedata

from core import skills
from core.llm import LLMError, complete_json, for_project, language_rule, model_name
from core.transcripts import format_time

CHUNK_CHARS = 12000
MAX_EXISTING_FOR_DEDUP = 400

# The guidance lives in the extract / dedup skills (skills/…/SKILL.md, editable by the user);
# the app adds these contracts, which keep the pipeline working whatever the skill says.
EXTRACT_CONTRACT = """- Every atom cites evidence: the number from the [S…] label of the line it came from, and a quote copied character for character from that line (a short contiguous fragment, not a paraphrase, no ellipses). Atoms without such a quote are discarded.
- type is one of: business, functional, nfr, risk, current, question — or action_item / other for things that are none of these.
- action_item: a task for people rather than a property of the system ("send the email", "schedule a call", "prepare the estimate", "Иван пришлёт письмо"). other: anything else that is not a requirement (small talk, project process, opinions without a need). Label them honestly instead of forcing them into functional: they are kept on a separate to-do list, never saved as requirements. For an action_item, also give owner (who will do it) and due (when), if they were said; otherwise leave them empty.
- If nothing in the text is a requirement, return an empty list."""

DEDUP_CONTRACT = """Items marked N are new; items marked E already exist. At least one side of every pair must be a new (N) item. For a duplicate, give the new item and the item it duplicates (prefer an E item, else an earlier N item)."""

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "atoms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["business", "functional", "nfr", "risk", "current", "question", "action_item", "other"]},
                    "statement": {"type": "string"},
                    "owner": {"type": "string"},
                    "due": {"type": "string"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"segment": {"type": "integer"}, "quote": {"type": "string"}},
                            "required": ["segment", "quote"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["type", "statement", "evidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["atoms"],
    "additionalProperties": False,
}

DEDUP_SCHEMA = {
    "type": "object",
    "properties": {
        "duplicates": {
            "type": "array",
            "items": {"type": "object", "properties": {"new": {"type": "string"}, "same_as": {"type": "string"}},
                      "required": ["new", "same_as"], "additionalProperties": False},
        },
        "conflicts": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "description": {"type": "string"}},
                      "required": ["a", "b", "description"], "additionalProperties": False},
        },
    },
    "required": ["duplicates", "conflicts"],
    "additionalProperties": False,
}

_QUOTE_CHARS = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'",
                              "—": "-", "–": "-", "ё": "е", "Ё": "Е"})


def normalize(text):
    """Compare quotes loosely: case, whitespace, quote styles, dashes and ё don't matter."""
    text = unicodedata.normalize("NFC", text or "").translate(_QUOTE_CHARS).casefold()
    text = re.sub(r"\s+", " ", text).strip()
    return text.strip(" .,;:!?\"'")


def segment_line(seg):
    who = seg.get("speaker_name") or seg.get("speaker")
    parts = [p for p in (who, format_time(seg["start"]) if seg.get("start") is not None else None) if p]
    return f"[S{seg['idx']}] " + (f"[{', '.join(parts)}] " if parts else "") + seg["text"]


def chunk_segments(segments, limit=None):
    limit = limit or CHUNK_CHARS
    chunks, current, size = [], [], 0
    for seg in segments:
        line = len(segment_line(seg)) + 1
        if current and size + line > limit:
            chunks.append(current)
            current, size = [], 0
        current.append(seg)
        size += line
    if current:
        chunks.append(current)
    return chunks


def verify_evidence(raw_evidence, chunk, source_id):
    """Keep only quotes that really occur in the transcript (BR-02).

    A quote attributed to the wrong line is re-attached to the line it is in,
    if that line is in the same chunk."""
    by_idx = {s["idx"]: s for s in chunk}
    kept, seen = [], set()
    for ev in raw_evidence or []:
        quote = (ev.get("quote") or "").strip()
        needle = normalize(quote)
        if len(needle) < 3:
            continue
        cited = by_idx.get(ev.get("segment"))
        candidates = ([cited] if cited else []) + [s for s in chunk if s is not cited]
        seg = next((s for s in candidates if needle in normalize(s["text"])), None)
        if seg is None or (seg["idx"], needle) in seen:
            continue
        seen.add((seg["idx"], needle))
        kept.append({"source_id": source_id, "segment_idx": seg["idx"], "start": seg.get("start"),
                     "speaker": seg.get("speaker"), "quote": quote})
    return kept


def _source_header(source):
    kind = {"email": "an email", "document": "a document", "material": "a reference material"}.get(source["kind"], "a call or meeting transcript")
    return f"Source: {kind} titled “{source['title']}”."


def extract_candidates(store, source_id, prefs, api_key, skillset=None, progress=None,
                       complete=complete_json, note=None):
    """Atoms found in one source, verified against the text, without saving anything
    (used by extraction and by "try this skill")."""
    source = store.get_source(source_id)
    segments, _ = store.transcript(source_id)
    if not segments:
        raise LLMError("This source has no text yet.")
    skillset = skillset or skills.resolve()
    rule = language_rule(store.get_project(source["project_id"]))
    system = skills.compose(skillset, "extract", EXTRACT_CONTRACT + (f"\n- {rule}" if rule else ""))
    report = progress or (lambda done, total, message: None)
    chunks = chunk_segments(segments)
    steps = len(chunks) + 1
    candidates, dropped, skipped = [], 0, []
    for i, chunk in enumerate(chunks):
        report(i, steps, f"Reading part {i + 1} of {len(chunks)}…" if len(chunks) > 1 else "Reading the source…")
        user = _source_header(source) + "\n\n" + "\n".join(segment_line(s) for s in chunk)
        if (note or "").strip():
            user += "\n\nThe analyst's instruction for this run (follow it unless it breaks the format): " + note.strip()
        reply = complete(system, user, EXTRACT_SCHEMA, prefs, api_key)
        for atom in reply.get("atoms") or []:
            statement = (atom.get("statement") or "").strip()
            if atom.get("type") in ("action_item", "other") and statement:
                item = {"type": atom["type"], "statement": statement}          # not requirements: set aside
                if atom["type"] == "action_item":                              # …but kept as a to-do (PM-19)
                    ev = verify_evidence(atom.get("evidence"), chunk, source_id)
                    if ev:
                        item.update(quote=ev[0]["quote"], segment_idx=ev[0]["segment_idx"], start=ev[0]["start"])
                    item.update(owner=(atom.get("owner") or "").strip(), due=(atom.get("due") or "").strip())
                skipped.append(item)
                continue
            if atom.get("type") not in ("functional", "nfr", "question", "business", "risk", "current") or not statement:
                dropped += 1
                continue
            evidence = verify_evidence(atom.get("evidence"), chunk, source_id)
            if not evidence:
                dropped += 1                                   # no evidence, no atom
                continue
            candidates.append({"type": atom["type"], "statement": statement, "evidence": evidence})
    return candidates, dropped, steps, skipped


def extract_atoms(store, source_id, prefs, api_key, progress=None, complete=complete_json, skillset=None,
                  note=None):
    """Extract atoms from one source into the store; returns counts for the UI.

    Re-extraction drops the source's atoms still pending review and keeps the
    reviewed ones, so no decision is lost."""
    source = store.get_source(source_id)
    project = store.get_project(source["project_id"])
    prefs = for_project(prefs, project)                        # FR-PRJ-05: nothing leaves the machine
    model = model_name(prefs)
    skillset = skillset or skills.resolve()
    report = progress or (lambda done, total, message: None)
    candidates, dropped, steps, skipped = extract_candidates(store, source_id, prefs, api_key, skillset=skillset,
                                                    progress=progress, complete=complete, note=note)
    report(steps - 1, steps, "Checking for duplicates and conflicts…")
    cleared = store.delete_pending_atoms_for_source(source_id)
    store.clear_actions_for_source(source_id)
    store.add_actions(project["id"], source_id, [{"text": x["statement"], **{k: x.get(k) for k in
                                                  ("owner", "due", "quote", "segment_idx", "start")}}
                                                 for x in skipped if x["type"] == "action_item"])
    new_ids = store.add_atoms(project["id"], candidates, model=model) if candidates else []
    merged, conflicts = _dedup(store, project["id"], new_ids, prefs, api_key, complete, skillset)
    report(steps, steps, "Done")
    return {"extracted": len(new_ids) - merged, "merged": merged, "conflicts": conflicts,
            "dropped": dropped, "skipped_actions": sum(1 for x in skipped if x["type"] == "action_item"),
            "skipped_other": sum(1 for x in skipped if x["type"] == "other"), "replaced": cleared, "provider": prefs["llm_provider"], "model": model}


def _dedup(store, project_id, new_ids, prefs, api_key, complete, skillset=None):
    if not new_ids:
        return 0, 0
    new_set = set(new_ids)
    atoms = [a for a in store.list_atoms(project_id) if a["status"] in ("pending", "accepted")]
    new = [a for a in atoms if a["id"] in new_set]
    existing = [a for a in atoms if a["id"] not in new_set][-MAX_EXISTING_FOR_DEDUP:]
    if len(new) + len(existing) < 2:
        return 0, 0
    labelled = [(f"N{i + 1}", a) for i, a in enumerate(new)] + [(f"E{i + 1}", a) for i, a in enumerate(existing)]
    ids = {key: a["id"] for key, a in labelled}
    lines = [f"{key} [{a['type']}] {a['statement']}" for key, a in labelled]
    try:
        system = skills.compose(skillset or skills.resolve(), "dedup", DEDUP_CONTRACT)
        reply = complete(system, "\n".join(lines), DEDUP_SCHEMA, prefs, api_key)
    except LLMError:
        return 0, 0          # the atoms are saved; a failed comparison just means no suggestions

    merged_away, merged = set(), 0
    for d in reply.get("duplicates") or []:
        dup, target = ids.get(d.get("new")), ids.get(d.get("same_as"))
        if (not dup or not target or dup == target or dup not in new_set
                or dup in merged_away or target in merged_away):
            continue
        store.merge_atoms(dup, target)
        merged_away.add(dup)
        merged += 1

    conflicts, pairs = 0, set()
    for c in reply.get("conflicts") or []:
        a, b = ids.get(c.get("a")), ids.get(c.get("b"))
        pair = frozenset((a, b))
        if (not a or not b or a == b or not (pair & new_set) or pair & merged_away
                or pair in pairs or not (c.get("description") or "").strip()):
            continue
        pairs.add(pair)
        store.add_conflict(project_id, a, b, c["description"])
        conflicts += 1
    return merged, conflicts


# ── reclassify existing atoms (3.3: business / risk / current were added) ────

RECLASSIFY_CONTRACT = """You get atoms that were already extracted and reviewed. They were typed by an older version that knew only functional, nfr and question, so business goals and rules, risks and facts about today's process were forced into those types. Type each atom from scratch, using the type definitions above: business, functional, nfr, risk, current or question.
- business: a goal, outcome, success measure, KPI or business rule — checked in the business, not in the system.
- risk: something uncertain that could hurt the project (a dependency, an unknown, a threat to scope, time or data).
- current: how things work today, or a problem of today's process.
- functional / nfr: what the system must do / how well it must do it. question: still open.
- Do not reword anything. Return every atom ID exactly once."""
RECLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "type": {"type": "string", "enum": ["business", "functional", "nfr", "risk", "current", "question"]}},
        "required": ["id", "type"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def reclassify(store, project_id, prefs, api_key, progress=None, complete=complete_json, skillset=None,
               chunk=60):
    """Suggest a better type for each accepted or pending atom; returns [{id, from, to}] without saving."""
    project = store.get_project(project_id)
    prefs = for_project(prefs, project)
    skillset = skillset or skills.resolve()
    atoms = [a for a in store.list_atoms(project_id) if a["status"] in ("pending", "accepted")]
    report = progress or (lambda done, total, message: None)
    system = skills.compose(skillset, "extract", RECLASSIFY_CONTRACT)
    changes = []
    parts = [atoms[i:i + chunk] for i in range(0, len(atoms), chunk)] or [[]]
    for n, part in enumerate(parts):
        if not part:
            break
        report(n, len(parts), f"Reading part {n + 1} of {len(parts)}…")
        keys = {f"A{i + 1}": a for i, a in enumerate(part)}
        user = "\n".join(f"{k} {a['statement']}" +
                         (f"  (quote: «{a['evidence'][0]['quote']}»)" if a["evidence"] else "")
                         for k, a in keys.items())
        reply = complete(system, user, RECLASSIFY_SCHEMA, prefs, api_key)
        for item in reply.get("items") or []:
            a = keys.get(str(item.get("id", "")).strip())
            new = item.get("type")
            if a and new in store_types() and new != a["type"]:
                changes.append({"id": a["id"], "from": a["type"], "to": new, "statement": a["statement"]})
    report(len(parts), len(parts), "Done")
    return changes


def store_types():
    from core.store import ATOM_TYPES
    return ATOM_TYPES
