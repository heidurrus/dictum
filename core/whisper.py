"""Шепнуть (spec 5.0 C7): press, speak, and what was said becomes a task, note, reminder or idea in a personal inbox.

The inbox is not part of any project: whispers live in their own table (core/store.py `whispers`), are listed whatever
project is current, and never reach a project's requirements, documents, backlog, Jira, search or export, unless one
is turned into a client question on demand (`to_question`).

AUDIO SAFETY: a whisper's microphone audio is written once, by the meeting recorder (core.recorder), into
<data>/whispers/<capture id>/mic.wav. The live words and the silence auto-stop come from the same read-only tails a
meeting uses (core.live.LiveTranscriber with a 2 s window, core.live.SilenceWatch with a 2 s threshold); nothing here
opens that file for writing, moves or deletes it, and deleting a whisper (soft) keeps it.

Dates: the model is told `now` (with the timezone and the weekday) and the rules for relative dates, and returns a
local ISO-8601 time. The same rules are also applied here, on the item's words (`resolve_due`), and they win when they
find a date: date arithmetic is deterministic code's job, and a small local model gets "next Monday" wrong often enough.
"""
import datetime as dt
import logging
import os
import re
import threading
import time
import uuid

from core import live as live_mod, skills
from core.paths import app_data_dir
from core.recorder import DualChannelRecorder, wav_duration

STAGE = "whisper"
KINDS = ("task", "note", "remind", "idea")
LIVE_WINDOW = 2                 # seconds: words appear as they are spoken
SILENCE_SECONDS = 2.0           # stop by itself after this much silence, once speech was heard
MAX_SECONDS = 90                # and after this long in any case
SILENCE_TICK = 0.25
NO_SYS = "a whisper records the microphone only"

log = logging.getLogger("dictum.whisper")


def whispers_dir():
    path = os.path.join(app_data_dir(), "whispers")
    os.makedirs(path, exist_ok=True)
    return path


