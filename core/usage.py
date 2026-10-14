"""Usage counters for Settings → stats (spec 5.0 C9): one row per model call, embedding batch and transcription.

The modules that call a model report here (`record`); the app points the sink at the library's `usage` table.
Counting must never break the call it counts, so a failing sink is logged and ignored, and nothing is written
before a sink is set (unit tests of the model code).
"""
import logging

log = logging.getLogger("dictum.usage")
SAMPLE_RATE = 16000
_sink = None


def set_sink(fn):
    """fn(kind, tokens_in, tokens_out, seconds, project_id); None turns counting off."""
    global _sink
    _sink = fn


def _int(v):
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def record(kind, tokens_in=None, tokens_out=None, seconds=None, project_id=None):
    fn = _sink
    if fn is None:
        return
    try:
        fn(kind, _int(tokens_in), _int(tokens_out), None if seconds is None else float(seconds), project_id)
    except Exception:
        log.exception("Could not record usage")


def openai_tokens(reply):
    """(prompt, completion) from a llama-server reply or stream event: `usage`, else the `timings` it adds."""
    if not isinstance(reply, dict):
        return None, None
    u = reply.get("usage") or {}
    if u.get("prompt_tokens") is not None or u.get("completion_tokens") is not None:
        return u.get("prompt_tokens"), u.get("completion_tokens")
    t = reply.get("timings") or {}
    if t.get("prompt_n") is not None or t.get("predicted_n") is not None:
        return t.get("prompt_n"), t.get("predicted_n")
    return None, None


def claude_tokens(message):
    """(input incl. cached prompt, output) from an Anthropic message, or (None, None)."""
    u = getattr(message, "usage", None)
    if u is None:
        return None, None
    tin = sum(v for v in (getattr(u, "input_tokens", None), getattr(u, "cache_creation_input_tokens", None),
                          getattr(u, "cache_read_input_tokens", None)) if isinstance(v, int))
    out = getattr(u, "output_tokens", None)
    return (tin if isinstance(getattr(u, "input_tokens", None), int) else None), (out if isinstance(out, int) else None)


def audio_seconds(chunks, rate=SAMPLE_RATE):
    """Seconds of audio in waveform chunks (1-D arrays or tensors of samples)."""
    n = 0
    for c in chunks:
        shape = getattr(c, "shape", None)
        n += int(shape[-1]) if shape else len(c)
    return n / rate
