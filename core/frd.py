"""FRD builder: accepted atoms → a structured, versioned document (spec increment 3).

One requirement in the document = one accepted atom, under a stable ID (FR-n,
NFR-n, Q-n; BR-14), with its sources copied into the version for provenance
(FR-DOC-03). The *frd* skill decides the document's sections, their titles and
order (plus extra AI-written sections) and how requirements are worded; the
*quality* skill decides which checks run. Code enforces the structure: every
atom appears exactly once, nothing is invented.

"Rebuild" regenerates only what changed since the last version (Q-15, FR-DOC-05
AC2): unchanged requirements keep their text and place word for word.
"""
import re

from core import skills
from core.llm import LLMError, complete_json, for_project, model_name, output_language

LABELS = {
    "ru": {"assumptions": "Допущения", "other": "Прочее"},
    "en": {"assumptions": "Assumptions", "other": "Other"},
}
RULES = list(skills.BUILTIN_RULES)

# Fallback vague stems when no quality skill is given (the quality skill's list wins).
VAGUE = {
    "ru": ["быстр", "удобн", "интуитивн", "современн", "надёжн", "надежн", "дружелюбн", "оптимальн",
           "эффективн", "гибк", "масштабируем", "по возможности", "при необходимости", "как правило", "максимально"],
    "en": ["fast", "quick", "user-friendly", "intuitive", "easy", "modern", "reliable", "efficient", "flexible",
           "scalable", "as appropriate", "if possible", "robust", "seamless", "as soon as possible"],
}
# NFRs about these qualities need a number or threshold to be testable (BR-08); others
# (access rules, compliance, localisation) are testable without one.
QUANTITATIVE = re.compile(r"(?<!\w)(быстр|скорост|врем|время|секунд|минут|задержк|отклик|откры|загруз|производительн|"
                          r"нагрузк|одновременн|пропускн|доступност|безотказн|аптайм|восстановлен|объ[её]м|ёмкост|емкост|"
                          r"масштаб|fast|speed|time|latency|response|load|perform|throughput|concurren|availab|uptime|"
                          r"recover|capacity|scal)", re.I)
NUMBER_WORDS = re.compile(r"\d|\b(одн|один|два|двух|три|трёх|трех|четыр|пят|шест|сем|восьм|восем|девят|десят|"
                          r"двадцат|тридцат|сорок|пятьдесят|сто|сотн|тысяч|миллион|процент|one|two|three|four|five|"
                          r"six|seven|eight|nine|ten|twenty|thirty|hundred|thousand|million|percent)", re.I)

# What the app adds to the frd skill, whatever the skill says (keeps the structure intact).
FULL_CONTRACT = """- items: each atom becomes exactly one item with the atom's ID. Keep every number, limit, role and name exactly; never add facts that are not in the atoms.
- groups: every FR ID goes into exactly one group (a sub-section with a short title).
- purpose, context, assumptions, out_of_scope: as instructed above; leave empty when the atoms give nothing.
{extra}- issues: check each FR and NFR item you wrote against the rules below and report only real problems, with a one-sentence message in {language}.

Quality rules:
{rules}"""

CHANGED_CONTRACT = """Only some requirement atoms are new or changed; everything else in the document stays as it is.
For each item under "To write":
- text: rewrite it as instructed above, keeping every number, limit and name exactly and adding nothing.
- group: for a functional requirement (FR-…), the title of the existing sub-section it belongs to, copied exactly, or a short new title if none fits. Empty for other items.
- issues: report real problems in the text you wrote, with a one-sentence message in {language}.

Quality rules:
{rules}"""

FIX_CONTRACT = """Keep every fact, number and name from the original; do not invent new facts. If fixing needs a value nobody has stated (for example a time limit), put a placeholder in square brackets, e.g. "[уточнить: N секунд]" or "[to confirm: N seconds]". Return only the rewritten requirement."""


def _issue_schema(rule_ids):
    return {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "rule": {"type": "string", "enum": rule_ids},
                                         "message": {"type": "string"}},
        "required": ["id", "rule", "message"], "additionalProperties": False}}


