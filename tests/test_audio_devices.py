"""5.0.5: the microphone list is re-read before a recording starts, and a saved index that no longer names an
input device falls back to the default microphone (the "whispers give me errors" bug: AirPods, an iPhone
microphone or Teams had changed the device list after PortAudio read it once)."""
import sys
import types

import pytest

from core import audio_devices


class FakeSd:
    def __init__(self, devices):
        self.devices = devices
        self.cycles = 0

    def query_devices(self):
        return self.devices

    def _terminate(self):
        self.cycles += 1

    def _initialize(self):
        pass


@pytest.fixture
def sd(monkeypatch):
    fake = FakeSd([{"name": "MacBook Pro Microphone", "max_input_channels": 1},
                   {"name": "MacBook Pro Speakers", "max_input_channels": 0},
                   {"name": "AirPods Pro", "max_input_channels": 1}])
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    return fake


def test_refresh_reinitialises_portaudio_and_survives_a_failure(sd, monkeypatch):
    audio_devices.refresh()
    assert sd.cycles == 1
    monkeypatch.setattr(sd, "_initialize", lambda: (_ for _ in ()).throw(RuntimeError("no audio host")))
    audio_devices.refresh()                       # logged, not raised


def test_inputs_leave_out_outputs_and_loopbacks(sd):
    sd.devices.append({"name": "BlackHole loopback", "max_input_channels": 2})
    assert audio_devices.inputs() == [(0, "MacBook Pro Microphone"), (2, "AirPods Pro")]


def test_a_gone_or_output_index_falls_back_to_the_default(sd):
    assert audio_devices.resolve_input(None) is None
    assert audio_devices.resolve_input("") is None
    assert audio_devices.resolve_input(2) == 2
    assert audio_devices.resolve_input("2") == 2
    assert audio_devices.resolve_input(1) is None      # speakers
    assert audio_devices.resolve_input(7) is None      # unplugged since the list was read
    assert audio_devices.resolve_input("x") is None


def test_the_name_wins_when_devices_renumber(sd):
    # AirPods were index 2 when chosen; after a phone appeared they are index 3.
    sd.devices.insert(2, {"name": "iPhone Microphone", "max_input_channels": 1})
    assert audio_devices.resolve_input_by_name(2, "AirPods Pro") == 3
    assert audio_devices.resolve_input_by_name(2, "Gone Headset") == 2      # index still an input: kept
    assert audio_devices.resolve_input_by_name(9, "Gone Headset") is None
