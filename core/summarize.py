"""Summarise a transcript with Claude (Anthropic API) or a local model (Ollama).

First AI stage of the app (spec increment 2 foundations: FR-SET-02 model per
stage, FR-SET-03 keys, D-02 transcript text may go to the cloud, local option).
The summary cites speakers and timestamps so every point can be traced back to
what was said (spec G2).
"""
import json
import re
import urllib.error
import urllib.request

import anthropic

from core import local_llm, skills
from core.llm import LLMError, claude_errors, claude_params, local_model_id

def default_prompt():
    """The summary skill in effect globally (skills/summarize-source by default) plus house rules."""
    return skills.compose(skills.resolve(), "summary")

# The same user-facing error for summaries and extraction.
SummaryError = LLMError


def _user_content(transcript, title=None):
    header = f"Transcript of: {title}\n\n" if title else "Transcript:\n\n"
    return header + transcript.strip()


# ── Claude ───────────────────────────────────────────────────────────────────

def summarize_with_claude(transcript, model, api_key, on_delta, title=None, client=None, system=None, user=None):
    if not api_key:
        raise SummaryError("Add your Anthropic API key in Settings to create summaries with Claude.")
    client = client or anthropic.Anthropic(api_key=api_key)
    params = claude_params(model, system or default_prompt(), [{"role": "user", "content": user or _user_content(transcript, title)}])
    with claude_errors(model):
        with client.beta.messages.stream(**params) as stream:
            for text in stream.text_stream:
                on_delta(text)
            message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise SummaryError("Claude declined to summarise this transcript.")
    text = "".join(b.text for b in message.content if b.type == "text")
    if message.stop_reason == "max_tokens":
        text += "\n\n*(The summary was cut off because it reached the length limit.)*"
    return text


# ── Ollama (local) ───────────────────────────────────────────────────────────

class _ThinkFilter:
    """Drops <think>…</think> sections that some local reasoning models stream inline."""

    def __init__(self):
        self.inside = False
        self.pending = ""

    def feed(self, chunk):
        self.pending += chunk
        out = []
        while self.pending:
            tag = "</think>" if self.inside else "<think>"
            idx = self.pending.find(tag)
            if idx == -1:
                # Keep a possible partial tag at the end for the next chunk.
                keep = max((i for i in range(1, len(tag)) if self.pending.endswith(tag[:i])), default=0)
                if not self.inside:
                    out.append(self.pending[:len(self.pending) - keep])
                self.pending = self.pending[len(self.pending) - keep:] if keep else ""
                break
            if not self.inside:
                out.append(self.pending[:idx])
            self.pending = self.pending[idx + len(tag):]
            self.inside = not self.inside
        return "".join(out)


def summarize_with_ollama(transcript, model, on_delta, url, title=None, opener=urllib.request.urlopen, system=None, user=None):
    body = json.dumps({
        "model": model,
        "stream": True,
        "think": False,
        "messages": [{"role": "system", "content": system or default_prompt()},
                     {"role": "user", "content": user or _user_content(transcript, title)}],
    }).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    parts, think = [], _ThinkFilter()
    try:
        with opener(req, timeout=600) as resp:
            for line in resp:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("error"):
                    raise SummaryError(f"Local model error: {event['error']}")
                piece = think.feed(event.get("message", {}).get("content", ""))
                if piece:
                    parts.append(piece)
                    on_delta(piece)
                if event.get("done"):
                    break
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if e.code == 404 or "not found" in detail.lower():
            raise SummaryError(f"The local model {model} isn't installed. In a terminal run: ollama pull {model}")
        raise SummaryError(f"Ollama error ({e.code}): {detail[:200]}")
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        raise SummaryError("Ollama isn't running. Start the Ollama app, or choose Claude in Settings.")
    return re.sub(r"^\s+", "", "".join(parts))


# ── built-in local model ─────────────────────────────────────────────────────

def summarize_with_local(transcript, model_id, on_delta, title=None, opener=None, system=None, user=None):
    body = {"stream": True, "temperature": 0.3,
            "messages": [{"role": "system", "content": system or default_prompt()},
                         {"role": "user", "content": user or _user_content(transcript, title)}]}
    parts, think = [], _ThinkFilter()
    kwargs = {"opener": opener} if opener else {}
    try:
        with local_llm.chat(model_id, body, **kwargs) as resp:
            for raw in resp:                       # server-sent events: "data: {...}"
                line = raw.decode(errors="replace").strip() if isinstance(raw, bytes) else raw.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                if event.get("error"):
                    raise SummaryError(f"Local model error: {event['error']}")
                delta = ((event.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                piece = think.feed(delta)
                if piece:
                    parts.append(piece)
                    on_delta(piece)
    except local_llm.LocalModelError as e:
        raise SummaryError(str(e))
    return re.sub(r"^\s+", "", "".join(parts))


# ── entry point ──────────────────────────────────────────────────────────────

def summarize(transcript, settings, api_key, ollama_url, on_delta, title=None, skillset=None, language_rule=""):
    """Summarise with the provider chosen in Settings and the summary skill in effect (global or project)."""
    if not transcript or not transcript.strip():
        raise SummaryError("There is no transcript text to summarise.")
    system = skills.compose(skillset or skills.resolve(), "summary")
    if language_rule:
        system += "\n\n" + language_rule
    if settings["llm_provider"] == "local":
        return summarize_with_local(transcript, local_model_id(settings), on_delta, title, system=system)
    if settings["llm_provider"] == "ollama":
        return summarize_with_ollama(transcript, settings["ollama_model"], on_delta, ollama_url, title, system=system)
    return summarize_with_claude(transcript, settings["claude_model"], api_key, on_delta, title, system=system)


def generate(system, user, settings, api_key, ollama_url, on_delta):
    """One streamed completion with a ready system prompt and user message (recaps, core/notes.py)."""
    if settings["llm_provider"] == "local":
        return summarize_with_local(None, local_model_id(settings), on_delta, system=system, user=user)
    if settings["llm_provider"] == "ollama":
        return summarize_with_ollama(None, settings["ollama_model"], on_delta, ollama_url, system=system, user=user)
    return summarize_with_claude(None, settings["claude_model"], api_key, on_delta, system=system, user=user)
