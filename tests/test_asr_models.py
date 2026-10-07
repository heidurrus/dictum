"""Speech models: listing, verified downloads with progress, cancel, delete."""
import hashlib
import io
import os
import threading
import time

import pytest

from core import asr_models
from core.asr_models import Downloader, AsrModelError, list_models, delete_model


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_opener(files, delay=0):
    def open_(url, timeout=0):
        time.sleep(delay)
        name = url.rsplit("/", 1)[1]
        return FakeResponse(files[name])
    return open_


def wait(d, timeout=5):
    t = time.time()
    while d.busy() and time.time() - t < timeout:
        time.sleep(0.02)
    return d.status()


def test_download_verifies_and_installs_weights_and_tokenizer(tmp_path, monkeypatch):
    weights = b"w" * 3000
    monkeypatch.setitem(asr_models.BY_ID["v3_e2e_rnnt"], "size", len(weights))
    files = {"v3_e2e_rnnt.ckpt": weights, "v3_e2e_rnnt_tokenizer.model": b"tok"}
    d = Downloader(str(tmp_path), opener=fake_opener(files), hashes=lambda: {"v3_e2e_rnnt": hashlib.md5(weights).hexdigest()})
    d.start("v3_e2e_rnnt")
    st = wait(d)
    assert st["status"] == "done" and st["done"] == len(weights)
    assert (tmp_path / "v3_e2e_rnnt.ckpt").read_bytes() == weights and (tmp_path / "v3_e2e_rnnt_tokenizer.model").exists()
    assert not list(tmp_path.glob("*.part"))
    [m] = [m for m in list_models(str(tmp_path), d) if m["id"] == "v3_e2e_rnnt"]
    assert m["installed"] and not m["damaged"] and m["size_on_disk"] == len(weights) + 3


def test_damaged_download_is_rejected_and_removed(tmp_path, monkeypatch):
    weights = b"x" * 100
    monkeypatch.setitem(asr_models.BY_ID["v3_ctc"], "size", 100)
    d = Downloader(str(tmp_path), opener=fake_opener({"v3_ctc.ckpt": weights}), hashes=lambda: {"v3_ctc": "0" * 32})
    d.start("v3_ctc")
    st = wait(d)
    assert st["status"] == "error" and "checksum" in st["error"]
    assert not (tmp_path / "v3_ctc.ckpt").exists() and not (tmp_path / "v3_ctc.ckpt.part").exists()


def test_cancel_stops_the_download_and_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setitem(asr_models.BY_ID["v3_ctc"], "size", 5 * asr_models.MB)
    slow = fake_opener({"v3_ctc.ckpt": b"y" * (5 * asr_models.MB)}, delay=0.1)
    d = Downloader(str(tmp_path), opener=slow, hashes=lambda: {})
    d.start("v3_ctc")
    with pytest.raises(AsrModelError):
        d.start("v3_rnnt")                       # one at a time
    d.cancel()
    st = wait(d)
    assert st["status"] == "cancelled"
    assert not list(tmp_path.iterdir())


def test_list_flags_a_file_of_the_wrong_size_as_damaged(tmp_path):
    (tmp_path / "multilingual_large_ctc.ckpt").write_bytes(b"half")
    [m] = [m for m in list_models(str(tmp_path)) if m["id"] == "multilingual_large_ctc"]
    assert m["damaged"] and not m["installed"]
    assert delete_model("multilingual_large_ctc", str(tmp_path)) == 1
    assert not (tmp_path / "multilingual_large_ctc.ckpt").exists()
