"""The local index (5.0 C5): the pinned embedding model, chunking, cosine, skipping what is embedded, the index job,
"Похожие материалы", "Где используется", and that indexing never leaves this machine."""
import io
import json
import socket
import urllib.request

import numpy as np
import pytest

from core import index, local_llm, materials, settings
from core.store import Store
from tests import fake_embed


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


@pytest.fixture()
def pid(lib):
    return lib.ensure_default_project()["id"]


@pytest.fixture()
def calls(monkeypatch, app_module, lib):
    """The fake model, and index passes run inline instead of in a background job."""
    seen = []
    fake_embed.install(monkeypatch, index, seen)

    def run_now(project_id, force_material=None):
        index.index_project(lib, project_id, force_material=force_material)
        return "inline"
    monkeypatch.setattr(app_module, "schedule_index", run_now)
    return seen


def note(lib, pid, text, title=None):
    return materials.import_text(lib, lib.get_project(pid), text, title)


# ── the model ────────────────────────────────────────────────────────────────

def test_the_embedding_model_is_pinned_like_the_chat_models():
    [m] = local_llm.EMBED_MODELS
    assert m.file.endswith("Q8_0.gguf") and len(m.asset.sha256) == 64 and m.asset.size > 500_000_000
    assert "/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/" in m.asset.url and "/main/" not in m.asset.url
    assert m.id not in local_llm.MODELS_BY_ID and local_llm._any_model(m.id) is m


