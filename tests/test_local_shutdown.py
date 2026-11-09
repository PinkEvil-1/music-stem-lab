from fastapi.testclient import TestClient

from music_stem_lab.app import create_app
from music_stem_lab.domain import Settings

HEADER = {"X-Music-Stem-Shutdown": "test-local-secret"}
PATH = "/api/local/shutdown"


def test_shutdown_authenticates_and_leaves_queued_job(tmp_path):
    stopped = []
    app = create_app(Settings(data_dir=tmp_path, worker_token="", local_workers=False),
                     shutdown=lambda: stopped.append(True), shutdown_token=HEADER["X-Music-Stem-Shutdown"])
    with TestClient(app) as client:
        assert client.get("/api/capabilities").json()["local_shutdown_enabled"]
        assert client.post(PATH).status_code == 403
        assert client.post(PATH, headers={**HEADER, "Origin": "https://example.com"}).status_code == 403
        job = app.state.store.submit(["https://youtu.be/EXAMPLE0001"], "download_audio", "real", "shutdown-queued")
        job_id = job["items"][0]["job_id"]
        assert client.post(PATH, headers=HEADER).status_code == 204
        assert stopped == [True]
        assert app.state.store.detail(job_id)["state"] == "queued"


def test_shutdown_does_not_interrupt_running_work(tmp_path):
    stopped = []
    app = create_app(Settings(data_dir=tmp_path, worker_token="", local_workers=False),
                     shutdown=lambda: stopped.append(True), shutdown_token=HEADER["X-Music-Stem-Shutdown"])
    with TestClient(app) as client:
        store = app.state.store
        store.submit(["https://youtu.be/EXAMPLE0001"], "download_audio", "real", "shutdown-running")
        job = store.claim("test", "real", ["download_audio"])
        assert client.post(PATH, headers=HEADER).status_code == 409
        assert store.detail(job["id"])["state"] == "running"
        assert not stopped
