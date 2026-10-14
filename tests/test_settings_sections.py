"""5.0 C9 Settings as sections: usage counters and stats, the settings keys, hot-key conflicts, storage and the
data-folder move with its pointer file."""
import contextlib
import json
import os
import sys
import time
import types

import pytest

from core import index, llm, local_llm, longform, notes, paths, settings, summarize, usage
from core.store import Store


# ── usage counters ───────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    s = Store(root=str(tmp_path / "lib"))
    monkeypatch.setattr(usage, "_sink", lambda kind, tin, tout, secs, pid: s.add_usage(kind, tin, tout, secs, pid or "p1"))
    return s


def _rows(store):
    with store._conn() as c:
        return [dict(r) for r in c.execute("SELECT kind, tokens_in, tokens_out, seconds, project_id FROM usage ORDER BY id")]


class _Resp:
    def __init__(self, body=None, lines=None):
        self._body, self._lines = body, lines or []

    def read(self):
        return json.dumps(self._body).encode()

    def __iter__(self):
        return iter(self._lines)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def local_server(monkeypatch):
    monkeypatch.setattr(local_llm.runtime, "acquire", lambda model_id: ("http://127.0.0.1:1", "k"))
    monkeypatch.setattr(local_llm.runtime, "release", lambda: None)


def test_stats_counters(store, local_server, monkeypatch):
    # Built-in model, structured: prompt and completion tokens from llama-server's `usage`.
    reply = {"choices": [{"message": {"content": '{"ok": true}'}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 120, "completion_tokens": 8}}
    assert llm._local_json("s", "u", {}, "qwen3.5-4b", opener=lambda req, timeout: _Resp(reply)) == {"ok": True}
    # Built-in model, streamed: the counts come with the last event (asked for with stream_options).
    sent = {}

    def stream_opener(req, timeout):
        sent["body"] = json.loads(req.data)
        events = [{"choices": [{"delta": {"content": "Итог"}}]},
                  {"choices": [{"delta": {}}], "usage": {"prompt_tokens": 300, "completion_tokens": 40}}]
        return _Resp(lines=[f"data: {json.dumps(e)}\n".encode() for e in events] + [b"data: [DONE]\n"])
    assert summarize.summarize_with_local("text", "qwen3.5-4b", lambda _p: None, opener=stream_opener) == "Итог"
    assert sent["body"]["stream_options"] == {"include_usage": True}
    # Older servers give `timings` instead.
    events = [{"choices": [{"delta": {"content": "x"}}], "timings": {"prompt_n": 7, "predicted_n": 3}}]
    summarize.summarize_with_local("t", "qwen3.5-4b", lambda _p: None,
                                   opener=lambda r, timeout: _Resp(lines=[f"data: {json.dumps(e)}".encode() for e in events]))
    # Claude: input (with the cached prompt) and output tokens, kind llm_cloud.
    msg = types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text='{"a": 1}')],
                                usage=types.SimpleNamespace(input_tokens=50, cache_creation_input_tokens=0,
                                                            cache_read_input_tokens=1000, output_tokens=20))

    class Stream:
        text_stream = iter(["x"])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return msg
    client = types.SimpleNamespace(beta=types.SimpleNamespace(messages=types.SimpleNamespace(stream=lambda **p: Stream())))
    assert llm._claude_json("s", "u", {}, "claude-sonnet-5", "sk", client=client) == {"a": 1}
    summarize.summarize_with_claude("t", "claude-sonnet-5", "sk", lambda _p: None, client=client)
    # Ollama: its own counters; a stream that never says done still counts the call, with no tokens.
    llm._ollama_json("s", "u", {}, "qwen3:8b", "http://o",
                     opener=lambda req, timeout: _Resp({"message": {"content": "{}"}, "prompt_eval_count": 11, "eval_count": 2}))
    summarize.summarize_with_ollama("t", "qwen3:8b", lambda _p: None, "http://o",
                                    opener=lambda req, timeout: _Resp(lines=[json.dumps({"message": {"content": "a"}}).encode()]))
    # Embeddings: one row per batch, texts in tokens_in.
    monkeypatch.setattr(index, "model_id", lambda: "qwen3-embedding-0.6b")
    monkeypatch.setattr(local_llm.embed_runtime, "acquire", lambda mid: ("http://e", "k"))
    monkeypatch.setattr(local_llm.embed_runtime, "release", lambda: None)
    monkeypatch.setattr(index, "EMBED_BATCH", 2)
    vec = lambda req, timeout: _Resp({"data": [{"index": i, "embedding": [1.0, 0.0]}  # noqa: E731
                                               for i in range(len(json.loads(req.data)["input"]))]})
    assert len(index.embed(["a", "b", "c"], opener=vec)) == 3
    # Transcription: seconds of audio through the one place every pass goes (files, channels, live, whispers).
    torch = sys.modules["torch"]
    monkeypatch.setattr(torch, "inference_mode", contextlib.nullcontext, raising=False)

    class Batch:
        def to(self, *_a):
            return self
    monkeypatch.setattr(sys.modules["gigaam.utils"], "AudioDataset",
                        types.SimpleNamespace(collate=lambda chunks: (Batch(), Batch())))
    model = types.SimpleNamespace(_device="cpu", _dtype=None, forward=lambda w, l: (None, None),
                                  _decode=lambda e, el, wl, ts: [("слово", None), ("ещё", None)])
    longform.transcribe_chunks(model, [[0] * 16000, [0] * 8000], batch_size=2)

    assert _rows(store) == [
        {"kind": "llm_local", "tokens_in": 120, "tokens_out": 8, "seconds": None, "project_id": "p1"},
        {"kind": "llm_local", "tokens_in": 300, "tokens_out": 40, "seconds": None, "project_id": "p1"},
        {"kind": "llm_local", "tokens_in": 7, "tokens_out": 3, "seconds": None, "project_id": "p1"},
        {"kind": "llm_cloud", "tokens_in": 1050, "tokens_out": 20, "seconds": None, "project_id": "p1"},
        {"kind": "llm_cloud", "tokens_in": 1050, "tokens_out": 20, "seconds": None, "project_id": "p1"},
        {"kind": "llm_local", "tokens_in": 11, "tokens_out": 2, "seconds": None, "project_id": "p1"},
        {"kind": "llm_local", "tokens_in": None, "tokens_out": None, "seconds": None, "project_id": "p1"},
        {"kind": "embed", "tokens_in": 2, "tokens_out": None, "seconds": None, "project_id": "p1"},
        {"kind": "embed", "tokens_in": 1, "tokens_out": None, "seconds": None, "project_id": "p1"},
        {"kind": "asr", "tokens_in": None, "tokens_out": None, "seconds": 1.5, "project_id": "p1"},
    ]


