"""Requirements on the fly while recording (spec 5.0 C4.2): core/live_atoms.py and the /live route's atoms."""
import os
import threading
import time

import pytest

from core import atoms as atoms_mod
from core.live_atoms import LiveAtoms, extractor, reconcile
from core.recorder import DualChannelRecorder
from core.store import Store
from tests.test_live import recording_app  # noqa: F401  (fixture)
from tests.test_recorder import tone_source, wait_for

LINES = [("BA", "Добрый день, начнём"), ("OTHER", "Заявки дилеров дублируются каждый день"),
         ("BA", "Нужна проверка дублей по VIN"), ("OTHER", "И по номеру телефона тоже"),
         ("BA", "Хорошо, записал"), ("OTHER", "Ещё нужен отчёт по дублям раз в неделю")]


@pytest.fixture()
def store(tmp_path):
    return Store(root=str(tmp_path / "lib"), user="ba")


@pytest.fixture()
def source(store):
    return store.create_source(store.current_project()["id"], "recording", "Встреча", status="recording")


def say(store, source, lines, at=0.0):
    return store.append_provisional_segments(source["id"], [
        {"speaker": who, "start": at + 2.0 * i, "end": at + 2.0 * i + 1.5, "text": text} for i, (who, text) in enumerate(lines)])


class FakeExtract:
    """extract(segments, context): one candidate per line containing `needle`, evidence verified like the real one."""

    def __init__(self, source_id, needle="VIN", gate=None, fail=False):
        self.source_id, self.needle, self.gate, self.fail = source_id, needle, gate, fail
        self.calls = []

    def __call__(self, segments, context):
        self.calls.append(([s["idx"] for s in segments], [s["idx"] for s in context]))
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise RuntimeError("model exploded")
        out = []
        for s in segments:
            if self.needle in s["text"]:
                ev = atoms_mod.verify_evidence([{"segment": s["idx"], "quote": s["text"]}], segments, self.source_id)
                out.append({"type": "functional", "statement": "Система: " + s["text"], "evidence": ev})
        return out


def live(store, source, extract, **kw):
    return LiveAtoms(source["id"], source["project_id"], store, extract, **kw)


def test_a_pass_runs_only_with_enough_new_segments_and_sends_earlier_lines_as_context(store, source):
    fake = FakeExtract(source["id"])
    la = live(store, source, fake, min_segments=4, context=2)
    say(store, source, LINES[:3])
    assert la.run_pass() == [] and fake.calls == []            # 3 new lines: not yet
    say(store, source, LINES[3:4], at=6.0)
    ids = la.run_pass()
    assert fake.calls == [([0, 1, 2, 3], [])] and len(ids) == 1
    say(store, source, LINES[4:6], at=8.0)
    assert la.run_pass() == [] and len(fake.calls) == 1        # only 2 new since the last pass
    say(store, source, LINES[:2], at=12.0)
    la.run_pass()
    assert fake.calls[-1] == ([4, 5, 6, 7], [2, 3])            # the new lines, the last 2 earlier ones as context


def test_candidates_become_pending_live_atoms_with_verified_evidence(store, source):
    say(store, source, LINES[:4])

    def complete(system, user, schema, prefs, api_key, ollama_url):
        assert "[S2]" in user and "Earlier in the meeting" not in user
        return {"atoms": [{"type": "functional", "statement": "Проверять дубли по VIN",
                           "evidence": [{"segment": 2, "quote": "проверка дублей по VIN"}]},
                          {"type": "functional", "statement": "Выдумка", "evidence": [{"segment": 1, "quote": "этого не было"}]}]}
    extract = extractor(store, source["id"], {"llm_provider": "claude"}, "k", "", complete=complete)
    ids = live(store, source, extract).run_pass()
    assert len(ids) == 1                                       # no evidence, no atom
    [a] = store.list_atoms(source["project_id"])
    assert a["status"] == "pending" and a["live"] == 1 and a["stale_evidence"] == 0
    assert [(e["segment_idx"], e["quote"]) for e in a["evidence"]] == [(2, "проверка дублей по VIN")]