def full_schema(rule_ids, extra_keys=(), table_keys=()):
    strings = {"type": "array", "items": {"type": "string"}}
    key = {"type": "string", "enum": list(extra_keys)} if extra_keys else {"type": "string"}
    tkey = {"type": "string", "enum": list(table_keys)} if table_keys else {"type": "string"}
    return {
        "type": "object",
        "properties": {
            "purpose": {"type": "string"}, "context": {"type": "string"}, "assumptions": strings,
            "groups": {"type": "array", "items": {
                "type": "object", "properties": {"title": {"type": "string"}, "ids": strings},
                "required": ["title", "ids"], "additionalProperties": False}},
            "items": {"type": "array", "items": {
                "type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"}},
                "required": ["id", "text"], "additionalProperties": False}},
            "out_of_scope": strings,
            "extra": {"type": "array", "items": {
                "type": "object", "properties": {"key": key, "text": {"type": "string"}},
                "required": ["key", "text"], "additionalProperties": False}},
            "tables": {"type": "array", "items": {
                "type": "object", "properties": {"key": tkey, "rows": {"type": "array", "items": strings}},
                "required": ["key", "rows"], "additionalProperties": False}},
            "issues": _issue_schema(rule_ids),
        },
        "required": ["purpose", "context", "assumptions", "groups", "items", "out_of_scope", "extra", "tables", "issues"],
        "additionalProperties": False,
    }


def changed_schema(rule_ids):
    return {
        "type": "object",
        "properties": {
            "items": {"type": "array", "items": {
                "type": "object", "properties": {"id": {"type": "string"}, "text": {"type": "string"},
                                                 "group": {"type": "string"}},
                "required": ["id", "text", "group"], "additionalProperties": False}},
            "issues": _issue_schema(rule_ids),
        },
        "required": ["items", "issues"],
        "additionalProperties": False,
    }


FIX_SCHEMA = {"type": "object", "properties": {"statement": {"type": "string"}},
              "required": ["statement"], "additionalProperties": False}


class BuildError(Exception):
    """A user-facing reason the document can't be built."""


def language_of(texts):
    text = " ".join(texts)
    cyr = len(re.findall(r"[а-яё]", text, flags=re.I))
    lat = len(re.findall(r"[a-z]", text, flags=re.I))
    return "ru" if cyr >= lat else "en"


def _lang_name(lang):
    return "Russian" if lang == "ru" else "English"


# ── quality ──────────────────────────────────────────────────────────────────

class Quality:
    """The rules in effect, from the quality skill."""

    def __init__(self, skill=None):
        meta = skill.meta if skill else {}
        self.skill = skill
        self.vague = {k: list(v) for k, v in (meta.get("vague_words") or VAGUE).items()}
        self.custom = [r for r in meta.get("rules") or [] if isinstance(r, dict)]
        self.rule_ids = RULES + [r["id"] for r in self.custom]
        self.titles = {r["id"]: r["title"] for r in self.custom}

    def prompt(self, language):
        text = skills.instructions(self.skill, language).strip() if self.skill else ""
        if self.custom:
            text += "\nYour own rules:\n" + "\n".join(f"- {r['id']}: {r['description']}" for r in self.custom)
        return text or "Report ambiguous, vague, compound, untestable and not measurable requirements."

    def checks(self, text, kind, lang):
        """Deterministic checks (BR-08), on top of what the model reports."""
        issues = []
        stems = [str(w).strip() for w in self.vague.get(lang, []) if str(w).strip()]
        found = None
        for w in stems:
            m = re.search(r"(?<!\w)" + re.escape(w) + r"\w*", text, flags=re.I)
            if m:
                found = m.group(0)
                break
        if found:
            issues.append({"rule": "vague", "message": (f"Нечёткое слово «{found}» — чем его измерить?" if lang == "ru"
                                                       else f"Vague word “{found}”: how would it be measured?")})
        if kind == "nfr" and QUANTITATIVE.search(text) and not NUMBER_WORDS.search(text):
            issues.append({"rule": "not_measurable", "message": ("Нет измеримого критерия (числа или порога)." if lang == "ru"
                                                                else "No measurable criterion (a number or threshold).")})
        return issues

    def merge(self, *lists):
        seen, out = set(), []
        for lst in lists:
            for issue in lst or []:
                if issue.get("rule") in self.rule_ids and issue["rule"] not in seen:
                    seen.add(issue["rule"])
                    out.append({"rule": issue["rule"], "message": str(issue.get("message") or "").strip()})
        return out


def rule_checks(text, kind, lang):
    return Quality().checks(text, kind, lang)


# ── document structure (from the frd skill) ──────────────────────────────────

def section_spec(skill, lang):
    """[(key, title, instructions)] in the skill's order."""
    return [(s["key"], skills.title_text(s.get("title"), lang), str(s.get("instructions") or "").strip())
            for s in skill.meta.get("sections") or []]


def section_formats(skill, lang):
    """Sections that are tables: key → {columns (in lang), id_prefix, heatmap}."""
    out = {}
    for s in skill.meta.get("sections") or []:
        if s.get("format") == "table":
            out[s["key"]] = {"columns": [skills.title_text(c, lang) for c in s.get("columns") or []],
                             "id_prefix": s.get("id_prefix"), "heatmap": s.get("heatmap")}
    return out


