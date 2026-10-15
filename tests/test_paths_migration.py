"""C0: the 4.x data folder becomes Dictum on first start."""
import errno
import os

import pytest

from core import paths


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBENCH_DATA_DIR", raising=False)
    monkeypatch.delenv("DICTUM_DATA_DIR", raising=False)
    monkeypatch.setattr(paths, "_user_data_root", lambda: str(tmp_path))
    monkeypatch.setattr(paths, "_migration_checked", False)
    monkeypatch.setattr(paths, "_resolved", None)
    monkeypatch.setattr(paths, "_server_started", False)
    return tmp_path


def _old_folder(root):
    old = root / "RequirementsWorkbench"
    (old / "recordings").mkdir(parents=True)
    (old / "recordings" / "call.wav").write_bytes(b"RIFF" + b"\0" * 100)
    (old / "models" / "gigaam").mkdir(parents=True)
    (old / "models" / "gigaam" / "v3.ckpt").write_bytes(b"x" * 1000)
    (old / "workbench.db").write_bytes(b"sqlite")
    return old


def test_fresh_start_creates_only_the_new_folder(root):
    assert paths.app_data_dir() == str(root / "Dictum")
    assert sorted(os.listdir(root)) == ["Dictum"]
    assert os.listdir(root / "Dictum") == []


def test_old_folder_is_moved_once_with_a_note(root):
    old = _old_folder(root)
    data = paths.app_data_dir()
    assert data == str(root / "Dictum")
    assert not old.exists()
    assert sorted(os.listdir(root)) == ["Dictum"]
    new = root / "Dictum"
    assert (new / "recordings" / "call.wav").read_bytes() == b"RIFF" + b"\0" * 100
    assert (new / "models" / "gigaam" / "v3.ckpt").stat().st_size == 1000
    assert (new / "workbench.db").read_bytes() == b"sqlite"
    note = (new / "migrated-from.txt").read_text(encoding="utf-8").splitlines()
    assert note[0] == str(old) and note[1][:4].isdigit()
    # Later calls do not move or copy anything again.
    assert paths.app_data_dir() == data
    assert sorted(os.listdir(root)) == ["Dictum"]


def test_both_folders_present_nothing_touched(root):
    old = _old_folder(root)
    (root / "Dictum").mkdir()
    (root / "Dictum" / "mine.txt").write_text("new")
    assert paths.app_data_dir() == str(root / "Dictum")
    assert (old / "recordings" / "call.wav").exists()
    assert os.listdir(root / "Dictum") == ["mine.txt"]


@pytest.mark.parametrize("var", ["WORKBENCH_DATA_DIR", "DICTUM_DATA_DIR"])
def test_env_override_skips_migration(root, monkeypatch, var):
    old = _old_folder(root)
    monkeypatch.setenv(var, str(root / "custom"))
    assert paths.app_data_dir() == str(root / "custom")
    assert old.exists() and not (root / "Dictum").exists()


def test_new_env_name_wins(root, monkeypatch):
    monkeypatch.setenv("WORKBENCH_DATA_DIR", str(root / "old-env"))
    monkeypatch.setenv("DICTUM_DATA_DIR", str(root / "new-env"))
    assert paths.app_data_dir() == str(root / "new-env")


def test_cross_volume_move_copies_verifies_and_removes(root, monkeypatch):
    old = _old_folder(root)
    real_rename = os.rename

    def rename(src, dst):
        if src == str(old):
            raise OSError(errno.EXDEV, "cross-device link")
        return real_rename(src, dst)

    monkeypatch.setattr(paths.os, "rename", rename)
    assert paths.app_data_dir() == str(root / "Dictum")
    assert not old.exists() and sorted(os.listdir(root)) == ["Dictum"]
    assert (root / "Dictum" / "models" / "gigaam" / "v3.ckpt").stat().st_size == 1000


def test_failed_move_keeps_using_the_old_folder(root, monkeypatch):
    old = _old_folder(root)

    def rename(src, dst):
        raise PermissionError(errno.EACCES, "in use")

    monkeypatch.setattr(paths.os, "rename", rename)
    assert paths.app_data_dir() == str(old)
    assert (old / "recordings" / "call.wav").exists() and not (root / "Dictum").exists()


def test_running_old_copy_is_not_moved(root, monkeypatch):
    old = _old_folder(root)
    monkeypatch.setattr(paths, "_legacy_app_running", lambda legacy: True)
    assert paths.app_data_dir() == str(old)
    assert old.exists() and not (root / "Dictum").exists()


def test_migration_refuses_once_the_server_runs(root, monkeypatch):
    _old_folder(root)
    monkeypatch.setattr(paths, "_server_started", True)
    with pytest.raises(AssertionError):
        paths.app_data_dir()
