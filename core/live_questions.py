"""The question card while a meeting is recorded (spec 5.0 C4.3, setting `live_questions`, off by default).

Every live window the new lines of the transcript are checked by a cheap detector: a line that ends with "?" or
starts with an interrogative word, and has at least MIN_WORDS words. For the newest such line, the materials marked
"в контексте" are searched (core/ask.retrieve, materials only); when the closest one scores above
ask.SHORT_MIN_SCORE the model writes a two-sentence answer with one citation (the `ask` skill, short mode). The card
`{id, text, answer, citation}` is shown on the meeting page until it is dismissed, a newer question replaces it, or
CARD_SECONDS pass.

Like core/live_atoms, this never touches audio and never blocks the transcriber: its own thread, a store snapshot of
the transcript, a tick skipped while the previous pass still runs, and errors logged instead of raised.
"""
import logging
import re
import threading
import time
import uuid

from core import ask

log = logging.getLogger("dictum.live_questions")

WINDOW = 15                      # the live transcript's window
MIN_WORDS = 6
CARD_SECONDS = 60
INTERROGATIVES = {"кто", "что", "как", "когда", "где", "почему", "сколько", "какой", "какая", "какие",
                  "who", "what", "how", "when", "where", "why", "which"}


def is_question(text):
    """A line worth answering: ends with "?" or starts with an interrogative word, and has at least MIN_WORDS words."""
    words = re.findall(r"[\w-]+", text or "")
    if len(words) < MIN_WORDS:
        return False
    return (text or "").rstrip().endswith("?") or words[0].casefold() in INTERROGATIVES


class LiveQuestions:
    """`answer(question)` → {answer, citation} or None (ask.short_answer bound to the project and its model)."""

    def __init__(self, source_id, store, answer, window=WINDOW, card_seconds=CARD_SECONDS, clock=time.monotonic):
        self.source_id = source_id
        self._store = store
        self._answer = answer
        self.window = window
        self.card_seconds = card_seconds
        self._clock = clock
        self.last_idx = -1
        self.passes = 0
        self.skipped = 0
        self.errors = 0
        self._card = None
        self._busy = False
        self._busy_lock = threading.Lock()
        self._closed = False
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="live-questions", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(self.window):
            self.tick()

    def stop(self, join_timeout=1.0):
        self._stop.set()
        self._closed = True
        self._card = None
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=join_timeout)

    @property
    def busy(self):
        return self._busy

    def tick(self):
        """Start a pass in the background unless one is still running. Returns whether one was started."""
        with self._busy_lock:
            if self._busy or self._closed:
                self.skipped += 1
                return False
            self._busy = True
        threading.Thread(target=self._guarded_pass, name="live-questions-pass", daemon=True).start()
        return True

    def _guarded_pass(self):
        try:
            self.run_pass()
        except Exception:                    # the index, the model, a bug: logged; the recording never notices
            self.errors += 1
            log.exception("Live question pass failed for %s", self.source_id)
        finally:
            with self._busy_lock:
                self._busy = False

    def run_pass(self):
        """One pass in the calling thread: the newest question in the new lines that has an answer becomes the card.
        Returns the card shown, or None."""
        if self._closed:
            return None
        segments, _ = self._store.transcript(self.source_id)
        new = [s for s in segments if s["idx"] > self.last_idx]
        if not new:
            return None
        self.last_idx = new[-1]["idx"]
        self.passes += 1
        for seg in reversed([s for s in new if is_question(s["text"])]):
            got = self._answer(seg["text"].strip())
            if got and not self._closed:
                self._card = {"id": str(uuid.uuid4()), "text": seg["text"].strip(), "answer": got["answer"],
                              "citation": got["citation"], "segment_idx": seg["idx"], "at": self._clock()}
                return self.current()
        return None

    def current(self):
        """The card to show, or None once it was dismissed or is older than card_seconds."""
        card = self._card
        if card is None:
            return None
        if self._clock() - card["at"] > self.card_seconds:
            self._card = None
            return None
        return {k: v for k, v in card.items() if k != "at"}

    def dismiss(self, card_id=None):
        """Hide the card (the one with this id, or whatever is shown). Returns whether one was hidden."""
        card = self._card
        if card is None or (card_id and card["id"] != card_id):
            return False
        self._card = None
        return True


def answerer(store, project_id, generate, skillset=None, min_score=ask.SHORT_MIN_SCORE):
    def answer(question):
        return ask.short_answer(store, project_id, question, generate, skillset=skillset, min_score=min_score)
    return answer