def _extra_contract(spec, tables=None):
    tables = tables or {}
    custom = [(k, t, i) for k, t, i in spec if k not in skills.FRD_KINDS and k not in tables]
    out = ""
    if not custom:
        out += "- extra: return an empty list.\n"
    else:
        lines = "\n".join(f"  - {k} (“{t}”): {i}" for k, t, i in custom)
        out += ("- extra: one entry per additional section below, with its key and its text (based only on the atoms "
                "and sources; empty text when they give nothing):\n" + lines + "\n")
    tab = [(k, t, i) for k, t, i in spec if k in tables]
    if not tab:
        out += "- tables: return an empty list.\n"
    else:
        lines = []
        for k, t, i in tab:
            if k == "risks":
                cols = tables[k]["columns"]
                lines.append(f"  - risks (“{t}”): {i} Exactly one row per RSK atom and no others; the first cell is the "
                             f"atom's ID (RSK-n). Each row is an array of exactly {len(cols)} strings, in this order: "
                             + " | ".join(cols) + ".")
                continue
            cols = tables[k]["columns"][1:] if tables[k].get("id_prefix") else tables[k]["columns"]
            lines.append(f"  - {k} (“{t}”): {i} Each row is an array of exactly {len(cols)} strings, in this order: "
                         + " | ".join(cols) + (". Do not number the rows: IDs are added by the app." if tables[k].get("id_prefix") else "."))
        out += ("- tables: one entry per table section below, with its key and its rows (based only on the atoms, "
                "the sources and their summaries; no rows when they give nothing):\n" + "\n".join(lines) + "\n")
    return out


LEVELS = {"high": 2, "medium": 1, "low": 0, "высок": 2, "средн": 1, "низк": 0, "h": 2, "m": 1, "l": 0}
HEAT = {"ru": {"corner": "Вероятность \\ Влияние", "levels": ["Низкое", "Среднее", "Высокое"],
               "p": ["Низкая", "Средняя", "Высокая"], "title": "Матрица рисков"},
        "en": {"corner": "Probability \\ Impact", "levels": ["Low", "Medium", "High"],
               "p": ["Low", "Medium", "High"], "title": "Risk matrix"}}


def _level(text):
    t = str(text or "").strip().lower()
    for k, v in LEVELS.items():
        if t.startswith(k):
            return v
    return None


def _table_blocks(key, fmt, rows, lang):
    """A table block (IDs added when the section asks), plus a probability × impact heat map if configured."""
    width = len(fmt["columns"]) - (1 if fmt.get("id_prefix") else 0)
    clean = []
    for r in rows or []:
        cells = [str(c).strip() for c in (r if isinstance(r, list) else [r])][:width]
        if any(cells):
            clean.append(cells + [""] * (width - len(cells)))
    if fmt.get("id_prefix"):
        clean = [[f"{fmt['id_prefix']}-{n}"] + r for n, r in enumerate(clean, 1)]
    if not clean:
        return []
    blocks = [{"id": key, "kind": "table", "columns": fmt["columns"], "rows": clean}]
    hm = fmt.get("heatmap")
    if isinstance(hm, dict):
        pi, ii = int(hm.get("probability", 0)), int(hm.get("impact", 0))
        t = HEAT.get(lang, HEAT["ru"])
        grid = [[[] for _ in range(3)] for _ in range(3)]
        for r in clean:
            p, i = _level(r[pi] if pi < len(r) else ""), _level(r[ii] if ii < len(r) else "")
            if p is not None and i is not None:
                grid[p][i].append(r[0])
        blocks.append({"id": key + "_heatmap", "kind": "table", "title": t["title"], "heatmap": True,
                       "columns": [t["corner"]] + t["levels"],
                       "rows": [[t["p"][p]] + [", ".join(grid[p][i]) for i in range(3)] for p in (2, 1, 0)]})
    return blocks


def _sources(evidence):
    return [{k: e.get(k) for k in ("source_id", "source_title", "source_kind", "source_date", "segment_idx",
                                   "start", "speaker", "speaker_name", "quote")} for e in evidence]


def _snapshot(atoms, rids):
    return {a["id"]: {"statement": a["statement"], "type": a["type"], "rid": rids[a["id"]]} for a in atoms}


def _atom_lines(atoms, rids, conflicts):
    lines = []
    for a in atoms:
        note = f"  (conflicts with another requirement: {conflicts[a['id']]})" if a["id"] in conflicts else ""
        lines.append(f"{rids[a['id']]} [{a['type']}] {a['statement']}{note}")
    return lines


def _open_conflicts(store, project_id):
    out = {}
    for c in store.list_conflicts(project_id):
        if c["status"] == "open":
            out.setdefault(c["atom_a"], c["description"])
            out.setdefault(c["atom_b"], c["description"])
    return out