def test_a_failing_sink_never_breaks_the_call(local_server, monkeypatch):
    monkeypatch.setattr(usage, "_sink", lambda *a: 1 / 0)
    reply = {"choices": [{"message": {"content": "{}"}}]}
    assert llm._local_json("s", "u", {}, "m", opener=lambda req, timeout: _Resp(reply)) == {}


def test_usage_aggregation_by_period(tmp_path):
    now = [1_000_000_000.0]
    s = Store(root=str(tmp_path / "lib"), clock=lambda: now[0])
    p = s.ensure_default_project()
    day = 86400
    s.add_usage("llm_local", 100, 20, at=now[0] - 2 * day)
    s.add_usage("llm_local", 1000, None, at=now[0] - 20 * day)
    s.add_usage("llm_cloud", 30, 5, at=now[0] - day)
    s.add_usage("llm_cloud", None, None, at=now[0] - 40 * day)
    s.add_usage("asr", seconds=61.25, at=now[0] - day)
    s.add_usage("embed", 16, at=now[0] - day)
    s.create_source(p["id"], "audio", "Звонок")
    s.create_source(p["id"], "material", "Регламент")
    with pytest.raises(ValueError):
        s.add_usage("gpu_minutes", 1)
    week = s.usage_stats(now[0] - 7 * day)
    assert week == {"tokens_local": 120, "tokens_cloud": 35, "cloud_calls": 1, "meetings": 1,
                    "seconds_transcribed": 61.2, "embeddings": 16}
    month = s.usage_stats(now[0] - 30 * day)
    assert month["tokens_local"] == 1120 and month["cloud_calls"] == 1
    every = s.usage_stats(None)
    assert every["cloud_calls"] == 2 and every["tokens_cloud"] == 35


