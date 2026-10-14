"""What the system lets Dictum use, for the first-run Разрешения step (5.0 C8).

Each permission is "granted", "denied", "undetermined" or "unsupported". Reading never shows a prompt:

- microphone: macOS asks AVFoundation for the authorization status (the same PyObjC path as
  macos_permissions.microphone_access); elsewhere it is granted when an input device enumerates.
- system audio: macOS 14.2+ only (macos_audio.support()). macOS offers no public way to read the "system audio
  recording" state without asking, so it stays undetermined until the first tap succeeds (the dry run behind
  Разрешить); the result is kept in setup-state.json.
- notifications: macOS only; undetermined until the first osascript notification ran, then granted.
"""
import sys

GRANTED, DENIED, UNDETERMINED, UNSUPPORTED = "granted", "denied", "undetermined", "unsupported"
WHICH = ("microphone", "system_audio", "notifications")
STATE_KEY = "perm:{}"            # setup-state.json keys for what can only be learned by trying

# AVAuthorizationStatus (see macos_permissions): not determined, restricted, denied, authorized
_AV = {0: UNDETERMINED, 1: DENIED, 2: DENIED, 3: GRANTED}

SETTINGS_URLS = {
    "darwin": {
        "microphone": "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        "system_audio": "x-apple.systempreferences:com.apple.preference.security?Privacy_AudioCapture",
        "notifications": "x-apple.systempreferences:com.apple.preference.notifications",
    },
    "win32": {"microphone": "ms-settings:privacy-microphone"},
}


def _input_count():
    import sounddevice as sd
    return sum(1 for d in sd.query_devices() if d["max_input_channels"] > 0)


def _support():
    from core.macos_audio import support
    return support()


def microphone_status(platform=None, av=None, inputs=_input_count):
    platform = platform or sys.platform
    if platform == "darwin":
        if av is None:
            try:
                import AVFoundation as av
            except ImportError:
                return UNDETERMINED
        try:
            return _AV.get(int(av.AVCaptureDevice.authorizationStatusForMediaType_(av.AVMediaTypeAudio)), UNDETERMINED)
        except Exception:
            return UNDETERMINED
    try:
        return GRANTED if inputs() else UNDETERMINED
    except Exception:
        return UNDETERMINED


def read(state, platform=None, av=None, support=None, inputs=None):
    """{microphone, system_audio, notifications}, without prompting."""
    platform, support = platform or sys.platform, support or _support
    out = {"microphone": microphone_status(platform, av, inputs or _input_count)}
    if platform == "darwin":
        out["system_audio"] = (state.get(STATE_KEY.format("system_audio")) or UNDETERMINED) if support()[0] else UNSUPPORTED
        out["notifications"] = state.get(STATE_KEY.format("notifications")) or UNDETERMINED
    else:
        out["system_audio"] = out["notifications"] = UNSUPPORTED
    return out


def request(which, state, mic_access, tap_dry_run, send_notification, platform=None, support=None):
    """Show the system prompt for one permission (or do what makes macOS show it). Blocks until answered."""
    platform, support = platform or sys.platform, support or _support
    if which not in WHICH:
        raise ValueError(f"unknown permission {which!r}")
    if which == "microphone":
        mic_access()
    elif platform == "darwin" and which == "system_audio":
        if support()[0]:
            try:
                tap_dry_run()
            except Exception:  # the tap could not be opened or read
                state.set(STATE_KEY.format(which), DENIED)
            else:
                state.set(STATE_KEY.format(which), GRANTED)
    elif platform == "darwin" and which == "notifications":
        if send_notification():
            state.set(STATE_KEY.format(which), GRANTED)


def settings_url(which, platform=None):
    return SETTINGS_URLS.get(platform or sys.platform, {}).get(which)
