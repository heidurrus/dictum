"""Built-in local model: download it with one click, run it without setup.

The engine is llama.cpp's `llama-server` (a small prebuilt program from its
official releases); the weights are GGUF files from Hugging Face. Both are
pinned to exact versions and checked by SHA-256. The app starts the server as
its own child process on a private port with a random API key, only when a
local model is needed, and stops it when idle or when the app quits, so the
user never installs or starts anything (spec D-02, FR-SET-02).
"""
import atexit
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass

from core.paths import app_data_dir

ENGINE_BUILD = "b11223"
_RELEASE = f"https://github.com/ggml-org/llama.cpp/releases/download/{ENGINE_BUILD}/"


@dataclass(frozen=True)
class Asset:
    url: str
    sha256: str
    size: int


# Windows x64 uses the Vulkan build: it runs on NVIDIA, AMD and Intel GPUs and
# falls back to the CPU when there is no usable GPU.
ENGINES = {
    ("darwin", "arm64"): Asset(_RELEASE + f"llama-{ENGINE_BUILD}-bin-macos-arm64.tar.gz",
                               "5bacea12237283699a196194b7f62a0e613438bd5feed694359ed6050492bb3e", 11756895),
    ("darwin", "x86_64"): Asset(_RELEASE + f"llama-{ENGINE_BUILD}-bin-macos-x64.tar.gz",
                                "20b0a6f67d384de5efa90ce95968ca5cd9d7d3a0d98b0873da07707d034f8234", 11310524),
    ("win32", "amd64"): Asset(_RELEASE + f"llama-{ENGINE_BUILD}-bin-win-vulkan-x64.zip",
                              "b450e71cfb2204955db784590af51b3f81fbc3bde0c5687f7a85c89edc977fd4", 33062159),
    ("win32", "arm64"): Asset(_RELEASE + f"llama-{ENGINE_BUILD}-bin-win-cpu-arm64.zip",
                              "b04e2a1389fbb04abb1ef5fe238cce7faf1d38925b4d87c9d3966f0dee992078", 12042144),
}


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    file: str
    asset: Asset
    min_ram_gb: int
    context: int
    gpu_gb: float = 0    # GPU memory for weights + working memory at full speed


def _hf(repo, revision, file):
    return f"https://huggingface.co/{repo}/resolve/{revision}/{file}"


# Open-weight models that are good in Russian and English, largest first. The recommendation
# is the first one that fits the machine's memory and runs at full speed (recommended_model_id).
# Every Qwen file here is the "qwen35" / "qwen35moe" GGUF architecture, which engine b11223 knows.
MODELS = [
    # 35B total, about 3B active per token: the fastest strong model on a 32 GB Mac.
    Model("qwen3.6-35b-a3b", "Qwen3.6 35B-A3B", "Qwen3.6-35B-A3B-UD-IQ4_XS.gguf",
          Asset(_hf("unsloth/Qwen3.6-35B-A3B-GGUF", "a483e9e6cbd595906af30beda3187c2663a1118c",
                    "Qwen3.6-35B-A3B-UD-IQ4_XS.gguf"),
                "649d7508507b84638732c4f52c24c8b15843c6dca2f3ff793ae07c14a67ebbb3", 17730509792),
          min_ram_gb=32, context=32768, gpu_gb=20),
    # Dense 27B: the best answers of the list, several times slower than the MoE above.
    Model("qwen3.8-27b", "Qwen3.8 27B", "Qwen3.8-27B-UD-Q4_K_M.gguf",
          Asset(_hf("unsloth/Qwen3.8-27B-GGUF", "4ca720788d1e01f1bff70c033e0d0028fd02e502",
                    "Qwen3.8-27B-UD-Q4_K_M.gguf"),
                "322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482", 16464440224),
          min_ram_gb=32, context=32768, gpu_gb=18),
    Model("gemma-4-12b", "Gemma 4 12B", "gemma-4-12b-it-qat-q4_0.gguf",
          Asset(_hf("google/gemma-4-12B-it-qat-q4_0-gguf", "29d097773436b69ff9feafd636ab4cf873786537",
                    "gemma-4-12b-it-qat-q4_0.gguf"),
                "93567e57a8fe10b23569b9d9ec38cd005deedf71e29477c421a4b83f418a538b", 6975879296),
          min_ram_gb=16, context=32768, gpu_gb=8),
    Model("qwen3.5-9b", "Qwen3.5 9B", "Qwen3.5-9B-Q4_K_M.gguf",
          Asset(_hf("unsloth/Qwen3.5-9B-GGUF", "3885219b6810b007914f3a7950a8d1b469d598a5", "Qwen3.5-9B-Q4_K_M.gguf"),
                "03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8", 5680522464),
          min_ram_gb=16, context=32768, gpu_gb=6.5),
    Model("qwen3.5-4b", "Qwen3.5 4B", "Qwen3.5-4B-Q4_K_M.gguf",
          Asset(_hf("unsloth/Qwen3.5-4B-GGUF", "e87f176479d0855a907a41277aca2f8ee7a09523", "Qwen3.5-4B-Q4_K_M.gguf"),
                "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4", 2740937888),
          min_ram_gb=8, context=32768, gpu_gb=3.5),
]
MODELS_BY_ID = {m.id: m for m in MODELS}

