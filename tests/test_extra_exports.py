"""Optional mixes remain separate from the model's native stems."""
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from music_stem_lab.app import create_app
from music_stem_lab.domain import Settings
from music_stem_lab.local_worker import demo_audio
from music_stem_lab.store import Store

URL = "https://youtu.be/EXAMPLE0001"
AUTH = {"Authorization": "Bearer example-worker-token"}
STEMS = ["vocals", "drums", "bass", "guitar"]

@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path / "data", local_workers=False,
                               worker_token="example-worker-token", min_free_bytes=0))

@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client

def payload(exports, key="example-extra-exports"):
    return {"urls": [URL], "mode": "separate", "extra_exports": exports,
            "idempotency_key": key}

def submit(client, exports):
    response = client.post("/api/jobs/batch", json=payload(exports))
    assert response.status_code == 202, response.text
    return response.json()["items"][0]["job_id"]

def claim(client, stems=STEMS):
    response = client.post("/api/worker/claim", headers=AUTH,
                           json={"worker_id": "example-model", "modes": ["separate"], "native_stems": stems})
    assert response.status_code == 200, response.text
    return response.json()["job"]

def upload(client, job, kind):
    return client.put("/api/worker/jobs/" + job["id"] + "/uploads/" + kind,
                      headers={**AUTH, "X-Attempt-Token": job["attempt_token"],
                               "Content-Type": "application/octet-stream"}, content=demo_audio())

def publish(client, job):
    return client.post("/api/worker/jobs/" + job["id"] + "/complete",
                       headers={**AUTH, "X-Attempt-Token": job["attempt_token"]},
                       json={"profile_id": "example-native-model", "version": "1"})

@pytest.mark.parametrize("exports", [[], ["no_vocals"], ["no_guitar"], ["no_guitar", "no_vocals"]])
def test_optional_mix_combinations_preserve_all_native_stems(client, exports):
    job_id = submit(client, exports)
    before = client.get("/api/jobs/" + job_id).json()
    assert before["extra_exports"] == sorted(exports)
    job = claim(client)
    assert job["native_stems"] == STEMS
    assert job["extra_exports"] == sorted(exports)
    for kind in ["source", *STEMS]:
        assert upload(client, job, kind).status_code == 200
    if exports:
        assert publish(client, job).status_code == 422
    for kind in exports:
        assert upload(client, job, kind).status_code == 200
    for unselected in set(["no_vocals", "no_guitar"]) - set(exports):
        assert upload(client, job, unselected).status_code == 422
    complete = publish(client, job)
    assert complete.status_code == 200, complete.text
    artifacts = complete.json()["artifacts"]
    assert {a["kind"] for a in artifacts} == {"source", *STEMS, *exports, "manifest"}
    manifest = client.get(next(a["url"] for a in artifacts if a["kind"] == "manifest")).json()
    assert manifest["native_stems"] == STEMS
    assert manifest["extra_exports"] == sorted(exports)
    assert complete.json()["attempts"][0]["native_stems"] == STEMS

def test_extra_exports_participate_in_idempotency(client):
    body = payload(["no_vocals", "no_guitar"])
    first = client.post("/api/jobs/batch", json=body)
    assert first.status_code == 202
    assert client.post("/api/jobs/batch", json={**body, "extra_exports": ["no_guitar", "no_vocals"]}).json() == first.json()
    assert client.post("/api/jobs/batch", json={**body, "extra_exports": []}).status_code == 409

def test_worker_without_requested_stem_cannot_claim(client):
    job_id = submit(client, ["no_guitar"])
    assert claim(client, ["vocals", "drums", "bass", "other"]) is None
    assert client.get("/api/jobs/" + job_id).json()["state"] == "queued"
    assert claim(client)["id"] == job_id

def test_unselected_exports_do_not_require_extra_model_capabilities(client):
    submit(client, [])
    job = claim(client, ["vocals", "other"])
    assert job and job["native_stems"] == ["vocals", "other"]

@pytest.mark.parametrize("stems", [
    [], ["source"], ["manifest"], ["no_guitar"], ["vocals", "vocals"], ["../guitar"], ["Mixed Case"],
])
def test_reject_missing_or_invalid_model_stems(client, stems):
    submit(client, [])
    response = client.post("/api/worker/claim", headers=AUTH,
                           json={"worker_id": "example-model", "modes": ["separate"], "native_stems": stems})
    if not stems:
        assert response.status_code == 200 and response.json()["job"] is None
    else:
        assert response.status_code == 422

def test_download_only_does_not_accept_mix_options(client):
    assert client.post("/api/jobs/batch", json={**payload(["no_vocals"]), "mode": "download_audio"}).status_code == 422

def test_retry_and_restart_preserve_mix_selection(client, app):
    job_id = submit(client, ["no_vocals", "no_guitar"])
    job = claim(client)
    result = client.post("/api/worker/jobs/" + job_id + "/finish",
                         headers={**AUTH, "X-Attempt-Token": job["attempt_token"]},
                         json={"state": "failed", "error_code": "WORKER_ERROR"})
    assert result.status_code == 200
    assert client.post("/api/jobs/" + job_id + "/retry").json()["extra_exports"] == ["no_guitar", "no_vocals"]
    other = Store(app.state.settings)
    assert other.detail(job_id)["extra_exports"] == ["no_guitar", "no_vocals"]
    assert other.detail(job_id)["attempts"][0]["native_stems"] == STEMS

def test_additive_schema_upgrade_preserves_legacy_jobs(tmp_path):
    settings = Settings(data_dir=tmp_path, local_workers=False, min_free_bytes=0)
    store = Store(settings)
    result = store.submit([URL], "download_audio", "real", "example-existing-key")
    job_id = result["items"][0]["job_id"]
    with store.connect() as c:
        c.execute("ALTER TABLE jobs DROP COLUMN extra_exports")
        c.execute("ALTER TABLE jobs DROP COLUMN native_stems")
        c.execute("ALTER TABLE attempts DROP COLUMN native_stems")
        c.execute("PRAGMA user_version=1")
    upgraded = Store(settings)
    detail = upgraded.detail(job_id)
    assert detail["state"] == "queued" and detail["extra_exports"] == []
    assert detail["native_stems"] == []
    assert upgraded.submit([URL], "download_audio", "real", "example-existing-key") == result
    with upgraded.connect() as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
