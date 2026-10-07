"""Speech-recognition models (GigaAM): what is on disk, what can be downloaded, one download at a time.

GigaAM fetches a model on first use with no progress and no resume; a broken connection leaves a damaged
file and "model checksum failed" at the next transcription. Here the download runs as its own job, is
verified before it replaces anything, and the Settings screen shows what is installed."""
import hashlib
import os
import threading
import urllib.request

URL_DIR = "https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM"
MB = 1024 * 1024

# name, size of the weights (bytes), tokenizer needed, which languages, note key
CATALOG = [
    {"id": "v3_e2e_rnnt", "size": 448929252, "tokenizer": True, "langs": "ru", "recommended": True},
    {"id": "v3_e2e_ctc", "size": 442404646, "tokenizer": True, "langs": "ru"},
    {"id": "v3_rnnt", "size": 446390032, "tokenizer": False, "langs": "ru"},
    {"id": "v3_ctc", "size": 441714678, "tokenizer": False, "langs": "ru"},
    {"id": "v2_rnnt", "size": 470224300, "tokenizer": False, "langs": "ru"},
    {"id": "v2_ctc", "size": 465549152, "tokenizer": False, "langs": "ru"},
    {"id": "v1_rnnt", "size": 490382668, "tokenizer": True, "langs": "ru"},
    {"id": "v1_ctc", "size": 484489040, "tokenizer": False, "langs": "ru"},
    {"id": "multilingual_ctc", "size": 883212109, "tokenizer": False, "langs": "multi"},
    {"id": "multilingual_large_ctc", "size": 2341654513, "tokenizer": False, "langs": "multi"},
]
BY_ID = {m["id"]: m for m in CATALOG}


class AsrModelError(Exception):
    pass


def _hashes():
    try:
        from gigaam import _MODEL_HASHES
        return _MODEL_HASHES
    except Exception:            # tests, or gigaam not installed yet
        return {}


def files_of(model_id, root):
    m = BY_ID[model_id]
    paths = [os.path.join(root, model_id + ".ckpt")]
    if m["tokenizer"]:
        paths.append(os.path.join(root, model_id + "_tokenizer.model"))
    return paths


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * MB), b""):
            h.update(chunk)
    return h.hexdigest()


class Downloader:
    """One model download at a time, with progress; the file lands under its final name only after the checksum passes."""

    def __init__(self, root, opener=urllib.request.urlopen, hashes=_hashes):
        self.root = root
        self._opener = opener
        self._hashes = hashes
        self._lock = threading.Lock()
        self._state = None           # {model, status: downloading|verifying|done|error|cancelled, done, total, error}
        self._stop = threading.Event()
        self._thread = None

    def status(self):
        with self._lock:
            return dict(self._state) if self._state else None

    def busy(self):
        s = self.status()
        return bool(s and s["status"] in ("downloading", "verifying"))

    def start(self, model_id):
        if model_id not in BY_ID:
            raise AsrModelError("unknown model")
        if self.busy():
            raise AsrModelError("another model is being downloaded")
        self._stop.clear()
        with self._lock:
            self._state = {"model": model_id, "status": "downloading", "done": 0, "total": BY_ID[model_id]["size"], "error": None}
        self._thread = threading.Thread(target=self._run, args=(model_id,), daemon=True)
        self._thread.start()
        return self.status()

    def cancel(self):
        self._stop.set()

    def _set(self, **changes):
        with self._lock:
            if self._state:
                self._state.update(changes)

    def _run(self, model_id):
        try:
            os.makedirs(self.root, exist_ok=True)
            for path in files_of(model_id, self.root):
                self._fetch(f"{URL_DIR}/{os.path.basename(path)}", path, model_id)
            self._set(status="done", done=BY_ID[model_id]["size"])
        except _Cancelled:
            self._set(status="cancelled")
        except Exception as e:
            self._set(status="error", error=str(e))

    def _fetch(self, url, path, model_id):
        part = path + ".part"
        is_weights = path.endswith(".ckpt")
        with self._opener(url, timeout=60) as source, open(part, "wb") as out:
            total = int(source.headers.get("Content-Length") or 0) if hasattr(source, "headers") else 0
            if is_weights and total:
                self._set(total=total)
            done = 0
            while True:
                if self._stop.is_set():
                    out.close()
                    os.remove(part)
                    raise _Cancelled()
                chunk = source.read(1 * MB)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if is_weights:
                    self._set(done=done)
        if is_weights:
            expected = self._hashes().get(model_id)
            self._set(status="verifying")
            if expected and md5_of(part) != expected:
                os.remove(part)
                raise AsrModelError("The downloaded file is damaged (checksum mismatch). Please try again.")
            self._set(status="downloading")
        os.replace(part, path)


class _Cancelled(Exception):
    pass


def list_models(root, downloader=None):
    """Every model of the catalogue with what is on disk."""
    st = downloader.status() if downloader else None
    out = []
    for m in CATALOG:
        paths = files_of(m["id"], root)
        present = [p for p in paths if os.path.exists(p)]
        weights = paths[0]
        installed = len(present) == len(paths)
        size_on_disk = sum(os.path.getsize(p) for p in present)
        damaged = os.path.exists(weights) and os.path.getsize(weights) != m["size"]
        entry = {**m, "installed": installed and not damaged, "damaged": damaged, "size_on_disk": size_on_disk,
                 "partial": os.path.exists(weights + ".part")}
        if st and st["model"] == m["id"] and st["status"] in ("downloading", "verifying"):
            entry["download"] = st
        out.append(entry)
    return out


def delete_model(model_id, root):
    if model_id not in BY_ID:
        raise AsrModelError("unknown model")
    removed = 0
    for p in files_of(model_id, root) + [files_of(model_id, root)[0] + ".part"]:
        if os.path.exists(p):
            os.remove(p)
            removed += 1
    return removed
