import os
import sys

APP_DIR_NAME = "RequirementsWorkbench"


def app_data_dir():
    """Per-user folder for recordings and app state (spec FR-PLAT-06 AC3).

    Override with WORKBENCH_DATA_DIR (used by tests and portable installs).
    """
    override = os.getenv("WORKBENCH_DATA_DIR")
    if override:
        base = override
    elif sys.platform == "win32":
        base = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), APP_DIR_NAME)
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~/Library/Application Support"), APP_DIR_NAME)
    else:
        base = os.path.join(os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), APP_DIR_NAME)
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
