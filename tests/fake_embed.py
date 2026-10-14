"""A deterministic stand-in for the index's embedding model (tests and e2e/fake_llm_server.py).

Hashed bag of words: every word (lower case, 3+ letters) adds 1 to one of DIM buckets chosen by its MD5, and the
vector is normalised. Texts that share words are close; texts that share none are near 0.
"""
import hashlib
import re

import numpy as np

DIM = 256


def vector(text):
    v = np.zeros(DIM, dtype=np.float32)
    for word in re.findall(r"\w{3,}", (text or "").lower()):
        v[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1
    n = float(np.linalg.norm(v))
    return (v / n if n else v).tolist()


def fake_embed(texts, calls=None):
    texts = list(texts)
    if calls is not None:
        calls.append(texts)
    return [vector(t) for t in texts]


def install(monkeypatch_or_module, index_module, calls=None):
    """Make the index available and route embed() to the fake (pytest monkeypatch, or None to patch directly)."""
    embed = (lambda texts, opener=None: fake_embed(texts, calls))
    if monkeypatch_or_module is None:
        index_module.embed = embed
        index_module.available = lambda: True
    else:
        monkeypatch_or_module.setattr(index_module, "embed", embed)
        monkeypatch_or_module.setattr(index_module, "available", lambda: True)