# The index's embedding model (5.0 C5, spec §9 A3): multilingual, run by a second llama-server with
# `--embedding --pooling last`. From the official Qwen/Qwen3-Embedding-0.6B-GGUF repo (not unsloth), Q8_0.
EMBED_MODELS = [
    Model("qwen3-embedding-0.6b", "Qwen3 Embedding 0.6B", "Qwen3-Embedding-0.6B-Q8_0.gguf",
          Asset(_hf("Qwen/Qwen3-Embedding-0.6B-GGUF", "370f27d7550e0def9b39c1f16d3fbaa13aa67728",
                    "Qwen3-Embedding-0.6B-Q8_0.gguf"),
                "06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439", 639150592),
          min_ram_gb=4, context=8192, gpu_gb=1),
]
EMBED_MODELS_BY_ID = {m.id: m for m in EMBED_MODELS}


def _any_model(model_id):
    """A chat model or an embedding model by id (both download and run the same way)."""
    return MODELS_BY_ID.get(model_id) or EMBED_MODELS_BY_ID.get(model_id)

IDLE_STOP_SECONDS = 15 * 60
START_TIMEOUT_SECONDS = 240
DISK_MARGIN = 1 * 1024 ** 3


class LocalModelError(Exception):
    """A user-facing problem with the built-in model."""


# ── system facts ─────────────────────────────────────────────────────────────

def platform_key():
    machine = platform.machine().lower()
    machine = {"aarch64": "arm64", "x64": "amd64"}.get(machine, machine)
    if sys.platform == "darwin" and machine == "amd64":
        machine = "x86_64"
    return sys.platform, machine


def engine_asset():
    return ENGINES.get(platform_key())


def total_ram_bytes():
    try:
        if sys.platform == "darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                      timeout=5).stdout.strip())
        if sys.platform == "win32":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return int(status.ullTotalPhys)
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except Exception:
        return None


_machine_cache = {}


def machine_info(run=subprocess.run):
    """{ram, chip, os} for the first run's "На этом Mac 16 ГБ памяти и чип M1 Pro" (5.0 C8). chip: the Apple chip
    ("M1 Pro") on a Mac, else None (Windows reports cryptic processor strings; the GPU line covers those)."""
    if "m" in _machine_cache:
        return _machine_cache["m"]
    chip = None
    try:
        if sys.platform == "darwin":
            brand = run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=5).stdout.strip()
            chip = re.sub(r"^Apple\s+", "", brand) or None
    except Exception:
        chip = None
    _machine_cache["m"] = {"ram": total_ram_bytes(), "chip": chip, "os": sys.platform}
    return _machine_cache["m"]


# ── GPU ──────────────────────────────────────────────────────────────────────
# What decides speed is GPU memory: a model that fits runs fast; one that half
# fits runs partly on the CPU; with no usable GPU it all runs on the CPU (slow).
# On Apple Silicon, RAM *is* GPU memory (macOS lets the GPU use about 3/4 of it).

_gpu_cache = {}


def _parse_devices(text):
    """`llama-server --list-devices` lines like "  Vulkan0: NVIDIA GeForce RTX 3060 (12288 MiB, 11200 MiB free)"."""
    found = []
    for name, desc, total in re.findall(r"^\s*(\w+):\s*(.+?)\s*\((\d+) MiB,", text, flags=re.M):
        if int(total) > 0 and not name.upper().startswith(("BLAS", "CPU")):
            found.append({"name": desc, "memory": int(total) * 1024 ** 2, "backend": name})
    return found