# ── capture ──────────────────────────────────────────────────────────────────
class _Words:
    """The live transcriber's store for a whisper: it only collects the provisional lines, in order."""

    def __init__(self):
        self._lock = threading.Lock()
        self.lines = []

    def append_provisional_segments(self, source_id, segments):
        with self._lock:
            self.lines.extend((s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip())
        return segments

    @property
    def text(self):
        with self._lock:
            return " ".join(self.lines)


class SpeechThenSilence(live_mod.SilenceWatch):
    """The meeting's silence watch (same read-only tail, same -50 dBFS speech floor), counting silence only once
    speech was heard: a whisper waits for the first word however long the BA takes to start."""

    def silent_seconds(self):
        if self.last_speech <= 0:
            return 0.0
        return super().silent_seconds()


class Capture:
    """One whisper being recorded: the recorder with the microphone source only (one channel), the live words, and the
    three ways it stops (the button, 2 s of silence after speech, 90 s). `mic` is a recorder source (or a string saying
    why there is none); `live_asr` an object with transcribe(chunks), or a factory returning one, or None."""

    def __init__(self, mic, live_asr=None, root=None, window=LIVE_WINDOW, silence_seconds=SILENCE_SECONDS,
                 max_seconds=MAX_SECONDS, tick=SILENCE_TICK, clock=time.monotonic):
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        self.root = root or whispers_dir()
        self.folder = os.path.join(self.root, self.id)
        self.recorder = DualChannelRecorder(self.root, {"mic": mic, "sys": NO_SYS})
        self.words = _Words()
        self._live_asr = live_asr
        self.window, self.silence_seconds, self.max_seconds, self.tick = window, silence_seconds, max_seconds, tick
        self._clock = clock
        self._lock = threading.Lock()
        self.live = self.silence = self._timer = None
        self.started = None
        self.stopped_by = None          # button | silence | limit
        self.result = None              # what stop() returned
        self.finished = None            # the stop route's answer, once computed (so a second call returns the same)

    @property
    def recording(self):
        return self.recorder.recording

    @property
    def audio_file(self):
        """The mic file relative to the whispers folder, as stored in whispers.audio_file."""
        return f"{self.id}/mic.wav"

    def start(self):
        self.recorder.start(folder=self.folder)
        self.started = self._clock()
        if self._live_asr is not None:
            try:
                self.live = live_mod.LiveTranscriber(self.id, self.folder, self._live_asr, window=self.window,
                                                     store=self.words, pauses=self.recorder.pauses).start()
            except Exception:           # the words are a convenience: the capture runs without them
                log.exception("Live words could not start for whisper %s", self.id)
        try:
            self.silence = SpeechThenSilence(self.folder, self.silence_seconds / 60.0, lambda _m: self._auto("silence"),
                                             pauses=self.recorder.pauses, tick=self.tick).start()
        except Exception:
            log.exception("Silence watch could not start for whisper %s", self.id)
        self._timer = threading.Timer(self.max_seconds, lambda: self._auto("limit"))
        self._timer.daemon = True
        self._timer.start()
        return self

    def _auto(self, reason):
        try:
            self.stop(reason)
        except Exception:
            log.exception("Whisper %s could not stop itself (%s)", self.id, reason)

    def stop(self, reason="button"):
        """Stop capture (idempotent): {mic: path or None, errors, folder}. The live words stay readable."""
        with self._lock:
            if self.result is not None:
                return self.result
            self.stopped_by = reason          # before the recorder says it stopped: a poll then sees why
            try:
                result = self.recorder.stop()
            except RuntimeError:              # the recorder never started
                result = {"mic": None, "sys": None, "errors": {}, "folder": self.folder}
            self.result = result
        for helper in (self.live, self.silence):
            if helper is not None:
                helper.stop()
        if self._timer is not None:
            self._timer.cancel()
        return result

    def elapsed(self):
        if self.started is None:
            return 0.0
        return round(self._clock() - self.started, 1)

    def duration(self):
        mic = (self.result or {}).get("mic")
        try:
            return round(wav_duration(mic), 1) if mic and os.path.exists(mic) else 0.0
        except Exception:
            return 0.0

    def status(self):
        st = self.recorder.status()
        return {"recording": st["recording"], "text": self.words.text,
                "elapsed": st["elapsed"] if st["recording"] else self.duration(), "stopped_by": self.stopped_by,
                "id": self.id, "error": (st["channels"].get("mic") or {}).get("error")}


# ── relative dates ───────────────────────────────────────────────────────────
RU_NUM = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7,
          "восемь": 8, "девять": 9, "десять": 10, "одиннадцать": 11, "двенадцать": 12, "пятнадцать": 15,
          "двадцать": 20, "тридцать": 30, "сорок": 40}
EN_NUM = {"one": 1, "an": 1, "a": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40}
RU_WEEKDAYS = (("понедельник", 0), ("вторник", 1), ("сред", 2), ("четверг", 3), ("пятниц", 4), ("суббот", 5),
               ("воскресень", 6))
EN_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_HOUR = 9                # a day without a time: 09:00
EVENING_HOUR = 18               # "до вечера", "tonight", a bare "сегодня": 18:00

_NUM = "|".join(sorted({*RU_NUM, *EN_NUM} - {"a", "an"}, key=len, reverse=True))
_RE_IN = re.compile(r"\bчерез\s+(?:(\d+|" + _NUM + r")\s+)?(полчаса|минут\w*|мин\b|час\w*)"
                    r"|\bin\s+(?:(\d+|" + _NUM + r"|an|a|half an?)\s+)?(minutes?|mins?\b|hours?|half an hour)")
_RE_CLOCK = re.compile(r"\b(\d{1,2})[:.](\d{2})\b")
_RE_HOUR = re.compile(r"\b(?:в|к|до|at|by|around)\s+(\d{1,2}|" + _NUM + r")(?!\s*(?:минут|мин|час\w*\s+назад|minutes?|hours?))\b"
                      r"(?:\s*(?:час\w*|o'?clock))?(?:\s*(утра|дня|вечера|ночи|am|pm|a\.m\.|p\.m\.))?")
_RE_AMPM = re.compile(r"\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)")
_RE_RU_WEEKDAY = re.compile(r"\b(?:в|во|к|до|на)\s+(понедельник\w*|вторник\w*|сред[уаеы]\b|четверг\w*|пятниц\w*|суббот\w*"
                            r"|воскресень\w*)")
