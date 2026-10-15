"""End-to-end: setup screen → install → hand over to the main app on the same port."""
import json
import types
import urllib.error
import urllib.request

from flask import Flask

import launcher
from core import instance
from core.hardware import Hardware
from core.setup_plan import Step
from core.setup_runner import SetupRunner
from tests.test_recorder import wait_for


def fake_app_module():
    app = Flask("fake-main")

    @app.route("/health")
    def health():
        return {"main": True}

    return types.SimpleNamespace(app=app, IS_DESKTOP=None, GPU_NAME=None, MPS_AVAILABLE=False,
                                 FFMPEG_AVAILABLE=True, hf_token=None)


def get(slot, path, method="GET"):
    url = f"http://127.0.0.1:{slot._server.server_port}{path}"
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_healthy_machine_starts_app_directly():
    slot = launcher.ServerSlot(port=0)
    module = fake_app_module()
    runner = launcher.start(slot, browser_mode=False, app_module=module,
                            detect_hw=lambda: Hardware("darwin", "arm64"),
                            plan_factory=lambda hw: [Step("a", "A", "", lambda: True)], log=lambda m: None,
                            defer_import=False)
    try:
        assert runner is None
        assert module.IS_DESKTOP is True
        assert get(slot, "/health")[0] == 200
    finally:
        slot.stop()


def test_healthy_machine_shows_starting_page_then_the_app():
    """The window opens on a 'starting' page at once; the app (a slow import) takes over the same port."""
    import threading
    release = threading.Event()
    module = fake_app_module()

    class SlowModule:
        """Stands in for `import app`: start() must not block on it."""
        def __getattr__(self, name):
            release.wait(5)
            return getattr(module, name)

        def __setattr__(self, name, value):
            setattr(module, name, value)

    slot = launcher.ServerSlot(port=0)
    runner = launcher.start(slot, browser_mode=True, app_module=SlowModule(),
                            detect_hw=lambda: Hardware("darwin", "arm64"),
                            plan_factory=lambda hw: [Step("a", "A", "", lambda: True)], log=lambda m: None)
    try:
        assert runner is None
        status, body = get(slot, "/")
        assert status == 200 and b"Starting Dictum" in body      # the page the window shows meanwhile
        assert json.loads(get(slot, "/starting/status")[1]) == {"state": "loading", "error": ""}
        assert get(slot, "/health")[0] == 404                   # main app not loaded yet
        assert instance.is_workbench(slot.port)                 # single-instance check works meanwhile
        port = slot.port
        release.set()
        assert wait_for(lambda: _up(port), timeout=5)
        assert slot.port == port                                # same address: the page just reloads
        assert get(slot, "/starting/status")[0] == 404
        assert module.IS_DESKTOP is False
    finally:
        release.set()
        slot.stop()


def test_failed_import_is_reported_on_the_starting_page():
    class BrokenModule:
        def __getattr__(self, name):
            raise ImportError("No module named 'torch'")

    logged = []
    slot = launcher.ServerSlot(port=0)
    launcher.start(slot, browser_mode=True, app_module=BrokenModule(),
                   detect_hw=lambda: Hardware("darwin", "arm64"),
                   plan_factory=lambda hw: [Step("a", "A", "", lambda: True)], log=logged.append)
    try:
        assert wait_for(lambda: json.loads(get(slot, "/starting/status")[1])["state"] == "failed", timeout=5)
        st = json.loads(get(slot, "/starting/status")[1])
        assert st["error"] == "ImportError: No module named 'torch'"
        assert get(slot, "/")[0] == 200                         # the page stays up to show the error
        assert any("Could not start the app" in m and "Traceback" in m for m in logged)
    finally:
        slot.stop()


def test_missing_dependency_shows_setup_then_hands_over_to_app():
    installed = {"x": False}

    def install(log):
        installed["x"] = True

    slot = launcher.ServerSlot(port=0)
    module = fake_app_module()
    runner = launcher.start(slot, browser_mode=True, app_module=module,
                            detect_hw=lambda: Hardware("win32", "x86_64"),
                            plan_factory=lambda hw: [Step("x", "Thing", "", lambda: installed["x"], install)],
                            log=lambda m: None)
    try:
        assert runner is not None
        status, body = get(slot, "/")
        assert status == 200 and b"Setting up" in body          # setup screen, not the app
        assert get(slot, "/health")[0] == 404                   # main app not loaded yet
        assert runner.wait(5) == "done"
        st = json.loads(get(slot, "/setup/status")[1])
        assert st["state"] == "done" and st["steps"][0]["status"] == "done"

        port = slot.port
        assert get(slot, "/setup/continue", "POST")[0] == 200
        assert wait_for(lambda: slot._server is not None and _up(port), timeout=5)
        status, body = get(slot, "/health")
        assert status == 200 and json.loads(body) == {"main": True}
        assert module.IS_DESKTOP is False
    finally:
        slot.stop()


def _up(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def test_continue_is_refused_before_setup_finishes():
    slot = launcher.ServerSlot(port=0)
    runner = launcher.start(slot, browser_mode=True, app_module=fake_app_module(),
                            detect_hw=lambda: Hardware("win32", "x86_64"),
                            plan_factory=lambda hw: [Step("x", "X", "", lambda: False,
                                                          lambda log: (_ for _ in ()).throw(OSError("offline")))],
                            runner_factory=lambda steps: SetupRunner(steps, sleep=lambda s: None),
                            log=lambda m: None)
    try:
        runner.wait(5)
        assert runner.state == "failed"
        assert get(slot, "/setup/continue", "POST")[0] == 409
    finally:
        slot.stop()


def test_join_survives_the_setup_to_app_handoff():
    """Regression: browser mode exited when setup handed over to the app, because
    join() returned in the moment between stopping one server and starting the next."""
    import threading
    import time
    slot = launcher.ServerSlot(port=0)
    slot.serve(Flask("setup"))
    returned = threading.Event()
    threading.Thread(target=lambda: (slot.join(), returned.set()), daemon=True).start()
    slot.stop()                      # handoff: old server gone…
    time.sleep(0.7)                  # …longer than join's poll interval
    assert not returned.is_set(), "join() must not return during a handoff"
    slot.serve(Flask("main"))        # …new server up
    slot.close()
    assert returned.wait(2)
