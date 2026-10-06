"""Long recordings: pyannote gets a waveform, never a path (torchaudio 2.9+ has no decoder without torchcodec)."""
import sys
import types

from core import longform


class _Seg:
    def __init__(self, start, end):
        self.start, self.end = start, end


class _Timeline:
    def __init__(self, segs):
        self._segs = segs

    def get_timeline(self):
        return self

    def support(self):
        return self._segs


def test_chunking_follows_gigaam_rules():
    sr = 100
    audio = list(range(100 * sr))                                    # 100 s of "audio"
    speech = _Timeline([_Seg(0, 10), _Seg(10.5, 20), _Seg(21, 24), _Seg(30, 70), _Seg(90, 90.1)])
    segments, bounds = longform.segment_waveform(audio, speech, sr)
    assert bounds[0] == (0, 20)                                      # 0–10 and 10.5–20 joined: 20 s > min 15
    assert bounds[1] == (21, 24)
    assert bounds[2:] == [(30.0, 50.0), (50.0, 70.0)], "a 40-s stretch is split in two"
    assert len(segments) == 4 and len(segments[0]) == 20 * sr
    assert all(b[1] - b[0] > 0.2 for b in bounds), "a 0.1-s blip is dropped"


def test_pipeline_receives_the_waveform_not_the_path(monkeypatch):
    seen = {}

    class Pipeline:
        def __call__(self, file):
            seen["file"] = file
            return _Timeline([_Seg(0, 1)])
    class Wave(list):                                               # what gigaam's load_audio returns, minus torch
        def unsqueeze(self, dim): return self
        def float(self): return self
        def cpu(self): return self
        shape = (1, 16000)
    fake = types.SimpleNamespace(load_audio=lambda path: Wave(range(16000)), get_pipeline=lambda device: Pipeline())
    monkeypatch.setitem(sys.modules, "gigaam.vad_utils", fake)
    segments, bounds = longform.segment_audio_file("call.wav", 16000)
    assert isinstance(seen["file"], dict) and seen["file"]["sample_rate"] == 16000
    assert seen["file"]["waveform"].shape == (1, 16000)
    assert bounds == [(0, 1)]


def test_install_replaces_gigaams_function(monkeypatch):
    fake = types.ModuleType("gigaam.vad_utils")
    fake.segment_audio_file = lambda *a, **k: "original"
    monkeypatch.setitem(sys.modules, "gigaam.vad_utils", fake)
    assert longform.install()
    assert fake.segment_audio_file is longform.segment_audio_file
