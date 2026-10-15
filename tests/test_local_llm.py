import hashlib
import io
import os
import sys
import threading
import urllib.error

import pytest

from core import llm, local_llm, summarize
from core.local_llm import Asset, LocalModelError, Model, download, recommended_model_id

GB = 1024 ** 3


# ── downloads ────────────────────────────────────────────────────────────────

class FakeResp(io.BytesIO):
    def __init__(self, data, status):
        super().__init__(data)
        self.status = status


def serving(payload, ignore_range=False, fail_after=None):
    """urlopen stub serving `payload`, honouring Range like a CDN; records requests."""
    calls = []

    def opener(req, timeout=None):
        rng = req.get_header("Range")
        calls.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng and not ignore_range else 0
        body = payload[start:]
        if fail_after is not None and len(calls) == 1:
            body = body[:fail_after]               # connection drops mid-way
        return FakeResp(body, 206 if start else 200)
    opener.calls = calls
    return opener


def asset_for(data):
    return Asset("https://example/x.bin", hashlib.sha256(data).hexdigest(), len(data))


def test_download_verifies_and_renames(tmp_path):
    data = os.urandom(3 * 1024 * 1024 + 17)
    dest = str(tmp_path / "m.gguf")
    seen = []
    download(asset_for(data), dest, on_bytes=seen.append, opener=serving(data))
    assert open(dest, "rb").read() == data and not os.path.exists(dest + ".part")
    assert seen[-1] == len(data)


def test_download_resumes_a_partial_file(tmp_path):
    data = os.urandom(2 * 1024 * 1024)
    dest = str(tmp_path / "m.gguf")
    with open(dest + ".part", "wb") as f:
        f.write(data[:700_000])
    opener = serving(data)
    download(asset_for(data), dest, opener=opener)
    assert opener.calls == ["bytes=700000-"] and open(dest, "rb").read() == data


def test_download_retries_after_a_dropped_connection(tmp_path):
    data = os.urandom(1024 * 1024)
    opener = serving(data, fail_after=300_000)
    download(asset_for(data), str(tmp_path / "m"), opener=opener, sleep=lambda s: None)
    assert opener.calls == [None, "bytes=300000-"]


def test_server_ignoring_range_starts_over(tmp_path):
    data = os.urandom(500_000)
    dest = str(tmp_path / "m")
    with open(dest + ".part", "wb") as f:
        f.write(data[:100_000])
    download(asset_for(data), dest, opener=serving(data, ignore_range=True))
    assert open(dest, "rb").read() == data


def test_checksum_mismatch_is_rejected_and_discarded(tmp_path):
    data = b"x" * 1000
    bad = Asset("https://example/x.bin", "0" * 64, len(data))
    with pytest.raises(LocalModelError, match="damaged"):
        download(bad, str(tmp_path / "m"), opener=serving(data))
    assert not os.path.exists(tmp_path / "m.part") and not os.path.exists(tmp_path / "m")


def test_cancel_keeps_the_partial_file_for_later(tmp_path):
    data = os.urandom(3 * 1024 * 1024)
    cancel = threading.Event()
    with pytest.raises(local_llm.Cancelled):
        download(asset_for(data), str(tmp_path / "m"), cancel=cancel,
                 on_bytes=lambda n: cancel.set(), opener=serving(data))
    assert os.path.getsize(tmp_path / "m.part") == 1024 * 1024


def test_network_failure_gives_a_clear_error(tmp_path):
    def down(req, timeout=None):
        raise urllib.error.URLError("no route")
    with pytest.raises(LocalModelError, match="internet"):
        download(asset_for(b"abc"), str(tmp_path / "m"), opener=down, sleep=lambda s: None)


# ── choice of model ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("ram_gb,expect", [(64, "qwen3.6-35b-a3b"), (32, "qwen3.6-35b-a3b"), (24, "gemma-4-12b"),
                                           (15.5, "gemma-4-12b"), (8, "qwen3.5-4b"), (4, "qwen3.5-4b"), (0, "qwen3.5-4b")])
def test_recommended_model_follows_memory(ram_gb, expect):
    assert recommended_model_id(ram_gb * GB) == expect