def test_status_lists_the_embedding_model_and_downloads_it(client, app_module, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    body = client.get("/api/local-llm").get_json()
    assert [m["id"] for m in body["embed_models"]] == ["qwen3-embedding-0.6b"]
    assert body["embed_models"][0]["installed"] is False
    assert "qwen3-embedding-0.6b" not in [m["id"] for m in body["models"]]
    started = []
    monkeypatch.setattr(app_module.local_llm.installer, "start", lambda m: started.append(m))
    assert client.post("/api/local-llm/download", json={"model": "qwen3-embedding-0.6b"}).status_code == 200
    assert started == ["qwen3-embedding-0.6b"]
    assert client.delete("/api/local-llm/models/qwen3-embedding-0.6b").status_code == 200


def test_the_embedding_server_runs_with_its_own_flags_port_and_pid_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    started = []

    class Proc:
        pid = 4242

        def poll(self):
            return None

    monkeypatch.setattr(local_llm.subprocess, "Popen", lambda cmd, **k: started.append(cmd) or Proc())
    monkeypatch.setattr(local_llm, "model_installed", lambda mid: True)
    monkeypatch.setattr(local_llm, "server_binary", lambda: str(tmp_path / "llama-server"))

    class Health:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(local_llm.urllib.request, "urlopen", lambda *a, **k: Health())
    rt = local_llm.Runtime(name="embed-server", embedding=True)
    url, key = rt.acquire("qwen3-embedding-0.6b")
    rt.release()
    cmd = started[0]
    assert "--embedding" in cmd and cmd[cmd.index("--pooling") + 1] == "last" and "--jinja" not in cmd
    assert url.startswith("http://127.0.0.1:") and cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert (tmp_path / "local-llm" / "embed-server.pid").read_text().split()[0] == "4242"
    assert not (tmp_path / "local-llm" / "server.pid").exists()
    assert rt.log_path().endswith("embed-server.log")
    rt._proc = None


def test_unavailable_without_the_model(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    assert index.model_id() is None and index.available() is False
    assert index.info()["model"] == "qwen3-embedding-0.6b"
    with pytest.raises(index.IndexUnavailable):
        index.embed(["текст"])


def test_tuning_defaults_and_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    assert settings.load_settings()["tuning"] == {"label_assign": 0.45, "graph_edge": 0.30, "retrieve_k": 12}
    settings.save_settings({"tuning": {"graph_edge": 0.5}})
    assert index.tuning() == {"label_assign": 0.45, "graph_edge": 0.5, "retrieve_k": 12}
    with pytest.raises(ValueError):
        settings.save_settings({"tuning": {"nope": 1}})
    with pytest.raises(ValueError):
        settings.save_settings({"embed_model": "gpt-17"})


# ── embedding through the local server ───────────────────────────────────────

class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_embed_batches_16_and_normalises_and_never_leaves_the_machine(tmp_path, monkeypatch):
    """Indexing with the local model only ever talks to 127.0.0.1: every other connection fails the test."""
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(index, "model_id", lambda: "qwen3-embedding-0.6b")
    monkeypatch.setattr(local_llm.embed_runtime, "acquire", lambda mid: ("http://127.0.0.1:9", "k"))
    monkeypatch.setattr(local_llm.embed_runtime, "release", lambda: None)
    sent = []

    def opener(req, timeout=None):
        sent.append(req.full_url)
        assert req.headers["Authorization"] == "Bearer k"
        batch = json.loads(req.data)["input"]
        data = [{"index": i, "embedding": [3.0, 4.0] if t else [0, 0]} for i, t in reversed(list(enumerate(batch)))]
        return _Resp(json.dumps({"data": data}).encode())
    real_connect = socket.create_connection

    def guarded(address, *a, **k):
        assert address[0] in ("127.0.0.1", "localhost"), f"network call to {address}"
        return real_connect(address, *a, **k)
    monkeypatch.setattr(socket, "create_connection", guarded)
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    out = index.embed([f"t{i}" for i in range(20)], opener=opener)
    assert len(out) == 20 and np.allclose(out[0], [0.6, 0.8])
    assert sent == ["http://127.0.0.1:9/v1/embeddings"] * 2


def test_indexing_a_project_makes_no_network_call(lib, pid, monkeypatch):
    fake_embed.install(monkeypatch, index)

    def no_network(*a, **k):
        raise AssertionError("network call during indexing")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    note(lib, pid, "Регламент приёма заявок дилеров.")
    out = index.index_project(lib, pid)
    assert out["materials"] == 1


# ── chunking and vectors ─────────────────────────────────────────────────────

def test_chunks_are_about_800_characters_and_cut_between_sentences():
    sentence = "Заявка дилера проверяется оператором в течение одного рабочего дня. "
    text = sentence * 40
    chunks = index.chunk_text(text)
    assert len(chunks) > 1 and all(len(c) <= 800 for c in chunks) and all(len(c) > 600 for c in chunks[:-1])
    assert all(c.endswith(".") for c in chunks)
    assert " ".join(chunks) == " ".join(text.split())
    long = "слово " * 400                                    # no sentence end at all: cut at a space
    assert all(len(c) <= 800 and not c.startswith(" ") for c in index.chunk_text(long))
    assert index.chunk_text("") == [] and index.chunk_text("Коротко.") == ["Коротко."]
    assert index.chunk_text("Первый абзац\nВторой абзац") == ["Первый абзац Второй абзац"]


def test_segment_windows_group_lines_by_about_600_characters():
    segs = [{"idx": i, "text": f"Реплика номер {i} " + "х" * 180} for i in range(7)]
    wins = index.segment_windows(segs)
    assert [w[0] for w in wins] == [0, 3, 6] and all(len(t) <= 600 for _i, t in wins)
    assert index.segment_windows([{"idx": 0, "text": " "}]) == []


def test_blobs_and_cosine():
    v = [0.6, 0.8, 0.0]
    blob = index.to_blob(v)
    assert len(blob) == 12 and blob == np.array(v, dtype="<f4").tobytes()
    assert np.allclose(index.from_blob(blob), v)
    assert index.cosine([1, 0], [1, 0]) == pytest.approx(1.0) and index.cosine([1, 0], [0, 2]) == pytest.approx(0.0)
    assert index.cosine([1, 1], [2, 2]) == pytest.approx(1.0) and index.cosine([0, 0], [1, 0]) == 0.0


# ── the index pass ───────────────────────────────────────────────────────────

def test_index_project_embeds_materials_meetings_and_atoms_and_skips_what_is_done(client, lib, pid, monkeypatch):
    seen = []
    fake_embed.install(monkeypatch, index, seen)
    m = note(lib, pid, "Регламент приёма заявок. " * 50)
    meeting = lib.create_source(pid, "transcript", "Созвон")
    lib.save_transcript(meeting["id"], {"segments": [{"text": "Дилер спросил про заявки " * 10} for _ in range(5)]})
    [aid] = lib.add_atoms(pid, [{"type": "functional", "statement": "Система принимает заявки",
                                 "evidence": [{"source_id": meeting["id"], "segment_idx": 0, "quote": "заявки"}]}])
    steps = []
    out = index.index_project(lib, pid, progress=lambda d, t: steps.append((d, t)))
    assert out["materials"] == 1 and out["meetings"] == 1 and out["atoms"] == 1
    assert steps[0] == (0, 3) and steps[-1] == (3, 3)
    chunks = lib.material_chunks(m["id"])
    assert len(chunks) == 2 and all(len(c["embedding"]) == 4 * fake_embed.DIM for c in chunks)
    wins = lib.embeddings("segment", meeting["id"])
    assert sorted(wins) == [0, 2, 4] and lib.embeddings("atom", aid)[0]["text"] == "Система принимает заявки"
    # nothing changed: nothing is embedded again
    seen.clear()
    assert index.index_project(lib, pid) == {"materials": 0, "meetings": 0, "atoms": 0, "labeled": {}}
    assert seen == []
    # an edited atom is embedded again, only that one text
    lib.update_atom(aid, statement="Система принимает и проверяет заявки")
    index.index_project(lib, pid)
    assert seen == [["Система принимает и проверяет заявки"]]
    # a rejected atom is dropped from the index
    lib.update_atom(aid, status="rejected", reject_reason="wrong")
    index.index_project(lib, pid)
    assert lib.embeddings("atom", aid) == {}
    # "Переиндексировать": re-embeds the material from scratch
    seen.clear()
    index.index_project(lib, pid, force_material=m["id"])
    assert sum(len(b) for b in seen) == 2


def test_index_route_and_job(client, app_module, lib, pid, monkeypatch):
    fake_embed.install(monkeypatch, index)
    m = note(lib, pid, "Текст материала.")
    res = client.post(f"/api/projects/{pid}/index", json={"material_id": m["id"]}).get_json()
    assert res["available"] is True and res["job_id"]
    for _ in range(100):
        job = client.get(f"/job/{res['job_id']}").get_json()
        if job["status"] != "processing":
            break
        __import__("time").sleep(0.05)
    assert job["status"] == "done" and job["result"]["materials"] == 1
    assert lib.material_chunks(m["id"])
    assert client.post("/api/projects/nope/index").status_code == 404


def test_one_waiting_pass_per_project(client, app_module, lib, pid, monkeypatch):
    fake_embed.install(monkeypatch, index)
    started = []
    monkeypatch.setattr(app_module.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args)})())
    first = app_module.schedule_index(pid)
    assert app_module.schedule_index(pid) == first and len(started) == 1      # the waiting pass covers it
    app_module._index_pending.clear()


