"""Спросить (spec 5.0 C6): questions answered from the project's meetings, requirements and materials.

Retrieval: the question is embedded by the local index and compared (cosine) with the chunks of the project's
materials (only those "в контексте" when the switch is on), the meeting windows and the atoms' statements; the
best `tuning.retrieve_k` become numbered sources. Up to FTS_EXTRA keyword hits (FTS5) add exact terms the vectors
missed. Without the index model only the keyword search runs, and the answer says so.

The answer: the project's `ask` skill (editable like the recap skills) plus the app's contract below, through the
project's provider (core/llm.for_project: a "Только локально" project never reaches the cloud). The model puts
[Источник N] / [Source N] after every claim; those markers become citations that open the source. It may end with
one intent, create_question, which becomes a Q atom quoting the cited sources.

The short mode answers a question heard in a live call in two sentences with one citation (core/live_questions).
"""
import json
import re
import time

import numpy as np

from core import index, skills

STAGE = "ask"
FTS_EXTRA = 4                    # keyword hits added for exact terms
QUOTE_CHARS = 240                # evidence quoted from a cited source
SOURCE_CHARS = 1200              # a source as the model sees it
SHORT_K = 3                      # sources for the short (live) answer
SHORT_MIN_SCORE = 0.5            # the live card needs a material at least this close
NOT_FOUND = {"ru": "Не нашёл в материалах проекта.", "en": "Not found in the project's materials."}

CONTRACT = """Use only the numbered sources below the question. After every claim put the marker of the source it comes
from: [Источник N] when you answer in Russian, [Source N] in English (one marker per source, e.g. [Источник 2]
[Источник 5]). Never cite a number that is not listed.
If nothing in the sources answers the question, reply exactly: "Не нашёл в материалах проекта." (in English: "Not
found in the project's materials.") and nothing else.
Intent: only when the analyst asks to turn something into a question for the client (e.g. "сделай из этого вопрос
для клиента", "make a question"), write your short reply with the markers, then on the last line exactly
<intent>{"create_question": {"statement": "<the question for the client>", "source_ns": [N, ...]}}</intent>
where source_ns are the sources the question rests on. Otherwise never write <intent>."""

SHORT_CONTRACT = """A question was just asked in a live call. Answer it in at most two sentences, using only the
numbered sources, in the language of the question, and end with exactly one marker of the source you used:
[Источник N] in Russian, [Source N] in English. If the sources do not answer it, reply exactly: "—"."""

MARKER = re.compile(r"\[\s*(Источник|Источники|Source|Sources)\s+(\d+(?:\s*(?:,|и|and)\s*\d+)*)\s*\]", re.I)
INTENT = re.compile(r"<intent>\s*(\{.*?\})\s*</intent>", re.S)
INTENT_OPEN = "<intent>"


def lang_of(text):
    return "ru" if re.search(r"[а-яё]", text or "", re.I) else "en"


# ── retrieval ────────────────────────────────────────────────────────────────

