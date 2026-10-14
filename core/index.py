"""Local index (spec 5.0 C5): embeddings for materials, meeting lines and requirements, computed on this machine.

Vectors come from the pinned embedding model (local_llm.EMBED_MODELS) through a second llama-server started with
`--embedding --pooling last` (local_llm.embed_runtime), are normalised, and are stored as float32 little-endian
BLOBs: materials as ~800-character sentence-aware chunks (`material_chunks`), meetings as ~600-character windows of
lines and atoms as their statement (`source_embeddings`). Cosine similarity is a dot product in numpy.

On top of that: "Похожие материалы" (max chunk cosine), the graph, and labels that assign themselves. While the
model is not downloaded, `available()` is False; callers then skip all of this and keyword search keeps working.
"""
import json
import re
import urllib.error
import urllib.request

import numpy as np

from core import local_llm, settings

EMBED_BATCH = 16                 # texts per /v1/embeddings request
CHUNK_CHARS = 800                # a material chunk
WINDOW_CHARS = 600               # a window of meeting lines
RELATED_TOP = 5
UNSEEDED_MIN = 0.35              # a label with no seed: materials closer than this to the label's name ...
UNSEEDED_TOP = 5                 # ... at most this many
GRAPH_MAX_EDGES = 5              # per node
GRAPH_MAX_NODES = 200            # the client's force layout is fine up to about this many
ATOM_STATUSES = ("accepted", "pending")


class IndexUnavailable(Exception):
    """The embedding model is not downloaded (or its server did not answer)."""


# ── the model ────────────────────────────────────────────────────────────────

def model_id():
    """The embedding model to use: the chosen one if downloaded, else any downloaded one, else None."""
    preferred = settings.load_settings().get("embed_model")
    if preferred and local_llm.model_installed(preferred):
        return preferred
    have = local_llm.installed_embed_models()
    return have[0] if have else None


def available():
    return local_llm.server_binary() is not None and model_id() is not None


def info():
    """What the UI needs for "Скачайте модель индекса": whether the index works and which model to download."""
    m = local_llm.EMBED_MODELS[0]
    return {"available": available(), "model": m.id, "label": m.label, "size": m.asset.size}