def test_no_index_job_without_the_model(client, app_module, lib, pid):
    assert app_module.schedule_index(pid) is None
    body = client.post(f"/api/projects/{pid}/materials", json={"text": "Текст"}).get_json()
    assert body["index_job"] is None
    m = body["materials"][0]
    assert client.get(f"/api/materials/{m['id']}/related").get_json() == {
        "related": [], **index.info()}
    graph = client.get(f"/api/projects/{pid}/materials/graph").get_json()
    assert graph["available"] is False and graph["nodes"] == []


def test_importing_a_material_triggers_the_index(client, lib, pid, calls):
    m = client.post(f"/api/projects/{pid}/materials", json={"text": "Регламент заявок."}).get_json()["materials"][0]
    assert lib.material_chunks(m["id"]) and calls


# ── related ──────────────────────────────────────────────────────────────────

def test_related_ranks_by_best_chunk(client, lib, pid, calls):
    a = note(lib, pid, "Регламент приёма заявок дилеров: сроки, проверка, отказ.", "A")
    b = note(lib, pid, "Регламент приёма заявок дилеров и сроки проверки.", "B")
    c = note(lib, pid, "Отпуска и дежурства команды летом.", "C")
    d = note(lib, pid, "Приём заявок. " + "Совсем другая тема про погоду. " * 40, "D")
    index.index_project(lib, pid)
    body = client.get(f"/api/materials/{a['id']}/related").get_json()
    ids = [r["id"] for r in body["related"]]
    assert body["available"] is True and ids[0] == b["id"] and c["id"] not in ids[:2]
    assert ids.index(d["id"]) < (ids.index(c["id"]) if c["id"] in ids else 99)
    top = body["related"][0]
    assert top["title"] == "B" and top["ext"] == "md" and top["kind"] == "note" and 0.5 < top["score"] <= 1
    assert body["related"] == sorted(body["related"], key=lambda r: -r["score"]) and len(body["related"]) <= 5
    assert client.get("/api/materials/nope/related").status_code == 404


def test_related_is_empty_for_an_unindexed_material(lib, pid, monkeypatch):
    fake_embed.install(monkeypatch, index)
    m = note(lib, pid, "Ничего")
    assert index.related(lib, pid, m["id"]) == []


# ── "Где используется" ───────────────────────────────────────────────────────

def test_used_in_lists_atoms_and_the_documents_that_cite_them(client, lib, pid):
    m = note(lib, pid, "Система должна принимать заявки.", "Регламент")
    other = note(lib, pid, "Другое.")
    [a1, a2] = lib.add_atoms(pid, [
        {"type": "functional", "statement": "Принимать заявки", "evidence": [{"source_id": m["id"], "segment_idx": 0, "quote": "заявки"}]},
        {"type": "nfr", "statement": "Другое", "evidence": [{"source_id": other["id"], "segment_idx": 0, "quote": "Другое"}]}])
    doc = lib.document(pid)
    lib.requirement_ids(pid, [lib.get_atom(a1)])
    lib.add_version(doc["id"], {}, {a1: {"statement": "Принимать заявки", "type": "functional", "rid": "FR-1"}}, 1)
    other_doc = lib.create_document(pid, "brd", "BRD")
    lib.add_version(other_doc["id"], {}, {a2: {}}, 1)
    body = client.get(f"/api/materials/{m['id']}/used-in").get_json()
    assert body["atoms"] == [{"id": a1, "type": "functional", "statement": "Принимать заявки", "status": "pending",
                              "rid": "FR-1"}]
    assert body["documents"] == [{"id": doc["id"], "title": doc["title"], "version": 1}]
    lonely = note(lib, pid, "Никто не цитирует.")
    assert client.get(f"/api/materials/{lonely['id']}/used-in").get_json() == {"atoms": [], "documents": []}
    assert client.get("/api/materials/nope/used-in").status_code == 404