def test_the_context_lines_are_shown_but_never_cited(store, source):
    say(store, source, LINES[:4])
    seen = []

    def complete(system, user, schema, prefs, api_key, ollama_url):
        seen.append(user)
        return {"atoms": [{"type": "functional", "statement": "Из контекста",
                           "evidence": [{"segment": 0, "quote": "Добрый день, начнём"}]}]}
    la = live(store, source, extractor(store, source["id"], {"llm_provider": "claude"}, "k", "", complete=complete))
    la.run_pass()
    say(store, source, LINES[4:6] + LINES[1:3], at=8.0)
    assert la.run_pass() == []                                 # the quote is in a context line only: dropped
    assert "Earlier in the meeting" in seen[1] and "  [S0]" in seen[1]


def test_a_slow_pass_is_not_overlapped(store, source):
    gate = threading.Event()
    fake = FakeExtract(source["id"], gate=gate)
    la = live(store, source, fake, min_segments=1)
    say(store, source, LINES[:4])
    assert la.tick() is True
    assert wait_for(lambda: len(fake.calls) == 1)
    say(store, source, LINES[4:5], at=8.0)
    assert la.tick() is False and la.skipped == 1             # the first pass is still waiting for the model
    gate.set()
    assert wait_for(lambda: not la.busy)
    assert la.tick() is True
    assert wait_for(lambda: len(fake.calls) == 2 and not la.busy)
    assert fake.calls[1][0] == [4]


def test_an_exception_is_logged_and_never_touches_the_recorder(tmp_path, store, source):
    rec = DualChannelRecorder(str(tmp_path / "rec"), {"mic": tone_source(1000), "sys": tone_source(2000)})
    rec.start()
    try:
        fake = FakeExtract(source["id"], fail=True)
        la = live(store, source, fake, min_segments=1)
        say(store, source, LINES[:2])
        frames = rec.status()["channels"]["mic"]["frames"]
        assert la.tick() is True
        assert wait_for(lambda: la.errors == 1 and not la.busy)
        assert rec.recording and not rec.paused
        assert wait_for(lambda: rec.status()["channels"]["mic"]["frames"] > frames)
        say(store, source, LINES[2:3], at=4.0)
        fake.fail = False
        assert la.tick() is True                               # the next pass runs as usual
        assert wait_for(lambda: len(fake.calls) == 2 and not la.busy)
    finally:
        result = rec.stop()
    assert os.path.getsize(result["mic"]) > 44 and os.path.getsize(result["sys"]) > 44


def test_nothing_is_saved_after_stop(store, source):
    gate = threading.Event()
    la = live(store, source, FakeExtract(source["id"], gate=gate), min_segments=1)
    say(store, source, LINES[:4])
    la.tick()
    assert wait_for(lambda: la.busy)
    la.stop()
    gate.set()
    assert wait_for(lambda: not la.busy)
    assert store.list_atoms(source["project_id"]) == [] and la.tick() is False


def test_the_thread_ticks_every_window(store, source):
    fake = FakeExtract(source["id"])
    say(store, source, LINES[:4])
    la = live(store, source, fake, window=0.05).start()
    try:
        assert wait_for(lambda: len(store.list_atoms(source["project_id"])) == 1)
    finally:
        la.stop()


# ── the final pass ─────────────────────────────────────────────────────────────

def final_transcript(store, source, lines):
    store.delete_provisional_segments(source["id"])
    store.save_transcript(source["id"], {"segments": [{"speaker": w, "start": 3.0 * i, "end": 3.0 * i + 2, "text": t}
                                                      for i, (w, t) in enumerate(lines)]})