_RE_EN_WEEKDAY = re.compile(r"\b(" + "|".join(EN_WEEKDAYS) + r")\b")
_EVENING = re.compile(r"до вечера|вечером|к вечеру|сегодня вечером|до конца дня|к концу дня|tonight|this evening"
                      r"|by the evening|in the evening|by (?:the )?end of (?:the )?day|by eod")
_MORNING = re.compile(r"\bутром\b|\bс утра\b|in the morning")
_NOON = re.compile(r"\bв полдень\b|\bat noon\b|\bby noon\b")


def _num(word):
    word = (word or "").strip()
    if word.isdigit():
        return int(word)
    return RU_NUM.get(word) or EN_NUM.get(word)


def _localize(naive, now):
    """A wall-clock time as an aware datetime: in now's timezone, or the system's (DST-correct) when now is naive."""
    return naive.astimezone() if now.tzinfo is None else naive.replace(tzinfo=now.tzinfo)


def _hour(h, mark):
    mark = (mark or "").replace(".", "")
    if mark in ("дня", "вечера", "pm") and h < 12:
        return h + 12
    if mark in ("ночи", "am") and h == 12:
        return 0
    if not mark and 1 <= h <= 7:     # "в два", "at 3": working hours, the afternoon
        return h + 12
    return h


def resolve_due(text, now):
    """The time a phrase like "завтра в десять", "до вечера", "в понедельник", "через час" (or the English ones) points
    at, as an aware datetime; None when the words name no time. `now`: a datetime (naive = the system's local time)."""
    t = (text or "").casefold().replace("ё", "е")
    if not t.strip():
        return None
    naive_now = now.replace(tzinfo=None)
    m = _RE_IN.search(t)
    if m:
        count_word, unit = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
        if unit in ("полчаса", "half an hour") or (count_word or "").startswith("half"):
            delta = dt.timedelta(minutes=30)
        else:
            n = _num(count_word) if count_word else 1
            if n:
                delta = dt.timedelta(minutes=n) if unit.startswith("мин") or unit.startswith("min") else dt.timedelta(hours=n)
            else:
                delta = None
        if delta is not None:
            return _localize((naive_now + delta).replace(second=0, microsecond=0), now)

    day, evening_word = None, False
    if "послезавтра" in t or "day after tomorrow" in t:
        day = 2
    elif "завтра" in t or "tomorrow" in t:
        day = 1
    elif "сегодня" in t or "today" in t or "tonight" in t:
        day = 0
    else:
        wd = None
        m = _RE_RU_WEEKDAY.search(t)
        if m:
            wd = next(n for stem, n in RU_WEEKDAYS if m.group(1).startswith(stem))
        else:
            m = _RE_EN_WEEKDAY.search(t)
            if m:
                wd = EN_WEEKDAYS.index(m.group(1))
        if wd is not None:
            day = (wd - naive_now.weekday() - 1) % 7 + 1          # the next one, never today
    if _EVENING.search(t):
        evening_word = True
        if day is None:
            day = 0

    hour = minute = None
    m = _RE_CLOCK.search(t)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        hour, minute = int(m.group(1)), int(m.group(2))
        mark = re.match(r"\s*(утра|дня|вечера|ночи|am|pm)", t[m.end():])
        if mark:
            hour = _hour(hour, mark.group(1))
    else:
        m = _RE_AMPM.search(t)
        if m and 1 <= int(m.group(1)) <= 12:
            hour, minute = _hour(int(m.group(1)), m.group(2)), 0
        else:
            for m in _RE_HOUR.finditer(t):
                h = _num(m.group(1))
                if h is not None and 0 <= h <= 23:
                    hour, minute = _hour(h, m.group(2)), 0
                    break
    if hour is None and _NOON.search(t):
        hour, minute = 12, 0
    if hour is None and _MORNING.search(t):
        hour, minute = DEFAULT_HOUR, 0
    if hour is None and evening_word:
        hour, minute = EVENING_HOUR, 0

    if day is None and hour is None:
        return None
    if day is None:                                           # a time alone: the next time it comes
        at = naive_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= naive_now:
            at += dt.timedelta(days=1)
        return _localize(at, now)
    if hour is None:
        hour, minute = (EVENING_HOUR, 0) if day == 0 else (DEFAULT_HOUR, 0)
    date = naive_now.date() + dt.timedelta(days=day)
    return _localize(dt.datetime.combine(date, dt.time(hour, minute)), now)


