"""The first-run gate (5.0 C8): `onboarding:v5` in setup-state.json, with the step to resume at."""
import json
import os


def test_fresh_install_starts_at_step_one_and_resumes(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    assert client.get("/api/onboarding").get_json() == {"done": False, "step": 1}
    assert client.post("/api/onboarding", json={"step": 4}).get_json() == {"done": False, "step": 4}
    assert client.get("/api/onboarding").get_json() == {"done": False, "step": 4}        # a restart resumes here
    assert client.post("/api/onboarding", json={"step": 7}).status_code == 400
    assert client.post("/api/onboarding", json={"step": "2"}).status_code == 400
    assert client.post("/api/onboarding", json={"done": True}).get_json()["done"] is True
    with open(os.path.join(tmp_path, "setup-state.json"), encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["onboarding:v5"] is True and saved["onboarding:v5:step"] == 4


def test_other_setup_state_is_kept(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    with open(os.path.join(tmp_path, "setup-state.json"), "w", encoding="utf-8") as f:
        json.dump({"model:v3_e2e_rnnt": True}, f)
    client.post("/api/onboarding", json={"done": True})
    with open(os.path.join(tmp_path, "setup-state.json"), encoding="utf-8") as f:
        assert json.load(f) == {"model:v3_e2e_rnnt": True, "onboarding:v5": True}


def test_local_llm_reports_the_machine(client, app_module, monkeypatch):
    monkeypatch.setitem(app_module.local_llm._machine_cache, "m", {"ram": 16 * 1024 ** 3, "chip": "M1 Pro", "os": "darwin"})
    assert client.get("/api/local-llm").get_json()["machine"] == {"ram": 16 * 1024 ** 3, "chip": "M1 Pro", "os": "darwin"}


def test_machine_info_reads_the_apple_chip(app_module, monkeypatch):
    import types
    llm = app_module.local_llm
    monkeypatch.setattr(llm, "_machine_cache", {})
    monkeypatch.setattr(llm.sys, "platform", "darwin")
    monkeypatch.setattr(llm, "total_ram_bytes", lambda: 32 * 1024 ** 3)
    info = llm.machine_info(run=lambda *a, **k: types.SimpleNamespace(stdout="Apple M3 Pro\n"))
    assert info == {"ram": 32 * 1024 ** 3, "chip": "M3 Pro", "os": "darwin"}