def _engine_gpu(binary):
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        out = subprocess.run([binary, "--list-devices"], capture_output=True, text=True, timeout=30,
                             creationflags=flags, cwd=os.path.dirname(binary))
        devices = _parse_devices(out.stdout + out.stderr)
    except (OSError, subprocess.SubprocessError):
        return None
    return max(devices, key=lambda d: d["memory"]) if devices else {}


def _registry_gpu(winreg=None):
    """Windows before the engine is downloaded: dedicated video memory per adapter from the registry
    (64-bit value, unlike WMI's AdapterRAM which stops at 4 GB)."""
    if winreg is None:
        import winreg
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    best = {}
    for i in range(16):
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{i:04d}")
        except OSError:
            continue
        try:
            memory = 0
            for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                try:
                    raw, _type = winreg.QueryValueEx(key, value)
                except OSError:
                    continue
                memory = int.from_bytes(raw, "little") if isinstance(raw, (bytes, bytearray)) else int(raw)
                if memory:
                    break
            try:
                name = winreg.QueryValueEx(key, "DriverDesc")[0]
            except OSError:
                name = "GPU"
            if memory > best.get("memory", 0):
                best = {"name": name, "memory": memory, "backend": "registry"}
        finally:
            winreg.CloseKey(key)
    return best


def gpu_info(refresh=False):
    """The main GPU as {name, memory, backend}; {} when there is none; None when unknown."""
    if "gpu" in _gpu_cache and not refresh:
        return _gpu_cache["gpu"]
    binary = server_binary()
    gpu = _engine_gpu(binary) if binary else None
    if gpu is None:
        if sys.platform == "win32":
            try:
                gpu = _registry_gpu()
            except Exception:
                gpu = None
        elif platform_key() == ("darwin", "arm64"):
            ram = total_ram_bytes()
            gpu = {"name": "Apple Silicon", "memory": int(ram * 0.75), "backend": "unified"} if ram else None
    # Tiny "dedicated" memory (integrated graphics) is no help for a model.
    if gpu and gpu.get("memory", 0) < 2 * 1024 ** 3:
        gpu = {}
    _gpu_cache["gpu"] = gpu
    return gpu


def speed(model, gpu):
    """"fast" (fits the GPU), "partial" (half on the CPU), "slow" (CPU only), or None if unknown."""
    if gpu is None:
        return None
    memory = gpu.get("memory", 0) / 1024 ** 3
    if memory >= model.gpu_gb:
        return "fast"
    return "partial" if memory >= model.gpu_gb / 2 else "slow"


def _fits_ram(model, ram):
    # A "16 GB" machine reports slightly less; allow for that.
    return ram is None or ram >= model.min_ram_gb * 0.9 * 1024 ** 3


def recommended_model_id(ram=None, gpu=None):
    """The largest model that fits memory and runs at full speed; else the smallest one."""
    ram = total_ram_bytes() if ram is None else ram
    for m in MODELS:
        if _fits_ram(m, ram) and speed(m, gpu) in ("fast", None):
            return m.id
    return MODELS[-1].id


# ── files ────────────────────────────────────────────────────────────────────

def root_dir():
    path = os.path.join(app_data_dir(), "local-llm")
    os.makedirs(path, exist_ok=True)
    return path


def models_path():
    path = os.path.join(root_dir(), "models")
    os.makedirs(path, exist_ok=True)
    return path


def engine_dir():
    return os.path.join(root_dir(), "engine", ENGINE_BUILD)


def server_binary():
    """Path of llama-server if the engine is installed, else None."""
    name = "llama-server.exe" if sys.platform == "win32" else "llama-server"
    base = engine_dir()
    if not os.path.isdir(base):
        return None
    for folder, _dirs, files in os.walk(base):
        if name in files:
            return os.path.join(folder, name)
    return None


def model_file(model_id):
    return os.path.join(models_path(), _any_model(model_id).file)


def model_installed(model_id):
    m = _any_model(model_id)
    return bool(m) and os.path.isfile(model_file(model_id)) and os.path.getsize(model_file(model_id)) == m.asset.size


def installed_models():
    return [m.id for m in MODELS if model_installed(m.id)]


