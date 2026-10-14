"""Global hot keys and the menu-bar item (5.0 C7, increment 12). Carbon and AppKit are replaced by fakes."""
import json
import sys

import pytest

from core import hotkeys, settings


class FakeCarbon:
    def __init__(self, taken=()):
        self.taken = set(taken)
        self.installed = None
        self.registered = {}            # ref → (code, mask, id)
        self.unregistered = []
        self._next = 0

    def install(self, on_press):
        self.installed = on_press

    def register(self, code, mask, hotkey_id):
        if (code, mask) in self.taken:
            raise hotkeys.HotKeyTaken("taken")
        self._next += 1
        self.registered[self._next] = (code, mask, hotkey_id)
        return self._next

    def unregister(self, ref):
        self.unregistered.append(ref)
        self.registered.pop(ref, None)


class FakeMenuBar:
    def __init__(self):
        self.shown = None
        self.removed = 0

    def show(self, titles, busy):
        self.shown = (titles, busy)

    def remove(self):
        self.shown = None
        self.removed += 1


class FakeWindow:
    def __init__(self):
        self.calls = []

    def restore(self):
        self.calls.append("restore")

    def show(self):
        self.calls.append("show")

    def evaluate_js(self, js):
        self.calls.append(js)

    def destroy(self):
        self.calls.append("destroy")


def run_now(fn, *args):
    fn(*args)


@pytest.fixture(autouse=True)
def own_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "settings_file", lambda: str(tmp_path / "settings.json"))


@pytest.fixture()
def ctl(monkeypatch):
    monkeypatch.setattr(hotkeys, "_controller", None)
    monkeypatch.setattr(hotkeys, "_activate", lambda: None)
    monkeypatch.setattr(hotkeys, "_system_lang", lambda: "ru")
    monkeypatch.setattr(hotkeys, "_ui_lang", {"lang": None})
    monkeypatch.setattr(hotkeys, "_hook_installed", False)
    monkeypatch.setattr(settings, "_save_hooks", [])
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(hotkeys, "available", lambda: True)
    carbon, bar, window = FakeCarbon(), FakeMenuBar(), FakeWindow()
    c = hotkeys.start(window, run_now, backend=carbon, menubar=bar, spawn=lambda fn: fn())
    c.carbon, c.bar, c.win = carbon, bar, window
    yield c
    monkeypatch.setattr(hotkeys, "_controller", None)


# ── parsing ──

@pytest.mark.parametrize("combo, code, mask", [
    ("alt+space", 0x31, hotkeys.OPTION),
    ("cmd+shift+d", 0x02, hotkeys.CMD | hotkeys.SHIFT),
    ("ctrl+alt+shift+cmd+a", 0x00, hotkeys.CMD | hotkeys.SHIFT | hotkeys.OPTION | hotkeys.CONTROL),
    ("Option+Command+R", 0x0F, hotkeys.CMD | hotkeys.OPTION),
    ("control+1", 0x12, hotkeys.CONTROL),
    ("cmd+0", 0x1D, hotkeys.CMD),
    ("alt+9", 0x19, hotkeys.OPTION),
    ("f5", 0x60, 0),
    ("shift+f12", 0x6F, hotkeys.SHIFT),
    ("f19", 0x50, 0),
    (" alt + space ", 0x31, hotkeys.OPTION),
])
def test_parse(combo, code, mask):
    assert hotkeys.parse(combo) == (code, mask)


@pytest.mark.parametrize("combo", ["", "   ", None, 5, "space", "a", "alt+", "+a", "alt++a", "hyper+a",
                                   "alt+alt+a", "cmd+f99", "alt+ä", "cmd+shift"])
def test_parse_rejects(combo):
    with pytest.raises(ValueError):
        hotkeys.parse(combo)


def test_labels():
    assert hotkeys.label("alt+space") == "⌥Space"
    assert hotkeys.label("cmd+r") == "⌘R"
    assert hotkeys.label("ctrl+alt+shift+cmd+f5") == "⌃⌥⇧⌘F5"
    assert hotkeys.label("nonsense") == ""