CHECKED = ("functional", "nfr", "business")          # quality rules apply to requirements, not risks or facts
ORDER = {"FR": 0, "BR": 1, "NFR": 2, "AS": 3, "RSK": 4, "Q": 5}


def _block(atom, rid, text, conflicts, issues):
    return {"id": rid, "kind": "req", "atom_id": atom["id"], "type": atom["type"], "text": text.strip(),
            "sources": _sources(atom["evidence"]), "conflict": conflicts.get(atom["id"]), "issues": issues}


def _number(sections):
    for i, sec in enumerate(sections, 1):
        sec["number"] = str(i)
        for j, sub in enumerate(sec.get("subsections") or [], 1):
            sub["number"] = f"{i}.{j}"
    return sections


def _assemble(spec, lang, parts):
    """Sections in the skill's order. parts: purpose, context, assumptions, groups, nfr, out_of_scope,
    questions, extra {key: text}."""
    sections = []
    for key, title, _instr in spec:
        sec = {"key": key, "title": title, "blocks": []}
        if key == "purpose" and parts["purpose"].strip():
            sec["blocks"] = [{"id": "purpose", "kind": "text", "text": parts["purpose"].strip()}]
        elif key == "context":
            if parts["context"].strip():
                sec["blocks"].append({"id": "context", "kind": "text", "text": parts["context"].strip()})
            items = [a.strip() for a in parts["assumptions"] if a.strip()]
            if items:
                sec["blocks"].append({"id": "assumptions", "kind": "list", "title": LABELS[lang]["assumptions"],
                                      "items": items})
        elif key == "functional":
            sec["subsections"] = [{"key": f"functional.{i}", "title": t, "blocks": b}
                                  for i, (t, b) in enumerate(parts["groups"], 1) if b]
        elif key == "nfr":
            sec["blocks"] = parts["nfr"]
        elif key == "out_of_scope" and parts["out_of_scope"]:
            sec["blocks"] = [{"id": "out_of_scope", "kind": "list", "items": parts["out_of_scope"]}]
        elif key == "questions":
            sec["blocks"] = parts["questions"]
        elif key == "business":
            sec["blocks"] = parts.get("business", [])
        elif key == "current":
            sec["blocks"] = parts.get("current", [])
        elif key == "risks":
            sec["blocks"] = parts.get("risks", [])
        elif key in parts.get("formats", {}):
            sec["blocks"] = _table_blocks(key, parts["formats"][key], parts.get("tables", {}).get(key), lang)
        elif key not in skills.FRD_KINDS and (parts["extra"].get(key) or "").strip():
            sec["blocks"] = [{"id": key, "kind": "text", "text": parts["extra"][key].strip()}]
        sections.append(sec)
    return {"sections": _number(sections)}


def decomposes(doc, skill):
    """Does this document go into the backlog? The document's own setting, else its type's default
    (types that hold functional requirements do)."""
    if doc.get("decompose") is not None:
        return bool(doc["decompose"])
    if "decompose" in skill.meta:
        return bool(skill.meta["decompose"])
    return "functional" in skills.doc_atom_types(skill.meta)[0]


def decompose_documents(store, project_id):
    """[(document, latest version)] that feed the backlog, in the project's order; only built ones."""
    skillset = skills.resolve(store.project_skills(project_id))
    out = []
    for d in store.documents(project_id):
        v = store.version(d["id"])
        if v and decomposes(d, document_skill(d, skillset)):
            out.append((d, v))
    return out


def requirements_document(store, project_id):
    """The document the backlog, Jira and traceability read requirements from: the first document marked
    for decomposition; failing that the primary one when it holds FR/NFR, else the newest one that does."""
    docs = store.documents(project_id)
    if not docs:
        return store.document(project_id)
    dec = decompose_documents(store, project_id)
    if dec:
        return dec[0][0]
    best, best_at = None, -1
    for i, d in enumerate(docs):
        v = store.version(d["id"])
        if v and any(b["id"].startswith(("FR-", "NFR-")) for _n, _k, b in req_blocks(v["content"])):
            if i == 0:
                return d
            if v["created_at"] > best_at:
                best, best_at = d, v["created_at"]
    return best or docs[0]


def req_blocks(content):
    """Every requirement block of a version, with the number of the (sub)section holding it."""
    for sec in content["sections"]:
        for b in sec["blocks"]:
            if b["kind"] == "req":
                yield sec["number"], sec["key"], b
        for sub in sec.get("subsections") or []:
            for b in sub["blocks"]:
                yield sub["number"], sub["key"], b


