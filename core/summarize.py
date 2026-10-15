"""Summarise a transcript with Claude (Anthropic API) or the built-in local model.

First AI stage of the app (spec increment 2 foundations: FR-SET-02 model per
stage, FR-SET-03 keys, D-02 transcript text may go to the cloud, local option).
The summary cites speakers and timestamps so every point can be traced back to
what was said (spec G2).
"""
import json
import re

import anthropic

from core import local_llm, skills, usage
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
    usage.record("llm_cloud", *usage.claude_tokens(message))

    if message.stop_reason == "refusal":
        raise SummaryError("Claude declined to summarise this transcript.")
    text = "".join(b.text for b in message.content if b.type == "text")
    if message.stop_reason == "max_tokens":
        text += "\n\n*(The summary was cut off because it reached the length limit.)*"
    return text


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


# ── built-in local model ─────────────────────────────────────────────────────

def summarize_with_local(transcript, model_id, on_delta, title=None, opener=None, system=None, user=None):
    body = {"stream": True, "temperature": 0.3, "stream_options": {"include_usage": True},   # counts for the stats
            "messages": [{"role": "system", "content": system or default_prompt()},
                         {"role": "user", "content": user or _user_content(transcript, title)}]}
    parts, think, tokens = [], _ThinkFilter(), (None, None)
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
                found = usage.openai_tokens(event)     # the last event carries the counts
                if found != (None, None):
                    tokens = found
                delta = ((event.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                piece = think.feed(delta)
                if piece:
                    parts.append(piece)
                    on_delta(piece)
    except local_llm.LocalModelError as e:
        raise SummaryError(str(e))
    usage.record("llm_local", *tokens)
    return re.sub(r"^\s+", "", "".join(parts))


# ── entry point ──────────────────────────────────────────────────────────────

def summarize(transcript, settings, api_key, on_delta, title=None, skillset=None, language_rule=""):
    """Summarise with the provider chosen in Settings and the summary skill in effect (global or project)."""
    if not transcript or not transcript.strip():
        raise SummaryError("There is no transcript text to summarise.")
    system = skills.compose(skillset or skills.resolve(), "summary")
    if language_rule:
        system += "\n\n" + language_rule
    if settings["llm_provider"] == "local":
        return summarize_with_local(transcript, local_model_id(settings), on_delta, title, system=system)
    return summarize_with_claude(transcript, settings["claude_model"], api_key, on_delta, title, system=system)


def generate(system, user, settings, api_key, on_delta):
    """One streamed completion with a ready system prompt and user message (recaps, core/notes.py)."""
    if settings["llm_provider"] == "local":
        return summarize_with_local(None, local_model_id(settings), on_delta, system=system, user=user)
    return summarize_with_claude(None, settings["claude_model"], api_key, on_delta, system=system, user=user)
