"""Windows parity for 5.0 (spec C11), checked on any OS by faking sys.platform: the data folder in LOCALAPPDATA,
global keys and the menu-bar item off, the permissions that do not exist there reported as unsupported, the
strings the Windows UI swaps in, and the installer icon. The CPU fallback of live transcription (slow passes widen
the window, then live mode turns off and the transcript comes after stop) is test_live.test_backpressure_doubles_the_window_then_turns_live_off."""
import os
import re
import sys

from core import hotkeys, paths, permissions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_data_folder_is_in_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert paths._user_data_root() == str(tmp_path)
    assert paths.default_data_dir() == os.path.join(str(tmp_path), paths.APP_DIR_NAME)


def test_hotkeys_off_and_status_says_why(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(hotkeys, "_controller", None)
    assert hotkeys.status() == {"available": False, "supported": False, "platform": "win32",
                                "whisper": "off", "record": "off"}


def test_permissions_without_a_windows_counterpart_are_unsupported():
    out = permissions.read({}, platform="win32", inputs=lambda: 1)
    assert out["system_audio"] == out["notifications"] == permissions.UNSUPPORTED
    assert permissions.settings_url("microphone", "win32") == "ms-settings:privacy-microphone"
    assert permissions.settings_url("notifications", "win32") is None
    calls = []
    for which in ("system_audio", "notifications"):      # nothing to ask for on Windows: no call, no state written
        permissions.request(which, {}, mic_access=None, tap_dry_run=lambda: calls.append("tap"),
                            send_notification=lambda: calls.append("n"), platform="win32")
    assert calls == []


def _dict(lang):
    with open(os.path.join(ROOT, "frontend", "src", "lib", "i18n.js"), encoding="utf-8") as f:
        src = f.read()
    start = src.index(f"const {lang} = {{")
    return src[start:src.index("\n};", start)]


def _value(d, key):
    return re.search(rf'"{re.escape(key)}": "([^"]+)"', d).group(1)


def test_windows_strings_exist_in_both_languages():
    ru, en = _dict("ru"), _dict("en")
    for key in ("lib.reveal_win", "set.sto.placeholder_win", "tut.whisper_d_win", "set.k.needs_mod_win",
                "live.after_stop", "live.catching_up"):
        assert f'"{key}":' in ru and f'"{key}":' in en, key
    assert "Проводник" in _value(ru, "lib.reveal_win") and "Explorer" in _value(en, "lib.reveal_win")
    # shown on every platform, so the key comes in as a variable (comboLabel) instead of a hard-coded ⌘ glyph
    for key in ("shell.record_tip", "set.theme_hint", "nt.b", "nt.i"):
        for d in (ru, en):
            value = _value(d, key)
            assert "{key}" in value and "⌘" not in value, key


def test_installer_and_build_use_the_ico():
    with open(os.path.join(ROOT, "installer", "Dictum.iss"), encoding="utf-8") as f:
        iss = f.read()
    assert re.search(r"^SetupIconFile=.*Dictum\.ico$", iss, re.M)
    assert re.search(r"^UninstallDisplayIcon=\{app\}\\Dictum\.ico$", iss, re.M)
    assert iss.count('IconFilename: "{app}\\Dictum.ico"') >= 2
    with open(os.path.join(ROOT, "packaging", "build.py"), encoding="utf-8") as f:
        assert "Dictum.ico" in f.read()
    with open(os.path.join(ROOT, "packaging", "windows", "Dictum.ico"), "rb") as f:
        data = f.read()
    assert data[:4] == b"\x00\x00\x01\x00"
    count = int.from_bytes(data[4:6], "little")
    sizes = sorted((data[6 + 16 * i] or 256) for i in range(count))
    assert sizes == [16, 24, 32, 48, 64, 128, 256]
