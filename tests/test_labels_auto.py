"""Labels that assign themselves (5.0 C5): seeded and unseeded, tombstones and the BA's own rows respected, the
centroid kept up to date, and new materials picking up labels on import."""
import sqlite3

import numpy as np
import pytest

from core import index, materials
from core.store import Store
from tests import fake_embed

DEALERS = "Регламент приёма заявок дилеров: сроки проверки заявок и отказ дилеру."
DEALERS2 = "Сроки проверки заявок дилеров по регламенту приёма."
VACATION = "Отпуска команды летом и график дежурств."


@pytest.fixture()
def lib(app_module, monkeypatch, tmp_path):
    store = Store(root=str(tmp_path / "lib"), user="ba")
    monkeypatch.setattr(app_module, "library", store)
    return store


@pytest.fixture()
def pid(lib):
    return lib.ensure_default_project()["id"]


@pytest.fixture()
def fake(monkeypatch, app_module, lib):
    fake_embed.install(monkeypatch, index)
    monkeypatch.setattr(app_module, "schedule_index",
                        lambda project_id, force_material=None: index.index_project(lib, project_id) and None)


def add(client, pid, text, title):
    return client.post(f"/api/projects/{pid}/materials", json={"text": text, "title": title}).get_json()["materials"][0]


def labels_of(client, mid):
    return {x["name"]: x for x in client.get(f"/api/materials/{mid}").get_json()["labels"]}


def test_a_seeded_label_lands_on_the_seed_and_its_neighbours(client, lib, pid, fake):
    a, b, c = add(client, pid, DEALERS, "A"), add(client, pid, DEALERS2, "B"), add(client, pid, VACATION, "C")
    res = client.post(f"/api/projects/{pid}/labels", json={"name": "дилеры", "seed_material_id": a["id"]}).get_json()
    assert res["index"] is True and res["assigned"] == [a["id"], b["id"]] and res["label"]["count"] == 2
    assert [x["id"] for x in res["auto"]] == [b["id"]] and 0.45 <= res["auto"][0]["score"] <= 1
    assert labels_of(client, a["id"])["дилеры"]["assigned_by"] == "user"
    got = labels_of(client, b["id"])["дилеры"]
    assert got["assigned_by"] == "auto" and got["score"] == res["auto"][0]["score"]
    assert labels_of(client, c["id"]) == {}


def test_the_threshold_comes_from_tuning(client, lib, pid, fake, monkeypatch):
    a, b = add(client, pid, DEALERS, "A"), add(client, pid, DEALERS2, "B")
    monkeypatch.setattr(index, "tuning", lambda: {"label_assign": 0.99, "graph_edge": 0.3, "retrieve_k": 12})
    res = client.post(f"/api/projects/{pid}/labels", json={"name": "x", "seed_material_id": a["id"]}).get_json()
    assert res["assigned"] == [a["id"]] and res["auto"] == []


def test_an_unseeded_label_goes_to_the_materials_closest_to_its_name(client, lib, pid, fake):
    hits = [add(client, pid, f"Заявки дилеров номер {i}. Заявки.", f"Z{i}") for i in range(7)]
    off = add(client, pid, VACATION, "C")
    res = client.post(f"/api/projects/{pid}/labels", json={"name": "заявки"}).get_json()
    assert len(res["assigned"]) == 5 and set(res["assigned"]) <= {h["id"] for h in hits}
    assert all(x["score"] > 0.35 for x in res["auto"]) and off["id"] not in res["assigned"]
    none = client.post(f"/api/projects/{pid}/labels", json={"name": "ксилофон"}).get_json()
    assert none["assigned"] == [] and none["auto"] == []


