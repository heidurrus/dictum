"""The microphone list, kept fresh (5.0.5).

PortAudio reads the audio devices once, when it is initialised, and sounddevice initialises it on import. Dictum
runs for days, and on a Mac the devices change all the time: AirPods come and go, an iPhone offers its
microphone, Teams adds a virtual device. A device index taken from that first list can then point at a device
macOS no longer has, and opening it fails ("no object with given ID" in the unified log), which the user sees as
"whispers give me errors". So the list is re-read right before a microphone is opened, and a saved index that no
longer names an input device falls back to the default microphone.

Re-reading tears PortAudio down and up again, which would break any stream that is open, so the caller only
refreshes when nothing records (the start routes hold the recorder lock and have just checked that).
"""
import logging
import threading

log = logging.getLogger("dictum.audio")
_lock = threading.Lock()


def refresh():
    """Re-read the device list. Safe only while no stream is open. Never raises: a failed refresh leaves the old list."""
    with _lock:
        try:
            import sounddevice as sd
            sd._terminate()
            sd._initialize()
        except Exception:                       # the old list is still usable
            log.exception("Audio devices could not be re-read")


def inputs():
    """[(index, name)] of the current input devices, loopbacks left out."""
    import sounddevice as sd
    return [(i, d["name"]) for i, d in enumerate(sd.query_devices())
            if d["max_input_channels"] > 0 and "loopback" not in d["name"].lower()]


def resolve_input(index):
    """The saved index if it still names an input device, else None (the default microphone). A name saved with the
    index wins when the index moved to another device, which happens after a refresh."""
    if index is None or index == "":
        return None
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        i = int(index)
        if 0 <= i < len(devices) and devices[i]["max_input_channels"] > 0:
            return i
    except Exception:
        pass
    log.warning("Saved microphone %r is gone; recording from the default microphone", index)
    return None


def resolve_input_by_name(index, name):
    """Like resolve_input, but when `name` is given and names a current input device, that device is used even if
    its index changed (devices renumber when one is added or removed)."""
    if name:
        try:
            for i, n in inputs():
                if n == name:
                    return i
        except Exception:
            pass
    return resolve_input(index)
