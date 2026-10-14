"""First-run discovery (5.0 C8): files in Загрузки, Документы and Рабочий стол that look like project material.

Audio and video (what the app imports as meetings) and documents (what Материалы imports), newest first, at most
LIMIT. Hidden files and folders, files over MAX_SIZE and files already imported into any project (same original
name and size) are left out. The files are only listed here; importing copies them, the originals stay put.

DICTUM_DISCOVER_ROOTS (folders separated by os.pathsep) replaces the default folders, for the e2e suite.
"""
import os

from core.materials import FILE_EXTENSIONS

LIMIT = 50
MAX_SIZE = 2 * 1024 ** 3
MAX_DEPTH = 2                 # the folder itself and two levels of subfolders
MAX_ENTRIES = 20000           # stop walking a huge Documents folder after this many entries
ROOT_NAMES = ("Downloads", "Documents", "Desktop")
DOCUMENT_EXTENSIONS = frozenset(FILE_EXTENSIONS)


def default_roots(home=None, env=None):
    env = os.environ if env is None else env
    override = env.get("DICTUM_DISCOVER_ROOTS")
    if override:
        return [p for p in override.split(os.pathsep) if p]
    home = home or os.path.expanduser("~")
    return [os.path.join(home, name) for name in ROOT_NAMES]


def kind_of(name, audio_extensions):
    ext = os.path.splitext(name)[1].lower()
    if ext in audio_extensions:
        return "audio"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return None


def _walk(root):
    """Files under root, hidden entries skipped, at most MAX_DEPTH levels down and MAX_ENTRIES entries."""
    seen = 0
    stack = [(root, 0)]
    while stack:
        folder, depth = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            seen += 1
            if seen > MAX_ENTRIES:
                return
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH and not e.name.endswith((".app", ".photoslibrary", ".bundle")):
                        stack.append((e.path, depth + 1))
                elif e.is_file():
                    yield e
            except OSError:
                continue


def candidates(roots, audio_extensions, imported=frozenset(), limit=LIMIT):
    """[{path, name, kind, size, modified, folder}], newest first. `imported`: {(original filename, size)}."""
    found = {}
    for root in roots:
        if not os.path.isdir(root):
            continue
        for e in _walk(root):
            kind = kind_of(e.name, audio_extensions)
            if not kind:
                continue
            try:
                st = e.stat()
            except OSError:
                continue
            if st.st_size == 0 or st.st_size > MAX_SIZE or (e.name, st.st_size) in imported:
                continue
            found[os.path.realpath(e.path)] = {"path": e.path, "name": e.name, "kind": kind, "size": st.st_size,
                                               "modified": st.st_mtime, "folder": os.path.basename(os.path.normpath(root))}
    return sorted(found.values(), key=lambda c: -c["modified"])[:limit]
