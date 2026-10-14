"""Requirements on the fly while a meeting is recorded (spec 5.0 C4.2).

Every `window` seconds, when at least `min_segments` new lines reached the transcript since the last pass, the
new lines go through the normal extractor (atoms.extract_candidates, the project's skill set) with the last few
earlier lines as context. What it finds is saved as pending atoms marked `live`, with evidence checked against
the lines it came from, and compared with the project's atoms by the normal duplicate check.

This never touches audio and never blocks the live transcriber: it runs in its own thread, reads the transcript
through the store (a snapshot), skips a tick while the previous pass is still running, and logs its errors
instead of raising them. The recording does not know it exists.

After the final transcription, `reconcile` re-checks the live atoms' quotes against the final lines: segment
indices are rewritten to the final ones, and an atom whose quote is gone is kept, flagged `stale_evidence`.
"""
import logging
import threading

from core import atoms as atoms_mod

log = logging.getLogger("dictum.live_atoms")

WINDOW = 90
MIN_SEGMENTS = 4
CONTEXT_SEGMENTS = 10


class LiveAtoms:
    """`extract(segments, context)` returns verified candidates; `dedup(new_ids)` folds duplicates in."""

    def __init__(self, source_id, project_id, store, extract, dedup=None, model=None, window=WINDOW,
                 min_segments=MIN_SEGMENTS, context=CONTEXT_SEGMENTS):
        self.source_id = source_id
        self.project_id = project_id
        self._store = store
        self._extract = extract
        self._dedup = dedup
        self.model = model
        self.window = window
        self.min_segments = min_segments
        self.context = context
        self.last_idx = -1                 # the newest line a pass has already read
        self.passes = 0
        self.skipped = 0
        self.errors = 0
        self._busy = False
        self._busy_lock = threading.Lock()
        self._lock = threading.Lock()      # held while saving, so nothing is saved after stop()
        self._closed = False
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="live-atoms", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(self.window):
            self.tick()

    def stop(self, join_timeout=1.0):
        """No atom is saved after this returns; a pass still waiting for the model drops its result."""
        self._stop.set()
        with self._lock:
            self._closed = True
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
        threading.Thread(target=self._guarded_pass, name="live-atoms-pass", daemon=True).start()
        return True

    def _guarded_pass(self):
        try:
            self.run_pass()
        except Exception:                    # the model, the network, a bug: logged, and the next pass tries again
            self.errors += 1
            log.exception("Live requirements pass failed for %s", self.source_id)
        finally:
            with self._busy_lock:
                self._busy = False

    def run_pass(self):
        """One pass, in the calling thread. Returns the ids of the atoms saved."""
        if self._closed:
            return []
        segments, _ = self._store.transcript(self.source_id)
        new = [s for s in segments if s["idx"] > self.last_idx]
        if len(new) < self.min_segments:
            return []
        context = [s for s in segments if s["idx"] <= self.last_idx][-self.context:] if self.context else []
        self.last_idx = new[-1]["idx"]
        candidates = self._extract(new, context)
        self.passes += 1
        if not candidates:
            return []
        with self._lock:
            if self._closed:
                return []
            ids = self._store.add_atoms(self.project_id, [{**c, "live": True} for c in candidates], model=self.model)
        if self._dedup is not None and ids:
            self._dedup(ids)
        return ids


def extractor(store, source_id, prefs, api_key, ollama_url, skillset=None, complete=None):
    """extract(segments, context) for LiveAtoms: the normal extractor on just those lines, requirements only
    (action items and small talk found mid-meeting wait for the final pass)."""
    def extract(segments, context):
        kwargs = {"complete": complete} if complete is not None else {}
        candidates, _dropped, _steps, _skipped = atoms_mod.extract_candidates(
            store, source_id, prefs, api_key, ollama_url, skillset=skillset, segments=segments, context=context,
            **kwargs)
        return candidates
    return extract


def deduper(store, project_id, prefs, api_key, ollama_url, skillset=None, complete=None):
    def dedup(new_ids):
        return atoms_mod._dedup(store, project_id, new_ids, prefs, api_key, ollama_url,
                                complete or atoms_mod.complete_json, skillset)
    return dedup


def reconcile(store, source_id):
    """After the final transcript was saved: find each live atom's quotes again by their text, point the evidence
    at the final lines, flag the atom `stale_evidence` when a quote is not there any more. Returns
    {"checked", "moved", "stale"}."""
    atoms = store.live_atoms_for_source(source_id)
    if not atoms:
        return {"checked": 0, "moved": 0, "stale": 0}
    segments, _ = store.transcript(source_id)
    moved_n = stale_n = 0
    for atom in atoms:
        moved, stale = [], False
        for ev in atom["evidence"]:
            found = atoms_mod.verify_evidence([{"segment": None, "quote": ev["quote"]}], segments, source_id)
            if found:
                f = found[0]
                moved.append({"id": ev["id"], "segment_idx": f["segment_idx"], "start": f["start"],
                              "speaker": f["speaker"]})
                moved_n += f["segment_idx"] != ev["segment_idx"]
            else:                            # the line it was on is gone: keep the quote, point at no line
                stale = True
                moved.append({"id": ev["id"], "segment_idx": None, "start": ev["start"], "speaker": ev["speaker"]})
        stale_n += stale
        store.set_live_evidence(atom["id"], moved, stale)
    return {"checked": len(atoms), "moved": moved_n, "stale": stale_n}