def test_plain_cmd_key_stays_in_the_window():
    assert hotkeys.window_only("cmd+r")
    assert not hotkeys.window_only("cmd+shift+r")
    assert not hotkeys.window_only("alt+space")
    assert not hotkeys.window_only("cmd+f5")


# ── registration ──

def test_install_registers_whisper_and_record_from_settings(ctl):
    regs = sorted(ctl.carbon.registered.values(), key=lambda r: r[2])
    assert regs == [(0x31, hotkeys.OPTION, 1)]           # ⌥Space; ⌘R stays a window-level key
    assert ctl.hotkeys.status == {"whisper": "ok", "record": "window"}
    assert ctl.carbon.installed is not None


def test_settings_save_re_registers(ctl):
    first_ref = next(iter(ctl.carbon.registered))
    settings.save_settings({"hotkeys": {"whisper": "cmd+shift+d", "record": "ctrl+alt+r"}})
    assert first_ref in ctl.carbon.unregistered
    assert sorted(ctl.carbon.registered.values(), key=lambda r: r[2]) == [
        (0x02, hotkeys.CMD | hotkeys.SHIFT, 1), (0x0F, hotkeys.CONTROL | hotkeys.OPTION, 2)]
    assert ctl.hotkeys.status == {"whisper": "ok", "record": "ok"}
    assert "⇧⌘D" in ctl.bar.shown[0]["whisper"]


def test_unrelated_settings_save_keeps_registrations(ctl):
    before = dict(ctl.carbon.registered)
    settings.save_settings({"silence_stop_minutes": 15})
    assert ctl.carbon.registered == before and ctl.carbon.unregistered == []


def test_taken_and_invalid(ctl):
    ctl.carbon.taken.add((0x31, hotkeys.OPTION))
    ctl.apply_settings({"hotkeys": {"whisper": "alt+space", "record": "bogus+x"}}, force=True)
    assert ctl.hotkeys.status == {"whisper": "taken", "record": "invalid"}


def test_hotkey_press_brings_window_forward_and_tells_the_page(ctl):
    ctl.carbon.installed(1)
    assert ctl.win.calls[:2] == ["restore", "show"]
    assert "dictum:hotkey" in ctl.win.calls[2] and '"whisper"' in ctl.win.calls[2]
    ctl.carbon.installed(99)                             # not ours: ignored
    assert len(ctl.win.calls) == 3


# ── menu ──

def test_menu_titles_follow_language_and_state(ctl, tmp_path, monkeypatch):
    menu = tmp_path / "menu.json"
    menu.write_text(json.dumps({"ru": {"menu.whisper": "Шепнуть", "menu.record": "Записать встречу",
                                       "menu.stop_record": "Остановить запись", "menu.stop_whisper": "Остановить",
                                       "menu.show": "Показать Dictum", "menu.quit": "Выйти"},
                                "en": {"menu.whisper": "Whisper"}}), encoding="utf-8")
    monkeypatch.setattr(hotkeys, "MENU_JSON", str(menu))
    monkeypatch.setattr(hotkeys, "_menu_cache", {})
    hotkeys.set_ui_lang("ru")
    titles = ctl.bar.shown[0]
    assert titles == {"whisper": "Шепнуть ⌥Space", "record": "Записать встречу ⌘R", "show": "Показать Dictum",
                      "quit": "Выйти"}
    ctl.set_busy({"recording": True, "whisper": False})
    assert ctl.bar.shown[0]["record"] == "Остановить запись" and ctl.bar.shown[1]["recording"]
    hotkeys.set_ui_lang("en")
    assert ctl.bar.shown[0]["whisper"] == "Whisper ⌥Space"
    with pytest.raises(ValueError):
        hotkeys.set_ui_lang("de")


