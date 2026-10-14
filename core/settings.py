"""User settings: secrets in a per-user .env, preferences in settings.json.

Both live in the app data folder, never next to the app code: inside an
installed app that folder is the signed macOS bundle or Program Files, where
writing would break the signature or be lost on update (spec FR-SET-03,
NFR-SEC-01/02). A .env next to the code (how 1.0 and source checkouts stored
it) is still read, so existing tokens keep working.
"""
import json
import logging
import os
import sys

from dotenv import load_dotenv

from core.paths import app_data_dir

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEGACY_ENV_FILE = os.path.join(ROOT, ".env")

SECRET_KEYS = {"HF_TOKEN", "ANTHROPIC_API_KEY"}
DEFAULTS = {
    "llm_provider": "claude",          # "claude" | "local" (built-in) | "ollama"
    "claude_model": "claude-opus-5",
    "ollama_model": "qwen3:8b",
    "local_model": "",                 # built-in model id; empty = the downloaded one
    "live_transcription": True,        # transcript on the meeting page while recording (5.0 C4.1)
    "live_requirements": True,         # requirements extracted while recording (5.0 C4.2)
    "live_questions": False,           # the question card: answers from the materials to questions heard (5.0 C4.3)
    "live_window_atoms": 90,           # seconds between two live extraction passes
    "silence_stop_minutes": 10,        # stop the recording after this much silence; 0 = never (5.0 C4.3)
    "menubar": True,                   # the macOS menu-bar item (5.0 C7, core/hotkeys.py)
    "embed_model": "",                 # the index's embedding model id; empty = the downloaded one (5.0 C5)
    # Index thresholds (spec §9 A4): cosine for auto labels and graph edges, chunks retrieved per question.
    # Starting points, kept out of the UI; settings.json can override them.
    "tuning": {"label_assign": 0.45, "graph_edge": 0.30, "retrieve_k": 12},
    "hotkeys": {                       # action → key combo, read by the UI's one key handler
        "record": "cmd+r", "palette": "cmd+k", "theme": "cmd+shift+l", "ask": "cmd+j", "whisper": "alt+space",
        **{f"nav{i}": f"cmd+{i}" for i in range(1, 9)},
    },
}
CLAUDE_MODELS = [
    ("claude-opus-5", "Claude Opus 5 (best quality)"),
    ("claude-sonnet-5", "Claude Sonnet 5 (faster, cheaper)"),
    ("claude-haiku-4-5", "Claude Haiku 4.5 (fastest, cheapest)"),
]
PROVIDERS = {"claude", "local", "ollama"}
_save_hooks = []


def on_save(fn):
    """Call fn(settings) after every save (core/hotkeys.py re-registers the global hot keys)."""
    _save_hooks.append(fn)


def env_file():
    return os.path.join(app_data_dir(), ".env")


def settings_file():
    return os.path.join(app_data_dir(), "settings.json")


def load_env():
    """Legacy .env first, then the app-data one, which wins."""
    if os.path.exists(LEGACY_ENV_FILE):
        load_dotenv(LEGACY_ENV_FILE)
    if os.path.exists(env_file()):
        load_dotenv(env_file(), override=True)


def _write_private(path, text):
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def set_secret(key, value):
    """Write or remove one key in the app-data .env and update this process."""
    if key not in SECRET_KEYS:
        raise ValueError(f"unknown secret {key}")
    value = (value or "").strip()
    lines, found = [], False
    if os.path.exists(env_file()):
        with open(env_file(), encoding="utf-8") as f:
            for line in f:
                if line.startswith(f"{key}="):
                    found = True
                    if value:
                        lines.append(f"{key}={value}\n")
                else:
                    lines.append(line)
    if value and not found:
        lines.append(f"{key}={value}\n")
    _write_private(env_file(), "".join(lines))
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)


def secret(key):
    return os.getenv(key) or None


def load_settings():
    data = {**DEFAULTS, "hotkeys": dict(DEFAULTS["hotkeys"]), "tuning": dict(DEFAULTS["tuning"])}
    try:
        with open(settings_file(), encoding="utf-8") as f:
            stored = json.load(f)
        data.update({k: v for k, v in stored.items() if k in DEFAULTS and k not in ("hotkeys", "tuning")})
        if isinstance(stored.get("hotkeys"), dict):
            data["hotkeys"].update({k: v for k, v in stored["hotkeys"].items() if k in DEFAULTS["hotkeys"]})
        if isinstance(stored.get("tuning"), dict):
            data["tuning"].update({k: v for k, v in stored["tuning"].items() if k in DEFAULTS["tuning"]
                                   and isinstance(v, (int, float)) and not isinstance(v, bool)})
    except (OSError, ValueError):
        pass
    return data


def _hotkeys(current, value):
    """Merge a partial {action: combo} map; unknown actions and non-text combos are refused."""
    if not isinstance(value, dict):
        raise ValueError("hotkeys must be an object")
    unknown = sorted(set(value) - set(DEFAULTS["hotkeys"]))
    if unknown:
        raise ValueError(f"unknown hotkey {unknown[0]}")
    for action, combo in value.items():
        if not isinstance(combo, str):
            raise ValueError(f"hotkey {action} must be text")
    return {**current, **{a: c.strip().lower() for a, c in value.items()}}


def save_settings(updates):
    """Validate and persist preference changes; returns the full settings."""
    data = load_settings()
    for key, value in updates.items():
        if key not in DEFAULTS:
            raise ValueError(f"unknown setting {key}")
        if key == "hotkeys":
            data[key] = _hotkeys(data[key], value)
            continue
        if key == "tuning":
            if not isinstance(value, dict) or set(value) - set(DEFAULTS["tuning"]):
                raise ValueError(f"tuning takes {sorted(DEFAULTS['tuning'])}")
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values()):
                raise ValueError("tuning values must be numbers")
            data[key] = {**data[key], **value}
            continue
        if key in ("live_transcription", "live_requirements", "live_questions", "menubar"):
            data[key] = value is True or str(value).strip().lower() in ("true", "1", "yes", "on")
            continue
        if key in ("live_window_atoms", "silence_stop_minutes"):
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a whole number") from None
            low, high = (30, 3600) if key == "live_window_atoms" else (0, 240)
            if not low <= number <= high:
                raise ValueError(f"{key} must be between {low} and {high}")
            data[key] = number
            continue
        value = str(value).strip()
        if key == "llm_provider" and value not in PROVIDERS:
            raise ValueError(f"llm_provider must be one of {sorted(PROVIDERS)}")
        if key == "claude_model" and value not in dict(CLAUDE_MODELS):
            raise ValueError(f"unsupported Claude model {value}")
        if key == "local_model" and value:
            from core.local_llm import MODELS_BY_ID
            if value not in MODELS_BY_ID:
                raise ValueError(f"unknown local model {value}")
        if key == "embed_model" and value:
            from core.local_llm import EMBED_MODELS_BY_ID
            if value not in EMBED_MODELS_BY_ID:
                raise ValueError(f"unknown index model {value}")
        if key == "ollama_model" and not value:
            raise ValueError("ollama_model must not be empty")
        data[key] = value
    tmp = settings_file() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, settings_file())
    for hook in list(_save_hooks):
        try:
            hook(data)
        except Exception:      # a hook (the menu bar) must never make a save fail
            logging.getLogger("dictum.settings").exception("Settings hook failed")
    return data