def test_a_removed_auto_label_is_never_put_back(client, lib, pid, fake):
    a, b = add(client, pid, DEALERS, "A"), add(client, pid, DEALERS2, "B")
    res = client.post(f"/api/projects/{pid}/labels", json={"name": "дилеры", "seed_material_id": a["id"]}).get_json()
    lid = res["label"]["id"]
    assert client.delete(f"/api/materials/{b['id']}/labels/{lid}").status_code == 200
    with sqlite3.connect(lib.db_path) as c:
        assert c.execute("SELECT assigned_by FROM material_labels WHERE source_id = ?", (b["id"],)).fetchall() == [("removed",)]
    label = lib.get_label(lid)
    assert index.auto_assign_label(lib, pid, label, a["id"]) == []
    assert index.assign_from_centroids(lib, pid, b["id"]) == []
    assert "дилеры" not in labels_of(client, b["id"])
    # deleting the label and making it again by name keeps the removal
    assert client.delete(f"/api/labels/{lid}").status_code == 200
    assert [x["name"] for x in client.get(f"/api/projects/{pid}/labels").get_json()["labels"]] == []
    assert labels_of(client, a["id"]) == {}
    again = client.post(f"/api/projects/{pid}/labels", json={"name": "Дилеры", "seed_material_id": a["id"]}).get_json()
    assert again["label"]["id"] == lid and again["assigned"] == [a["id"]]
    assert "Дилеры" not in labels_of(client, b["id"]) and "Дилеры" in labels_of(client, a["id"])
    assert client.post(f"/api/projects/{pid}/labels", json={"name": "дилеры"}).status_code == 400


def test_the_bas_rows_are_never_touched_by_auto_runs(client, lib, pid, fake):
    a, b = add(client, pid, DEALERS, "A"), add(client, pid, DEALERS2, "B")
    lab = lib.create_label(pid, "ручная")
    client.post(f"/api/materials/{b['id']}/labels/{lab['id']}")
    assert index.auto_assign_label(lib, pid, lab, a["id"]) == []
    row = labels_of(client, b["id"])["ручная"]
    assert row["assigned_by"] == "user" and row["score"] is None


def test_the_centroid_follows_assign_and_unassign(client, lib, pid, fake):
    a, b, c = add(client, pid, DEALERS, "A"), add(client, pid, DEALERS2, "B"), add(client, pid, VACATION, "C")
    res = client.post(f"/api/projects/{pid}/labels", json={"name": "дилеры", "seed_material_id": a["id"]}).get_json()
    lid = res["label"]["id"]

    def centroid():
        rows = dict(lib.label_centroids(pid))
        return index.from_blob(rows[lid]) if lid in rows else None

    def mean_of(*ids):
        means = []
        for i in ids:
            v = np.mean([index.from_blob(x["embedding"]) for x in lib.material_chunks(i)], axis=0)
            means.append(v / np.linalg.norm(v))
        m = np.mean(means, axis=0)
        return m / np.linalg.norm(m)
    assert np.allclose(centroid(), mean_of(a["id"], b["id"]), atol=1e-5)
    client.post(f"/api/materials/{c['id']}/labels/{lid}")
    assert np.allclose(centroid(), mean_of(a["id"], b["id"], c["id"]), atol=1e-5)
    client.delete(f"/api/materials/{c['id']}/labels/{lid}")
    client.delete(f"/api/materials/{b['id']}/labels/{lid}")
    assert np.allclose(centroid(), mean_of(a["id"]), atol=1e-5)
    client.delete(f"/api/materials/{a['id']}/labels/{lid}")
    assert centroid() is None


def test_a_new_material_gets_the_labels_whose_centroid_is_close(client, lib, pid, fake):
    a = add(client, pid, DEALERS, "A")
    v = add(client, pid, VACATION, "V")
    client.post(f"/api/projects/{pid}/labels", json={"name": "дилеры", "seed_material_id": a["id"]})
    client.post(f"/api/projects/{pid}/labels", json={"name": "отпуск", "seed_material_id": v["id"]})
    new = add(client, pid, "Проверка заявок дилеров и сроки по регламенту приёма.", "New")
    got = labels_of(client, new["id"])
    assert set(got) == {"дилеры"} and got["дилеры"]["assigned_by"] == "auto" and got["дилеры"]["score"] >= 0.45
    far = add(client, pid, "Погода в выходные.", "Far")
    assert labels_of(client, far["id"]) == {}


def test_without_the_model_labels_work_as_before(client, lib, pid):
    a = materials.import_text(lib, lib.get_project(pid), DEALERS)
    materials.import_text(lib, lib.get_project(pid), DEALERS2)
    res = client.post(f"/api/projects/{pid}/labels", json={"name": "дилеры", "seed_material_id": a["id"]}).get_json()
    assert res["assigned"] == [a["id"]] and res["auto"] == [] and res["index"] is False


def test_export_drops_the_centroid(client, lib, pid, fake):
    a = add(client, pid, DEALERS, "A")
    client.post(f"/api/projects/{pid}/labels", json={"name": "дилеры", "seed_material_id": a["id"]})
    assert lib.label_centroids(pid)
    data = lib.export_project(pid)
    assert data["tables"]["labels"][0]["centroid"] is None
