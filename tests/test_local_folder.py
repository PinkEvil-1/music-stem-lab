import os
from pathlib import Path
import time

from fastapi.testclient import TestClient

from music_stem_lab.app import create_app
from music_stem_lab.domain import Settings

HEADER = {"X-Music-Stem-Local": "1"}


def test_folder_action_requires_completed_job_and_opens_its_published_directory(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(os, "startfile", lambda path, operation: opened.append((Path(path), operation)), raising=False)
    settings = Settings(data_dir=tmp_path / "data", enable_local_folder=True, demo_stage_seconds=0)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/capabilities").json()["local_folder_enabled"]
        response = client.post("/api/jobs/batch", json={
            "urls": ["https://youtu.be/EXAMPLE0001"], "mode": "download_audio",
            "execution_kind": "demo", "idempotency_key": "open-folder-fixture",
        })
        assert response.status_code == 202, response.text
        job_id = response.json()["items"][0]["job_id"]
        job_url = f"/api/jobs/{job_id}"
        assert client.post(job_url + "/open-folder").status_code == 403
        cross_site = {**HEADER, "Origin": "https://example.com"}
        assert client.post(job_url + "/open-folder", headers=cross_site).status_code == 403
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = client.get(job_url).json()
            if job["state"] == "completed":
                break
            time.sleep(.05)
        assert job["state"] == "completed", job
        assert client.post(job_url + "/open-folder", headers=HEADER).status_code == 204
        path = settings.data_dir / "jobs" / job_id / "attempts" / job["attempt_id"] / "published"
        assert opened == [(path, "explore")]
        assert (path / "manifest.json").is_file()


def test_folder_action_rejects_unpublished_job(tmp_path, monkeypatch):
    def unexpected_open(*args):
        raise AssertionError("An unpublished job must never open Explorer")

    monkeypatch.setattr(os, "startfile", unexpected_open, raising=False)
    with TestClient(create_app(Settings(data_dir=tmp_path, enable_local_folder=True))) as client:
        response = client.post("/api/jobs/batch", json={
            "urls": ["https://youtu.be/EXAMPLE0001"], "mode": "separate",
            "execution_kind": "real", "idempotency_key": "queued-folder-fixture",
        })
        job_id = response.json()["items"][0]["job_id"]
        assert client.post(f"/api/jobs/{job_id}/open-folder", headers=HEADER).status_code == 409
