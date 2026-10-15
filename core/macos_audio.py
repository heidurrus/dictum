"""System-audio capture in the macOS desktop app via Core Audio process taps.

Spec FR-PLAT-02. macOS 14.2+ can "tap" the audio all apps are playing. The tap
is wrapped in a private aggregate input device, which PortAudio/sounddevice
then reads like a microphone. No virtual audio driver and no screen-sharing
permission are needed. macOS asks once for "system audio recording"
permission, using NSAudioCaptureUsageDescription from the app's Info.plist.

The private tap and aggregate device vanish automatically if the process
exits, so a crash can't leave devices behind.
"""
import importlib.util
import platform
import sys
import uuid

from core.recorder import SAMPLE_RATE
from core.resample import StreamResampler

DEVICE_NAME = "Dictum System Audio"
MIN_MACOS = (14, 2)
BLOCK = 1024


def _macos_version():
    try:
        return tuple(int(p) for p in platform.mac_ver()[0].split(".")[:2])
    except ValueError:
        return (0, 0)


def support():
    """(supported, reason_if_not). Cheap: creates nothing."""
    if sys.platform != "darwin":
        return False, "not macOS"
    ver = _macos_version()
    if ver < MIN_MACOS:
        return False, (f"system audio capture in the desktop app needs macOS 14.2 or newer "
                       f"(this Mac has {'.'.join(map(str, ver))}) — use browser mode to include call audio")
    if importlib.util.find_spec("CoreAudio") is None or importlib.util.find_spec("objc") is None:
        return False, "the CoreAudio component is missing — run Check & repair"
    return True, None


def _key(k):
    return k.decode() if isinstance(k, bytes) else k   # PyObjC exposes these C-string keys as bytes


def _get_property(ca, objc, obj, selector, size):
    addr = ca.AudioObjectPropertyAddress(selector, ca.kAudioObjectPropertyScopeGlobal,
                                         ca.kAudioObjectPropertyElementMain)
    err, _, data = ca.AudioObjectGetPropertyData(obj, addr, 0, objc.NULL, size, None)
    if err:
        raise OSError(f"Core Audio property {selector} failed ({err})")
    return bytes(data)


class SystemAudioTap:
    """Callable recorder source: ``tap(stop_event)`` yields int16 mono 16 kHz chunks.

    Call ``open()`` before other PortAudio streams start (it re-scans devices),
    and ``close()`` after recording.
    """

    def __init__(self):
        self._tap_id = None
        self._agg_id = None
        self.device_index = None
        self.samplerate = None

    def open(self):
        import CoreAudio as ca
        import objc
        from Foundation import NSArray
        import sounddevice as sd

        out_id = int.from_bytes(_get_property(ca, objc, ca.kAudioObjectSystemObject,
                                              ca.kAudioHardwarePropertyDefaultOutputDevice, 4), "little")
        uid_ptr = int.from_bytes(_get_property(ca, objc, out_id, ca.kAudioDevicePropertyDeviceUID, 8), "little")
        out_uid = str(objc.objc_object(c_void_p=uid_ptr))

        desc = ca.CATapDescription.alloc().initStereoGlobalTapButExcludeProcesses_(NSArray.array())
        desc.setName_(DEVICE_NAME)
        desc.setPrivate_(True)
        err, tap_id = ca.AudioHardwareCreateProcessTap(desc, None)
        if err:
            raise OSError(f"could not create the system audio tap (Core Audio error {err}); "
                          "check System Settings → Privacy & Security → Screen & System Audio Recording")
        self._tap_id = tap_id

        aggregate = {
            _key(ca.kAudioAggregateDeviceNameKey): DEVICE_NAME,
            _key(ca.kAudioAggregateDeviceUIDKey): "workbench-sysaudio-" + uuid.uuid4().hex[:12],
            _key(ca.kAudioAggregateDeviceMainSubDeviceKey): out_uid,
            _key(ca.kAudioAggregateDeviceIsPrivateKey): True,
            _key(ca.kAudioAggregateDeviceIsStackedKey): False,
            _key(ca.kAudioAggregateDeviceTapAutoStartKey): True,
            _key(ca.kAudioAggregateDeviceSubDeviceListKey): [{_key(ca.kAudioSubDeviceUIDKey): out_uid}],
            _key(ca.kAudioAggregateDeviceTapListKey): [{
                _key(ca.kAudioSubTapDriftCompensationKey): True,
                _key(ca.kAudioSubTapUIDKey): str(desc.UUID().UUIDString()),
            }],
        }
        err, agg_id = ca.AudioHardwareCreateAggregateDevice(aggregate, None)
        if err:
            self.close()
            raise OSError(f"could not create the system audio device (Core Audio error {err})")
        self._agg_id = agg_id

        # PortAudio only sees devices that existed when it initialised.
        sd._terminate()
        sd._initialize()
        for i, d in enumerate(sd.query_devices()):
            if d["name"] == DEVICE_NAME and d["max_input_channels"] > 0:
                self.device_index, self.samplerate = i, int(d["default_samplerate"])
                break
        else:
            self.close()
            raise OSError("the system audio device did not appear")
        return self

    def __call__(self, stop):
        import sounddevice as sd
        resampler = StreamResampler(self.samplerate, SAMPLE_RATE)
        with sd.InputStream(device=self.device_index, channels=2, samplerate=self.samplerate,
                            dtype="float32", blocksize=BLOCK) as stream:
            while not stop.is_set():
                if stream.read_available < BLOCK:   # never block in read(): a tap that delivers nothing
                    stop.wait(0.01)                 # (permission pending or off) must still notice stop
                    continue
                chunk, _ = stream.read(BLOCK)
                yield resampler.process(chunk.mean(axis=1))

    def close(self):
        try:
            import CoreAudio as ca
        except ImportError:
            return
        if self._agg_id is not None:
            ca.AudioHardwareDestroyAggregateDevice(self._agg_id)
            self._agg_id = None
        if self._tap_id is not None:
            ca.AudioHardwareDestroyProcessTap(self._tap_id)
            self._tap_id = None


def dry_run(seconds=1.0, tap_factory=SystemAudioTap, grace=1.0):
    """Open the tap and read it for about a second, so macOS asks for "system audio recording" permission (5.0 C8).
    The audio is dropped as it arrives: nothing is kept and nothing is written. Returns how many chunks arrived.

    The tap is read on a daemon thread, so this returns within ``seconds + grace`` even when the tap delivers
    nothing (the macOS prompt is still pending, or the permission is off) and the read blocks. Raises OSError when
    the tap cannot be opened."""
    import threading
    tap = tap_factory().open()
    stop, finished, lock = threading.Event(), threading.Event(), threading.Lock()
    count, gave_up = [0], [False]

    def read():
        chunks = None
        try:
            chunks = tap(stop)
            for _chunk in chunks:
                count[0] += 1
                if stop.is_set():
                    break
        except Exception:   # noqa: BLE001 - a failed read only means no audio arrived
            pass
        finally:
            if chunks is not None:
                try:
                    chunks.close()     # closes the input stream before the device goes away
                except Exception:      # noqa: BLE001
                    pass
            with lock:
                finished.set()
                late = gave_up[0]
            if late:                   # the caller returned without us: close the tap now
                tap.close()

    threading.Thread(target=read, name="system-audio-dry-run", daemon=True).start()
    finished.wait(seconds)             # a stream that ends early ends the wait early
    stop.set()
    finished.wait(grace)
    with lock:
        done = finished.is_set()
        gave_up[0] = not done
    if done:
        tap.close()
    return count[0]