def test_catalog_is_pinned():
    for m in local_llm.MODELS:
        assert "/resolve/" in m.asset.url and "/main/" not in m.asset.url, "weights must be pinned to a revision"
        assert len(m.asset.sha256) == 64 and m.asset.size > 1e9
    for a in local_llm.ENGINES.values():
        assert local_llm.ENGINE_BUILD in a.url and len(a.sha256) == 64


# ── installer ────────────────────────────────────────────────────────────────

def test_installer_refuses_when_the_disk_is_too_full(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(local_llm.shutil, "disk_usage", lambda p: type("U", (), {"free": 2 * GB})())
    monkeypatch.setattr(local_llm, "engine_asset", lambda: Asset("u", "0" * 64, 10))
    with pytest.raises(LocalModelError, match="disk space"):
        local_llm.Installer().start("gemma-4-12b")


def test_installer_downloads_engine_then_model(tmp_path, monkeypatch):
    import tarfile
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    engine_src = tmp_path / "src" / "llama-b1"
    engine_src.mkdir(parents=True)
    exe = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    (engine_src / exe).write_text("#!/bin/sh\n")
    tgz = tmp_path / "engine.tar.gz"
    with tarfile.open(tgz, "w:gz") as t:
        t.add(engine_src, arcname="llama-b1")
    engine_bytes, weights = tgz.read_bytes(), os.urandom(200_000)
    engine = Asset("https://x/llama-bin.tar.gz", hashlib.sha256(engine_bytes).hexdigest(), len(engine_bytes))
    model = Model("tiny", "Tiny", "tiny.gguf", asset_for(weights), min_ram_gb=1, context=512)
    monkeypatch.setattr(local_llm, "engine_asset", lambda: engine)
    monkeypatch.setattr(local_llm, "MODELS_BY_ID", {"tiny": model})
    monkeypatch.setattr(local_llm, "download", lambda asset, dest, on_bytes=None, cancel=None: (
        open(dest, "wb").write(engine_bytes if asset is engine else weights), on_bytes and on_bytes(asset.size)))
    inst = local_llm.Installer()
    inst.start("tiny")
    inst._thread.join(5)
    assert inst.status()["status"] == "done"
    assert local_llm.server_binary().endswith(exe) and local_llm.model_installed("tiny")
    if sys.platform != "win32":
        assert os.access(local_llm.server_binary(), os.X_OK)


def test_unknown_model_is_rejected():
    with pytest.raises(LocalModelError):
        local_llm.Installer().start("gpt-17")


# ── running a server (a tiny stand-in for llama-server) ──────────────────────

FAKE_SERVER = r'''#!{python}
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
args = sys.argv[1:]
port, key = int(args[args.index("--port") + 1]), args[args.index("--api-key") + 1]
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404); self.end_headers(); self.wfile.write(b"{{}}")
    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + key:
            self.send_response(401); self.end_headers(); return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for piece in ["## Итоги", "\n- карточка", " за 2 с"]:
                self.wfile.write(("data: " + json.dumps({{"choices": [{{"delta": {{"content": piece}}}}]}}) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n"); return
        assert body["response_format"]["type"] == "json_schema"
        out = {{"choices": [{{"finish_reason": "stop", "message": {{"content": json.dumps({{"atoms": [], "echo": body["messages"][1]["content"]}})}}}}]}}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
HTTPServer(("127.0.0.1", port), H).serve_forever()
'''


@pytest.fixture()
def fake_engine(tmp_path, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("the stand-in server is a shebang script")
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    folder = tmp_path / "local-llm" / "engine" / local_llm.ENGINE_BUILD / "llama-x"
    folder.mkdir(parents=True)
    server = folder / "llama-server"
    server.write_text(FAKE_SERVER.format(python=sys.executable))
    server.chmod(0o755)
    weights = b"GGUF" + b"\0" * 60
    model = Model("tiny", "Tiny", "tiny.gguf", asset_for(weights), min_ram_gb=1, context=512)
    monkeypatch.setattr(local_llm, "MODELS_BY_ID", {"tiny": model})
    monkeypatch.setattr(local_llm, "MODELS", [model])
    (tmp_path / "local-llm" / "models").mkdir()
    (tmp_path / "local-llm" / "models" / "tiny.gguf").write_bytes(weights)
    rt = local_llm.Runtime(idle_seconds=3600)
    monkeypatch.setattr(local_llm, "runtime", rt)
    yield rt
    rt.stop()


PREFS = {"llm_provider": "local", "claude_model": "claude-opus-5", "local_model": "tiny"}


def test_structured_json_through_the_built_in_server(fake_engine):
    out = llm.complete_json("sys", "текст транскрипта", {"type": "object"}, PREFS, None, "")
    assert out == {"atoms": [], "echo": "текст транскрипта"}
    assert fake_engine.running_model() == "tiny"
    llm.complete_json("sys", "again", {"type": "object"}, PREFS, None, "")    # reuses the running server
    assert fake_engine.running_model() == "tiny" and fake_engine._busy == 0


def test_streamed_summary_through_the_built_in_server(fake_engine):
    pieces = []
    text = summarize.summarize("[A] текст", PREFS, None, pieces.append)
    assert text == "## Итоги\n- карточка за 2 с" and len(pieces) == 3


def test_server_requires_the_private_key(fake_engine):
    import urllib.request
    url, _key = fake_engine.acquire("tiny")
    fake_engine.release()
    req = urllib.request.Request(url + "/v1/chat/completions", data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=5)
    assert e.value.code == 401


def test_server_that_dies_on_start_reports_why(fake_engine, tmp_path):
    server = local_llm.server_binary()
    with open(server, "w") as f:
        f.write("#!/bin/sh\necho 'error: failed to allocate 7 GB buffer' >&2\nexit 1\n")
    with pytest.raises(LocalModelError, match="allocate"):
        fake_engine.acquire("tiny")


def test_missing_model_asks_to_download(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    with pytest.raises(llm.LLMError, match="Settings"):
        llm.complete_json("s", "u", {}, {**PREFS, "local_model": ""}, None, "")


def test_deleting_the_running_model_stops_the_server(fake_engine):
    fake_engine.acquire("tiny")
    fake_engine.release()
    local_llm.delete_model("tiny")
    assert fake_engine.running_model() is None and not local_llm.model_installed("tiny")


# ── API ──────────────────────────────────────────────────────────────────────

def test_status_and_download_api(client, app_module, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    body = client.get("/api/local-llm").get_json()
    assert [m["id"] for m in body["models"]] == ["qwen3.6-35b-a3b", "qwen3.8-27b", "gemma-4-12b", "qwen3.5-9b", "qwen3.5-4b"]
    assert sum(m["recommended"] for m in body["models"]) == 1 and body["download"]["status"] == "idle"
    assert client.post("/api/local-llm/download", json={"model": "nope"}).status_code == 400
    started = []
    monkeypatch.setattr(app_module.local_llm.installer, "start", lambda m: started.append(m))
    assert client.post("/api/local-llm/download", json={"model": "qwen3.5-4b"}).status_code == 200
    assert started == ["qwen3.5-4b"]
    assert client.delete("/api/local-llm/models/nope").status_code == 404


def test_settings_accept_the_local_provider(client, monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    r = client.post("/settings", json={"llm_provider": "local", "local_model": "qwen3.5-4b"}).get_json()
    assert r["llm_provider"] == "local" and r["local_model"] == "qwen3.5-4b"
    assert client.post("/settings", json={"local_model": "gpt-17"}).status_code == 400


def test_a_server_left_by_a_crash_is_stopped_on_next_launch(fake_engine):
    fake_engine.acquire("tiny")
    fake_engine.release()
    proc = fake_engine._proc
    fake_engine._proc = None                     # simulate the app dying without cleanup
    port = int(fake_engine._url.rsplit(":", 1)[1])
    assert local_llm._is_our_server(proc.pid, port) and not local_llm._is_our_server(proc.pid, port + 1)
    assert local_llm.cleanup_stale() is True
    proc.wait(timeout=10)
    assert local_llm.cleanup_stale() is False    # nothing left, and the pid file is gone


def test_cleanup_never_kills_an_unrelated_process(tmp_path, monkeypatch):
    """Even one whose command line mentions llama-server and the port (e.g. a shell or an editor)."""
    import subprocess
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    if sys.platform == "win32":
        pytest.skip("POSIX command-line check")
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "llama-server", "--port", "4321"])
    try:
        with open(local_llm._pid_file(), "w") as f:
            f.write(f"{bystander.pid} 4321")
        assert local_llm.cleanup_stale() is False
        assert bystander.poll() is None
    finally:
        bystander.kill()


# ── GPU-aware choice (Windows: VRAM decides speed; Mac: unified memory) ──────

def gpu(gb, name="GPU"):
    return {"name": name, "memory": int(gb * GB), "backend": "Vulkan0"}


@pytest.mark.parametrize("ram_gb,gpu_,expect", [
    (32, gpu(24, "Apple M2 Pro"), "qwen3.6-35b-a3b"),   # 32 GB Mac: the MoE fits the GPU's share
    (32, gpu(12), "gemma-4-12b"),        # RTX 3060 12 GB: the 35B and 27B would half run on the CPU
    (32, gpu(6), "qwen3.5-4b"),          # 6 GB card: Gemma would half run on the CPU
    (16, {}, "qwen3.5-4b"),              # no usable GPU: the small model, on the CPU
    (8, gpu(24), "qwen3.5-4b"),          # plenty of VRAM but too little RAM
    (16, gpu(12, "Apple M1 Pro"), "gemma-4-12b"),
])
def test_recommendation_uses_gpu_memory(ram_gb, gpu_, expect):
    assert recommended_model_id(ram_gb * GB, gpu_) == expect


def test_speed_classes():
    gemma = local_llm.MODELS_BY_ID["gemma-4-12b"]
    assert [local_llm.speed(gemma, g) for g in (gpu(12), gpu(5), gpu(2), {}, None)] == \
        ["fast", "partial", "slow", "slow", None]


def test_parse_engine_devices():
    out = """load_backend: loaded Vulkan backend
Available devices:
  Vulkan0: NVIDIA GeForce RTX 3060 (12288 MiB, 11200 MiB free)
  Vulkan1: Intel(R) UHD Graphics (0 MiB, 0 MiB free)
  BLAS: Accelerate (0 MiB, 0 MiB free)
"""
    assert local_llm._parse_devices(out) == [
        {"name": "NVIDIA GeForce RTX 3060", "memory": 12288 * 1024 ** 2, "backend": "Vulkan0"}]
    assert local_llm._parse_devices("Available devices:\n") == []


class FakeWinreg:
    HKEY_LOCAL_MACHINE = "HKLM"

    def __init__(self, adapters):
        self.adapters = adapters            # {"0000": {value: data}}

    def OpenKey(self, root, path):
        sub = path.rsplit("\\", 1)[1]
        if sub not in self.adapters:
            raise OSError("no key")
        return sub

    def QueryValueEx(self, key, value):
        if value not in self.adapters[key]:
            raise OSError("no value")
        return self.adapters[key][value], 0

    def CloseKey(self, key):
        pass


def test_windows_registry_reports_the_biggest_card():
    reg = FakeWinreg({
        "0000": {"DriverDesc": "Intel(R) UHD Graphics 770", "HardwareInformation.MemorySize": 128 * 1024 ** 2},
        "0001": {"DriverDesc": "NVIDIA GeForce RTX 4070", "HardwareInformation.qwMemorySize": (12 * GB).to_bytes(8, "little")},
    })
    g = local_llm._registry_gpu(reg)
    assert g["name"] == "NVIDIA GeForce RTX 4070" and g["memory"] == 12 * GB


def test_integrated_graphics_counts_as_no_gpu(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(local_llm, "_gpu_cache", {})
    monkeypatch.setattr(local_llm.sys, "platform", "win32")
    monkeypatch.setattr(local_llm, "_registry_gpu", lambda: {"name": "Intel UHD", "memory": 128 * 1024 ** 2})
    assert local_llm.gpu_info() == {}
    st = local_llm.status()
    assert st["recommended"] == "qwen3.5-4b" and {m["speed"] for m in st["models"]} == {"slow"}