def test_menu_actions(ctl):
    ctl.on_menu("record")
    assert '"record"' in ctl.win.calls[-1]
    ctl.busy = {"recording": True, "whisper": False}
    ctl.on_menu("record")
    assert '"record_stop"' in ctl.win.calls[-1]
    n = len(ctl.win.calls)
    ctl.on_menu("show")
    assert ctl.win.calls[n:] == ["restore", "show"]
    ctl.on_menu("quit")
    assert ctl.win.calls[-1] == "destroy"


def test_menubar_setting_removes_and_restores_the_item(ctl):
    assert ctl.bar.shown is not None
    settings.save_settings({"menubar": False})
    assert ctl.bar.shown is None and ctl.bar.removed == 1
    assert settings.load_settings()["menubar"] is False
    settings.save_settings({"menubar": True})
    assert ctl.bar.shown is not None


def test_menu_failure_does_not_break_settings(ctl):
    def boom(*a):
        raise RuntimeError("AppKit said no")
    ctl.bar.show = boom
    settings.save_settings({"hotkeys": {"whisper": "alt+f"}})    # logged, not raised
    assert ctl.hotkeys.status["whisper"] == "ok"


def test_poll_schedules_menu_update(ctl, monkeypatch):
    seen = []
    monkeypatch.setattr(hotkeys, "_state_source", lambda: {"recording": False, "whisper": True})
    ctl.call_main = lambda fn, *a: (seen.append(a), ctl._stop.set())
    ctl.poll(interval=0.001)
    assert seen == [({"recording": False, "whisper": True},)]


# ── routes and the non-macOS no-op ──

def test_status_route(client, ctl):
    body = client.get("/api/hotkeys/status").get_json()
    assert body == {"available": True, "whisper": "ok", "record": "window"}


def test_status_route_without_controller(client, monkeypatch):
    monkeypatch.setattr(hotkeys, "_controller", None)
    assert client.get("/api/hotkeys/status").get_json() == {"available": False, "whisper": "off", "record": "off"}


def test_ui_lang_route(client, monkeypatch):
    monkeypatch.setattr(hotkeys, "_controller", None)
    monkeypatch.setattr(hotkeys, "_ui_lang", {"lang": None})
    assert client.post("/api/ui-lang", json={"lang": "en"}).status_code == 200
    assert hotkeys._ui_lang["lang"] == "en"
    assert client.post("/api/ui-lang", json={"lang": "xx"}).status_code == 400


def test_menu_i18n_route(client, tmp_path, monkeypatch):
    menu = tmp_path / "menu.json"
    menu.write_text(json.dumps({"ru": {"menu.quit": "Выйти"}, "en": {"menu.quit": "Quit"}}), encoding="utf-8")
    monkeypatch.setattr(hotkeys, "MENU_JSON", str(menu))
    monkeypatch.setattr(hotkeys, "_menu_cache", {})
    body = client.get("/api/i18n/menu?lang=ru").get_json()
    assert body["lang"] == "ru" and body["strings"]["menu.quit"] == "Выйти"
    assert client.get("/api/i18n/menu?lang=zz").get_json()["lang"] == "en"


def test_menubar_setting_round_trips(client):
    assert client.get("/settings").get_json()["menubar"] is True
    assert client.post("/settings", json={"menubar": False}).get_json()["menubar"] is False
    assert client.post("/settings", json={"menubar": True}).get_json()["menubar"] is True


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_no_op_off_macos(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(hotkeys, "_controller", None)
    assert hotkeys.available() is False
    assert hotkeys.start(FakeWindow(), run_now) is None
    hotkeys.desktop_start(FakeWindow())                  # returns without touching AppKit or Carbon
    assert hotkeys._controller is None
    assert hotkeys.status()["available"] is False


def test_built_menu_json_has_both_languages():
    import os
    path = os.path.join(hotkeys.ROOT, "static", "app", "menu.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert set(data) == {"ru", "en"}
    assert set(data["ru"]) == set(data["en"]) == set(hotkeys._FALLBACK)
