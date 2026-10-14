"""The materials graph (5.0 C5): nodes with their first label, edges above tuning.graph_edge, at most 5 per node,
the best-connected 200 when there are more."""
import numpy as np
import pytest

from core import index, materials
from core.store import Store
from tests import fake_embed


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


@pytest.fixture()
def pid(lib, monkeypatch):
    fake_embed.install(monkeypatch, index)
    return lib.ensure_default_project()["id"]


def note(lib, pid, text, title):
    return materials.import_text(lib, lib.get_project(pid), text, title)


def test_nodes_edges_and_labels(client, lib, pid):
    a = note(lib, pid, "Регламент приёма заявок дилеров и сроки проверки.", "A")
    b = note(lib, pid, "Сроки проверки заявок дилеров по регламенту.", "B")
    c = note(lib, pid, "Отпуска команды летом.", "C")
    lab = lib.create_label(pid, "дилеры")
    lib.assign_label(a["id"], lab["id"])
    index.index_project(lib, pid)
    g = client.get(f"/api/projects/{pid}/materials/graph").get_json()
    assert g["available"] is True and g["truncated"] is False
    nodes = {n["id"]: n for n in g["nodes"]}
    assert set(nodes) == {a["id"], b["id"], c["id"]}
    assert nodes[a["id"]] == {"id": a["id"], "title": "A", "ext": "md", "kind": "note", "label": "дилеры",
                              "color": lab["color"]}
    assert nodes[c["id"]]["label"] is None and nodes[c["id"]]["color"] is None
    assert len(g["edges"]) == 1 and {g["edges"][0]["a"], g["edges"][0]["b"]} == {a["id"], b["id"]}
    # the edge's weight is what "Похожие материалы" shows
    rel = client.get(f"/api/materials/{a['id']}/related").get_json()["related"]
    assert rel[0]["id"] == b["id"] and rel[0]["score"] == g["edges"][0]["w"]
    assert client.get("/api/projects/nope/materials/graph").status_code == 404


def test_edges_respect_the_threshold(lib, pid, monkeypatch):
    note(lib, pid, "заявки дилеров сроки", "A")
    note(lib, pid, "заявки дилеров отпуск", "B")
    index.index_project(lib, pid)
    w = index.graph(lib, pid, threshold=0.0)["edges"][0]["w"]
    assert 0.5 < w < 0.8
    assert index.graph(lib, pid, threshold=w - 0.01)["edges"] and not index.graph(lib, pid, threshold=w + 0.01)["edges"]
    monkeypatch.setattr(index, "tuning", lambda: {"label_assign": 0.45, "graph_edge": 0.9, "retrieve_k": 12})
    assert index.graph(lib, pid)["edges"] == []


def test_at_most_five_edges_per_node_strongest_first(lib, pid):
    for i in range(9):
        note(lib, pid, "общая тема заявки дилеры " + f"слово{i}", f"M{i}")
    index.index_project(lib, pid)
    g = index.graph(lib, pid, threshold=0.1)
    degree = {}
    for e in g["edges"]:
        degree[e["a"]] = degree.get(e["a"], 0) + 1
        degree[e["b"]] = degree.get(e["b"], 0) + 1
    assert max(degree.values()) == 5 and len(g["edges"]) >= 15 and len(degree) == 9
    assert [e["w"] for e in g["edges"]] == sorted((e["w"] for e in g["edges"]), reverse=True)


def test_over_the_cap_the_best_connected_nodes_are_kept(lib, pid):
    cluster = [note(lib, pid, f"заявки дилеры регламент сроки {i}", f"C{i}") for i in range(4)]
    loners = [note(lib, pid, f"уникальное{i} одиночка{i} слово{i}", f"L{i}") for i in range(4)]
    index.index_project(lib, pid)
    g = index.graph(lib, pid, threshold=0.3, max_nodes=5)
    ids = {n["id"] for n in g["nodes"]}
    assert g["truncated"] is True and len(ids) == 5 and {c["id"] for c in cluster} <= ids
    assert all(e["a"] in ids and e["b"] in ids for e in g["edges"])
    assert index.graph(lib, pid, threshold=0.3)["truncated"] is False and loners


def test_unindexed_materials_are_nodes_without_edges(lib, pid):
    a = note(lib, pid, "заявки", "A")
    g = index.graph(lib, pid)
    assert [n["id"] for n in g["nodes"]] == [a["id"]] and g["edges"] == []


def test_pair_scores_match_the_best_chunk_pair():
    rng = np.random.default_rng(1)
    mats = {k: (lambda m: m / np.linalg.norm(m, axis=1, keepdims=True))(rng.normal(size=(n, 8)).astype(np.float32))
            for k, n in (("a", 3), ("b", 1), ("c", 4))}
    ids, s = index.pair_scores(mats)
    for i, x in enumerate(ids):
        for j, y in enumerate(ids):
            assert s[i, j] == pytest.approx(float((mats[x] @ mats[y].T).max()), abs=1e-5)