def tuning():
    return settings.load_settings()["tuning"]


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def embed(texts, opener=urllib.request.urlopen):
    """Normalised vectors for texts, through the local embedding server, EMBED_BATCH texts per request."""
    texts = list(texts)
    if not texts:
        return []
    mid = model_id()
    if mid is None:
        raise IndexUnavailable("the index model is not downloaded")
    url, key = local_llm.embed_runtime.acquire(mid)
    out = []
    try:
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i:i + EMBED_BATCH]
            req = urllib.request.Request(url + "/v1/embeddings", data=json.dumps({"input": batch}).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            with opener(req, timeout=300) as resp:
                body = json.loads(resp.read())
            data = sorted(body["data"], key=lambda d: d.get("index", 0))
            if len(data) != len(batch):
                raise IndexUnavailable("the index model returned the wrong number of vectors")
            out += [_unit(d["embedding"]).tolist() for d in data]
    except (urllib.error.URLError, ConnectionError, TimeoutError, ValueError, KeyError) as e:
        raise IndexUnavailable(f"the index model did not answer ({getattr(e, 'reason', e)})")
    finally:
        local_llm.embed_runtime.release()
    return out


# ── vectors ──────────────────────────────────────────────────────────────────

def to_blob(vec):
    return np.asarray(vec, dtype="<f4").tobytes()


def from_blob(blob):
    return np.frombuffer(blob, dtype="<f4")


def cosine(a, b):
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    return float(a @ b / (na * nb)) if na and nb else 0.0


def _vectors(texts, known):
    """Blobs for texts, embedding only those not already in `known` ({text: blob})."""
    todo = [t for t in dict.fromkeys(texts) if t not in known]
    if todo:
        known = {**known, **{t: to_blob(v) for t, v in zip(todo, embed(todo))}}
    return [known[t] for t in texts], len(todo)


# ── chunking ─────────────────────────────────────────────────────────────────

def _sentences(text, size):
    out = []
    for para in re.split(r"\n+", text or ""):
        para = " ".join(para.split())
        for s in re.split(r"(?<=[.!?…;])\s+", para) if para else []:
            while len(s) > size:                         # a sentence longer than a chunk: cut at a space
                cut = s.rfind(" ", 0, size)
                cut = cut if cut > size // 2 else size
                out.append(s[:cut].strip())
                s = s[cut:].strip()
            if s:
                out.append(s)
    return out


def chunk_text(text, size=CHUNK_CHARS):
    """About `size` characters per chunk, cut between sentences (inside one only when it is longer than a chunk)."""
    chunks, cur = [], ""
    for s in _sentences(text, size):
        if cur and len(cur) + 1 + len(s) > size:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def segment_windows(segments, size=WINDOW_CHARS):
    """Consecutive meeting lines grouped into windows of about `size` characters: [(first segment idx, text)]."""
    out, first, cur = [], None, ""
    for s in segments:
        text = " ".join((s.get("text") or "").split())
        if not text:
            continue
        if cur and len(cur) + 1 + len(text) > size:
            out.append((first, cur))
            first, cur = None, ""
        if first is None:
            first = s["idx"]
        cur = f"{cur} {text}".strip()
    if cur:
        out.append((first, cur))
    return out


# ── indexing ─────────────────────────────────────────────────────────────────

def index_material(store, source_id, force=False):
    """Chunk and embed one material; returns True when something was (re)embedded."""
    chunks = chunk_text(store.get_material(source_id)["text"])
    old = store.material_chunks(source_id)
    if not force and [o["text"] for o in old] == chunks and all(o["embedding"] for o in old):
        return False
    known = {} if force else {o["text"]: o["embedding"] for o in old if o["embedding"]}
    blobs, _n = _vectors(chunks, known)
    store.set_material_chunks(source_id, list(zip(chunks, blobs)))
    return True


def _index_entity(store, entity, entity_id, rows):
    """rows: [(idx, text)]. Embeds what changed; returns True when the stored rows changed."""
    old = store.embeddings(entity, entity_id)
    if {i: t for i, t in rows} == {i: o["text"] for i, o in old.items()} and all(o["embedding"] for o in old.values()):
        return False
    known = {o["text"]: o["embedding"] for o in old.values() if o["embedding"]}
    blobs, _n = _vectors([t for _i, t in rows], known)
    store.set_embeddings(entity, entity_id, [(i, t, b) for (i, t), b in zip(rows, blobs)])
    return True


def index_project(store, project_id, progress=lambda done, total: None, force_material=None):
    """Bring the project's index up to date: materials, meeting windows, accepted and pending atoms. What is already
    embedded with the same text is skipped. A material embedded for the first time gets the labels whose centroid
    is close enough. `force_material`: re-embed that one from scratch ("Переиндексировать")."""
    mats = store.list_materials(project_id)
    meetings = [s for s in store.list_sources(project_id) if s.get("status") == "ready"]
    atoms = [a for a in store.list_atoms(project_id) if a["status"] in ATOM_STATUSES]
    total, done = len(mats) + len(meetings) + (1 if atoms else 0), 0
    out = {"materials": 0, "meetings": 0, "atoms": 0, "labeled": {}}
    progress(done, total)
    for m in mats:
        force = m["id"] == force_material
        fresh = force or not store.material_chunks(m["id"])
        if index_material(store, m["id"], force=force):
            out["materials"] += 1
            if fresh:
                got = assign_from_centroids(store, project_id, m["id"])
                if got:
                    out["labeled"][m["id"]] = got
        done += 1
        progress(done, total)
    for s in meetings:
        segs = [x for x in store.transcript(s["id"])[0] if not x.get("provisional")]
        if _index_entity(store, "segment", s["id"], segment_windows(segs)):
            out["meetings"] += 1
        done += 1
        progress(done, total)
    for a in atoms:
        if _index_entity(store, "atom", a["id"], [(0, a["statement"])]):
            out["atoms"] += 1
    if atoms:
        done += 1
        progress(done, total)
    store.drop_embeddings_except("segment", {s["id"] for s in meetings}, project_id)
    store.drop_embeddings_except("atom", {a["id"] for a in atoms}, project_id)
    return out


# ── similarity ───────────────────────────────────────────────────────────────

def material_matrices(store, project_id):
    """{source_id: chunks × dim matrix} of the project's indexed live materials."""
    groups = {}
    for sid, blob in store.project_chunks(project_id):
        groups.setdefault(sid, []).append(from_blob(blob))
    return {sid: np.vstack(vs) for sid, vs in groups.items()}


def _best(a, b):
    """Max cosine between any chunk of a and any chunk of b (rows are unit vectors)."""
    return float((a @ b.T).max())


def related(store, project_id, source_id, k=RELATED_TOP):
    """[(source_id, score)] of the materials most like this one, by their best pair of chunks."""
    mats = material_matrices(store, project_id)
    a = mats.get(source_id)
    if a is None:
        return []
    scores = sorted(((sid, _best(a, m)) for sid, m in mats.items() if sid != source_id), key=lambda x: -x[1])
    return [(sid, round(s, 4)) for sid, s in scores[:k] if s > 0]


def pair_scores(mats):
    """(ids, n × n matrix of best-chunk cosine) for {id: matrix}."""
    ids = list(mats)
    if not ids:
        return ids, np.zeros((0, 0), dtype=np.float32)
    allc = np.vstack([mats[i] for i in ids])
    offsets = np.cumsum([0] + [len(mats[i]) for i in ids[:-1]])
    out = np.zeros((len(ids), len(ids)), dtype=np.float32)
    for r, i in enumerate(ids):
        out[r] = np.maximum.reduceat((mats[i] @ allc.T).max(axis=0), offsets)
    return ids, out


def graph(store, project_id, threshold=None, max_edges=GRAPH_MAX_EDGES, max_nodes=GRAPH_MAX_NODES):
    """Materials as nodes (first label and its colour), edges between pairs above the threshold, at most `max_edges`
    per node (strongest first). Over `max_nodes`, the best-connected ones are kept and `truncated` is set."""
    threshold = tuning()["graph_edge"] if threshold is None else threshold
    rows = store.list_materials(project_id)
    ids, scores = pair_scores(material_matrices(store, project_id))
    pairs = sorted(((float(scores[i, j]), ids[i], ids[j]) for i in range(len(ids)) for j in range(i + 1, len(ids))
                    if scores[i, j] > threshold), key=lambda x: -x[0])
    degree, edges = {}, []
    for w, a, b in pairs:
        if degree.get(a, 0) < max_edges and degree.get(b, 0) < max_edges:
            edges.append({"a": a, "b": b, "w": round(w, 4)})
            degree[a], degree[b] = degree.get(a, 0) + 1, degree.get(b, 0) + 1
    truncated = len(rows) > max_nodes
    if truncated:
        order = sorted(range(len(rows)), key=lambda i: (-degree.get(rows[i]["id"], 0), i))[:max_nodes]
        rows = [rows[i] for i in sorted(order)]
        keep = {m["id"] for m in rows}
        edges = [e for e in edges if e["a"] in keep and e["b"] in keep]
    nodes = [{"id": m["id"], "title": m["title"], "ext": m["ext"], "kind": m["material_kind"],
              "label": m["labels"][0]["name"] if m["labels"] else None,
              "color": m["labels"][0]["color"] if m["labels"] else None} for m in rows]
    return {"nodes": nodes, "edges": edges, "truncated": truncated}


# ── labels that assign themselves ────────────────────────────────────────────

def refresh_centroid(store, label_id):
    """The label's centroid: the mean of its members' chunk means (unit vectors), or none without indexed members."""
    means = []
    for sid in store.label_members(label_id):
        chunks = store.material_chunks(sid)
        vecs = [from_blob(c["embedding"]) for c in chunks if c["embedding"]]
        if vecs:
            means.append(_unit(np.mean(vecs, axis=0)))
    store.set_label_centroid(label_id, to_blob(_unit(np.mean(means, axis=0))) if means else None)


def _assign(store, project_id, label_id, scores, threshold, limit=None):
    """Put the label ("auto", with the score) on materials scoring at least `threshold`, best first. A material that
    already has a row for this label (the BA's, an earlier auto one, or a removal tombstone) is left alone."""
    rows = store.label_rows(project_id)
    assigned = []
    for sid, score in sorted(scores.items(), key=lambda x: -x[1]):
        if score < threshold or (limit is not None and len(assigned) >= limit):
            break
        if (sid, label_id) in rows:
            continue
        if store.assign_label(sid, label_id, by="auto", score=round(score, 4)):
            assigned.append({"id": sid, "score": round(score, 4)})
    return assigned


def auto_assign_label(store, project_id, label, seed_id=None):
    """A new label finds its materials. With a seed: every material whose best chunk is within `label_assign` of the
    seed's chunks. Without: the materials closest to the label's name (top UNSEEDED_TOP above UNSEEDED_MIN).
    Returns [{id, score}] of what it assigned; the centroid is refreshed either way."""
    mats = material_matrices(store, project_id)
    if seed_id:
        if seed_id not in mats and index_material(store, seed_id):
            mats = material_matrices(store, project_id)
        seed = mats.get(seed_id)
        scores = {sid: _best(seed, m) for sid, m in mats.items() if sid != seed_id} if seed is not None else {}
        assigned = _assign(store, project_id, label["id"], scores, tuning()["label_assign"])
    else:
        q = np.asarray(embed([label["name"]])[0], dtype=np.float32)
        scores = {sid: float((m @ q).max()) for sid, m in mats.items()}
        assigned = _assign(store, project_id, label["id"], scores, UNSEEDED_MIN, limit=UNSEEDED_TOP)
    refresh_centroid(store, label["id"])
    return assigned


def assign_from_centroids(store, project_id, source_id):
    """A newly indexed material gets every label whose centroid is within `label_assign` of one of its chunks."""
    chunks = [from_blob(c["embedding"]) for c in store.material_chunks(source_id) if c["embedding"]]
    if not chunks:
        return []
    m, threshold, got = np.vstack(chunks), tuning()["label_assign"], []
    for label_id, blob in store.label_centroids(project_id):
        score = float((m @ from_blob(blob)).max())
        if _assign(store, project_id, label_id, {source_id: score}, threshold):
            got.append(label_id)
            refresh_centroid(store, label_id)
    return got
