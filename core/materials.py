"""Материалы: documents, links and pasted text the BA brings into a project (spec 5.0 C5, first half).

A material is a source of kind "material" (paragraphs are its segments, no timestamps) plus a `materials` row.
Files are read with the extractors text sources already use (core/transcripts.py, core/emails.py) and copied to
`<data>/library/<project>/materials/<source_id>.<ext>`; the original is never touched. Links are fetched once
(10 s, a plain User-Agent) and keep the readable text; in a "Только локально" project a link is stored with the
error "offline" and never fetched. A folder is walked (hidden entries skipped, 200 files at most) as a job.
"""
import os
import re
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlsplit

from core.emails import parse_email_file
from core.store import StoreError
from core.transcripts import MAX_BYTES, TranscriptError, decode_text, docx_text, pdf_text

FILE_EXTENSIONS = (".docx", ".pdf", ".md", ".txt", ".rtf", ".html", ".htm", ".eml")
FOLDER_LIMIT = 200
FETCH_TIMEOUT = 10
FETCH_MAX_BYTES = 5 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; Dictum)"
OFFLINE = "offline"
LONG_PARAGRAPH = 2000          # a block longer than this (a PDF page, a wall of text) is split at its lines


class MaterialError(ValueError):
    """A file, link or text that cannot become a material."""


def is_material_file(filename):
    return os.path.splitext(filename or "")[1].lower() in FILE_EXTENSIONS


# ── text extraction ─────────────────────────────────────────────────────────

def paragraphs(text, lines=False):
    """Blank-line separated blocks, each joined into one line. With `lines`, every non-empty line is one
    (a .docx keeps one paragraph per line). Overlong blocks are cut at their line breaks."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    blocks = text.split("\n") if lines else re.split(r"\n\s*\n", text)
    out = []
    for block in blocks:
        rows = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not rows:
            continue
        if len(" ".join(rows)) <= LONG_PARAGRAPH:
            out.append(" ".join(rows))
            continue
        part = ""
        for ln in rows:
            if part and len(part) + len(ln) > LONG_PARAGRAPH // 2:
                out.append(part)
                part = ""
            part = f"{part} {ln}".strip()
        if part:
            out.append(part)
    return out


class _Readable(HTMLParser):
    """The readable text of a page: headings, paragraphs and list items; scripts, styles, navigation dropped."""
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form", "template", "iframe"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote", "section",
             "article", "pre", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(re.sub(r"[ \t\r\n]+", " ", data))


def readable_html(markup):
    """(title, paragraphs) of an HTML page."""
    p = _Readable()
    try:
        p.feed(markup)
        p.close()
    except Exception as e:                      # HTMLParser is lenient; anything left is a broken file
        raise MaterialError(f"not readable HTML ({e})")
    return " ".join(p.title.split()), paragraphs("".join(p.parts))


_RTF_DEST = re.compile(r"\\\*?\\?(?:fonttbl|colortbl|stylesheet|info|pict|header|footer|themedata|colorschememapping|"
                       r"latentstyles|datastore|xmlnstbl|listtable|listoverridetable|rsidtbl|generator)\b")


def rtf_text(data):
    """Plain text of an RTF document: control words dropped, \\par as a line break, \\'xx and \\uN decoded."""
    raw = data.decode("latin-1")
    if not raw.lstrip().startswith("{\\rtf"):
        raise MaterialError("not an RTF file")
    out, stack, skip, i = [], [], False, 0
    codepage = "cp1251" if "\\ansicpg1251" in raw[:400] else "cp1252"
    uc_skip = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "{":
            stack.append(skip)
            if _RTF_DEST.match(raw, i + 1):
                skip = True
            i += 1
        elif ch == "}":
            skip = stack.pop() if stack else False
            i += 1
        elif ch == "\\":
            m = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)", raw[i:], re.S)
            if not m:
                i += 1
                continue
            i += m.end()
            if skip:
                continue
            word, arg, hexa, sym = m.groups()
            if hexa:
                if uc_skip:
                    uc_skip -= 1
                else:
                    out.append(bytes([int(hexa, 16)]).decode(codepage, "replace"))
            elif word in ("par", "line", "sect", "page"):
                out.append("\n\n" if word in ("par", "sect", "page") else "\n")
            elif word == "tab":
                out.append(" ")
            elif word == "u" and arg:
                n = int(arg)
                out.append(chr(n + 65536 if n < 0 else n))
                uc_skip = 1
            elif word == "*":
                skip = True
            elif sym in ("\\", "{", "}"):
                out.append(sym)
            elif sym == "~":
                out.append(" ")
        else:
            if not skip and ch not in "\r\n":
                if uc_skip:
                    uc_skip -= 1
                else:
                    out.append(ch)
            i += 1
    return "".join(out)