def parse_iso(value, now):
    """The model's `due` (ISO-8601, local unless it carries an offset) → aware datetime, or None if unreadable."""
    if not value or not isinstance(value, str):
        return None
    try:
        d = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None else _localize(d, now)


# ── project matching ─────────────────────────────────────────────────────────
_WORD = re.compile(r"[\wё-]+", re.I)


def _stem(word):
    word = word.casefold().replace("ё", "е")
    return word if len(word) <= 4 else word[:max(4, len(word) - 2)]


def _tokens(text):
    return [(w, w.casefold().replace("ё", "е")) for w in _WORD.findall(text or "")]


def match_project(text, projects, current_id=None, labels=()):
    """{project_id, project_name, words} for the project the words point at, or None. A project matches by its name
    (whole, or its words of 4+ letters by stem, so "заявки" finds "Заявки дилеров"); a label of the current project
    ("Ирина") points at the current project. The words found are kept for the reason the UI shows."""
    tokens = _tokens(text)
    if not tokens:
        return None
    low = " ".join(t for _, t in tokens)

    def found(name):
        words = []
        name_low = " ".join(t for _, t in _tokens(name))
        if name_low and re.search(r"(?<![\w])" + re.escape(name_low) + r"(?![\w])", low):
            whole = [w for w, t in tokens if t in name_low.split()]
            return whole or [name]
        for _, part in _tokens(name):
            if len(part) < 4:
                continue
            stem = _stem(part)
            for w, t in tokens:
                if t.startswith(stem) and w not in words:
                    words.append(w)
                    break
        return words

    best = None
    for p in projects:
        words = found(p["name"])
        if p["id"] == current_id:
            for label in labels:
                words += [w for w in found(label) if w not in words]
        if words and (best is None or len(words) > len(best["words"])):
            best = {"project_id": p["id"], "project_name": p["name"], "words": words}
    return best


# ── parse ────────────────────────────────────────────────────────────────────
_NULLABLE = {"anyOf": [{"type": "string"}, {"type": "null"}]}
SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": list(KINDS)}, "title": {"type": "string"},
                       "text": {"type": "string"}, "due": _NULLABLE, "project_hint": _NULLABLE},
        "required": ["kind", "title", "text", "due", "project_hint"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}

CONTRACT = """Return JSON: {"items": [{"kind", "title", "text", "due", "project_hint"}]}, one item per thing to do or
remember in the utterance (usually one; two when the speaker says "и ещё…" / "and also…").
- kind: "remind" when the speaker asks to be reminded or names a time to do something at; "task" for something to do
  (with or without a deadline); "note" for a fact or thought to keep; "idea" for an idea or proposal.
- title: a short imperative line in the speaker's language ("Позвонить Ирине насчёт истории изменений заявки"),
  without the date words and without "напомни" / "remind me".
- text: the item's own words from the utterance, as said (with the date words).
- due: the local date and time as ISO-8601 "YYYY-MM-DDTHH:MM" when the words name one, else null. Resolve relative
  dates from `now` below: "завтра в десять" / "tomorrow at ten" = tomorrow 10:00; "до вечера" / "by tonight" = today
  18:00; "в понедельник" / "on Monday" = the next Monday 09:00; "через час" / "in an hour" = now + 1 hour; a day
  without a time = 09:00 that day; a time without a day = the next time that time comes.
- project_hint: the words that name a project, a client, a person or a topic the item belongs to, as said, else null.
Never invent anything that was not said."""


def system_prompt(skillset=None):
    return skills.compose(skillset or skills.resolve(), STAGE, CONTRACT)


def user_prompt(transcript, now, lang, project_names):
    aware = now if now.tzinfo is not None else now.astimezone()
    offset = aware.strftime("%z")
    tz = f"UTC{offset[:3]}:{offset[3:]}" if offset else "local"
    names = "\n".join(f"- {n}" for n in project_names) or "- (none)"
    return (f"now: {aware.strftime('%Y-%m-%dT%H:%M')} ({tz}, {aware.strftime('%A')})\n"
            f"interface language: {'Russian' if lang == 'ru' else 'English'}\n"
            f"projects:\n{names}\n\nutterance:\n{transcript.strip()}")


