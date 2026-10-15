"""A minimal MCP client over Streamable HTTP (spec D-08: the app calls MCP tools directly).

JSON-RPC 2.0: initialize → notifications/initialized → tools/call. Replies come
as JSON or as a Server-Sent Events stream; both are handled. The session id the
server returns is sent back on every request. Deterministic: no LLM anywhere.
"""
import itertools
import json
import time
import urllib.error
import urllib.request

from core.atlassian_auth import AuthRequired, user_agent

PROTOCOL = "2025-06-18"


class McpError(Exception):
    """A tool or transport error, with a message meant for the user."""


class RateLimited(McpError):
    pass


class McpSession:
    def __init__(self, url, token, opener=urllib.request.urlopen, retries=3, sleep=time.sleep):
        self.url = url
        self.token = token                      # callable(force_refresh=False) -> access token
        self.open = opener
        self.retries = retries
        self.sleep = sleep
        self.session_id = None
        self._ids = itertools.count(1)
        self._ready = False

    def _post(self, message, expect_reply=True, refreshed=False):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "Authorization": f"Bearer {self.token(force_refresh=refreshed)}",
                   "MCP-Protocol-Version": PROTOCOL, "User-Agent": user_agent()}
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=json.dumps(message).encode(), headers=headers, method="POST")
        try:
            with self.open(req, timeout=120) as resp:
                sid = resp.headers.get("Mcp-Session-Id") if hasattr(resp, "headers") else None
                if sid:
                    self.session_id = sid
                if not expect_reply:
                    return None
                ctype = (resp.headers.get("Content-Type") if hasattr(resp, "headers") else "") or ""
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 401 and not refreshed:
                return self._post(message, expect_reply, refreshed=True)      # the token may just have expired
            if e.code == 401:
                raise AuthRequired("The Jira session has expired. Connect again.")
            if e.code == 403:
                raise McpError("Atlassian refused access: check that your account can use this Jira site and project.")
            if e.code == 404 and self.session_id:
                self.session_id, self._ready = None, False                    # session expired on the server
                raise McpError("session expired")
            if e.code == 429 or e.code >= 500:
                raise RateLimited(f"Jira is busy ({e.code})")
            raise McpError(f"Jira MCP error ({e.code}): {e.read().decode(errors='replace')[:200]}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise RateLimited(f"Could not reach Atlassian ({getattr(e, 'reason', e)})")
        return self._parse(raw, ctype, message.get("id"))

    @staticmethod
    def _parse(raw, ctype, want_id):
        messages = []
        if "text/event-stream" in ctype:
            for block in raw.split("\n\n"):
                data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
                if data:
                    try:
                        messages.append(json.loads(data))
                    except ValueError:
                        continue
        elif raw.strip():
            parsed = json.loads(raw)
            messages = parsed if isinstance(parsed, list) else [parsed]
        for m in messages:
            if m.get("id") == want_id:
                if m.get("error"):
                    raise McpError(m["error"].get("message") or "MCP error")
                return m.get("result") or {}
        raise McpError("The Jira MCP server sent no reply.")

    def _call(self, method, params):
        """A request with retries and backoff for rate limits and hiccups (FR-JIRA-04 AC5)."""
        for attempt in range(self.retries + 1):
            try:
                if not self._ready and method != "initialize":
                    self.initialize()
                return self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params})
            except RateLimited:
                if attempt == self.retries:
                    raise
                self.sleep(min(20, 2 ** attempt))
            except McpError as e:
                if str(e) == "session expired" and attempt < self.retries:
                    continue
                raise

    def initialize(self):
        self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": "initialize",
                    "params": {"protocolVersion": PROTOCOL, "capabilities": {},
                               "clientInfo": {"name": "dictum", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
        self._ready = True

    def call(self, tool, **arguments):
        """Call a tool; returns its JSON result (or the plain text if it isn't JSON)."""
        result = self._call("tools/call", {"name": tool, "arguments": arguments})
        text = "".join(c.get("text", "") for c in result.get("content") or [] if c.get("type") == "text")
        if result.get("isError"):
            raise McpError(text.strip()[:500] or f"{tool} failed")
        if "structuredContent" in result and result["structuredContent"] is not None:
            return result["structuredContent"]
        try:
            return json.loads(text)
        except ValueError:
            return text
