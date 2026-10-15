"""Shared LLM plumbing for summaries and requirement extraction.

Claude goes through the official anthropic SDK (streaming, server-side refusal
fallback on Claude Opus 5, prompt caching, typed errors → clear messages);
local models through the built-in llama-server (core/local_llm.py). Spec FR-SET-02, D-02.
"""
import json
import re
from contextlib import contextmanager

import anthropic

from core import local_llm, usage

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MODELS_WITH_DEFAULT_FALLBACKS = {"claude-opus-5"}
CLAUDE_MAX_TOKENS = 32000


class LLMError(Exception):
    """A user-facing problem (bad key, no internet, model missing…)."""


def claude_params(model, system, messages, max_tokens=CLAUDE_MAX_TOKENS, **extra):
    params = dict(model=model, max_tokens=max_tokens, system=system, messages=messages,
                  # Caches the prompt prefix, so re-running on the same source is cheap.
                  cache_control={"type": "ephemeral"}, **extra)
    if model in MODELS_WITH_DEFAULT_FALLBACKS:
        # If a safety classifier declines, the API re-runs the request on Anthropic's
        # recommended fallback model instead of returning a refusal.
        params.update(betas=[FALLBACK_BETA], fallbacks="default")
    return params


@contextmanager
def claude_errors(model):
    """Translate SDK errors into messages a BA can act on."""
    try:
        yield
    except anthropic.AuthenticationError:
        raise LLMError("Anthropic rejected the API key. Check it in Settings.")
    except anthropic.PermissionDeniedError:
        raise LLMError(f"This API key isn't allowed to use {model}. Check your Anthropic account or pick another model in Settings.")
    except anthropic.NotFoundError:
        raise LLMError(f"The model {model} isn't available to this API key. Pick another model in Settings.")
    except anthropic.RequestTooLargeError:
        raise LLMError("This text is too large to send in one request.")
    except anthropic.RateLimitError as e:
        wait = e.response.headers.get("retry-after") if e.response is not None else None
        raise LLMError("Anthropic rate limit reached. " + (f"Try again in {wait} s." if wait else "Try again shortly."))
    except anthropic.OverloadedError:
        raise LLMError("Anthropic is overloaded right now. Try again in a minute.")
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error ({e.status_code}): {e.message}")
    except (anthropic.APIConnectionError, anthropic.APITimeoutError):
        raise LLMError("Could not reach Anthropic. Check your internet connection.")


def model_name(prefs):
    if prefs["llm_provider"] == "local":
        return local_label(prefs)
    return prefs["claude_model"]


def local_label(prefs):
    m = local_llm.MODELS_BY_ID.get(_local_model(prefs))
    return m.label if m else "local model"


def _local_model(prefs):
    try:
        return local_llm.resolve_model(prefs.get("local_model"))
    except local_llm.LocalModelError:
        return prefs.get("local_model") or None


LANGUAGE_NAMES = {"ru": "Russian", "en": "English"}


def output_language(project, fallback=None):
    """The language the AI writes in for this project: its setting, or the fallback when "auto"."""
    lang = (project or {}).get("language") or "auto"
    return lang if lang in LANGUAGE_NAMES else fallback


def language_rule(project):
    """Added to every stage's prompt when the project has a fixed output language."""
    lang = output_language(project)
    if not lang:
        return ""
    return (f"Write everything you produce (statements, headings, text, stories) in {LANGUAGE_NAMES[lang]}, "
            "translating from the source's language when it differs. Quotes and evidence stay exactly as in the source.")


def for_project(prefs, project):
    """A "Local only" project never uses the cloud: it uses the built-in model."""
    if project and project["local_only"] and prefs["llm_provider"] == "claude":
        return {**prefs, "llm_provider": "local"}
    return prefs


def local_model_id(prefs):
    try:
        return local_llm.resolve_model(prefs.get("local_model"))
    except local_llm.LocalModelError as e:
        raise LLMError(str(e))


# ── structured JSON ──────────────────────────────────────────────────────────

def _claude_json(system, user, schema, model, api_key, client=None, max_tokens=CLAUDE_MAX_TOKENS):
    if not api_key:
        raise LLMError("Add your Anthropic API key in Settings, or choose a local model.")
    client = client or anthropic.Anthropic(api_key=api_key)
    params = claude_params(model, system, [{"role": "user", "content": user}], max_tokens=max_tokens,
                           output_config={"format": {"type": "json_schema", "schema": schema}})
    with claude_errors(model):
        # Streaming: extraction output can be long, and streaming avoids request timeouts.
        with client.beta.messages.stream(**params) as stream:
            message = stream.get_final_message()
    usage.record("llm_cloud", *usage.claude_tokens(message))
    if message.stop_reason == "refusal":
        raise LLMError("Claude declined to process this text.")
    if message.stop_reason == "max_tokens":
        raise LLMError("The answer was cut off at the length limit; try a shorter source.")
    text = next((b.text for b in message.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        raise LLMError("Claude returned malformed JSON.")


def _local_json(system, user, schema, model_id, opener=None):
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0, "stream": False,
            # Constrained decoding: the server can only produce JSON matching the schema.
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}}}
    kwargs = {"opener": opener} if opener else {}
    try:
        with local_llm.chat(model_id, body, **kwargs) as resp:
            reply = json.loads(resp.read())
    except local_llm.LocalModelError as e:
        raise LLMError(str(e))
    usage.record("llm_local", *usage.openai_tokens(reply))
    choice = (reply.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "length":
        raise LLMError("The local model's answer was cut off; try a shorter source.")
    content = re.sub(r"<think>.*?</think>", "", (choice.get("message") or {}).get("content") or "", flags=re.S)
    try:
        return json.loads(content)
    except ValueError:
        raise LLMError("The local model returned malformed JSON; try again.")


def complete_json(system, user, schema, prefs, api_key, claude_client=None, opener=None):
    """One structured call with the provider chosen in Settings; returns the parsed JSON."""
    if prefs["llm_provider"] == "local":
        return _local_json(system, user, schema, local_model_id(prefs), opener=opener)
    return _claude_json(system, user, schema, prefs["claude_model"], api_key, client=claude_client)
