"""Test setup: stub the heavy ML stack (torch and the speech package) so the Flask app imports
anywhere, including CI machines without a GPU or model weights."""
import os
import sys
import tempfile
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _install_stubs():
    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: False, get_device_name=lambda i: None)
    torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))
    torch.device = lambda name: name
    utils = types.ModuleType("torch.utils")
    data = types.ModuleType("torch.utils.data")
    data.DataLoader = object
    torch.utils = utils
    utils.data = data

    gigaam = types.ModuleType("gigaam")
    gigaam.load_model = lambda name: None
    gigaam.format_time = lambda seconds: f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"
    preprocess = types.ModuleType("gigaam.preprocess")
    preprocess.load_audio = lambda path: None
    preprocess.SAMPLE_RATE = 16000
    gutils = types.ModuleType("gigaam.utils")
    gutils.AudioDataset = object

    sys.modules.update({
        "torch": torch, "torch.utils": utils, "torch.utils.data": data,
        "gigaam": gigaam, "gigaam.preprocess": preprocess, "gigaam.utils": gutils,
    })


_install_stubs()
os.environ["DICTUM_DATA_DIR"] = tempfile.mkdtemp(prefix="dictum-test-")


@pytest.fixture()
def app_module():
    import app as app_module
    return app_module


@pytest.fixture()
def client(app_module):
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def pytest_runtest_logreport(report):
    """On GitHub Actions, turn each failure into an annotation (readable without the raw log)."""
    if os.environ.get("GITHUB_ACTIONS") != "true" or not report.failed:
        return
    path, line, _ = report.location
    text = str(report.longrepr).strip().splitlines()
    message = " | ".join(text[-6:])[:900].replace("%", "%25").replace("\r", "").replace("\n", " ")
    sys.__stdout__.write(f"\n::error file={path},line={(line or 0) + 1},title={report.nodeid.replace('::', ' · ')}::{message}\n")
    sys.__stdout__.flush()