def extract(filename, data):
    """(title or None, paragraphs, format) of a file."""
    if len(data) > MAX_BYTES:
        raise MaterialError(f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
    ext = os.path.splitext(filename or "")[1].lower()
    try:
        if ext == ".docx":
            return None, paragraphs(docx_text(data), lines=True), "docx"
        if ext == ".pdf":
            return None, paragraphs(pdf_text(data)), "pdf"
        if ext == ".eml":
            r = parse_email_file(filename, data)
            return r.get("title"), [s["text"] for s in r["segments"]], "eml"
    except TranscriptError as e:
        raise MaterialError(str(e))
    if ext == ".rtf":
        return None, paragraphs(rtf_text(data)), "rtf"
    if ext in (".html", ".htm"):
        title, paras = readable_html(decode_text(data))
        return title or None, paras, "html"
    if ext in (".md", ".txt"):
        return None, paragraphs(decode_text(data)), ext[1:]
    raise MaterialError(f"{filename}: unsupported file type. Use .docx, .pdf, .md, .txt, .rtf, .html or .eml")


# ── import ──────────────────────────────────────────────────────────────────

def _copy(store, project_id, source_id, ext, data):
    folder = store.material_dir(project_id)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{source_id}.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return path


def import_file(store, project, filename, data):
    """A file → a material. The bytes are copied into the library; nothing is written where they came from."""
    filename = os.path.basename(filename or "file")
    title, paras, fmt = extract(filename, data)
    if not paras:
        raise MaterialError(f"{filename}: no text found in this file")
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    source = store.create_material(project["id"], "file", title or os.path.splitext(filename)[0] or filename,
                                   original_filename=filename, import_format=fmt, size=len(data))
    path = _copy(store, project["id"], source["id"], ext, data)
    return store.set_material_text(source["id"], paras, path=path)


def import_text(store, project, text, title=None):
    """Pasted text → a note material."""
    text = (text or "").strip()
    if not text:
        raise MaterialError("the text is empty")
    paras = paragraphs(text)
    title = " ".join((title or "").split()) or paras[0][:80]
    source = store.create_material(project["id"], "note", title, import_format="md",
                                   size=len(text.encode("utf-8")))
    return store.set_material_text(source["id"], paras)


def check_url(url):
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise MaterialError("a link must start with http:// or https://")
    return url


def fetch_url(url, opener=None):
    """(title, paragraphs) of a web page, fetched once."""
    opener = opener or urllib.request.urlopen
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html, text/plain, */*"})
    try:
        with opener(req, timeout=FETCH_TIMEOUT) as resp:
            ctype = resp.headers.get("Content-Type", "") if getattr(resp, "headers", None) else ""
            data = resp.read(FETCH_MAX_BYTES + 1)
    except Exception as e:
        raise MaterialError(f"could not fetch the page ({e})")
    charset = re.search(r"charset=([\w-]+)", ctype or "")
    try:
        markup = data[:FETCH_MAX_BYTES].decode(charset.group(1)) if charset else decode_text(data[:FETCH_MAX_BYTES])
    except (LookupError, UnicodeDecodeError):
        markup = decode_text(data[:FETCH_MAX_BYTES])
    if "html" in (ctype or "").lower() or re.search(r"<(html|body|p|div)\b", markup[:5000], re.I):
        return readable_html(markup)
    return None, paragraphs(markup)


def _apply_fetch(store, source_id, url, fetch=None):
    try:
        title, paras = (fetch or fetch_url)(url)
    except MaterialError as e:
        store.set_material_text(source_id, [], error=str(e))
        return None
    store.set_material_text(source_id, paras, error=None if paras else "no text found on the page",
                            synced_at=time.time(), size=sum(len(p.encode("utf-8")) for p in paras))
    return title


def import_url(store, project, url, fetch=None):
    """A link → a material. A "Только локально" project stores it with the error "offline" and never fetches."""
    url = check_url(url)
    title = urlsplit(url).hostname + (urlsplit(url).path.rstrip("/") or "")
    if project.get("local_only"):
        source = store.create_material(project["id"], "url", title, import_format="url", url=url, error=OFFLINE)
        return store.set_material_text(source["id"], [])
    source = store.create_material(project["id"], "url", title, import_format="url", url=url)
    page_title = _apply_fetch(store, source["id"], url, fetch)
    if page_title:
        store.update_source(source["id"], audit=False, title=page_title)
    return store.get_material(source["id"])


def resync(store, project, source_id, fetch=None):
    """Fetch a link again. Offline in a "Только локально" project, as on import."""
    m = store.get_material(source_id)
    if m["material_kind"] != "url":
        raise MaterialError("only links can be synced")
    if project.get("local_only"):
        store._set_material(source_id, {"error": OFFLINE}, audit=False)
        return store.get_material(source_id)
    _apply_fetch(store, source_id, m["url"], fetch)
    store.audit_event("source", source_id, "resync", after={"url": m["url"]})
    return store.get_material(source_id)


def folder_files(folder):
    """The material files under a folder, hidden files and folders skipped, at most FOLDER_LIMIT; and whether
    there were more."""
    if not folder or not os.path.isdir(folder):
        raise MaterialError("folder not found")
    found, more = [], False
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.startswith(".") or not is_material_file(name):
                continue
            if len(found) >= FOLDER_LIMIT:
                more = True
                break
            found.append(os.path.join(root, name))
        if more:
            break
    return found, more


def import_folder(store, project, folder, progress=lambda done, total, name: None):
    """Every material file under a folder, one by one (the files are read, never changed)."""
    files, more = folder_files(folder)
    imported, failed = [], []
    for i, path in enumerate(files):
        progress(i, len(files), os.path.basename(path))
        try:
            with open(path, "rb") as f:
                data = f.read(MAX_BYTES + 1)
            imported.append(import_file(store, project, os.path.basename(path), data)["id"])
        except (MaterialError, StoreError, OSError) as e:
            failed.append(f"{os.path.basename(path)}: {e}")
    progress(len(files), len(files), "")
    return {"imported": imported, "failed": failed, "truncated": more, "limit": FOLDER_LIMIT}
