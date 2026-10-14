"""First-run permissions (5.0 C8): read without prompting, request, open the settings pane. Platform calls are fakes."""
import types

import pytest

from core import macos_audio, permissions
from core.setup_plan import StateFile


class FakeAV:
    AVMediaTypeAudio = "soun"

    def __init__(self, status):
        self.AVCaptureDevice = types.SimpleNamespace(authorizationStatusForMediaType_=lambda media: status)


@pytest.fixture()
def state(tmp_path):
    return StateFile(str(tmp_path / "setup-state.json"))


@pytest.fixture()
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.mark.parametrize("status, expected", [(0, "undetermined"), (1, "denied"), (2, "denied"), (3, "granted")])
def test_macos_microphone_status_maps_avfoundation(state, status, expected):
    out = permissions.read(state, platform="darwin", av=FakeAV(status), support=lambda: (True, None))
    assert out["microphone"] == expected


def test_macos_system_audio_and_notifications_until_tried(state):
    supported = lambda: (True, None)  # noqa: E731
    out = permissions.read(state, platform="darwin", av=FakeAV(3), support=supported)
    assert out == {"microphone": "granted", "system_audio": "undetermined", "notifications": "undetermined"}
    assert permissions.read(state, platform="darwin", av=FakeAV(3), support=lambda: (False, "old"))["system_audio"] == "unsupported"


def test_windows_microphone_from_devices_rest_unsupported(state):
    out = permissions.read(state, platform="win32", inputs=lambda: 2)
    assert out == {"microphone": "granted", "system_audio": "unsupported", "notifications": "unsupported"}
    assert permissions.read(state, platform="win32", inputs=lambda: 0)["microphone"] == "undetermined"


def test_request_runs_the_right_call_and_remembers(state):
    calls = []
    kw = dict(mic_access=lambda: calls.append("mic"), tap_dry_run=lambda: calls.append("tap"),
              send_notification=lambda: calls.append("notify") or True, platform="darwin", support=lambda: (True, None))
    for which in permissions.WHICH:
        permissions.request(which, state, **kw)
    assert calls == ["mic", "tap", "notify"]
    out = permissions.read(state, platform="darwin", av=FakeAV(3), support=lambda: (True, None))
    assert out == {"microphone": "granted", "system_audio": "granted", "notifications": "granted"}


def test_failed_tap_reads_as_denied(state):
    def fail():
        raise OSError("tap refused")
    permissions.request("system_audio", state, mic_access=None, tap_dry_run=fail, send_notification=None,
                        platform="darwin", support=lambda: (True, None))
    assert permissions.read(state, platform="darwin", av=FakeAV(3), support=lambda: (True, None))["system_audio"] == "denied"
    with pytest.raises(ValueError):
        permissions.request("camera", state, None, None, None)


def test_dry_run_reads_about_a_second_then_closes_and_keeps_nothing():
    events = []
    now = [0.0]

    class Tap:
        def open(self):
            events.append("open")
            return self

        def __call__(self, stop):
            try:
                while not stop.is_set():
                    now[0] += 0.25
                    yield b"\0" * 32
            finally:
                events.append("stream closed")

        def close(self):
            events.append("close")

    macos_audio.dry_run(1.0, tap_factory=Tap, clock=lambda: now[0])
    assert events == ["open", "stream closed", "close"] and now[0] == pytest.approx(1.0)


def test_permissions_routes(client, app_module, monkeypatch, data_dir):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(permissions, "microphone_status", lambda *a, **k: "undetermined")
    monkeypatch.setattr(permissions, "_support", lambda: (True, None))
    asked = []
    monkeypatch.setattr(app_module, "microphone_access", lambda: asked.append("mic") or (True, None))
    monkeypatch.setattr(app_module.macos_audio, "dry_run", lambda seconds: asked.append(("tap", seconds)))
    monkeypatch.setattr(app_module, "notify", lambda title, text: asked.append((title, text)) or True)

    assert client.get("/api/permissions").get_json() == {"microphone": "undetermined", "system_audio": "undetermined",
                                                       "notifications": "undetermined"}
    client.post("/api/permissions/request/microphone")
    r = client.post("/api/permissions/request/system_audio").get_json()
    assert r["system_audio"] == "granted"
    r = client.post("/api/permissions/request/notifications?lang=ru").get_json()
    assert r["notifications"] == "granted"
    assert asked == ["mic", ("tap", 1.0), ("Dictum", "Dictum готов")]
    assert client.post("/api/permissions/request/camera").status_code == 404


def test_open_settings_opens_the_right_pane(client, app_module, monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(permissions.sys, "platform", "darwin")
    opened = []
    monkeypatch.setattr(app_module.subprocess, "Popen", lambda args: opened.append(args))
    for which in ("microphone", "system_audio", "notifications"):
        assert client.post(f"/api/permissions/open-settings/{which}").status_code == 200
    assert opened == [["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"],
                      ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AudioCapture"],
                      ["open", "x-apple.systempreferences:com.apple.preference.notifications"]]
    assert client.post("/api/permissions/open-settings/camera").status_code == 404


def test_a_working_notification_counts_as_granted(app_module, monkeypatch, data_dir):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0))
    assert app_module.notify("Dictum", "test") is True
    assert StateFile().get("perm:notifications") == "granted"