def _first_sentence(text, limit=QUOTE_CHARS):
    text = " ".join((text or "").split())
    m = re.match(r"(.+?[.!?…])(?:\s|$)", text)
    out = m.group(1) if m and len(m.group(1)) >= 20 else text
    if len(out) > limit:
        cut = out.rfind(" ", 0, limit)
        out = out[:cut if cut > limit // 2 else limit]
    return out


def _atom_labels(store, project_id, atom_ids):
    if not atom_ids:
        return {}
    atoms = [store.get_atom(a) for a in atom_ids]
    return store.requirement_ids(project_id, atoms)


def _vector_hits(store, project_id, question, context_only, materials_only, k):
    """[(score, hit)] best first, or None when the index is not available."""
    if not index.available():
        return None
    try:
        q = np.asarray(index.embed([question])[0], dtype=np.float32)
    except index.IndexUnavailable:
        return None
    rows = store.ask_vectors(project_id, context_only=context_only, materials_only=materials_only)
    if not rows:
        return []
    m = np.vstack([index.from_blob(r["embedding"]) for r in rows])
    scores = m @ q
    order = np.argsort(-scores, kind="stable")[:k]
    return [(float(scores[i]), {key: rows[i][key] for key in ("entity", "entity_id", "locator", "title", "text", "start")})
            for i in order if scores[i] > 0]


def _keyword_hits(store, project_id, question, context_only, materials_only, limit):
    """Hits of the FTS5 index for the question's words (any of them), as sources."""
    out = []
    for h in store.search(project_id, question, limit=limit * 3, any_term=True):
        if h["entity"] == "material":
            m = store.get_material(h["id"])
            if context_only and not m["in_context"]:
                continue
            chunks = index.chunk_text(m["text"]) or [m["title"]]
            words = [w for w in re.findall(r"\w{4,}", question.casefold())]
            at = next((i for i, c in enumerate(chunks) if any(w in c.casefold() for w in words)), 0)
            out.append({"entity": "material", "entity_id": h["id"], "locator": at, "title": h["title"],
                        "text": chunks[at], "start": None})
        elif materials_only:
            continue
        elif h["entity"] == "segment":
            segs = store.transcript(h["source_id"], final=True)[0]
            seg = next((s for s in segs if s["idx"] == h["idx"]), None)
            if seg is None:
                continue
            out.append({"entity": "segment", "entity_id": h["source_id"], "locator": h["idx"], "title": h["title"],
                        "text": seg["text"], "start": h.get("start")})
        elif h["entity"] == "atom":
            out.append({"entity": "atom", "entity_id": h["id"], "locator": 0, "title": h["title"], "text": h["title"],
                        "start": None})
        if len(out) >= limit:
            break
    return out


def _covered(hit, hits):
    for h in hits:
        if h["entity"] != hit["entity"] or h["entity_id"] != hit["entity_id"]:
            continue
        if hit["entity"] == "segment":
            if " ".join(hit["text"].split()) in h["text"]:
                return True
        elif h["locator"] == hit["locator"]:
            return True
    return False


def retrieve(store, project_id, question, context_only=True, k=None, materials_only=False):
    """{sources: [{n, entity, entity_id, locator, title, text, start, score}], indexed, best}.
    `best` is the top cosine (0 without the index)."""
    k = int(k or index.tuning().get("retrieve_k") or 12)
    vec = _vector_hits(store, project_id, question, context_only, materials_only, k)
    indexed = vec is not None
    hits = [{**h, "score": round(s, 4)} for s, h in (vec or [])]
    extra = FTS_EXTRA if indexed else k
    for h in _keyword_hits(store, project_id, question, context_only, materials_only, k + FTS_EXTRA):
        if extra <= 0:
            break
        if not _covered(h, hits):
            hits.append({**h, "score": None})
            extra -= 1
    labels = _atom_labels(store, project_id, list(dict.fromkeys(h["entity_id"] for h in hits if h["entity"] == "atom")))
    for n, h in enumerate(hits, 1):
        h["n"] = n
        if h["entity"] == "atom":
            h["statement"] = h["text"]
            h["title"] = labels.get(h["entity_id"], h["title"])
    return {"sources": hits, "indexed": indexed, "best": max((h["score"] or 0 for h in hits), default=0.0)}


def sources_block(sources, lang):
    word = "Источник" if lang == "ru" else "Source"
    kinds = {"material": "material", "segment": "meeting", "atom": "requirement"}
    parts = []
    for s in sources:
        where = f"«{s['title']}»"
        if s["entity"] == "segment" and s.get("start") is not None:
            where += f", {int(s['start'] // 60):02d}:{int(s['start'] % 60):02d}"
        text = " ".join((s["text"] or "").split())[:SOURCE_CHARS]
        parts.append(f"[{word} {s['n']}] ({kinds[s['entity']]} {where})\n{text}")
    return "\n\n".join(parts)


def system_prompt(skillset, short=False, language_rule=""):
    system = skills.compose(skillset, STAGE, SHORT_CONTRACT if short else CONTRACT)
    return system + ("\n\n" + language_rule if language_rule else "")


def user_prompt(question, sources):
    lang = lang_of(question)
    return f"Question: {question.strip()}\n\nSources:\n\n{sources_block(sources, lang)}"


# ── the answer ───────────────────────────────────────────────────────────────

class StreamFilter:
    """Passes streamed text on, holding back an <intent> block (and a possible start of one at the end)."""

    def __init__(self, emit):
        self.emit = emit
        self.text = ""
        self.shown = 0

    def feed(self, piece):
        self.text += piece
        visible = self.text.split(INTENT_OPEN, 1)[0]
        if INTENT_OPEN not in self.text:
            keep = max((i for i in range(1, len(INTENT_OPEN)) if visible.endswith(INTENT_OPEN[:i])), default=0)
            visible = visible[:len(visible) - keep]
        if len(visible) > self.shown:
            self.emit(visible[self.shown:])
            self.shown = len(visible)


def parse_intent(text):
    """(answer without the intent, {statement, source_ns} or None)."""
    m = INTENT.search(text or "")
    intent = None
    if m:
        try:
            body = json.loads(m.group(1)).get("create_question")
            if isinstance(body, dict) and str(body.get("statement") or "").strip():
                ns = [int(n) for n in body.get("source_ns") or [] if str(n).strip().isdigit()]
                intent = {"statement": str(body["statement"]).strip(), "source_ns": ns}
        except (ValueError, AttributeError, TypeError):
            intent = None
    clean = (text or "").split(INTENT_OPEN, 1)[0]
    return clean.strip(), intent


def parse_citations(text, sources):
    """Markers → citations. Returns (text with one marker per known source and unknown ones removed,
    [{n, entity, entity_id, locator, title, start?}] in order of first mention)."""
    by_n = {s["n"]: s for s in sources}
    order = []

    def one(m):
        word = "Источник" if m.group(1).lower().startswith("источник") else "Source"
        ns = [int(x) for x in re.findall(r"\d+", m.group(2))]
        kept = [n for n in ns if n in by_n]
        for n in kept:
            if n not in order:
                order.append(n)
        return "".join(f"[{word} {n}]" for n in kept)

    out = MARKER.sub(one, text or "")
    out = re.sub(r"[ \t]+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out))
    cites = []
    for n in order:
        s = by_n[n]
        c = {k: s[k] for k in ("n", "entity", "entity_id", "locator", "title")}
        if s["entity"] == "segment":
            c["start"] = s.get("start")
        cites.append(c)
    return out.strip(), cites


def _evidence(store, source):
    """One evidence row for an atom created from an answer: a quote from the cited source's own text."""
    if source["entity"] == "segment":
        segs = store.transcript(source["entity_id"], final=True)[0]
        seg = next((s for s in segs if s["idx"] == source["locator"]), None)
        if seg is None:
            return None
        return {"source_id": source["entity_id"], "segment_idx": seg["idx"], "start": seg.get("start"),
                "speaker": seg.get("speaker"), "quote": _first_sentence(seg["text"], QUOTE_CHARS * 2)}
    if source["entity"] == "material":
        quote = _first_sentence(source["text"])
        segs = store.transcript(source["entity_id"], final=True)[0]
        seg = next((s for s in segs if quote in " ".join(s["text"].split())), None)
        return {"source_id": source["entity_id"], "segment_idx": seg["idx"] if seg else None, "start": None,
                "speaker": None, "quote": quote}
    atom = store.get_atom(source["entity_id"])
    ev = (atom.get("evidence") or [None])[0]
    if not ev:
        return None
    return {k: ev.get(k) for k in ("source_id", "segment_idx", "start", "speaker", "quote")}


def create_question(store, project_id, intent, sources, cited, model=None):
    """The create_question intent: a Q atom whose evidence quotes the sources it rests on (those it names, else
    the ones the answer cites). → {atom_id, label, statement} or None when there is nothing to quote."""
    by_n = {s["n"]: s for s in sources}
    ns = [n for n in intent["source_ns"] if n in by_n] or [c["n"] for c in cited]
    evidence, seen = [], set()
    for n in ns:
        ev = _evidence(store, by_n[n])
        if ev and (ev["source_id"], ev["quote"]) not in seen:
            seen.add((ev["source_id"], ev["quote"]))
            evidence.append(ev)
    if not evidence:
        return None
    [aid] = store.add_atoms(project_id, [{"type": "question", "statement": intent["statement"], "evidence": evidence}],
                            model=model)
    atom = store.get_atom(aid)
    return {"atom_id": aid, "label": store.requirement_ids(project_id, [atom])[aid], "statement": atom["statement"]}


def answer(store, project_id, question, context_only, generate, skillset=None, model=None, language_rule="",
           on_delta=lambda _t: None, on_stage=lambda _s: None, clock=time.monotonic):
    """Retrieve, ask the model, parse, act on the intent, save to the history.
    `generate(system, user, on_delta)` → text (the project's provider). Returns
    {id, answer, citations, created, sources_used, elapsed, indexed, model}."""
    question = (question or "").strip()
    if not question:
        raise ValueError("Ask a question first.")
    started = clock()
    on_stage("search")
    found = retrieve(store, project_id, question, context_only)
    sources = found["sources"]
    lang = lang_of(question)
    created = None
    if not sources:
        text, cites = NOT_FOUND[lang], []
        on_delta(text)
    else:
        on_stage("generate")
        stream = StreamFilter(on_delta)
        raw = generate(system_prompt(skillset or skills.resolve(), language_rule=language_rule),
                       user_prompt(question, sources), stream.feed)
        body, intent = parse_intent(raw)
        text, cites = parse_citations(body, sources)
        if not text:
            text = NOT_FOUND[lang]
        # A project with business analysis off (5.0.4) holds no requirements: the intent is dropped, the answer stays.
        if intent and store.get_project(project_id).get("analysis", True):
            created = create_question(store, project_id, intent, sources, cites, model=model)
    elapsed = round(clock() - started, 1)
    used = len({(c["entity"], c["entity_id"]) for c in cites})
    row = store.add_ask(project_id, question, text, cites, context_only, created=created, model=model,
                        elapsed=elapsed, sources_used=used, indexed=found["indexed"])
    return {"id": row["id"], "question": question, "answer": text, "citations": cites, "created": created,
            "sources_used": used, "elapsed": elapsed, "indexed": found["indexed"], "model": model,
            "context_only": bool(context_only), "created_at": row["created_at"]}


def short_answer(store, project_id, question, generate, skillset=None, min_score=SHORT_MIN_SCORE):
    """Two grounded sentences and one citation for a question heard in a call, from the materials "в контексте"
    only; None when no material is close enough (above `min_score`) or the model has no answer."""
    found = retrieve(store, project_id, question, context_only=True, k=SHORT_K, materials_only=True)
    sources = [s for s in found["sources"] if s["score"] is not None]
    if not found["indexed"] or not sources or sources[0]["score"] <= min_score:
        return None
    raw = generate(system_prompt(skillset or skills.resolve(), short=True), user_prompt(question, sources),
                   lambda _t: None)
    body, _intent = parse_intent(raw)
    text, cites = parse_citations(body, sources)
    plain = MARKER.sub("", text).strip()
    if not plain or plain in ("—", "-") or plain.rstrip(".") in (NOT_FOUND["ru"].rstrip("."), NOT_FOUND["en"].rstrip(".")):
        return None
    cite = cites[0] if cites else {k: sources[0][k] for k in ("n", "entity", "entity_id", "locator", "title")}
    return {"answer": re.sub(r"\s+([.,;:!?])", r"\1", plain), "citation": cite}