# ── building ─────────────────────────────────────────────────────────────────

NOTE = "\n\nThe analyst's instruction for this run (follow it unless it breaks the format): "


def build(store, project_id, prefs, api_key, mode="changed", progress=None, complete=complete_json,
          skillset=None, save=True, note=None, document_id=None):
    """Build a new version of a project document. mode "changed": rewrite only new/changed atoms; "full":
    rewrite everything. The document's type (BRD, SRS, Vision & Scope, …) is its own document skill.
    save=False returns the content without storing a version (used to try a skill)."""
    report = progress or (lambda pct, msg: None)
    project = store.get_project(project_id)
    doc = store.get_document(document_id) if document_id else store.document(project_id)
    accepted = store.list_atoms(project_id, status="accepted")
    if not accepted:
        raise BuildError("There are no accepted atoms yet. Review the atoms first.")
    prefs = for_project(prefs, project)
    skillset = dict(skillset or skills.resolve())
    doc_skill = document_skill(doc, skillset)
    skillset["frd"] = doc_skill
    # Each document takes the atoms of its own types (SRS: FR/NFR, BRD: BR, risks: RSK…), and may read others.
    placed_types, context_types = skills.doc_atom_types(doc_skill.meta)
    atoms = [a for a in accepted if a["type"] in placed_types]
    context_atoms = [a for a in accepted if a["type"] in context_types and a["type"] not in placed_types]
    if not atoms and not doc_skill.meta.get("use_summaries"):
        raise BuildError("There are no accepted atoms of the types this document holds yet.")
    rids = store.requirement_ids(project_id, atoms + context_atoms)
    key = lambda a: (ORDER[rids[a["id"]].split("-")[0]], int(rids[a["id"]].split("-")[1]))  # noqa: E731
    atoms.sort(key=key)
    context_atoms.sort(key=key)
    by_rid = {rids[a["id"]]: a for a in atoms}
    conflicts = _open_conflicts(store, project_id)
    lang = output_language(project) or language_of([a["statement"] for a in atoms])
    ctx = {"store": store, "project": project, "atoms": atoms, "rids": rids, "by_rid": by_rid, "conflicts": conflicts,
           "lang": lang, "prefs": prefs, "api_key": api_key, "report": report,
           "complete": complete, "skillset": skillset, "quality": Quality(skillset.get("quality")),
           "spec": section_spec(doc_skill, lang), "formats": section_formats(doc_skill, lang), "note": (note or "").strip(),
           "summaries": _summaries(store, project_id) if doc_skill.meta.get("use_summaries") else "",
           "context_atoms": context_atoms, "placed_types": placed_types}
    previous = store.version(doc["id"])
    if previous is not None and previous["content"].get("language") != lang:
        mode = "full"                                   # a new output language means rewriting everything
    if previous is not None and (previous["content"].get("skills") or {}).get("frd") not in (None, doc_skill.name):
        mode = "full"                                   # the document changed type: its sections are different
    if "risks" in ctx["formats"]:
        mode = "full"                                   # the risk table is rewritten as a whole
    if previous is None or mode == "full":
        content = _build_full(ctx)
        mode = "full"
    else:
        content = _build_changed(ctx, previous)
    _add_scoped_out(content, store, project_id, ctx["spec"], lang)
    content["language"] = lang
    content["atom_types"] = placed_types
    content["skills"] = {"frd": doc_skill.name, "quality": skillset["quality"].name}
    content["rule_titles"] = ctx["quality"].titles
    if not save:
        report(100, "Done")
        return {"content": content, "atoms": len(atoms), "mode": mode}
    number = store.add_version(doc["id"], content, _snapshot(atoms, rids), len(atoms),
                               provider=prefs["llm_provider"], model=model_name(prefs), mode=mode)
    report(100, "Done")
    return {"document_id": doc["id"], "version": number, "atoms": len(atoms), "mode": mode,
            "conflicts": sum(1 for a in atoms if a["id"] in conflicts)}


def _add_scoped_out(content, store, project_id, spec, lang):
    """Atoms the BA rejected as "out of scope" are listed in that section (PM-22). They go in their own
    block, recomputed on every build, so returning an atom to review takes it out again."""
    sec = next((x for x in content["sections"] if x["key"] == "out_of_scope"), None)
    if sec is None:
        return                                          # the FRD skill has no such section
    sec["blocks"] = [b for b in sec["blocks"] if b.get("id") != "out_of_scope_ba"]
    ai = {x.casefold() for b in sec["blocks"] if b["kind"] == "list" for x in b["items"]}
    scoped = [a["statement"] for a in store.list_atoms(project_id, status="rejected")
              if a.get("reject_reason") == "out_of_scope" and a["statement"].casefold() not in ai]
    if scoped:
        sec["blocks"].append({"id": "out_of_scope_ba", "kind": "list", "items": scoped})


