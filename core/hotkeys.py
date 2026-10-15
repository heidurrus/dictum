"""Global hot keys and the menu-bar item in the macOS desktop app (spec 5.0 C7, increment 12).

Hot keys go through Carbon's RegisterEventHotKey (ctypes on Carbon.framework): it needs no permission and is
allowed in the App Store sandbox, unlike an NSEvent global monitor, which needs Accessibility. The settings
"hotkeys" map ("alt+space", "cmd+shift+d", …) is parsed into Carbon key codes and modifier masks; "whisper" and
"record" are registered, and registered again when the settings are saved.

The menu-bar item is an NSStatusItem with a template image (macOS tints it for light and dark menu bars) and a
small menu: Шепнуть, Записать встречу, Показать Dictum, Выйти. Its titles follow the UI language the page reports
to /api/ui-lang; while a recording or a whisper runs, the first items become "stop" and a red dot shows.

Every AppKit and Carbon call runs on the main thread: pywebview owns the Cocoa run loop, so `desktop_start` (the
function given to `webview.start`) schedules them with PyObjCTools.AppHelper.callAfter. Calls into the pywebview
window (show, evaluate_js) go from a short-lived worker thread, since pywebview marshals them to the main thread
itself and waits for the result. Any failure is logged and the app keeps running without the item or the keys.

On Windows (and in browser mode) nothing here runs: `available()` is false and the window-level keys still work.
"""
import ctypes
import json
import logging
import os
import sys
import threading

log = logging.getLogger("dictum.hotkeys")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARBON = "/System/Library/Frameworks/Carbon.framework/Carbon"
ACTIONS = ("whisper", "record")                 # the hot-key ids are their position + 1

# Carbon modifier masks (Events.h).
CMD, SHIFT, OPTION, CONTROL = 0x0100, 0x0200, 0x0800, 0x1000
MODIFIERS = {"cmd": CMD, "command": CMD, "meta": CMD, "shift": SHIFT, "alt": OPTION, "opt": OPTION,
             "option": OPTION, "ctrl": CONTROL, "control": CONTROL}
MODIFIER_SYMBOLS = ((CONTROL, "⌃"), (OPTION, "⌥"), (SHIFT, "⇧"), (CMD, "⌘"))

