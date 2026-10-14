"""Run the app with a deterministic stand-in for the AI model (for e2e/atoms.mjs).

Usage: WORKBENCH_DATA_DIR=<tmp> .venv/bin/python frontend/e2e/fake_llm_server.py [port]
Extraction turns every transcript line into an atom quoting that line; the
duplicate check reports the first two new atoms as conflicting. torch and GigaAM
are stubbed (tests/conftest.py); speech recognition returns one fixed line after ~3 s.
"""
import functools
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

_data_dir = os.environ.get("WORKBENCH_DATA_DIR")
import tests.conftest  # noqa: E402,F401  stubs torch and gigaam (it also points the data dir at a temp folder)
if _data_dir:
    os.environ["WORKBENCH_DATA_DIR"] = _data_dir                  # keep the folder the caller chose

import app as app_module  # noqa: E402
from core import atoms  # noqa: E402
from core import usage as usage_mod  # noqa: E402


def fake_complete(system, user, schema, prefs, api_key, ollama_url):
    props = schema["properties"]
    reqs = re.findall(r"^((?:FR|NFR|Q)-\d+) \[\w+\] (.+?)(?:  \(conflicts.*)?$", user, flags=re.M)
    if "epics" in props:                                         # backlog: decomposition
        frs = re.findall(r"^(FR-\d+) \(section [\d.]+\): (.+)$", user, flags=re.M)
        nfrs = re.findall(r"^(NFR-\d+) \(section", user, flags=re.M)
        return {"epics": [{"title": "Работа оператора", "goal": "Быстрее обслуживать звонки", "stories": [
            {"title": t[:60], "story": f"Как оператор, я хочу {t.lower()}, чтобы работать быстрее", "refs": [r],
             "acceptance": [{"given": "звонок поступил", "when": "оператор открывает карточку", "then": "данные видны"},
                            {"given": "номер неизвестен", "when": "звонок поступил", "then": "открыт поиск"}],
             "subtasks": ["API", "Интерфейс"]} for r, t in frs]}],
            "nfr_links": [{"id": n, "stories_for": [frs[0][0]] if frs else []} for n in nfrs]}
    if "findings" in props:                                      # backlog: INVEST
        return {"findings": [{"id": "S1", "letter": "S", "reason": "История слишком большая для спринта.",
                              "fix": "Разделить на просмотр карточки и поиск по номеру."}]}
    if "groups" in props:                                        # FRD: full build
        return {"purpose": "Документ описывает требования к карточке клиента.", "context": "Операторы колл-центра.",
                "assumptions": [], "out_of_scope": [],
                "groups": [{"title": "Карточка клиента", "ids": [r for r, _ in reqs if r.startswith("FR-")]}],
                "items": [{"id": r, "text": "Требование: " + t} for r, t in reqs], "issues": []}
    if "items" in props:                                         # FRD: rebuild of changed atoms
        return {"items": [{"id": r, "text": "Требование: " + t, "group": "Карточка клиента"} for r, t in reqs],
                "issues": []}
    if "statement" in props:                                     # FRD: quality fix
        return {"statement": "Карточка открывается не дольше [уточнить: N секунд]"}
    if "duplicates" in props:
        new = re.findall(r"^(N\d+) ", user, flags=re.M)
        return {"duplicates": [], "conflicts": [{"a": new[0], "b": new[1], "description": "Разные требования к сроку"}]
                if len(new) > 1 else []}
    found = []
    for idx, text in re.findall(r"^\[S(\d+)\] (?:\[[^\]]*\] )?(.+)$", user, flags=re.M):
        kind = "nfr" if "секунд" in text else "question" if "?" in text else "functional"
        found.append({"type": kind, "statement": "Система: " + text, "evidence": [{"segment": int(idx), "quote": text}]})
    return {"atoms": found}


app_module.extract_atoms = functools.partial(atoms.extract_atoms, complete=fake_complete)
atoms.extract_candidates = functools.partial(atoms.extract_candidates, complete=fake_complete)
app_module.frd.build = functools.partial(app_module.frd.build, complete=fake_complete)
app_module.backlog.build = functools.partial(app_module.backlog.build, complete=fake_complete)
app_module.backlog.invest = functools.partial(app_module.backlog.invest, complete=fake_complete)
app_module.frd.suggest_fix = functools.partial(app_module.frd.suggest_fix, complete=fake_complete)
app_module.settings.secret = lambda name: "fake-key"