def document_skill(doc, skillset):
    """The skill that shapes this document: its own type, else the project's default document skill."""
    name = (doc or {}).get("kind")
    if name:
        try:
            sk = skills.get(name)
            if sk.stage == "frd" and not sk.error:
                return sk
        except skills.SkillError:
            pass
    return skillset["frd"]


def _summaries(store, project_id, limit=12000):
    """Source summaries, for documents that describe processes rather than list requirements (As-Is, Vision)."""
    out, used = [], 0
    for s in store.list_sources(project_id):
        summ = store.latest_summary(s["id"]) if s["status"] == "ready" else None
        if summ and summ.get("text"):
            chunk = f"### {s['title']}\n{summ['text'].strip()}"
            if used + len(chunk) > limit:
                break
            out.append(chunk)
            used += len(chunk)
    return "\n\n".join(out)


def _sources_line(store, project_id):
    lines = [f"- {s['title']} ({s['kind']})" for s in store.list_sources(project_id) if s["status"] == "ready"]
    return "\n".join(lines[:40])


def _system(ctx, contract):
    lang = _lang_name(ctx["lang"])
    return skills.compose(ctx["skillset"], "frd", contract.replace("{language}", lang), language=lang)


def _model_issues(reply):
    out = {}
    for issue in reply.get("issues") or []:
        out.setdefault(str(issue.get("id", "")).strip(), []).append(issue)
    return out


def _build_full(ctx):
    ctx["report"](5, "Writing the document…")
    q, by_rid, lang = ctx["quality"], ctx["by_rid"], ctx["lang"]
    contract = FULL_CONTRACT.replace("{extra}", _extra_contract(ctx["spec"], ctx["formats"])).replace("{rules}", q.prompt(_lang_name(lang)))
    user = (f"Project: {ctx['project']['name']}\n\nSources:\n{_sources_line(ctx['store'], ctx['project']['id'])}\n\n"
            "Accepted requirement atoms:\n" + "\n".join(_atom_lines(ctx["atoms"], ctx["rids"], ctx["conflicts"])))
    if ctx.get("context_atoms"):
        user += ("\n\nRelated atoms (context only: cite their IDs where useful, do not make items for them):\n"
                 + "\n".join(_atom_lines(ctx["context_atoms"], ctx["rids"], ctx["conflicts"])))
    if ctx.get("summaries"):
        user += "\n\nSummaries of the sources (for the descriptive sections):\n" + ctx["summaries"]
    if ctx.get("note"):
        user += NOTE + ctx["note"]
    custom = [(k, t) for k, t, _i in ctx["spec"] if k not in skills.FRD_KINDS and k not in ctx["formats"]]
    reply = ctx["complete"](_system(ctx, contract), user,
                            full_schema(q.rule_ids, [k for k, _t in custom], list(ctx["formats"])),
                            ctx["prefs"], ctx["api_key"])
    ctx["report"](85, "Checking quality…")
    texts = {str(i.get("id", "")).strip(): i["text"] for i in reply.get("items") or []
             if str(i.get("id", "")).strip() in by_rid and str(i.get("text", "")).strip()}
    model_issues = _model_issues(reply)

    def block(rid):
        atom = by_rid[rid]
        text = texts.get(rid) or atom["statement"]
        return _block(atom, rid, text, ctx["conflicts"], q.merge(
            model_issues.get(rid), q.checks(text, atom["type"], lang) if atom["type"] in CHECKED else []))

    frs = [r for r in by_rid if r.startswith("FR-")]
    placed, groups = set(), []
    for g in reply.get("groups") or []:
        ids = [str(i).strip() for i in g.get("ids") or []]
        ids = [i for i in ids if i in by_rid and i.startswith("FR-") and i not in placed]
        placed.update(ids)
        if ids and str(g.get("title", "")).strip():
            groups.append((g["title"].strip(), [block(r) for r in ids]))
    missing = [r for r in frs if r not in placed]
    if missing:                                   # the model skipped some: never drop a requirement
        groups.append((LABELS[lang]["other"], [block(r) for r in missing]))
    # Match by key; models sometimes answer with the section's title instead.
    by_title = {t.strip().casefold(): k for k, t in custom}
    extra = {}
    for e in reply.get("extra") or []:
        raw = str(e.get("key", "")).strip()
        k = raw if raw in dict(custom) else by_title.get(raw.casefold())
        if k and str(e.get("text") or "").strip():
            extra[k] = e["text"]
    tables = {}
    for tb in reply.get("tables") or []:
        k = str(tb.get("key", "")).strip()
        if k in ctx["formats"]:
            tables[k] = tb.get("rows") or []
    risks = _risk_blocks(ctx, tables.pop("risks", []), texts)
    return _assemble(ctx["spec"], lang, {"formats": ctx["formats"], "tables": tables, "risks": risks,
        "business": [block(r) for r in by_rid if r.startswith("BR-")],
        "current": [block(r) for r in by_rid if r.startswith("AS-")],
        "purpose": reply.get("purpose") or "", "context": reply.get("context") or "",
        "assumptions": reply.get("assumptions") or [], "groups": groups,
        "nfr": [block(r) for r in by_rid if r.startswith("NFR-")],
        "out_of_scope": [x.strip() for x in reply.get("out_of_scope") or [] if str(x).strip()],
        "questions": [block(r) for r in by_rid if r.startswith("Q-")], "extra": extra})


