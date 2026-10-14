"""Functions the page can call in the desktop window (pywebview js_api).

Downloads are disabled inside the native window, so files the user saves
(transcripts, FRD .docx) go through a native Save dialog here instead.
"""
import os
import shutil
import subprocess
import sys
import urllib.request
import webbrowser


class DesktopApi:
    def __init__(self, base_url, ask_path, opener=urllib.request.urlopen, ask_folder=None):
        self._base = base_url.rstrip("/")
        self._ask = ask_path            # filename -> chosen path or None
        self._open = opener
        self._ask_folder = ask_folder   # () -> chosen folder or None (Settings → Хранилище → Сменить папку…)

    def choose_folder(self):
        """A native folder picker: {"path"} or {"cancelled": True}."""
        if self._ask_folder is None:
            return {"error": "folder picker unavailable"}
        path = self._ask_folder()
        return {"path": path} if path else {"cancelled": True}

    def open_in_browser(self):
        webbrowser.open(self._base)

    def open_url(self, url):
        """Open an Atlassian sign-in page in the system browser (only Atlassian's own https pages)."""
        from urllib.parse import urlparse
        host = urlparse(url or "").hostname or ""
        if not url.startswith("https://") or not (host == "mcp.atlassian.com" or host.endswith(".atlassian.com")
                                                  or host.endswith(".atlassian.net")):
            return {"error": "only Atlassian pages can be opened"}
        webbrowser.open(url)
        return {"ok": True}

    def save_file(self, path, filename):
        """Fetch one of the app's own URLs (e.g. /api/documents/…/export.docx) and save it where the user says."""
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            return {"error": "invalid path"}
        target = self._ask(filename)
        if not target:
            return {"cancelled": True}
        try:
            with self._open(self._base + path, timeout=300) as resp, open(target, "wb") as f:
                shutil.copyfileobj(resp, f)
        except Exception as e:
            return {"error": f"Could not save the file: {e}"}
        return {"saved": target}

    def save_text(self, filename, text):
        target = self._ask(filename)
        if not target:
            return {"cancelled": True}
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            return {"error": f"Could not save the file: {e}"}
        return {"saved": target}

    def reveal(self, path):
        """Show a saved file in Finder / Explorer."""
        if not isinstance(path, str) or not os.path.exists(path):
            return {"error": "file not found"}
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", path], check=False)
        elif sys.platform == "win32":
            subprocess.run(["explorer", "/select,", os.path.normpath(path)], check=False)
        else:
            subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
        return {"ok": True}


def pywebview_asker(webview):
    def ask(filename):
        window = webview.windows[0] if webview.windows else None
        if window is None:
            return None
        result = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename)
        if not result:
            return None
        return result if isinstance(result, str) else result[0]
    return ask


def pywebview_folder_asker(webview):
    def ask():
        window = webview.windows[0] if webview.windows else None
        if window is None:
            return None
        result = window.create_file_dialog(webview.FileDialog.FOLDER)
        if not result:
            return None
        return result if isinstance(result, str) else result[0]
    return ask