def ready():
    return server_binary() is not None and bool(installed_models())


def installed_embed_models():
    return [m.id for m in EMBED_MODELS if model_installed(m.id)]


def delete_model(model_id):
    if _any_model(model_id) is None:
        raise LocalModelError("unknown model")
    runtime.stop_if(model_id)
    embed_runtime.stop_if(model_id)
    for path in (model_file(model_id), model_file(model_id) + ".part"):
        if os.path.exists(path):
            os.remove(path)


# ── downloads ────────────────────────────────────────────────────────────────

class Cancelled(Exception):
    pass


def download(asset, dest, on_bytes=None, cancel=None, opener=urllib.request.urlopen, retries=4, sleep=time.sleep):
    """Download to dest with resume (dest.part + Range) and a SHA-256 check."""
    part = dest + ".part"
    for attempt in range(retries + 1):
        try:
            have = os.path.getsize(part) if os.path.exists(part) else 0
            if have > asset.size:
                os.remove(part)
                have = 0
            if have < asset.size:
                req = urllib.request.Request(asset.url, headers={"Range": f"bytes={have}-"} if have else {})
                with opener(req, timeout=60) as resp:
                    if have and getattr(resp, "status", 206) != 206:   # server ignored Range: start over
                        have = 0
                    with open(part, "ab" if have else "wb") as f:
                        while True:
                            if cancel is not None and cancel.is_set():
                                raise Cancelled()
                            chunk = resp.read(1024 * 1024)
                            if not chunk:
                                break
                            f.write(chunk)
                            have += len(chunk)
                            if on_bytes:
                                on_bytes(have)
            if os.path.getsize(part) != asset.size:
                raise OSError("the download ended early")
            digest = hashlib.sha256()
            with open(part, "rb") as f:
                for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    digest.update(chunk)
            if digest.hexdigest() != asset.sha256:
                os.remove(part)
                raise LocalModelError("The downloaded file is damaged (checksum mismatch). Please try again.")
            os.replace(part, dest)
            return dest
        except (Cancelled, LocalModelError):
            raise
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if attempt == retries:
                raise LocalModelError(f"Download failed: {getattr(e, 'reason', e)}. Check your internet connection and try again.")
            sleep(min(30, 2 ** attempt))


def _extract(archive, dest):
    tmp = dest + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        with tarfile.open(archive) as t:
            t.extractall(tmp, filter="data")
    shutil.rmtree(dest, ignore_errors=True)
    os.replace(tmp, dest)
    if sys.platform != "win32":
        for folder, _dirs, files in os.walk(dest):
            for name in files:
                if name.startswith("llama-") or name == "ggml-rpc-server":
                    path = os.path.join(folder, name)
                    os.chmod(path, os.stat(path).st_mode | 0o755)


