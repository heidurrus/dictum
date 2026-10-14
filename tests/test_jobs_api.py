"""GET /api/jobs: what the status chip shows (jobs, downloads, the recorder)."""
import pytest

from core.jobs import JobStore


@pytest.fixture(autouse=True)
def quiet_machine(app_module, monkeypatch):
    monkeypatch.setattr(app_module, "jobs", JobStore())
    monkeypatch.setattr(app_module, "_recorder", None)
    monkeypatch.setattr(app_module.local_llm.installer, "state", {"status": "idle"})
    monkeypatch.setattr(app_module.asr_downloads, "status", lambda: None)


def test_nothing_running(client):
    assert client.get("/api/jobs").get_json() == {"jobs": [], "recording": None}


def test_running_job_with_progress(client, app_module):
    store = app_module.jobs
    job_id = store.create("transcribe", "Daily sync")
    store.set_progress(job_id, 42, "Transcribing segments… 4/10")
    done = store.create("summarize", "Old")
    store.finish(done, {"summary": "x"})
    body = client.get("/api/jobs").get_json()
    assert body["recording"] is None
    [job] = body["jobs"]
    assert job["id"] == job_id and job["kind"] == "transcribe" and job["label"] == "Daily sync"
    assert job["progress"] == 42 and job["message"].startswith("Transcribing")
    assert job["cancellable"] is False and job["started_at"] > 0


def test_job_without_progress_reports_null(client, app_module):
    app_module.jobs.create("extract", "Interview")
    [job] = client.get("/api/jobs").get_json()["jobs"]
    assert job["progress"] is None and job["kind"] == "extract"


def test_download_in_progress(client, app_module, monkeypatch):
    model_id = app_module.local_llm.MODELS[0].id
    monkeypatch.setattr(app_module.local_llm.installer, "state",
                        {"status": "downloading", "model": model_id, "done": 1024 ** 3, "total": 4 * 1024 ** 3, "error": None})
    monkeypatch.setattr(app_module.asr_downloads, "status",
                        lambda: {"model": "v3_e2e_rnnt", "status": "downloading", "done": 0, "total": 100, "error": None})
    jobs = client.get("/api/jobs").get_json()["jobs"]
    llm, asr = jobs
    assert llm["kind"] == "download" and llm["progress"] == 25 and llm["cancellable"] is True
    assert "1.0 / 4.0 GB" in llm["label"] and llm["cancel_url"] == "/api/local-llm/cancel"
    assert asr["kind"] == "download" and asr["progress"] == 0 and asr["cancel_url"] == "/api/asr/download/cancel"


def test_recording_in_progress(client, app_module, monkeypatch):
    class FakeRecorder:
        def status(self):
            return {"recording": True, "recording_id": "r1", "elapsed": 724.0, "channels": {}}

    monkeypatch.setattr(app_module, "_recorder", FakeRecorder())
    body = client.get("/api/jobs").get_json()
    assert body["recording"]["elapsed"] == 724.0 and body["jobs"] == []
