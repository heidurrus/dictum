import datetime
import errno
import json
import os
import shutil
import sys

APP_DIR_NAME = "Dictum"
LEGACY_DIR_NAME = "RequirementsWorkbench"   # up to 4.2.x; moved to APP_DIR_NAME on first start
MIGRATION_NOTE = "migrated-from.txt"

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
                files += 1
                total += os.path.getsize(path)
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
        try:
            os.rename(legacy, target)
        except OSError as e:
            if e.errno != errno.EXDEV:
                raise
            _move_across_volumes(legacy, target)
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

    Override with DICTUM_DATA_DIR (or the older WORKBENCH_DATA_DIR; used by tests
    and portable installs). Without an override, the first call moves a 4.x
    RequirementsWorkbench folder to Dictum (see migrate_legacy_data_dir).
    """
    global _migration_checked, _resolved
    override = os.getenv("DICTUM_DATA_DIR") or os.getenv("WORKBENCH_DATA_DIR")
    if override:
        base = override
    elif _migration_checked:
        base = _resolved
    else:
        base = _resolved = migrate_legacy_data_dir()
        _migration_checked = True
    os.makedirs(base, exist_ok=True)
    return base


def recordings_dir():
    path = os.path.join(app_data_dir(), "recordings")
    os.makedirs(path, exist_ok=True)
    return path


def models_dir(kind):
    """Downloaded model weights live with the app's data, so uninstall can remove them.

    kind: "gigaam" or "huggingface".
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