def _risk_blocks(ctx, ai_rows, texts):
    """One row per accepted risk atom, whatever the model returned: its row when it wrote one (first cell =
    the RSK ID), else the risk's own wording with the other columns left for the BA."""
    fmt = ctx["formats"].get("risks")
    if not fmt:
        return []
    width = len(fmt["columns"])
    by_id = {}
    for r in ai_rows or []:
        if isinstance(r, list) and r and str(r[0]).strip() in ctx["by_rid"]:
            by_id[str(r[0]).strip()] = [str(x).strip() for x in r]
    rows = []
    for rid, atom in ctx["by_rid"].items():
        if not rid.startswith("RSK-"):
            continue
        row = (by_id.get(rid) or [rid])[:width]
        row += [""] * (width - len(row))
        row[0] = rid
        if width > 1 and not row[1]:
            row[1] = texts.get(rid) or atom["statement"]
        rows.append(row)
    return _table_blocks("risks", {**fmt, "id_prefix": None}, rows, ctx["lang"])


def _build_changed(ctx, previous):
    snap, rids, by_rid, lang, q = previous["snapshot"], ctx["rids"], ctx["by_rid"], ctx["lang"], ctx["quality"]
    old = {b["id"]: (num, key, b) for num, key, b in req_blocks(previous["content"])}
    sections = {s["key"]: s for s in previous["content"]["sections"]}
    functional = sections.get("functional", {"subsections": []})
    group_titles = [sub["title"] for sub in functional.get("subsections") or []]
    old_group = {b["id"]: sub["title"] for sub in functional.get("subsections") or [] for b in sub["blocks"]}

    def unchanged(atom):
        s = snap.get(atom["id"])
        return s is not None and s["statement"] == atom["statement"] and s["type"] == atom["type"] \
            and s["rid"] == rids[atom["id"]] and rids[atom["id"]] in old

    to_write = [a for a in ctx["atoms"] if not unchanged(a)]
    removed = [aid for aid in snap if aid not in {a["id"] for a in ctx["atoms"]}]
    if not to_write and not removed:
        raise BuildError("The document is up to date: no atoms changed since the last version.")
    reply = {"items": [], "issues": []}
    if to_write:
        ctx["report"](10, f"Rewriting {len(to_write)} changed requirement(s)…")
        contract = CHANGED_CONTRACT.replace("{rules}", q.prompt(_lang_name(lang)))
        user = ("Existing functional sub-sections:\n" + ("\n".join(f"- {t}" for t in group_titles) or "(none)") +
                "\n\nTo write:\n" + "\n".join(_atom_lines(to_write, rids, ctx["conflicts"])))
        if ctx.get("note"):
            user += NOTE + ctx["note"]
        reply = ctx["complete"](_system(ctx, contract), user, changed_schema(q.rule_ids), ctx["prefs"],
                                ctx["api_key"])
    ctx["report"](85, "Checking quality…")
    written = {str(i.get("id", "")).strip(): i for i in reply.get("items") or [] if str(i.get("id", "")).strip() in by_rid}
    model_issues = _model_issues(reply)

    def block(rid):
        atom = by_rid[rid]
        if unchanged(atom):
            prev = dict(old[rid][2])
            prev.update(sources=_sources(atom["evidence"]), conflict=ctx["conflicts"].get(atom["id"]))
            return prev
        text = str((written.get(rid) or {}).get("text", "")).strip() or atom["statement"]
        return _block(atom, rid, text, ctx["conflicts"], q.merge(
            model_issues.get(rid), q.checks(text, atom["type"], lang) if atom["type"] in CHECKED else []))

    groups = {t: [] for t in group_titles}
    for rid in (r for r in by_rid if r.startswith("FR-")):
        if unchanged(by_rid[rid]) and rid in old_group:
            title = old_group[rid]
        else:
            title = str((written.get(rid) or {}).get("group", "")).strip() or old_group.get(rid) or LABELS[lang]["other"]
        groups.setdefault(title, []).append(block(rid))

    def text_of(key):
        sec = sections.get(key)
        return next((b["text"] for b in sec["blocks"] if b["kind"] == "text"), "") if sec else ""

    def list_of(key):
        sec = sections.get(key)
        return next((b["items"] for b in sec["blocks"] if b["kind"] == "list"), []) if sec else []
    extra = {k: text_of(k) for k, _t, _i in ctx["spec"] if k not in skills.FRD_KINDS}

    def rows_of(key):
        sec = sections.get(key)
        b = next((b for b in sec["blocks"] if b["kind"] == "table" and not b.get("heatmap")), None) if sec else None
        if not b:
            return []
        return [r[1:] for r in b["rows"]] if ctx["formats"][key].get("id_prefix") else b["rows"]
    tables = {k: rows_of(k) for k in ctx["formats"] if k != "risks"}
    return _assemble(ctx["spec"], lang, {"formats": ctx["formats"], "tables": tables,
        "business": [block(r) for r in by_rid if r.startswith("BR-")],
        "current": [block(r) for r in by_rid if r.startswith("AS-")],
        "purpose": text_of("purpose"), "context": text_of("context"), "assumptions": list_of("context"),
        "groups": list(groups.items()), "nfr": [block(r) for r in by_rid if r.startswith("NFR-")],
        "out_of_scope": list_of("out_of_scope"), "questions": [block(r) for r in by_rid if r.startswith("Q-")],
        "extra": extra})