def _clean(items, transcript, now, projects, current_id, labels):
    """The model's items → the items the result card shows: due resolved (rules first), project matched."""
    out = []
    raw = [i for i in (items or []) if isinstance(i, dict)]
    for i in raw:
        kind = i.get("kind") if i.get("kind") in KINDS else "note"
        text = " ".join(str(i.get("text") or "").split()) or " ".join(str(i.get("title") or "").split())
        title = " ".join(str(i.get("title") or "").split()) or text
        if not title:
            continue
        due = resolve_due(f"{text} {title}", now) or (resolve_due(transcript, now) if len(raw) == 1 else None) \
            or parse_iso(i.get("due"), now)
        if due is not None and kind in ("note", "idea"):
            kind = "remind"
        hint = i.get("project_hint") if isinstance(i.get("project_hint"), str) else ""
        match = match_project(" ".join(x for x in (hint, text, title) if x), projects, current_id, labels)
        out.append({"kind": kind, "title": title[:300], "text": text[:4000],
                    "due_at": due.timestamp() if due else None,
                    "due": due.isoformat(timespec="minutes") if due else None,
                    "project_id": match["project_id"] if match else None,
                    "project_name": match["project_name"] if match else None,
                    "project_words": match["words"] if match else []})
    return out


def fallback_items(transcript, now, projects, current_id=None, labels=()):
    """No model ready: the transcript itself as one note (with the time and project the rules find)."""
    text = " ".join((transcript or "").split())
    if not text:
        return []
    return _clean([{"kind": "note", "title": text[:120], "text": text}], text, now, projects, current_id, labels)


def parse(transcript, complete, now, lang="ru", projects=(), current_id=None, labels=(), skillset=None):
    """One structured call: the transcript → [items] (see _clean). `complete(system, user, schema)` → dict."""
    transcript = (transcript or "").strip()
    if not transcript:
        return []
    reply = complete(system_prompt(skillset), user_prompt(transcript, now, lang, [p["name"] for p in projects]), SCHEMA)
    items = _clean((reply or {}).get("items"), transcript, now, projects, current_id, labels)
    return items or fallback_items(transcript, now, projects, current_id, labels)


# ── turning an item into a client question ───────────────────────────────────
def to_question(store, whisper, project_id):
    """A Q atom in `project_id` quoting the whisper's transcript (a line of the project's hidden "Шепнуть" source);
    the whisper is marked with it. Returns {atom_id, label, statement, project_id, whisper}."""
    store.get_project(project_id)
    source = store.whisper_source(project_id)
    quote = whisper["transcript"] or whisper["text"]
    idx = store.add_note_line(source["id"], quote)
    statement = whisper["title"].rstrip(".!")
    if not statement.endswith("?"):
        statement += "?"
    [aid] = store.add_atoms(project_id, [{"type": "question", "statement": statement, "evidence": [
        {"source_id": source["id"], "segment_idx": idx, "start": None, "speaker": None, "quote": quote}]}])
    atom = store.get_atom(aid)
    marked = store.set_whisper_atom(whisper["id"], aid)
    return {"atom_id": aid, "label": store.requirement_ids(project_id, [atom])[aid], "statement": atom["statement"],
            "project_id": project_id, "whisper": marked}


# ── reminders ────────────────────────────────────────────────────────────────
def fire_due(store, notify, now=None):
    """Announce every task and reminder whose time has come, once each (notified_at). Returns the ones announced."""
    fired = []
    for w in store.due_whispers(now if now is not None else time.time()):
        try:
            notify("Dictum", w["title"])
        except Exception:                 # a failed notification is not retried in a loop
            log.exception("Reminder notification failed for %s", w["id"])
        store.mark_whisper_notified(w["id"])
        fired.append(w)
    return fired


class ReminderScheduler:
    """Checks every `interval` seconds while the app runs (reminders do not fire while it is closed, spec A6)."""

    def __init__(self, store, notify, interval=30.0, clock=time.time):
        self.store, self.notify, self.interval, self._clock = store, notify, interval, clock
        self._stop = threading.Event()
        self._thread = None

    def tick(self):
        return fire_due(self.store, self.notify, self._clock())

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="whisper-reminders", daemon=True)
            self._thread.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Reminder check failed")
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
