"""Sign-in to the Atlassian Remote MCP server (spec FR-SET-05, D-05, NFR-SEC-05).

OAuth 2.1 as the server advertises it: dynamic client registration (no secret,
public client), authorization code with PKCE (S256), refresh tokens. The redirect
lands on this app's own local server. Tokens are kept in a private file in the
app's data folder (readable only by the user, like the Anthropic key), never in
logs or exports. Not in the macOS Keychain: it prompts for access again and again
(PO decision D-21).
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MCP_BASE = "https://mcp.atlassian.com"
MCP_URL = MCP_BASE + "/v1/mcp"


def user_agent():
    """Atlassian's Cloudflare rejects Python's default "Python-urllib" agent (error 1010)."""
    import os
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")) as f:
            version = f.read().strip()
    except OSError:
        version = "dev"
    return f"Dictum/{version} (+https://getdictum.app)"


class AuthError(Exception):
    """A user-facing sign-in problem."""


class AuthRequired(AuthError):
    """Not signed in (or the session can't be refreshed): the user must connect again."""


# ── token storage ────────────────────────────────────────────────────────────

class FileStore:
    """JSON values in one private file in the app's data folder (0600 on macOS)."""

    def __init__(self, path=None):
        self._path = path

    @property
    def path(self):
        if self._path is None:
            from core.paths import app_data_dir
            self._path = os.path.join(app_data_dir(), "jira-auth.json")
        return self._path

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        from core.settings import _write_private
        _write_private(self.path, json.dumps(data))

    def get(self, name):
        return self._load().get(name)

    def set(self, name, value):
        data = self._load()
        data[name] = value
        self._save(data)

    def delete(self, name):
        data = self._load()
        if name in data:
            data.pop(name)
            self._save(data)


class MemoryStore:
    """For tests."""

    def __init__(self):
        self.data = {}

    def get(self, name):
        return self.data.get(name)

    def set(self, name, value):
        self.data[name] = json.loads(json.dumps(value))

    def delete(self, name):
        self.data.pop(name, None)


# ── OAuth ────────────────────────────────────────────────────────────────────

def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class AtlassianAuth:
    def __init__(self, store=None, opener=urllib.request.urlopen, clock=time.time, base=MCP_BASE):
        self._store = store
        self.open = opener
        self.clock = clock
        self.base = base
        self._pending = {}              # state → {verifier, redirect_uri, client_id, started}
        self._lock = threading.Lock()
        self._meta = None

    @property
    def store(self):
        if self._store is None:
            self._store = FileStore()
        return self._store

    def _request(self, url, data=None, form=False, method=None):
        headers = {"Accept": "application/json", "User-Agent": user_agent()}
        body = None
        if data is not None:
            if form:
                body = urllib.parse.urlencode(data).encode()
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(data).encode()
                headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.open(req, timeout=30) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise AuthError(f"Atlassian sign-in failed ({e.code}): {detail}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise AuthError(f"Could not reach Atlassian ({getattr(e, 'reason', e)}). Check your internet connection.")

    def metadata(self):
        if self._meta is None:
            self._meta = self._request(self.base + "/.well-known/oauth-authorization-server")
        return self._meta

    def _client(self, redirect_uri):
        """A registered client for this redirect URI (registered once, then reused)."""
        clients = self.store.get("clients") or {}
        if redirect_uri in clients:
            return clients[redirect_uri]
        reg = self._request(self.metadata()["registration_endpoint"], {
            "client_name": "Dictum", "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
            "token_endpoint_auth_method": "none"})
        if not reg.get("client_id"):
            raise AuthError("Atlassian did not register the app.")
        clients[redirect_uri] = reg["client_id"]
        self.store.set("clients", clients)
        return reg["client_id"]

    def start(self, redirect_uri):
        """The URL to open in the browser to sign in."""
        client_id = self._client(redirect_uri)
        verifier = _b64(secrets.token_bytes(32))
        state = _b64(secrets.token_bytes(16))
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if self.clock() - v["started"] < 900}
            self._pending[state] = {"verifier": verifier, "redirect_uri": redirect_uri, "client_id": client_id,
                                    "started": self.clock()}
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state,
                  "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"}
        return self.metadata()["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)

    def finish(self, state, code):
        """The browser came back to our redirect: exchange the code for tokens."""
        with self._lock:
            pending = self._pending.pop(state or "", None)
        if not pending:
            raise AuthError("This sign-in link has expired. Press “Подключить Jira” again.")
        tokens = self._request(self.metadata()["token_endpoint"], {
            "grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
            "client_id": pending["client_id"], "code_verifier": pending["verifier"]}, form=True)
        self._save(tokens, pending["client_id"])

    def _save(self, tokens, client_id, old=None):
        if not tokens.get("access_token"):
            raise AuthError("Atlassian did not return a token.")
        self.store.set("tokens", {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token") or (old or {}).get("refresh_token"),
            "expires_at": self.clock() + float(tokens.get("expires_in") or 3600) - 60,
            "client_id": client_id})

    def connected(self):
        return bool(self.store.get("tokens"))

    def access_token(self, force_refresh=False):
        """A valid access token, refreshed when it's about to expire."""
        tok = self.store.get("tokens")
        if not tok:
            raise AuthRequired("Jira is not connected.")
        if not force_refresh and tok["expires_at"] > self.clock():
            return tok["access_token"]
        if not tok.get("refresh_token"):
            self.store.delete("tokens")
            raise AuthRequired("The Jira session has expired. Connect again.")
        try:
            fresh = self._request(self.metadata()["token_endpoint"], {
                "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": tok["client_id"]},
                form=True)
        except AuthError:
            self.store.delete("tokens")
            raise AuthRequired("The Jira session has expired. Connect again.")
        self._save(fresh, tok["client_id"], old=tok)
        return self.store.get("tokens")["access_token"]

    def disconnect(self):
        tok = self.store.get("tokens")
        if tok:
            try:                           # best effort: revoke on Atlassian's side too
                self._request(self.metadata().get("revocation_endpoint") or self.metadata()["token_endpoint"],
                              {"token": tok.get("refresh_token") or tok["access_token"], "client_id": tok["client_id"]},
                              form=True)
            except AuthError:
                pass
        self.store.delete("tokens")
