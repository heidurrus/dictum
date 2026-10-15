import datetime
import errno
import json
import os
import shutil
import sys

APP_DIR_NAME = "Dictum"
LEGACY_DIR_NAME = "RequirementsWorkbench"   # up to 4.2.x; moved to APP_DIR_NAME on first start
MIGRATION_NOTE = "migrated-from.txt"
POINTER_FILE = "data-location.json"          # in the default folder, after "Сменить папку…" (5.0 C9)
WRITE_PROBE = ".dictum-write-test"

_migration_checked = False
_server_started = False
_resolved = None


def mark_server_started():
    """Called when the local server starts: from then on a recording may be active,
    so the data folder must never be moved by this process."""
    global _server_started
    _server_started = True


def _user_data_root():
    """The OS folder that holds per-user app data (the parent of our folder)."""
    if sys.platform == "win32":
        # Local, not Roaming: runtime and models are gigabytes and must not roam.
        return os.getenv("LOCALAPPDATA") or os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support")
    return os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")


def _legacy_app_running(legacy):
    """True when a 4.x copy still runs from the old folder (it may be recording)."""
    if sys.platform == "win32":
        return False  # os.kill would terminate it; a locked folder makes the rename fail instead
    try:
        with open(os.path.join(legacy, "instance.json"), encoding="utf-8") as f:
            pid = int(json.load(f)["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _tree_size(root):
    files = total = 0
    for folder, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                try:
                    size = os.path.getsize(path)
                except FileNotFoundError:       # gone while walking (SQLite's -wal / -shm come and go)
                    continue
                files += 1
                total += size
    return files, total


def _move_across_volumes(legacy, target):
    partial = target + ".partial"
    shutil.rmtree(partial, ignore_errors=True)
    shutil.copytree(legacy, partial, symlinks=True)
    if _tree_size(partial) != _tree_size(legacy):
        shutil.rmtree(partial, ignore_errors=True)
        raise OSError("copy of the data folder does not match the original")
    os.rename(partial, target)
    shutil.rmtree(legacy)


def move_tree(src, target):
    """Rename src to target; across volumes, copy, verify file count and bytes, then remove src."""
    try:
        os.rename(src, target)
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
        _move_across_volumes(src, target)


def migrate_legacy_data_dir(root=None):
    """Move the 4.x data folder to the new name, once, at process start.

    Returns the folder to use: the new one, or the old one when it cannot be moved
    right now (an old copy is running, or the move failed), so nothing is lost and
    the move is retried on the next start.
    """
    root = root or _user_data_root()
    target, legacy = os.path.join(root, APP_DIR_NAME), os.path.join(root, LEGACY_DIR_NAME)
    if os.path.exists(target) or not os.path.isdir(legacy):
        return target
    # A recording writes into this folder; moving it is only safe before our server runs.
    assert not _server_started, "data folder migration must run before the server starts"
    if _legacy_app_running(legacy):
        return legacy
    try:
        move_tree(legacy, target)
    except OSError:
        return legacy if os.path.isdir(legacy) and not os.path.exists(target) else target
    try:
        with open(os.path.join(target, MIGRATION_NOTE), "w", encoding="utf-8") as f:
            f.write(f"{legacy}\n{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}\n")
    except OSError:
        pass
    return target


def app_data_dir():
    """Per-user folder for recordings and app state (spec FR-PLAT-06 AC3).

    Override with DICTUM_DATA_DIR (the 4.x name is still read as a fallback; used by tests
    and portable installs). Without an override, the first call moves the 4.x
    data folder to Dictum (see migrate_legacy_data_dir).
    """
    global _migration_checked, _resolved
    override = _override()
    if override:
        base = override
    elif _migration_checked:
        base = _resolved
    else:
        base = migrate_legacy_data_dir()
        if base == default_data_dir():
            base = pointed_data_dir() or base   # the folder chosen in Settings → Хранилище
        _resolved = base
        _migration_checked = True
    os.makedirs(base, exist_ok=True)
    return base


def _override():
    return os.getenv("DICTUM_DATA_DIR") or os.getenv("WORKBENCH_DATA_DIR")


def default_data_dir():
    return os.path.join(_user_data_root(), APP_DIR_NAME)


def pointer_path():
    return os.path.join(default_data_dir(), POINTER_FILE)


def pointed_data_dir():
    """The folder named by the pointer file in the default location, when it exists; else None (the default is used:
    a folder on a drive that is not connected is not recreated empty somewhere else)."""
    try:
        with open(pointer_path(), encoding="utf-8") as f:
            path = json.load(f)["path"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return path if isinstance(path, str) and os.path.isabs(path) and os.path.isdir(path) else None


class DataDirError(ValueError):
    """A data-folder move that is refused; `code` says why: same, inside, not_empty, not_writable, override."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _writable(folder):
    probe = os.path.join(folder, WRITE_PROBE)
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def _only_pointer(folder):
    """The default folder after a move away: it holds nothing but the pointer file."""
    try:
        return os.path.realpath(folder) == os.path.realpath(default_data_dir()) and os.listdir(folder) == [POINTER_FILE]
    except OSError:
        return False


def check_move_target(current, target):
    """The absolute folder the data would move to, or DataDirError: the same folder, a folder inside the current one,
    a folder that is not empty (or is a file), or a place this user cannot write."""
    if not isinstance(target, str) or not target.strip():
        raise DataDirError("not_writable", "choose a folder")
    target = os.path.abspath(os.path.expanduser(target.strip()))
    real_cur, real_target = os.path.realpath(current), os.path.realpath(target)
    if real_target == real_cur:
        raise DataDirError("same", "this is already the data folder")
    if real_target.startswith(real_cur.rstrip(os.sep) + os.sep):
        raise DataDirError("inside", "the new folder is inside the current data folder")
    if os.path.lexists(target):
        if not os.path.isdir(target) or (os.listdir(target) and not _only_pointer(target)):
            raise DataDirError("not_empty", "the new folder is not empty")
        if not _writable(target):
            raise DataDirError("not_writable", "this folder cannot be written to")
        return target
    parent = os.path.dirname(target)
    if not os.path.isdir(parent) or not _writable(parent):
        raise DataDirError("not_writable", "this folder cannot be written to")
    return target


def move_data_dir(target, current=None):
    """Move the whole data folder to target (rename, or copy + verify + remove across volumes, as the 4.x migration
    does) and leave a pointer in the default location so the next start finds it. Returns the new folder. The caller
    makes sure nothing is recording; the running app keeps its open files and is restarted afterwards."""
    global _resolved, _migration_checked
    if _override():
        raise DataDirError("override", "the data folder is set by DICTUM_DATA_DIR")
    current = current or app_data_dir()
    target = check_move_target(current, target)
    default = default_data_dir()
    if os.path.isdir(target):
        if _only_pointer(target):
            os.remove(os.path.join(target, POINTER_FILE))
        os.rmdir(target)                  # empty: rename and copytree both want a free name
    move_tree(current, target)
    if os.path.realpath(target) == os.path.realpath(default):
        try:
            os.remove(pointer_path())
        except OSError:
            pass
    else:
        os.makedirs(default, exist_ok=True)
        tmp = pointer_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"path": target, "moved_from": current,
                       "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}, f, ensure_ascii=False)
        os.replace(tmp, pointer_path())
    _resolved, _migration_checked = target, True
    return target


def tree_bytes(root):
    """Bytes on disk under root (links not followed)."""
    return _tree_size(root)[1]


def recordings_dir():
    path = os.path.join(app_data_dir(), "recordings")
    os.makedirs(path, exist_ok=True)
    return path


def models_dir(kind):
    """Downloaded model weights live with the app's data, so uninstall can remove them.

    kind: "gigaam" (the speech models; the folder name is kept) or "huggingface".
    """
    path = os.path.join(app_data_dir(), "models", kind)
    os.makedirs(path, exist_ok=True)
    return path


def use_app_model_cache():
    """Point Hugging Face downloads (pyannote) at the app's model folder, unless the user chose one."""
    os.environ.setdefault("HF_HOME", models_dir("huggingface"))


def make_job_log():
    """A logger for long jobs: the full traceback of a failure goes to <app data>/logs/jobs.log,
    where the one line shown in the interface is not enough to see what went wrong."""
    import logging
    import logging.handlers
    log = logging.getLogger("workbench.jobs")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    try:
        folder = os.path.join(app_data_dir(), "logs")
        os.makedirs(folder, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(os.path.join(folder, "jobs.log"), maxBytes=2_000_000,
                                                       backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    except OSError:
        log.addHandler(logging.NullHandler())
    return log