# Virtual key codes of the ANSI layout (HIToolbox Events.h, kVK_*).
KEY_CODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09,
    "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14,
    "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18, "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
    "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29,
    "\\": 0x2A, ",": 0x2B, "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F, "`": 0x32,
    "enter": 0x24, "return": 0x24, "tab": 0x30, "space": 0x31, "backspace": 0x33, "esc": 0x35, "escape": 0x35,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
}
FUNCTION_KEYS = {
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64, "f9": 0x65,
    "f10": 0x6D, "f11": 0x67, "f12": 0x6F, "f13": 0x69, "f14": 0x6B, "f15": 0x71, "f16": 0x6A, "f17": 0x40,
    "f18": 0x4F, "f19": 0x50, "f20": 0x5A,
}
KEY_CODES.update(FUNCTION_KEYS)
KEY_NAMES = {"space": "Space", "enter": "↩", "return": "↩", "tab": "⇥", "backspace": "⌫", "esc": "⎋",
             "escape": "⎋", "left": "←", "right": "→", "down": "↓", "up": "↑"}


def parse(combo):
    """"alt+space" → (key code, Carbon modifier mask). ValueError for anything that can't be a global hot key:
    an unknown key or modifier, a repeated modifier, or a plain key without a modifier (only F-keys may go bare)."""
    if not isinstance(combo, str) or not combo.strip():
        raise ValueError("empty hot key")
    parts = [p.strip() for p in combo.strip().lower().split("+")]
    if any(not p for p in parts):
        raise ValueError(f"malformed hot key {combo!r}")
    *mods, key = parts
    mask = 0
    for m in mods:
        bit = MODIFIERS.get(m)
        if bit is None:
            raise ValueError(f"unknown modifier {m!r} in {combo!r}")
        if mask & bit:
            raise ValueError(f"repeated modifier {m!r} in {combo!r}")
        mask |= bit
    if key not in KEY_CODES:
        raise ValueError(f"unknown key {key!r} in {combo!r}")
    if not mask and key not in FUNCTION_KEYS:
        raise ValueError(f"{combo!r} needs a modifier to be a global hot key")
    return KEY_CODES[key], mask


def label(combo):
    """"alt+space" → "⌥Space", for the menu titles. Empty when the combo doesn't parse."""
    try:
        _, mask = parse(combo)
    except ValueError:
        return ""
    key = combo.strip().lower().split("+")[-1].strip()
    name = KEY_NAMES.get(key) or key.upper()
    return "".join(s for bit, s in MODIFIER_SYMBOLS if mask & bit) + name


def window_only(combo):
    """⌘ plus one key is every app's own menu shortcut (⌘R reloads a browser page): taking it system-wide would
    break other apps, so such a binding stays a window-level key."""
    code, mask = parse(combo)
    return mask == CMD and code not in FUNCTION_KEYS.values()


def available():
    """True where global hot keys and the menu-bar item can exist: macOS with Carbon present."""
    return sys.platform == "darwin" and os.path.exists(CARBON)


# ── Carbon (ctypes) ──────────────────────────────────────────────────────────

def fourcc(s):
    return int.from_bytes(s.encode("ascii"), "big")


class HotKeyTaken(Exception):
    """The combination is reserved by the system or registered already."""


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
EVENT_HOTKEY_EXISTS = -9878
EVENT_NOT_HANDLED = -9874


class CarbonHotKeys:
    """RegisterEventHotKey and its handler, through ctypes. Main thread only."""
    SIGNATURE = fourcc("DCTM")

    def __init__(self):
        self._lib = None
        self._handler = None            # the ctypes callback must stay alive as long as the handler is installed

    def _load(self):
        if self._lib is None:
            lib = ctypes.CDLL(CARBON)
            lib.GetApplicationEventTarget.restype = ctypes.c_void_p
            lib.GetApplicationEventTarget.argtypes = []
            lib.InstallEventHandler.restype = ctypes.c_int32
            lib.InstallEventHandler.argtypes = [ctypes.c_void_p, _HANDLER, ctypes.c_ulong,
                                                ctypes.POINTER(_EventTypeSpec), ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_void_p)]
            lib.RegisterEventHotKey.restype = ctypes.c_int32
            lib.RegisterEventHotKey.argtypes = [ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID, ctypes.c_void_p,
                                                ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
            lib.UnregisterEventHotKey.restype = ctypes.c_int32
            lib.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
            lib.GetEventParameter.restype = ctypes.c_int32
            lib.GetEventParameter.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                              ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
            self._lib = lib
        return self._lib

    def install(self, on_press):
        """Call on_press(hot key id) whenever one of our hot keys is pressed."""
        lib = self._load()

        def handler(_call_ref, event, _user_data):
            hk = _EventHotKeyID()
            err = lib.GetEventParameter(event, fourcc("----"), fourcc("hkid"), None, ctypes.sizeof(hk), None,
                                        ctypes.byref(hk))
            if err or hk.signature != self.SIGNATURE:
                return EVENT_NOT_HANDLED
            try:
                on_press(hk.id)
            except Exception:
                log.exception("Hot key %s failed", hk.id)
            return 0

        self._handler = _HANDLER(handler)
        spec = _EventTypeSpec(fourcc("keyb"), 5)        # kEventClassKeyboard, kEventHotKeyPressed
        ref = ctypes.c_void_p()
        err = lib.InstallEventHandler(lib.GetApplicationEventTarget(), self._handler, 1, ctypes.byref(spec), None,
                                      ctypes.byref(ref))
        if err:
            raise OSError(f"InstallEventHandler failed ({err})")

    def register(self, code, mask, hotkey_id):
        lib = self._load()
        ref = ctypes.c_void_p()
        err = lib.RegisterEventHotKey(code, mask, _EventHotKeyID(self.SIGNATURE, hotkey_id),
                                      lib.GetApplicationEventTarget(), 0, ctypes.byref(ref))
        if err == EVENT_HOTKEY_EXISTS:
            raise HotKeyTaken(f"hot key {code}/{mask:#x} is taken")
        if err or not ref.value:
            raise HotKeyTaken(f"RegisterEventHotKey failed ({err})")
        return ref

    def unregister(self, ref):
        self._load().UnregisterEventHotKey(ref)


class HotKeys:
    """The registered "whisper" and "record" hot keys and their status ("ok", "taken", "window", "invalid")."""

    def __init__(self, backend, on_action):
        self.backend, self.on_action = backend, on_action
        self.status = {a: "off" for a in ACTIONS}
        self.combos = {}
        self._refs = {}
        self._installed = False

    def apply(self, hotkey_map):
        """(Re-)register from the settings map. Main thread only."""
        if not self._installed:
            self.backend.install(self._pressed)
            self._installed = True
        self.clear()
        for i, action in enumerate(ACTIONS, 1):
            combo = (hotkey_map or {}).get(action) or ""
            self.combos[action] = combo
            try:
                code, mask = parse(combo)
                if window_only(combo):
                    self.status[action] = "window"
                    continue
                self._refs[action] = self.backend.register(code, mask, i)
                self.status[action] = "ok"
            except ValueError as e:
                self.status[action] = "invalid"
                log.warning("Hot key for %s not registered: %s", action, e)
            except Exception as e:      # HotKeyTaken, or any Carbon failure: the window-level key still works
                self.status[action] = "taken"
                log.warning("Hot key %s for %s is taken by the system or another app (%s)", combo, action, e)

    def clear(self):
        for action, ref in list(self._refs.items()):
            try:
                self.backend.unregister(ref)
            except Exception:
                log.exception("Could not unregister the %s hot key", action)
        self._refs.clear()
        self.status = {a: "off" for a in ACTIONS}

    def _pressed(self, hotkey_id):
        if 1 <= hotkey_id <= len(ACTIONS):
            self.on_action(ACTIONS[hotkey_id - 1])


# ── Menu titles ──────────────────────────────────────────────────────────────

MENU_JSON = os.path.join(ROOT, "static", "app", "menu.json")   # menu.* from i18n.js, written by the vite build
_FALLBACK = {"menu.whisper": "Whisper", "menu.record": "Record a meeting", "menu.stop_record": "Stop recording",
             "menu.stop_whisper": "Stop", "menu.show": "Show Dictum", "menu.quit": "Quit"}
_menu_cache = {}


def menu_strings(lang, path=None):
    """The menu.* strings for "ru" or "en" (anything else → "en"), from the build's menu.json."""
    path = path or MENU_JSON
    if path not in _menu_cache:
        try:
            with open(path, encoding="utf-8") as f:
                _menu_cache[path] = json.load(f)
        except (OSError, ValueError):
            log.warning("Menu titles not found at %s; using English", path)
            _menu_cache[path] = {}
    data = _menu_cache[path]
    lang = lang if lang in data else "en"
    return {**_FALLBACK, **data.get(lang, {})}


def menu_titles(lang, hotkey_map, busy):
    """The menu's item titles for this language, hot keys and state ({"recording", "whisper"})."""
    s = menu_strings(lang)
    hk = hotkey_map or {}

    def with_key(text, action):
        key = label(hk.get(action) or "")
        return f"{text} {key}" if key else text

    return {
        "whisper": s["menu.stop_whisper"] if busy.get("whisper") else with_key(s["menu.whisper"], "whisper"),
        "record": s["menu.stop_record"] if busy.get("recording") else with_key(s["menu.record"], "record"),
        "show": s["menu.show"],
        "quit": s["menu.quit"],
    }


# ── The menu-bar item (AppKit) ───────────────────────────────────────────────

ICON_NAMES = ("dictumTemplate.png", "dictumTemplate@2x.png")
ICON_HEIGHT = 18
MENU_TAGS = {1: "whisper", 2: "record", 3: "show", 4: "quit"}


def icon_dir():
    """packaging/macos in a source checkout; the bundle's Resources (next to app/) in the built app."""
    for d in (os.path.join(ROOT, "packaging", "macos"), os.path.dirname(ROOT)):
        if os.path.exists(os.path.join(d, ICON_NAMES[0])):
            return d
    return None


_target_class = None


def _menu_target_class():
    """The Objective-C object the menu items send their action to (defined once per process)."""
    global _target_class
    if _target_class is None:
        from Foundation import NSObject

        class DictumMenuTarget(NSObject):
            def fire_(self, sender):
                try:
                    self.callback(MENU_TAGS.get(int(sender.tag())))
                except Exception:
                    log.exception("Menu action failed")

        _target_class = DictumMenuTarget
    return _target_class


class MenuBar:
    """The NSStatusItem and its menu. Main thread only; every method may raise, the controller logs it."""

    def __init__(self, on_item):
        self.on_item = on_item
        self.item = None
        self._target = None
        self._items = {}

    def _image(self):
        from AppKit import NSImage, NSImageRep
        d = icon_dir()
        if d is None:
            return None
        reps = []
        for name in ICON_NAMES:
            reps += list(NSImageRep.imageRepsWithContentsOfFile_(os.path.join(d, name)) or [])
        if not reps:
            return None
        w, h = reps[0].pixelsWide(), reps[0].pixelsHigh()      # the 1x file sets the shape; 18 pt tall at most
        size = (w * ICON_HEIGHT / h, ICON_HEIGHT) if h > ICON_HEIGHT else (w, h)
        image = NSImage.alloc().initWithSize_(size)
        for rep in reps:
            rep.setSize_(size)
            image.addRepresentation_(rep)
        image.setTemplate_(True)
        return image

    def show(self, titles, busy):
        from AppKit import NSMenu, NSMenuItem, NSStatusBar, NSVariableStatusItemLength
        if self.item is None:
            self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
            image = self._image()
            button = self.item.button()
            if image is not None:
                button.setImage_(image)
            else:
                button.setTitle_("Dictum")
            self._target = _menu_target_class().alloc().init()
            self._target.callback = self.on_item
            menu = NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)
            for tag, key in MENU_TAGS.items():
                if key == "show":
                    menu.addItem_(NSMenuItem.separatorItem())
                mi = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(titles[key], "fire:", "")
                mi.setTarget_(self._target)
                mi.setTag_(tag)
                menu.addItem_(mi)
                self._items[key] = mi
            self.item.setMenu_(menu)
        self.update(titles, busy)

    def update(self, titles, busy):
        if self.item is None:
            return
        for key, mi in self._items.items():
            mi.setTitle_(titles[key])
        self._dot(bool(busy.get("recording") or busy.get("whisper")))

    def _dot(self, on):
        """A small red dot after the template glyph while something records; the glyph itself stays template."""
        button = self.item.button()
        if not on:
            button.setTitle_("")
            return
        try:
            from AppKit import (NSAttributedString, NSColor, NSFont, NSFontAttributeName,
                                NSForegroundColorAttributeName, NSImageLeft)
            attrs = {NSForegroundColorAttributeName: NSColor.systemRedColor(), NSFontAttributeName: NSFont.systemFontOfSize_(9)}
            button.setImagePosition_(NSImageLeft)
            button.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_("●", attrs))
        except Exception:
            log.exception("Red dot unavailable; using a plain one")
            button.setTitle_("● ")

    def remove(self):
        if self.item is not None:
            from AppKit import NSStatusBar
            NSStatusBar.systemStatusBar().removeStatusItem_(self.item)
        self.item, self._target, self._items = None, None, {}


# ── The controller: state, settings hook, the page bridge ───────────────────

def _no_state():
    return {"recording": False, "whisper": False}


_state_source = _no_state
_ui_lang = {"lang": None}
_controller = None
_hook_installed = False


def set_state_source(fn):
    """app.py tells us how to read "is a meeting or a whisper recording" (polled once a second)."""
    global _state_source
    _state_source = fn


def _busy():
    try:
        st = _state_source() or {}
        return {"recording": bool(st.get("recording")), "whisper": bool(st.get("whisper"))}
    except Exception:
        return _no_state()


def _system_lang():
    try:
        from Foundation import NSLocale
        return "ru" if str(NSLocale.preferredLanguages()[0]).lower().startswith("ru") else "en"
    except Exception:
        return "en"


def page_js(action):
    return f"window.dispatchEvent(new CustomEvent('dictum:hotkey', {{detail: {{action: {json.dumps(action)}}}}}))"


class Controller:
    def __init__(self, window, call_main, backend=None, menubar=None, settings_loader=None, spawn=None):
        from core import settings as settings_mod
        self.window = window
        self.call_main = call_main
        self.load_settings = settings_loader or settings_mod.load_settings
        self.spawn = spawn or (lambda fn: threading.Thread(target=fn, daemon=True).start())
        self.hotkeys = HotKeys(backend or CarbonHotKeys(), self.on_action)
        self.menubar = menubar or MenuBar(self.on_menu)
        self.prefs = {}
        self.busy = _no_state()
        self._stop = threading.Event()

    # main thread
    def install(self):
        try:
            prefs = self.load_settings()
        except Exception:
            log.exception("Settings unreadable; hot keys and menu bar use the defaults")
            from core.settings import DEFAULTS
            prefs = DEFAULTS
        self.apply_settings(prefs, force=True)

    def apply_settings(self, prefs, force=False):
        hk = {a: (prefs.get("hotkeys") or {}).get(a) for a in ACTIONS}
        old_hk = {a: (self.prefs.get("hotkeys") or {}).get(a) for a in ACTIONS}
        if force or hk != old_hk:
            try:
                self.hotkeys.apply(hk)
            except Exception:
                log.exception("Global hot keys unavailable")
        self.prefs = prefs
        self.refresh_menu()

    def refresh_menu(self):
        try:
            if self.prefs.get("menubar", True) is False:
                self.menubar.remove()
                return
            titles = menu_titles(_ui_lang["lang"] or _system_lang(), self.prefs.get("hotkeys"), self.busy)
            self.menubar.show(titles, self.busy)
        except Exception:
            log.exception("Menu-bar item unavailable")

    def set_busy(self, busy):
        self.busy = busy
        self.refresh_menu()

    # Carbon / menu callbacks (main thread): the window work goes to a worker thread
    def on_action(self, action):
        self.spawn(lambda: self.bring_forward(action))

    def on_menu(self, key):
        if key == "quit":
            self.spawn(self.quit)
        elif key == "show":
            self.spawn(lambda: self.bring_forward(None))
        elif key == "record" and self.busy.get("recording"):
            self.spawn(lambda: self.bring_forward("record_stop"))
        elif key in ACTIONS:
            self.spawn(lambda: self.bring_forward(key))

    # worker thread
    def bring_forward(self, action):
        for name in ("restore", "show"):
            try:
                getattr(self.window, name)()
            except Exception:
                log.exception("window.%s failed", name)
        self.call_main(_activate)
        if action:
            try:
                self.window.evaluate_js(page_js(action))
            except Exception:
                log.exception("Could not tell the page about %s", action)

    def quit(self):
        """The same path as closing the window: webview.start returns and the launcher shuts the server down
        (a recording's WAV is written as it goes, so it is kept)."""
        try:
            self.window.destroy()
        except Exception:
            log.exception("Could not close the window")

    def poll(self, interval=1.0):
        """Watch the recording state from a worker thread; the menu changes on the main thread."""
        while not self._stop.wait(interval):
            busy = _busy()
            if busy != self.busy:
                self.call_main(self.set_busy, busy)

    def stop(self):
        self._stop.set()


def _activate():
    try:
        from AppKit import NSApp
        NSApp.activateIgnoringOtherApps_(True)
    except Exception:
        log.exception("Could not activate the app")


def _settings_saved(prefs):
    ctl = _controller
    if ctl is not None:
        ctl.call_main(ctl.apply_settings, prefs)


def start(window, call_main, **kw):
    """Create the controller and schedule its install on the main thread. Returns it, or None off macOS."""
    global _controller, _hook_installed
    if not available():
        return None
    from core import settings as settings_mod
    _controller = Controller(window, call_main, **kw)
    if not _hook_installed:
        settings_mod.on_save(_settings_saved)
        _hook_installed = True
    call_main(_controller.install)
    return _controller


def desktop_start(window):
    """Given to webview.start: runs on pywebview's thread once the GUI loop is up."""
    if not available():
        return
    try:
        from PyObjCTools import AppHelper
        ctl = start(window, AppHelper.callAfter)
        if ctl is not None:
            threading.Thread(target=ctl.poll, daemon=True).start()
    except Exception:
        log.exception("Menu bar and global hot keys unavailable")


def set_ui_lang(lang):
    """The page's language (on boot and on switch); the menu is rebuilt in it."""
    if lang not in ("ru", "en"):
        raise ValueError("lang must be ru or en")
    _ui_lang["lang"] = lang
    ctl = _controller
    if ctl is not None:
        ctl.call_main(ctl.refresh_menu)


def status():
    """For GET /api/hotkeys/status: {available, supported, platform, whisper, record}. `available` is true once the
    controller runs; `supported` is `available()` (macOS with Carbon: the platform can have global keys and the
    menu-bar item at all; Settings hides the menu-bar switch when it is false); `platform` is sys.platform. whisper
    and record are each "ok" | "taken" | "window" | "invalid" | "off" (not registered: off macOS, in browser mode,
    or before the app has started)."""
    ctl = _controller
    st = dict(ctl.hotkeys.status) if ctl is not None else {a: "off" for a in ACTIONS}
    return {"available": ctl is not None, "supported": available(), "platform": sys.platform, **st}