def staleness(store, project_id, version):
    """What changed since the version was built (FR-DOC-05 AC1), per (sub)section."""
    if version is None:
        return None
    snap = version["snapshot"]
    types = version["content"].get("atom_types") or skills.DEFAULT_ATOM_TYPES
    current = {a["id"]: a for a in store.list_atoms(project_id, status="accepted") if a["type"] in types}
    where = {b["atom_id"]: num for num, _key, b in req_blocks(version["content"])}
    changed = [aid for aid, s in snap.items() if aid in current and
               (current[aid]["statement"] != s["statement"] or current[aid]["type"] != s["type"])]
    removed = [aid for aid in snap if aid not in current]
    added = [aid for aid in current if aid not in snap]
    sections = {}
    for aid in changed + removed:
        num = where.get(aid)
        if num:
            sections[num] = sections.get(num, 0) + 1
    return {"stale": bool(changed or removed or added), "changed": len(changed), "removed": len(removed),
            "added": len(added), "sections": sections, "atom_ids": changed + removed + added}


def diff(old, new):
    """Block-level differences between two versions (FR-DOC-02 AC2)."""
    def blocks(content):
        out = {}
        for sec in content["sections"]:
            for b in sec["blocks"]:
                out[b["id"]] = (sec["number"], b)
            for sub in sec.get("subsections") or []:
                for b in sub["blocks"]:
                    out[b["id"]] = (sub["number"], b)
        return out

    def text(b):
        return b.get("text") or "\n".join(b.get("items") or [])
    a, b = blocks(old["content"]), blocks(new["content"])
    changes = []
    for bid, (num, blk) in b.items():
        if bid not in a:
            changes.append({"id": bid, "section": num, "change": "added", "new": text(blk)})
        elif text(a[bid][1]) != text(blk) or a[bid][0] != num:
            changes.append({"id": bid, "section": num, "change": "changed", "old": text(a[bid][1]), "new": text(blk),
                            "moved_from": a[bid][0] if a[bid][0] != num else None})
    for bid, (num, blk) in a.items():
        if bid not in b:
            changes.append({"id": bid, "section": num, "change": "removed", "old": text(blk)})
    return changes


def suggest_fix(store, project_id, atom_id, rule, message, prefs, api_key, complete=complete_json,
                skillset=None):
    """A rewrite of the atom that fixes a quality finding; the BA accepts, edits or dismisses it (FR-DOC-06 AC2)."""
    atom = store.get_atom(atom_id)
    project = store.get_project(project_id)
    prefs = for_project(prefs, project)
    lang = _lang_name(output_language(project) or language_of([atom["statement"]]))
    system = skills.compose(skillset or skills.resolve(), "fix", FIX_CONTRACT, language=lang)
    user = f"Requirement ({atom['type']}): {atom['statement']}\n\nProblem ({rule}): {message}"
    reply = complete(system, user, FIX_SCHEMA, prefs, api_key)
    statement = (reply.get("statement") or "").strip()
    if not statement:
        raise LLMError("The model returned an empty suggestion; try again.")
    return {"atom_id": atom_id, "rule": rule, "statement": statement}