def test_stats_route(client, app_module):
    lib = app_module.library
    lib.add_usage("llm_local", 10, 5)
    lib.add_usage("llm_local", 1, 1, at=time.time() - 10 * 86400)
    week = client.get("/api/stats?period=7d").get_json()
    every = client.get("/api/stats?period=all").get_json()
    assert set(week) >= {"tokens_local", "tokens_cloud", "cloud_calls", "meetings", "seconds_transcribed", "embeddings"}
    assert every["tokens_local"] - week["tokens_local"] >= 2
    assert client.get("/api/stats").get_json()["period"] == "7d"
    assert client.get("/api/stats?period=year").status_code == 400


def test_app_sink_writes_against_the_current_project(app_module):
    lib = app_module.library
    usage.record("asr", seconds=3)
    with lib._conn() as c:
        row = dict(c.execute("SELECT * FROM usage ORDER BY id DESC LIMIT 1").fetchone())
    assert row["kind"] == "asr" and row["seconds"] == 3 and row["project_id"] == lib.current_project()["id"]


# ── settings keys ────────────────────────────────────────────────────────────

def test_every_section_key_round_trips(client):
    body = {"silence_stop_minutes": 0, "live_transcription": False, "live_requirements": False, "live_questions": True,
            "recap_style": "actions", "embed_model": "qwen3-embedding-0.6b", "menubar": False, "notes_style": "concise",
            "tuning": {"retrieve_k": 8}, "hotkeys": {"whisper": "alt+d"}}
    res = client.post("/settings", json=body)
    assert res.status_code == 200, res.get_json()
    got = client.get("/settings").get_json()
    for k, v in body.items():
        if k == "tuning":
            assert got[k]["retrieve_k"] == 8 and got[k]["label_assign"] == 0.45
        elif k == "hotkeys":
            assert got[k]["whisper"] == "alt+d"
        else:
            assert got[k] == v, k
    assert client.post("/settings", json={"recap_style": "poem"}).status_code == 400
    assert client.post("/settings", json={"notes_style": "verbose"}).status_code == 400
    client.post("/settings", json={"silence_stop_minutes": 10, "live_transcription": True, "live_requirements": True,
                                   "live_questions": False, "recap_style": "brief", "embed_model": "", "menubar": True,
                                   "notes_style": "standard", "tuning": {"retrieve_k": 12},
                                   "hotkeys": {"whisper": "alt+space"}})


def test_settings_hotkeys_conflict(data_dir_settings):
    out = settings.save_settings({"hotkeys": {"whisper": "Shift+Option+D"}})
    assert out["hotkeys"]["whisper"] == "alt+shift+d"                      # one spelling and order
    with pytest.raises(ValueError, match="already used by record"):
        settings.save_settings({"hotkeys": {"whisper": "cmd+r"}})
    with pytest.raises(ValueError, match="used by the system"):
        settings.save_settings({"hotkeys": {"ask": "cmd+space"}})
    for bad in ("d", "cmd+", "cmd+shift", "hyper+d", "cmd+cmd+d"):
        with pytest.raises(ValueError):
            settings.save_settings({"hotkeys": {"ask": bad}})
    # A swap in one request is fine; the map stays free of duplicates.
    out = settings.save_settings({"hotkeys": {"ask": "cmd+k", "palette": "cmd+j"}})
    assert out["hotkeys"]["ask"] == "cmd+k" and out["hotkeys"]["palette"] == "cmd+j"
    assert settings.save_settings({"hotkeys": {"ask": "f5"}})["hotkeys"]["ask"] == "f5"   # an F-key may go bare
    assert settings.load_settings()["hotkeys"]["whisper"] == "alt+shift+d"