class Installer:
    """One background download at a time (engine if missing, then the model)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread = None
        self.state = {"status": "idle"}

    def status(self):
        with self._lock:
            return dict(self.state)

    def _set(self, **kw):
        with self._lock:
            self.state = {**self.state, **kw}

    def start(self, model_id):
        if _any_model(model_id) is None:
            raise LocalModelError("unknown model")
        if engine_asset() is None:
            raise LocalModelError("The built-in model isn't available for this computer. Use Claude or Ollama.")
        with self._lock:
            if self.state.get("status") in ("downloading", "verifying"):
                return dict(self.state)
        model = _any_model(model_id)
        need = (0 if server_binary() else engine_asset().size) + (0 if model_installed(model_id) else model.asset.size)
        partial = model_file(model_id) + ".part"
        need -= os.path.getsize(partial) if os.path.exists(partial) else 0
        free = shutil.disk_usage(root_dir()).free
        if need + DISK_MARGIN > free:
            raise LocalModelError(f"Not enough disk space: {_gb(need + DISK_MARGIN)} needed, {_gb(free)} free.")
        self._cancel.clear()
        total = (0 if server_binary() else engine_asset().size) + model.asset.size
        self.state = {"status": "downloading", "model": model_id, "done": 0, "total": total, "error": None}
        self._thread = threading.Thread(target=self._run, args=(model,), daemon=True)
        self._thread.start()
        return self.status()

    def cancel(self):
        self._cancel.set()

    def _run(self, model):
        offset = 0
        try:
            if not server_binary():
                asset = engine_asset()
                archive = os.path.join(root_dir(), os.path.basename(asset.url))
                download(asset, archive, on_bytes=lambda n: self._set(done=n), cancel=self._cancel)
                _extract(archive, engine_dir())
                os.remove(archive)
                if not server_binary():
                    raise LocalModelError("The engine archive doesn't contain llama-server.")
                gpu_info(refresh=True)           # the engine sees the GPU exactly as it will use it
                offset = asset.size
            if not model_installed(model.id):
                def progress(n):
                    self._set(done=offset + n, status="verifying" if n >= model.asset.size else "downloading")
                download(model.asset, model_file(model.id), on_bytes=progress, cancel=self._cancel)
            self._set(status="done", done=self.state["total"])
        except Cancelled:
            self._set(status="cancelled")
        except LocalModelError as e:
            self._set(status="error", error=str(e))
        except Exception as e:  # keep the thread's failure visible in the UI
            self._set(status="error", error=f"Download failed: {e}")


def _gb(n):
    return f"{n / 1024 ** 3:.1f} GB"


# ── running the server ───────────────────────────────────────────────────────

SERVERS = ("server", "embed-server")     # the chat model's llama-server and the index's (5.0 C5)


def _pid_file(name="server"):
    return os.path.join(root_dir(), f"{name}.pid")


def _is_our_server(pid, port):
    """True only if pid is still the llama-server we started on that port, so a recycled pid
    (or any other program that merely mentions llama-server) is never killed. `-ww`: Linux ps
    cuts the command line at 80 columns when it isn't writing to a terminal."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW).stdout
            return '"llama-server.exe"' in out.lower()
        args = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True,
                              timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return False
    # The executable (or, for a script, its first argument) is llama-server, started with our port.
    exe = [os.path.basename(a) for a in args[:2]]
    return "llama-server" in exe and any(args[i] == "--port" and args[i + 1] == str(port) for i in range(len(args) - 1))


def cleanup_stale():
    """Stop servers left behind by a crash or force-quit, which would otherwise hold gigabytes of memory."""
    stopped = False
    for name in SERVERS:
        stopped = _cleanup_one(name) or stopped
    return stopped


def _cleanup_one(name):
    try:
        with open(_pid_file(name), encoding="utf-8") as f:
            pid, port = (int(x) for x in f.read().split())
    except (OSError, ValueError):
        return False
    try:
        os.remove(_pid_file(name))
    except OSError:
        pass
    if pid == os.getpid() or not _is_our_server(pid, port):
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.kill(pid, 15)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Runtime:
    """Starts llama-server on demand and stops it when idle or at exit. `embedding`: the index's own instance
    (`--embedding --pooling last`, its own port, pid file and log), so the chat model and the index never evict
    each other."""

    def __init__(self, idle_seconds=IDLE_STOP_SECONDS, clock=time.monotonic, name="server", embedding=False):
        self.name, self.embedding = name, embedding
        self._lock = threading.RLock()
        self._proc = None
        self._model = None
        self._url = None
        self._key = None
        self._last_used = 0.0
        self._busy = 0
        self._idle = idle_seconds
        self._clock = clock
        self._watcher = None
        atexit.register(self.stop)

    def running_model(self):
        with self._lock:
            return self._model if self._proc and self._proc.poll() is None else None

    def log_path(self):
        return os.path.join(root_dir(), f"{self.name}.log")

    def acquire(self, model_id):
        """Make sure the server runs the model; returns (base_url, api_key). Pair with release()."""
        with self._lock:
            if not model_installed(model_id):
                raise LocalModelError("The index model isn't downloaded yet." if self.embedding else
                                      "The local model isn't downloaded yet. Download it in Settings → AI.")
            binary = server_binary()
            if not binary:
                raise LocalModelError("The local engine isn't installed yet. Download the model in Settings → AI.")
            if self.running_model() != model_id:
                self._stop_locked()
                self._start_locked(binary, model_id)
            self._busy += 1
            self._last_used = self._clock()
            return self._url, self._key

    def release(self):
        with self._lock:
            self._busy = max(0, self._busy - 1)
            self._last_used = self._clock()

    def _start_locked(self, binary, model_id):
        model = _any_model(model_id)
        port, key = _free_port(), secrets.token_urlsafe(24)
        cmd = [binary, "-m", model_file(model_id), "--host", "127.0.0.1", "--port", str(port),
               "--api-key", key, "--no-webui", "-c", str(model.context)]
        if self.embedding:
            # One physical batch holds a whole input; a chunk is ~800 characters, far below this.
            cmd += ["--embedding", "--pooling", "last", "-b", "2048", "-ub", "2048"]
        else:
            cmd += ["-np", "1", "--reasoning", "off", "--jinja"]
        log = open(self.log_path(), "w", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self._proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                      cwd=os.path.dirname(binary), creationflags=flags)
        log.close()
        with open(_pid_file(self.name), "w", encoding="utf-8") as f:
            f.write(f"{self._proc.pid} {port}")
        self._url, self._key, self._model = f"http://127.0.0.1:{port}", key, model_id
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                tail = _tail(self.log_path())
                self._proc = self._model = None
                raise LocalModelError("The local model could not start"
                                      + (f": {tail}" if tail else ". Your computer may not have enough memory."))
            try:
                with urllib.request.urlopen(self._url + "/health", timeout=2) as r:
                    if r.status == 200:
                        break
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.5)
        else:
            self._stop_locked()
            raise LocalModelError("The local model took too long to start.")
        if self._watcher is None:
            self._watcher = threading.Thread(target=self._watch_idle, daemon=True)
            self._watcher.start()

    def _watch_idle(self):
        while True:
            time.sleep(30)
            with self._lock:
                if self._proc and not self._busy and self._clock() - self._last_used > self._idle:
                    self._stop_locked()          # frees several GB of memory

    def _stop_locked(self):
        proc, self._proc, self._model = self._proc, None, None
        if proc:
            try:
                os.remove(_pid_file(self.name))
            except OSError:
                pass
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop(self):
        with self._lock:
            self._stop_locked()

    def stop_if(self, model_id):
        with self._lock:
            if self._model == model_id:
                self._stop_locked()