def test_final_pass_keeps_live_atoms_rewrites_moved_indices_and_flags_lost_quotes(store, source):
    say(store, source, LINES[:6])
    pid = source["project_id"]
    fake = FakeExtract(source["id"], needle="дубл")
    live(store, source, fake, min_segments=1).run_pass()
    by_quote = {a["evidence"][0]["quote"]: a for a in store.list_atoms(pid)}
    assert set(by_quote) == {LINES[1][1], LINES[2][1], LINES[5][1]}
    # the final pass hears it differently: one line moves, one is gone, one becomes a different line
    final_transcript(store, source, [("BA", "Здравствуйте"), ("BA", "Добрый день, начнём"),
                                     ("BA", "Итак, нужна проверка дублей по VIN, это главное"),
                                     ("OTHER", "Заявки дилеров повторяются"), ("OTHER", LINES[5][1])])
    assert reconcile(store, source["id"]) == {"checked": 3, "moved": 1, "stale": 1}
    after = {a["id"]: a for a in store.list_atoms(pid)}
    vin = after[by_quote[LINES[2][1]]["id"]]
    assert vin["stale_evidence"] == 0 and vin["evidence"][0]["segment_idx"] == 2 and vin["evidence"][0]["start"] == 6.0
    report = after[by_quote[LINES[5][1]]["id"]]
    assert report["stale_evidence"] == 0 and report["evidence"][0]["segment_idx"] == 4
    lost = after[by_quote[LINES[1][1]]["id"]]
    assert lost["stale_evidence"] == 1 and lost["evidence"][0]["segment_idx"] is None and lost["status"] == "pending"
    assert lost["evidence"][0]["quote"] == LINES[1][1]          # the quote itself is kept
    marks = store.atom_marks(source["id"])
    assert set(marks) == {2, 4}                                 # no line is marked by a lost quote


def test_the_final_extraction_keeps_live_atoms_and_folds_its_duplicates_into_them(store, source):
    say(store, source, LINES[:4])
    pid = source["project_id"]
    [live_id] = live(store, source, FakeExtract(source["id"])).run_pass()
    store.update_atom(live_id, status="accepted")
    final_transcript(store, source, [("BA", "Нужна проверка дублей по VIN"), ("OTHER", "Нужен экспорт в Excel")])
    reconcile(store, source["id"])

    def complete(system, user, schema, prefs, api_key, ollama_url):
        if "duplicates" in schema["properties"]:
            new = {k: line for k, line in (line.split(" ", 1) for line in user.splitlines())}
            n = next(k for k, v in new.items() if k.startswith("N") and "VIN" in v)
            e = next(k for k, v in new.items() if k.startswith("E") and "VIN" in v)
            return {"duplicates": [{"new": n, "same_as": e}], "conflicts": []}
        return {"atoms": [{"type": "functional", "statement": "Проверять дубли по VIN",
                           "evidence": [{"segment": 0, "quote": "проверка дублей по VIN"}]},
                          {"type": "functional", "statement": "Экспорт в Excel",
                           "evidence": [{"segment": 1, "quote": "экспорт в Excel"}]}]}
    result = atoms_mod.extract_atoms(store, source["id"], {"llm_provider": "claude", "claude_model": "m"}, "k", "",
                                     complete=complete)
    assert result["merged"] == 1 and result["extracted"] == 1
    shown = [a for a in store.list_atoms(pid) if a["status"] != "merged"]
    assert sorted(a["statement"] for a in shown) == ["Система: Нужна проверка дублей по VIN", "Экспорт в Excel"]
    kept = store.get_atom(live_id)
    assert kept["status"] == "accepted" and kept["live"] == 1

    # a later re-extraction drops the pending atoms it made, never the live ones
    pending_live = live(store, source, FakeExtract(source["id"], needle="Excel"), min_segments=1)
    pending_live.last_idx = -1
    [pl] = pending_live.run_pass()
    atoms_mod.extract_atoms(store, source["id"], {"llm_provider": "claude", "claude_model": "m"}, "k", "",
                            complete=lambda *a: {"atoms": [], "duplicates": [], "conflicts": []})
    assert store.get_atom(pl)["status"] == "pending"