@pytest.fixture
def data_dir_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    return tmp_path


def test_concise_notes_style_reaches_the_recap_prompt():
    from core import skills
    plain = notes.system_prompt(skills.resolve(), "brief", False)
    concise = notes.system_prompt(skills.resolve(), "brief", False, concise=True)
    assert notes.CONCISE_RULE not in plain and notes.CONCISE_RULE in concise


# ── storage and the data-folder move ─────────────────────────────────────────

def test_storage_counts_and_size(client, app_module):
    lib = app_module.library
    before = client.get("/api/storage").get_json()
    p = lib.current_project()
    lib.create_source(p["id"], "recording", "Встреча")
    lib.create_source(p["id"], "material", "Файл")
    lib.add_whispers([{"kind": "task", "text": "позвонить", "title": "Позвонить"}], "позвонить")
    after = client.get("/api/storage").get_json()
    assert after["path"] == paths.app_data_dir() and after["bytes"] > 0
    for k in ("meetings", "materials", "whispers"):
        assert after["counts"][k] == before["counts"][k] + 1, k
    assert after["counts"]["projects"] >= 1
    assert after["movable"] is False                 # tests run with WORKBENCH_DATA_DIR: never moved


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A monkeypatched user data root: the default folder is <tmp>/support/Dictum."""
    monkeypatch.delenv("WORKBENCH_DATA_DIR", raising=False)
    monkeypatch.delenv("DICTUM_DATA_DIR", raising=False)
    root = tmp_path / "support"
    root.mkdir()
    monkeypatch.setattr(paths, "_user_data_root", lambda: str(root))
    monkeypatch.setattr(paths, "_migration_checked", False)
    monkeypatch.setattr(paths, "_resolved", None)
    data = paths.app_data_dir()
    os.makedirs(os.path.join(data, "recordings", "s1"))
    with open(os.path.join(data, "recordings", "s1", "mic.wav"), "wb") as f:
        f.write(b"RIFF" + b"\0" * 400)
    with open(os.path.join(data, "settings.json"), "w") as f:
        f.write("{}")
    return tmp_path


def test_move_refusals(home):
    data = paths.app_data_dir()
    with pytest.raises(paths.DataDirError) as e:
        paths.move_data_dir(os.path.join(data, "inner"))
    assert e.value.code == "inside"
    with pytest.raises(paths.DataDirError) as e:
        paths.move_data_dir(data)
    assert e.value.code == "same"
    full = home / "full"
    full.mkdir()
    (full / "x.txt").write_text("x")
    with pytest.raises(paths.DataDirError) as e:
        paths.move_data_dir(str(full))
    assert e.value.code == "not_empty"
    locked = home / "locked"
    locked.mkdir()
    os.chmod(locked, 0o500)
    try:
        for target in (locked, locked / "new"):
            with pytest.raises(paths.DataDirError) as e:
                paths.move_data_dir(str(target))
            assert e.value.code == "not_writable"
    finally:
        os.chmod(locked, 0o700)
    with pytest.raises(paths.DataDirError) as e:
        paths.move_data_dir(str(home / "no" / "such" / "parent"))
    assert e.value.code == "not_writable"
    # Nothing moved, no pointer written.
    assert os.path.exists(os.path.join(data, "recordings", "s1", "mic.wav"))
    assert not os.path.exists(paths.pointer_path())


def test_move_with_the_pointer_and_the_next_start_follows_it(home, monkeypatch):
    old = paths.app_data_dir()
    target = home / "Drive" / "DictumData"
    (home / "Drive").mkdir()
    assert paths.move_data_dir(str(target)) == str(target)
    assert (target / "recordings" / "s1" / "mic.wav").read_bytes() == b"RIFF" + b"\0" * 400   # audio kept
    assert (target / "settings.json").exists()
    assert sorted(os.listdir(old)) == [paths.POINTER_FILE]                  # the default folder holds only the pointer
    pointer = json.loads(open(paths.pointer_path(), encoding="utf-8").read())
    assert pointer["path"] == str(target) and pointer["moved_from"] == old
    assert paths.app_data_dir() == str(target)
    # The next start: a fresh process resolves the folder through the pointer.
    monkeypatch.setattr(paths, "_migration_checked", False)
    monkeypatch.setattr(paths, "_resolved", None)
    assert paths.app_data_dir() == str(target)
    # Across volumes: copy, verify, then remove the original.
    monkeypatch.setattr(paths.os, "rename", _exdev_once(paths.os.rename))
    second = home / "Other"
    second.mkdir()                                                            # empty: accepted
    assert paths.move_data_dir(str(second)) == str(second)
    assert (second / "recordings" / "s1" / "mic.wav").exists() and not target.exists()
    # Back to the default folder, which holds only the pointer: the pointer goes away.
    monkeypatch.setattr(paths.os, "rename", _REAL_RENAME)
    assert paths.move_data_dir(old) == old
    assert not os.path.exists(paths.pointer_path()) and os.path.exists(os.path.join(old, "recordings", "s1", "mic.wav"))
    monkeypatch.setattr(paths, "_migration_checked", False)
    assert paths.app_data_dir() == old


_REAL_RENAME = os.rename


def _exdev_once(real):
    import errno
    state = {"n": 0}

    def rename(a, b):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError(errno.EXDEV, "cross-device link")
        return real(a, b)
    return rename


def test_pointer_to_a_missing_folder_falls_back_to_the_default(home, monkeypatch):
    default = paths.app_data_dir()
    with open(paths.pointer_path(), "w", encoding="utf-8") as f:
        json.dump({"path": str(home / "unplugged")}, f)
    monkeypatch.setattr(paths, "_migration_checked", False)
    assert paths.app_data_dir() == default


def test_move_route_refusals_and_job(client, app_module, monkeypatch, tmp_path):
    # With DICTUM_DATA_DIR / WORKBENCH_DATA_DIR set (tests, portable installs) the folder never moves.
    res = client.post("/api/data-dir/move", json={"path": str(tmp_path / "x")})
    assert res.status_code == 400 and res.get_json()["code"] == "override"
    monkeypatch.setattr(paths, "_override", lambda: None)
    current = paths.app_data_dir()
    monkeypatch.setattr(paths, "app_data_dir", lambda: current)
    rec = types.SimpleNamespace(recording=True)
    monkeypatch.setattr(app_module, "_recorder", rec)
    res = client.post("/api/data-dir/move", json={"path": str(tmp_path / "x")})
    assert res.status_code == 409 and res.get_json()["code"] == "recording"
    rec.recording = False
    res = client.post("/api/data-dir/move", json={"path": os.path.join(current, "sub")})
    assert res.status_code == 400 and res.get_json()["code"] == "inside"
    moved = {}
    monkeypatch.setattr(paths, "move_data_dir", lambda target, current=None: moved.setdefault("to", target))
    res = client.post("/api/data-dir/move", json={"path": str(tmp_path / "x")})
    assert res.status_code == 200
    job_id = res.get_json()["job_id"]
    for _ in range(50):
        job = client.get(f"/job/{job_id}").get_json()
        if job["status"] != "processing":
            break
        time.sleep(0.05)
    assert job["status"] == "done" and job["result"] == {"path": str(tmp_path / "x"), "restart": True}
    assert moved["to"] == str(tmp_path / "x")
    assert client.get("/api/storage").get_json()["moved_to"] == str(tmp_path / "x")
    app_module._data_move["moved_to"] = None


def test_desktop_folder_picker():
    from core.desktop_api import DesktopApi
    assert DesktopApi("http://x", lambda n: None, ask_folder=lambda: "/Volumes/Data/Dictum").choose_folder() == {
        "path": "/Volumes/Data/Dictum"}
    assert DesktopApi("http://x", lambda n: None, ask_folder=lambda: None).choose_folder() == {"cancelled": True}
    assert "error" in DesktopApi("http://x", lambda n: None).choose_folder()