def _tail(path, lines=3):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = [ln.strip() for ln in f.readlines()[-40:] if ln.strip()]
        errors = [ln for ln in text if "error" in ln.lower() or "failed" in ln.lower()]
        return " ".join((errors or text)[-lines:])[:300]
    except OSError:
        return ""


runtime = Runtime()
embed_runtime = Runtime(name="embed-server", embedding=True)
installer = Installer()


def status():
    ram = total_ram_bytes()
    gpu = gpu_info()
    recommended = recommended_model_id(ram, gpu)
    return {
        "gpu": gpu,
        "supported": engine_asset() is not None,
        "engine_installed": server_binary() is not None,
        "ram": ram,
        "machine": machine_info(),
        "disk_free": shutil.disk_usage(root_dir()).free,
        "recommended": recommended,
        "running": runtime.running_model(),
        "download": installer.status(),
        "models": [{"id": m.id, "label": m.label, "size": m.asset.size, "min_ram_gb": m.min_ram_gb,
                    "installed": model_installed(m.id), "recommended": m.id == recommended,
                    "fits": _fits_ram(m, ram), "speed": speed(m, gpu)} for m in MODELS],
        "embed_running": embed_runtime.running_model(),
        "embed_models": [{"id": m.id, "label": m.label, "size": m.asset.size, "installed": model_installed(m.id)}
                         for m in EMBED_MODELS],
    }


def resolve_model(preferred):
    """The model to use: the chosen one if downloaded, else any downloaded one."""
    if preferred and model_installed(preferred):
        return preferred
    have = installed_models()
    if not have:
        raise LocalModelError("The local model isn't downloaded yet. Download it in Settings → AI.")
    return have[0]


@contextmanager
def chat(model_id, body, timeout=900, opener=urllib.request.urlopen):
    """POST an OpenAI-style chat request to the built-in server; yields the open response.

    The server is started if needed and isn't stopped for idleness while a request runs."""
    url, key = runtime.acquire(model_id)
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with opener(req, timeout=timeout) as resp:
            yield resp
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        if "context" in str(detail).lower() and ("exceed" in str(detail).lower() or "too long" in str(detail).lower()):
            raise LocalModelError("This text is too long for the local model. Use Claude for long sources.")
        raise LocalModelError(f"Local model error ({e.code}): {str(detail)[:200]}")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        raise LocalModelError(f"The local model stopped responding ({getattr(e, 'reason', e)}).")
    finally:
        runtime.release()
