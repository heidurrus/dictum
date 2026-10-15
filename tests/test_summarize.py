import json
import os
import stat
import sys
import types

import anthropic
import httpx2
import pytest

from core import settings, summarize
from core.summarize import SummaryError, _ThinkFilter, summarize_with_claude


# ── settings ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DICTUM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return tmp_path


def test_secrets_go_to_app_data_env_with_private_permissions(data_dir):
    settings.set_secret("ANTHROPIC_API_KEY", " sk-ant-test ")
    path = settings.env_file()
    assert os.path.dirname(path) == str(data_dir)
    assert open(path).read() == "ANTHROPIC_API_KEY=sk-ant-test\n"
    assert settings.secret("ANTHROPIC_API_KEY") == "sk-ant-test"
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    settings.set_secret("HF_TOKEN", "hf_x")
    settings.set_secret("ANTHROPIC_API_KEY", "")          # removing one key keeps the other
    assert open(path).read() == "HF_TOKEN=hf_x\n"
    assert settings.secret("ANTHROPIC_API_KEY") is None


def test_unknown_secret_rejected(data_dir):
    with pytest.raises(ValueError):
        settings.set_secret("PATH", "x")


def test_preferences_defaults_validation_and_persistence(data_dir):
    assert settings.load_settings()["claude_model"] == "claude-opus-5"
    settings.save_settings({"llm_provider": "local"})
    assert settings.load_settings()["llm_provider"] == "local"
    for bad in ({"llm_provider": "gpt"}, {"claude_model": "claude-2"}, {"local_model": "nope"}, {"nope": 1}):
        with pytest.raises(ValueError):
            settings.save_settings(bad)


def test_settings_from_before_5_0_3_load_without_the_removed_provider(data_dir):
    # 5.0.3 removed the Ollama provider and requirements on the fly: a settings.json written before loads with no
    # error, the provider as the built-in model, and the stale keys are dropped by the next save.
    with open(settings.settings_file(), "w", encoding="utf-8") as f:
        json.dump({"llm_provider": "ollama", "ollama_model": "qwen3:8b", "live_requirements": True,
                   "live_window_atoms": 90, "claude_model": "claude-sonnet-5"}, f)
    loaded = settings.load_settings()
    assert loaded["llm_provider"] == "local" and loaded["claude_model"] == "claude-sonnet-5"
    assert not {"ollama_model", "live_requirements", "live_window_atoms"} & set(loaded)
    settings.save_settings({"silence_stop_minutes": 5})
    with open(settings.settings_file(), encoding="utf-8") as f:
        stored = json.load(f)
    assert stored["llm_provider"] == "local" and stored["silence_stop_minutes"] == 5
    assert not {"ollama_model", "live_requirements", "live_window_atoms"} & set(stored)


def test_legacy_env_next_to_code_is_still_read(data_dir, monkeypatch, tmp_path):
    legacy = tmp_path / "legacy.env"
    legacy.write_text("HF_TOKEN=hf_old\n")
    monkeypatch.setattr(settings, "LEGACY_ENV_FILE", str(legacy))
    monkeypatch.delenv("HF_TOKEN", raising=False)
    settings.load_env()
    assert os.environ["HF_TOKEN"] == "hf_old"
    monkeypatch.delenv("HF_TOKEN")


# ── Claude ───────────────────────────────────────────────────────────────────

class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.text_stream = iter(chunks)
        self._final = types.SimpleNamespace(
            stop_reason=stop_reason,
            content=[types.SimpleNamespace(type="text", text="".join(chunks))])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._final


class FakeClient:
    def __init__(self, chunks=("## Summary\n", "Карточка клиента."), stop_reason="end_turn", error=None):
        self.calls = []
        client = self

        class Messages:
            def stream(self, **params):
                client.calls.append(params)
                if error:
                    raise error
                return FakeStream(list(chunks), stop_reason)

        self.beta = types.SimpleNamespace(messages=Messages())


def test_claude_streams_and_uses_caching_and_default_fallbacks():
    fake, deltas = FakeClient(), []
    out = summarize_with_claude("[Иван] [00:03 - 00:08] Привет", "claude-opus-5", "sk", deltas.append,
                                title="call.vtt", client=fake)
    assert out == "## Summary\nКарточка клиента." and deltas == ["## Summary\n", "Карточка клиента."]
    p = fake.calls[0]
    assert p["model"] == "claude-opus-5" and p["cache_control"] == {"type": "ephemeral"}
    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
    assert "Transcript of: call.vtt" in p["messages"][0]["content"]
    assert "same language as the transcript" in p["system"]


def test_other_models_do_not_send_fallbacks():
    fake = FakeClient()
    summarize_with_claude("x", "claude-sonnet-5", "sk", lambda t: None, client=fake)
    assert "fallbacks" not in fake.calls[0] and "betas" not in fake.calls[0]


def test_missing_key_is_a_settings_hint():
    with pytest.raises(SummaryError, match="API key in Settings"):
        summarize_with_claude("x", "claude-opus-5", None, lambda t: None, client=FakeClient())


def test_refusal_and_truncation():
    with pytest.raises(SummaryError, match="declined"):
        summarize_with_claude("x", "claude-opus-5", "sk", lambda t: None, client=FakeClient(stop_reason="refusal"))
    out = summarize_with_claude("x", "claude-opus-5", "sk", lambda t: None, client=FakeClient(stop_reason="max_tokens"))
    assert "cut off" in out


def _status_error(cls, code, headers=None):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx2.Response(code, request=req, headers=headers or {}), body=None)


@pytest.mark.parametrize("error,expected", [
    (lambda: _status_error(anthropic.AuthenticationError, 401), "rejected the API key"),
    (lambda: _status_error(anthropic.PermissionDeniedError, 403), "isn't allowed"),
    (lambda: _status_error(anthropic.NotFoundError, 404), "isn't available"),
    (lambda: _status_error(anthropic.RateLimitError, 429, {"retry-after": "30"}), "Try again in 30 s"),
    (lambda: _status_error(anthropic.OverloadedError, 529), "overloaded"),
    (lambda: anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "internet"),
])
def test_api_errors_become_clear_messages(error, expected):
    with pytest.raises(SummaryError, match=expected):
        summarize_with_claude("x", "claude-opus-5", "sk", lambda t: None, client=FakeClient(error=error()))


def test_think_filter_across_chunk_boundaries():
    f = _ThinkFilter()
    out = "".join(f.feed(c) for c in ["A<", "think", ">x</th", "ink>B", "<t", "C"])
    assert out + f.pending == "AB<tC"


def test_empty_transcript():
    with pytest.raises(SummaryError):
        summarize.summarize("  ", settings.DEFAULTS, "sk", lambda t: None)