def test_run_job_rechecks_live_atoms_after_saving_the_final_transcript(app_module, monkeypatch):
    a = app_module
    src = a.library.create_source(a.library.current_project()["id"], "recording", "Live", status="processing")
    a.library.append_provisional_segments(src["id"], [{"speaker": "BA", "start": 0, "end": 1, "text": "Нужна проверка дублей по VIN"}])
    a.library.add_atoms(src["project_id"], [{"type": "functional", "statement": "VIN", "live": True, "evidence": [
        {"source_id": src["id"], "segment_idx": 0, "quote": "дублей по VIN"}]}])
    a.library.delete_provisional_segments(src["id"])
    monkeypatch.setattr(a, "_transcribe", lambda *args: {"text": "x", "segments": [
        {"start": 0.0, "end": 1.0, "text": "Добрый день"}, {"start": 1.0, "end": 2.0, "text": "проверка дублей по VIN"}]})
    job = a.jobs.create("transcribe", "Live")
    a.run_job(job, "x.wav", "x.wav", "v3_ctc", False, False, "cpu", source_id=src["id"])
    [atom] = a.library.source_atoms(src["id"])
    assert atom["segment_idx"] == 1 and atom["stale_evidence"] is False and atom["live"] is True


# ── route ──────────────────────────────────────────────────────────────────────

def test_live_route_lists_the_meetings_atoms_newest_first_with_new_after_a_timestamp(client, recording_app):  # noqa: F811
    a = recording_app
    sid = client.post("/desktop-record/start", json={}).get_json()["source_id"]
    pid = a.library.get_source(sid)["project_id"]
    a.library.append_provisional_segments(sid, [{"speaker": "BA", "start": 0, "end": 1, "text": "Нужна проверка по VIN"},
                                                {"speaker": "OTHER", "start": 1, "end": 2, "text": "И отчёт раз в неделю"}])
    [first] = a.library.add_atoms(pid, [{"type": "functional", "statement": "VIN", "live": True, "evidence": [
        {"source_id": sid, "segment_idx": 0, "start": 0, "speaker": "BA", "quote": "проверка по VIN"}]}])
    seen_at = time.time()
    time.sleep(0.01)
    [second] = a.library.add_atoms(pid, [{"type": "nfr", "statement": "Отчёт", "live": True, "evidence": [
        {"source_id": sid, "segment_idx": 1, "start": 1, "speaker": "OTHER", "quote": "отчёт раз в неделю"}]}])
    body = client.get(f"/api/sources/{sid}/live").get_json()
    assert [x["id"] for x in body["atoms"]] == [second, first]
    x = body["atoms"][1]
    assert {k: x[k] for k in ("type", "statement", "status", "quote", "segment_idx", "live")} == \
        {"type": "functional", "statement": "VIN", "status": "pending", "quote": "проверка по VIN", "segment_idx": 0, "live": True}
    assert all(x["new"] for x in body["atoms"]) and x["created_at"] > 0
    body = client.get(f"/api/sources/{sid}/live?atoms_after={seen_at}").get_json()
    assert [x["new"] for x in body["atoms"]] == [True, False]
    client.post("/api/projects/%s/atoms/bulk" % pid, json={"items": [{"id": first, "status": "accepted"}]})
    assert client.get(f"/api/sources/{sid}/live").get_json()["atoms"][1]["status"] == "accepted"
    assert client.get(f"/api/sources/{sid}/live?atoms_after=soon").status_code == 400


def test_live_requirements_start_only_when_on_and_the_ai_is_set_up(client, recording_app, monkeypatch):  # noqa: F811
    a = recording_app
    monkeypatch.setitem(a._session, "atoms", None)
    monkeypatch.setattr(a.settings, "secret", lambda name: None)
    client.post("/desktop-record/start", json={})
    assert a._session["atoms"] is None                         # no API key: nothing to ask
    client.post("/desktop-record/stop")
    monkeypatch.setattr(a.settings, "secret", lambda name: "key")
    client.post("/desktop-record/start", json={})
    la = a._session["atoms"]
    assert la is not None and la.window == 90 and la.min_segments == 4
    client.post("/desktop-record/stop")
    assert a._session["atoms"] is None and la._closed
    monkeypatch.setattr(a.settings, "load_settings", lambda: {"live_requirements": False})
    client.post("/desktop-record/start", json={})
    assert a._session["atoms"] is None