# Recaps (5.0 C3): the style comes from its skill, the reply says how many transcript lines it was sent;
# every prompt is kept so a suite can check that an update sent only the new lines (GET /__fake/recaps).
RECAPS = []


def fake_recap_generate(prefs, api_key):
    def generate(system, user, on_delta):
        style = ("actions" if "list the outcomes" in system else "bullets" if "point-by-point" in system else "brief")
        incremental = "updating an existing recap" in system
        lines = len(re.findall(r"^(?:\[[^\]]*\] )?\[\d{1,2}:\d{2}", user, flags=re.M))
        RECAPS.append({"style": style, "incremental": incremental, "length": len(user), "lines": lines})
        text = f"## {style}\n- recap {style}: {lines} lines" + (" (updated)" if incremental else "")
        on_delta(text)
        # Counted like a real call (Settings → stats, e2e/settings.mjs): about four characters a token.
        usage_mod.record("llm_local" if prefs and prefs.get("llm_provider") != "claude" else "llm_cloud",
                         len(system + user) // 4, len(text) // 4)
        return text
    return generate


app_module._recap_generate = fake_recap_generate
app_module.app.add_url_rule("/__fake/recaps", "fake_recaps", lambda: app_module.jsonify(RECAPS))

# Спросить (5.0 C6, e2e/ask.mjs): a scripted answer citing two sources (a material first when there is one), streamed
# in pieces; a question with "сделай вопрос" / "make a question" also gets the create_question intent. The question
# card's short mode (e2e/session.mjs) answers in one sentence with one marker.
ASK_SHORT = {"ru": "Статус утверждает руководитель отдела или его заместитель",
             "en": "The head of the department or their deputy approves the status"}


def fake_ask_generate(prefs, api_key):
    def generate(system, user, on_delta):
        ru = "[Источник " in user
        word, lang = ("Источник", "ru") if ru else ("Source", "en")
        listed = re.findall(r"^\[(?:Источник|Source) (\d+)\] \((material|meeting|requirement) ", user, flags=re.M)
        mats = [n for n, kind in listed if kind == "material"]
        if "at most two sentences" in system:
            text = f"{ASK_SHORT[lang]} [{word} {(mats or [listed[0][0]])[0]}]."
        else:
            a = (mats or [listed[0][0]])[0]
            b = next((n for n, _kind in listed if n != a), a)
            text = (f"Ответ дилеру даётся не позднее двух часов [{word} {a}]. Это же прозвучало на встрече [{word} {b}]."
                    if ru else f"The dealer gets a reply within two hours [{word} {a}]. The meeting said the same [{word} {b}].")
            question = re.search(r"^Question: (.+)$", user, flags=re.M).group(1)
            if re.search(r"сделай вопрос|make a question", question, flags=re.I):
                statement = ("Какой срок ответа дилеру считать целевым?" if ru
                             else "Which reply time to the dealer is the target?")
                text += "\n<intent>" + json.dumps({"create_question": {"statement": statement,
                                                                      "source_ns": [int(a), int(b)]}},
                                                  ensure_ascii=False) + "</intent>"
        for i in range(0, len(text), 24):
            on_delta(text[i:i + 24])
            time.sleep(0.05)
        return text
    return generate


app_module._ask_generate = fake_ask_generate


def fake_transcribe(job_id, audio_path, model_name, diarize, word_timestamps, device):
    for pct in (20, 40, 60, 80):
        app_module.set_progress(job_id, pct, "Transcribing…")
        time.sleep(0.75)
    return {"text": "[00:00.00 - 00:03.00] Нужна выгрузка отчёта в Excel",
            "segments": [{"start": 0.0, "end": 3.0, "text": "Нужна выгрузка отчёта в Excel"}]}


app_module._transcribe = fake_transcribe

# The local index (5.0 C5): embeddings are a hashed bag of words (tests/fake_embed.py), so texts that share words are
# close; the index counts as available and its passes run as real jobs.
from core import index as local_index  # noqa: E402
from tests import fake_embed  # noqa: E402

fake_embed.install(None, local_index)

# Jira: a fake Atlassian sign-in and an in-memory Jira project "SBX". Nothing real is ever contacted.
from core.fake_jira import FakeJira  # noqa: E402

FAKE_JIRA = FakeJira(project_key="SBX", site="https://sandbox.atlassian.net")


class FakeAuth:
    def __init__(self):
        self.ok = False

    def connected(self):
        return self.ok

    def start(self, redirect_uri):
        return redirect_uri + "?state=s&code=c"

    def finish(self, state, code):
        self.ok = True

    def disconnect(self):
        self.ok = False

    def access_token(self, force_refresh=False):
        return "fake"


if os.getenv("REAL_JIRA"):
    # Live check against the user's sandbox: real sign-in and real Jira, but every write is
    # refused unless it targets the one allowed project, and every call is logged.
    ALLOWED = os.environ["REAL_JIRA"]                       # e.g. "SCRUM"
    LOG = os.getenv("JIRA_LOG", "/tmp/jira-live.log")
    real_session = app_module._jira_session

    class Guarded:
        def __init__(self, inner):
            self.inner = inner

        def call(self, tool, **args):
            if tool in ("createJiraIssue", "editJiraIssue", "createIssueLink", "addCommentToJiraIssue",
                        "transitionJiraIssue"):
                key = args.get("projectKey") or str(args.get("issueIdOrKey") or args.get("inwardIssue") or "").split("-")[0]
                if key != ALLOWED:
                    raise RuntimeError(f"blocked: writes are only allowed to {ALLOWED}, not {key!r}")
            out = self.inner.call(tool, **args)
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"tool": tool, "args": {k: v for k, v in args.items() if k != "description"},
                                    "result": out}, ensure_ascii=False, default=str)[:4000] + "\n")
            return out
    app_module._jira_session = lambda: Guarded(real_session())
else:
    app_module.jira_auth = FakeAuth()
    import core.private_browser
    core.private_browser.open_private = lambda url, **k: None       # tests open the sign-in in the test browser
    app_module._jira_session = lambda: FAKE_JIRA

# Live session (5.0 C4.1, e2e/session.mjs): FAKE_RECORDER=1 makes this a desktop window with a fake microphone and
# system audio (a steady tone, written by the real recorder into the meeting's folder) and a fake live pass that
# appends four scripted provisional lines 1 s apart (the last one is a question: with `live_questions` on, the
# question card checks every second and gets the scripted short answer). Stop runs the real stop route; the final transcription is
# fake_transcribe above, once per channel, and replaces the provisional lines. Requirements on the fly (C4.2) run
# for real every second once the three lines are in; the fake model finds one requirement in them.
LIVE_SCRIPT = [("BA", "Давайте начнём с заявок дилеров"), ("OTHER", "Заявки дублируются почти каждый день"),
               ("BA", "Проверяем дубли по VIN и телефону"),
               ("OTHER", "А кто утверждает изменение статуса заявки дилера?")]   # the question card (C4.3)


def _tone(value):
    def source(stop):
        import numpy as np
        chunk = 1600                                  # 0.1 s at 16 kHz, delivered in real time
        while not stop.is_set():
            yield np.full(chunk, value, dtype=np.int16)
            time.sleep(chunk / 16000)
    return source


class FakeLive:
    def __init__(self, source_id):
        self.source_id, self.state, self._stop = source_id, "on", threading.Event()
        self._lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        for i, (speaker, text) in enumerate(LIVE_SCRIPT):
            if self._stop.wait(1.0):
                return
            with self._lock:
                if self._stop.is_set():
                    return
                app_module.library.append_provisional_segments(self.source_id, [
                    {"speaker": speaker, "start": 2.0 * i, "end": 2.0 * i + 1.5, "text": text}])

    def turn_off(self, reason):
        self.state = "off"

    def stop(self, join_timeout=2.0):
        with self._lock:
            self._stop.set()


LIVE_REQUIREMENT = "Проверять дубли заявок по VIN и телефону"


def fake_live_complete(system, user, schema, prefs, api_key, ollama_url):
    if "duplicates" in schema["properties"]:
        return {"duplicates": [], "conflicts": []}
    found = re.search(r"^\[S(\d+)\] (?:\[[^\]]*\] )?(.*VIN.*)$", user, flags=re.M)
    return {"atoms": [{"type": "functional", "statement": LIVE_REQUIREMENT,
                       "evidence": [{"segment": int(found.group(1)), "quote": "дубли по VIN и телефону"}]}] if found else []}


if os.getenv("FAKE_RECORDER"):
    app_module.IS_DESKTOP = True
    app_module._start_live_atoms = functools.partial(app_module._start_live_atoms, window=1.0, min_segments=3,
                                                     complete=fake_live_complete)
    app_module.microphone_access = lambda: (True, None)
    app_module._mic_source = lambda idx: _tone(1000)
    app_module._system_source = lambda: _tone(2000)
    app_module._start_live = lambda source, folder, opts, recorder: FakeLive(source["id"])
    app_module._start_live_questions = functools.partial(app_module._start_live_questions, window=1.0,
                                                         generate=fake_ask_generate(None, None))
    app_module.app.view_functions["audio_devices"] = lambda: app_module.jsonify([{"index": 0, "name": "Fake microphone"}])

# Шепнуть (5.0 C7, e2e/whisper.mjs): with FAKE_RECORDER=1 the whisper capture records the fake microphone through the
# real recorder into <data>/whispers/<id>/mic.wav, the live words are scripted (one word every 150 ms) and the capture
# stops by itself after the script, as after two seconds of silence; the final pass returns the scripted sentence and
# the parse finds one reminder for tomorrow 10:00 and one task.
WHISPER_SAID = {
    "ru": "Напомни завтра в десять позвонить Ирине насчёт истории заявки и ещё надо отправить Олегу регламент",
    "en": "Remind me tomorrow at ten to call Irina about the request history and also send Oleg the policy",
}
WHISPER_ITEMS = {
    "ru": [("remind", "Позвонить Ирине насчёт истории заявки", "завтра в десять позвонить Ирине насчёт истории заявки"),
           ("task", "Отправить Олегу регламент", "отправить Олегу регламент")],
    "en": [("remind", "Call Irina about the request history", "tomorrow at ten call Irina about the request history"),
           ("task", "Send Oleg the policy", "send Oleg the policy")],
}
NOTIFIED = []


class FakeWhisperWords:
    def __init__(self, capture, words):
        self.capture, self._stop = capture, threading.Event()
        threading.Thread(target=self._run, args=(words,), daemon=True).start()

    def _run(self, words):
        for w in words:
            if self._stop.wait(0.15):
                return
            self.capture.words.append_provisional_segments(self.capture.id, [{"text": w}])
        if not self._stop.wait(0.6):
            self.capture._auto("silence")

    def stop(self, join_timeout=2.0):
        self._stop.set()


def fake_whisper_capture(mic, opts):
    from core import whisper as whisper_mod

    class Capture(whisper_mod.Capture):
        def start(self):
            super().start()
            self.live = FakeWhisperWords(self, WHISPER_SAID[app_module._whisper.get("lang") or "ru"].split())
            return self
    return Capture(mic)


def fake_whisper_complete(prefs, api_key):
    def complete(system, user, schema):
        lang = "ru" if "interface language: Russian" in user else "en"
        now = re.search(r"^now: (\d{4}-\d{2}-\d{2})", user, flags=re.M).group(1)
        import datetime
        tomorrow = (datetime.date.fromisoformat(now) + datetime.timedelta(days=1)).isoformat()
        return {"items": [{"kind": kind, "title": title, "text": text,
                           "due": f"{tomorrow}T10:00" if kind == "remind" else None, "project_hint": None}
                          for kind, title, text in WHISPER_ITEMS[lang]]}
    return complete


app_module._whisper_complete = fake_whisper_complete
app_module.notify = lambda title, text: NOTIFIED.append({"title": title, "text": text}) or True
app_module.app.add_url_rule("/__fake/notified", "fake_notified", lambda: app_module.jsonify(NOTIFIED))
if os.getenv("FAKE_RECORDER"):
    app_module._new_whisper_capture = fake_whisper_capture
    app_module._whisper_final_text = lambda path, opts: WHISPER_SAID[app_module._whisper.get("lang") or "ru"]

# Pretend to be another machine for screenshots: FAKE_GPU="none" or a size in GB.
if os.getenv("FAKE_GPU"):
    fake = {} if os.environ["FAKE_GPU"] == "none" else {"name": "NVIDIA GeForce RTX 2060", "backend": "Vulkan0",
                                                        "memory": int(float(os.environ["FAKE_GPU"]) * 1024 ** 3)}
    app_module.local_llm.gpu_info = lambda refresh=False: fake

# First run (5.0 C8, e2e/onboarding.mjs). Every suite starts from a fresh data dir, so the onboarding is marked done
# before serving, except with ONBOARDING=1. Permissions read "undetermined" until requested, then "granted"; nothing
# opens System Settings. A model download completes in 2 s and nothing is fetched. Discovery looks only in a temp folder:
# empty, or with ONBOARDING=1 two files (a call recording and a document), shown at /__fake/discover-root.
import tempfile  # noqa: E402

from core import permissions as permissions_mod  # noqa: E402
from core.setup_plan import StateFile  # noqa: E402

FAKE_PERMS = {w: "undetermined" for w in permissions_mod.WHICH}
permissions_mod.read = lambda state, **k: dict(FAKE_PERMS)
permissions_mod.request = lambda which, state, *a, **k: FAKE_PERMS.__setitem__(which, "granted")
app_module.app.view_functions["api_permissions_open_settings"] = lambda which: app_module.jsonify({"ok": True})


class FakeDownload:
    """The shape of asr_models.Downloader / local_llm.Installer status, finishing 2 s after start."""

    def __init__(self, idle=None):
        self.state, self._idle = None, idle

    def status(self):
        return dict(self.state) if self.state else (dict(self._idle) if self._idle else None)

    def busy(self):
        return bool(self.state and self.state["status"] in ("downloading", "verifying"))

    def start(self, model_id):
        total = 100 * 1024 ** 2
        self.state = {"model": model_id, "status": "downloading", "done": 0, "total": total, "error": None}

        def run():
            for i in range(1, 11):
                time.sleep(0.2)
                self.state = {**self.state, "done": total * i // 10, "status": "done" if i == 10 else "downloading"}
        threading.Thread(target=run, daemon=True).start()
        return self.status()

    def cancel(self):
        if self.busy():
            self.state = {**self.state, "status": "cancelled"}


app_module.asr_downloads = FakeDownload()
app_module.local_llm.installer = FakeDownload(idle={"status": "idle"})

DISCOVER_ROOT = tempfile.mkdtemp(prefix="dictum-discover-")
os.environ["DICTUM_DISCOVER_ROOTS"] = DISCOVER_ROOT
if os.getenv("ONBOARDING"):
    import wave
    with wave.open(os.path.join(DISCOVER_ROOT, "Звонок с дилером.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000)
    with open(os.path.join(DISCOVER_ROOT, "Регламент обработки заявок.md"), "w", encoding="utf-8") as f:
        f.write("# Регламент обработки заявок\n\nОтвет дилеру даётся не позднее двух часов.\n")
else:
    StateFile().set("onboarding:v5", True)
app_module.app.add_url_rule("/__fake/discover-root", "fake_discover_root", lambda: app_module.jsonify({"root": DISCOVER_ROOT}))


def fake_reset_onboarding():
    """The next language's run of onboarding.mjs starts over: a fresh install's state and permissions."""
    FAKE_PERMS.update({w: "undetermined" for w in permissions_mod.WHICH})
    state = StateFile()
    state.set("onboarding:v5", False)
    state.set("onboarding:v5:step", 1)
    return app_module.jsonify({"ok": True})


app_module.app.add_url_rule("/__fake/reset-onboarding", "fake_reset_onboarding", fake_reset_onboarding, methods=["POST"])

if __name__ == "__main__":
    app_module.start_background()               # the reminder check, as the launcher starts it
    app_module.app.run(host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 5098, threaded=True)
