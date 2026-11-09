from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import time
import wave

from fastapi.testclient import TestClient
import pytest

from music_stem_lab.app import create_app
from music_stem_lab.domain import MODES, Problem, Settings, video_id
from music_stem_lab.local_worker import demo_audio
from music_stem_lab.store import Store

TOKEN = "example-worker-token"
AUTH = {"Authorization": "Bearer " + TOKEN}
URLS = ["https://youtu.be/EXAMPLE0001", "https://youtu.be/EXAMPLE0002", "https://youtu.be/EXAMPLE0003"]

@pytest.fixture
def app(tmp_path):
    return create_app(Settings(data_dir=tmp_path / "data", worker_token=TOKEN, local_workers=False, min_free_bytes=0))

@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client

def submit(client, urls=None, mode="remove_guitar", key="example-key-0001"):
    response = client.post("/api/jobs/batch", json={
        "urls": urls or [URLS[0]], "mode": mode, "idempotency_key": key})
    assert response.status_code == 202, response.text
    return [i["job_id"] for i in response.json()["items"] if "job_id" in i]

def claim(client, modes=None, name="example-worker"):
    response = client.post("/api/worker/claim", headers=AUTH,
                           json={"worker_id": name, "modes": modes or list(MODES)})
    assert response.status_code == 200, response.text
    return response.json()["job"]

def headers(job):
    return {**AUTH, "X-Attempt-Token": job["attempt_token"]}

def upload(client, job, kind, data=None):
    return client.put("/api/worker/jobs/" + job["id"] + "/uploads/" + kind,
                      headers={**headers(job), "Content-Type": "application/octet-stream"},
                      content=data if data is not None else demo_audio())

def complete(client, job):
    return client.post("/api/worker/jobs/" + job["id"] + "/complete", headers=headers(job),
                       json={"profile_id": "example-test-profile", "version": "1"})

def fill(client, job):
    for kind in MODES[job["mode"]]:
        response = upload(client, job, kind)
        assert response.status_code == 200, response.text

@pytest.mark.parametrize("url", [
    URLS[0], "https://www.youtube.com/watch?v=EXAMPLE0001&list=example-list",
    "https://youtube.com/shorts/EXAMPLE0001", "https://m.youtube.com/watch?v=EXAMPLE0001",
    "https://youtu.be/EXAMPLE0001?t=20"])
def test_url_normalization(url):
    assert video_id(url) == "EXAMPLE0001"

@pytest.mark.parametrize("url", [
    "http://youtu.be/EXAMPLE0001", "https://youtube.com.evil.test/watch?v=EXAMPLE0001",
    "https://user:example-token@youtube.com/watch?v=EXAMPLE0001",
    "https://127.0.0.1/watch?v=EXAMPLE0001", "file:///example.wav",
    "https://youtu.be/EXAMPLE0001/extra", "https://www.youtube.com/playlist?list=example",
    "https://youtu.be:1234/EXAMPLE0001", "https://youtu.be/too_short",
    "https://www.youtube.com/watch?v=EXAMPLE0001&v=EXAMPLE0002",
    "https://youtube.com/live/EXAMPLE0001", "https://[invalid"])
def test_reject_unsafe_urls(url):
    with pytest.raises(Problem):
        video_id(url)

def test_static_and_capabilities(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    info = client.get("/api/capabilities").json()
    assert info["model_inference_available"] is False
    assert info["remote_worker_configured"] is True
    assert info["download_enabled"] is False
    assert "Content-Security-Policy" in client.get("/").headers
    assert TOKEN not in json.dumps(info)

def test_partial_batch_dedup_and_conflict(client):
    payload = {"urls": [URLS[0], "not a URL", URLS[1]], "mode": "remove_vocals", "idempotency_key": "example-batch-key"}
    first = client.post("/api/jobs/batch", json=payload)
    assert first.status_code == 202
    assert "error" in first.json()["items"][1]
    assert client.post("/api/jobs/batch", json=payload).json() == first.json()
    assert client.get("/api/jobs").json()["total"] == 2
    assert client.post("/api/jobs/batch", json={**payload, "mode": "remove_guitar"}).status_code == 409

def test_invalid_batch_has_no_jobs(client):
    reply = client.post("/api/jobs/batch", json={"urls": ["bad"], "mode": "download_audio", "idempotency_key": "example-invalid"})
    assert reply.status_code == 422
    assert client.get("/api/jobs").json()["total"] == 0

def test_fifo_and_retry_tail(client):
    ids = submit(client, URLS)
    assert claim(client, ["download_audio"]) is None
    job = claim(client)
    assert job["id"] == ids[0]
    assert claim(client) is None
    assert client.delete("/api/jobs/" + ids[0]).status_code == 409
    assert client.post("/api/worker/jobs/" + ids[0] + "/finish", headers=headers(job),
                       json={"state": "failed", "error_code": "MODEL_NOT_CONFIGURED"}).status_code == 200
    assert client.post("/api/jobs/" + ids[0] + "/retry").status_code == 200
    assert claim(client)["id"] == ids[1]

def test_atomic_claim_two_store_instances(app):
    a = app.state.store
    a.submit(URLS, "remove_guitar", "real", "example-concurrency")
    b = Store(app.state.settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda store: store.claim("example", "real", list(MODES)), [a, b]))
    assert len([r for r in results if r is not None]) == 1

def test_cancel_requires_worker_ack(client):
    job_id = submit(client)[0]
    job = claim(client)
    reply = client.post("/api/jobs/" + job_id + "/cancel").json()
    assert reply["state"] == "running" and reply["cancel_requested"]
    assert upload(client, job, "source").status_code == 409
    heartbeat = client.post("/api/worker/jobs/" + job_id + "/heartbeat", headers=headers(job), json={"stage": "fetching"})
    assert heartbeat.json()["cancel_requested"]
    assert client.post("/api/worker/jobs/" + job_id + "/finish", headers=headers(job),
                       json={"state": "cancelled"}).json()["state"] == "cancelled"

def test_expired_lease_recovery_and_fencing(client, app):
    ids = submit(client, URLS[:2])
    old = claim(client)
    with app.state.store.transaction() as c:
        c.execute("UPDATE jobs SET lease_until=0 WHERE id=?", (ids[0],))
    assert client.get("/api/jobs/" + ids[0]).json()["state"] == "recovering"
    assert claim(client) is None
    assert client.post("/api/jobs/" + ids[0] + "/recover", json={"old_worker_stopped": False}).status_code == 422
    assert client.post("/api/jobs/" + ids[0] + "/recover", json={"old_worker_stopped": True}).status_code == 200
    new = claim(client)
    assert new["id"] == ids[0]
    assert new["attempt_token"] != old["attempt_token"]
    assert upload(client, old, "source").status_code == 409
    assert client.post("/api/worker/jobs/" + ids[0] + "/finish", headers=headers(old),
                       json={"state": "failed"}).status_code == 409

def test_publish_and_range_and_manifest(client):
    job_id = submit(client)[0]
    job = claim(client)
    uploaded = upload(client, job, "source")
    artifact_id = uploaded.json()["artifact_id"]
    assert client.get("/api/artifacts/" + artifact_id + "/content").status_code == 404
    assert complete(client, job).status_code == 422
    for kind in ("guitar", "no_guitar"):
        assert upload(client, job, kind).status_code == 200
    response = complete(client, job)
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "completed"
    artifacts = response.json()["artifacts"]
    assert len(artifacts) == 4
    audio = next(a for a in artifacts if a["kind"] == "no_guitar")
    response = client.get(audio["url"], headers={"Range": "bytes=0-15"})
    assert response.status_code == 206 and len(response.content) == 16
    assert response.content[:4] == b"RIFF"
    assert "attachment" in client.get(audio["url"] + "?download=true").headers["content-disposition"]
    manifest = client.get(next(a for a in artifacts if a["kind"] == "manifest")["url"]).json()
    assert manifest["simulated"] is False
    assert "attempt_token" not in json.dumps(manifest)
    assert complete(client, job).status_code == 409

def test_mismatched_audio_cannot_complete(client):
    submit(client)
    job = claim(client)
    fill(client, job)
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 8000)
    assert upload(client, job, "guitar", data.getvalue()).status_code == 200
    assert complete(client, job).status_code == 422

def test_invalid_upload_and_path(client):
    submit(client)
    job = claim(client)
    assert upload(client, job, "source", b"not audio").status_code == 422
    assert upload(client, job, "other").status_code == 422
    reply = client.put("/api/worker/jobs/" + job["id"] + "/uploads/source?extension=../../escape",
                       headers={**headers(job), "Content-Type": "application/octet-stream"}, content=demo_audio())
    assert reply.status_code == 422

def test_corruption_detected(client, app):
    submit(client, mode="download_audio")
    job = claim(client); fill(client, job)
    artifacts = complete(client, job).json()["artifacts"]
    source = next(a for a in artifacts if a["kind"] == "source")
    with app.state.store.connect() as c:
        row = c.execute("SELECT path FROM artifacts WHERE id=?", (source["id"],)).fetchone()
    path = app.state.store.root / row["path"]
    content = bytearray(path.read_bytes()); content[-1] ^= 1; path.write_bytes(content)
    assert client.get(source["url"]).status_code == 410

def test_restart_preserves_queue_and_completed_files(client, app):
    ids = submit(client, URLS[:2], mode="download_audio")
    job = claim(client); fill(client, job); complete(client, job)
    restarted = create_app(app.state.settings)
    app.state.service_lock.__exit__()
    with TestClient(restarted) as other:
        assert other.get("/api/jobs").json()["total"] == 2
        assert other.get("/api/jobs/" + ids[0]).json()["state"] == "completed"
        assert claim(other)["id"] == ids[1]

def test_crash_after_rename_reconciles(client, app, monkeypatch):
    submit(client, mode="download_audio")
    job = claim(client); fill(client, job)
    original = os.replace
    def crash_after_move(src, dst):
        original(src, dst)
        raise OSError("example crash")
    with monkeypatch.context() as patch:
        patch.setattr("music_stem_lab.artifacts.os.replace", crash_after_move)
        with pytest.raises(OSError):
            app.state.files.publish(job["id"], job["attempt_token"], {"profile_id": "example", "version": "1"})
    assert app.state.store.detail(job["id"])["state"] == "publishing"
    app.state.files.reconcile()
    assert app.state.store.detail(job["id"])["state"] == "completed"
    app.state.files.reconcile()
    assert len(app.state.store.detail(job["id"])["artifacts"]) == 2

def test_cancel_between_intent_and_commit(client, app, monkeypatch):
    submit(client, mode="download_audio")
    job = claim(client); fill(client, job)
    original = app.state.files._commit_publish
    def cancel_first(job_id, token, **kwargs):
        app.state.store.cancel(job_id)
        return original(job_id, token, **kwargs)
    monkeypatch.setattr(app.state.files, "_commit_publish", cancel_first)
    assert complete(client, job).status_code == 409
    assert client.post("/api/worker/jobs/" + job["id"] + "/finish", headers=headers(job),
                       json={"state": "cancelled"}).json()["state"] == "cancelled"
    assert app.state.store.detail(job["id"])["artifacts"] == []

def test_delete_tombstone_recovery(client, app, monkeypatch):
    job_id = submit(client)[0]
    with monkeypatch.context() as patch:
        (app.state.store.root / "jobs" / job_id).mkdir(parents=True)
        def fail_delete(*args, **kwargs):
            raise OSError("example interruption")
        patch.setattr("music_stem_lab.artifacts.shutil.rmtree", fail_delete)
        with pytest.raises(OSError):
            app.state.files.delete(job_id)
    assert app.state.store.detail(job_id)["state"] == "deleting"
    app.state.files.reconcile()
    assert client.get("/api/jobs/" + job_id).status_code == 404

def test_quota_blocks_new_work(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, quota_bytes=1, local_workers=False, min_free_bytes=0))
    with TestClient(app) as c:
        assert c.post("/api/jobs/batch", json={"urls": [URLS[0]], "mode": "download_audio",
                      "idempotency_key": "example-quota"}).status_code == 507

def test_auth_origin_and_host(client):
    assert client.post("/api/worker/claim", json={"worker_id": "x", "modes": ["download_audio"]}).status_code == 401
    assert client.post("/api/jobs/" + "x" + "/cancel", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/jobs", headers={"Host": "evil.example"}).status_code == 400
    response = client.post("/api/worker/claim", headers=AUTH, json={"worker_id": "<script>example-token</script>", "modes": []})
    assert response.status_code == 422
    assert "example-token" not in response.text

def test_demo_explicit_and_no_network(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Demo must not launch a downloader")
    monkeypatch.setattr("music_stem_lab.local_worker.subprocess.Popen", no_network)
    app = create_app(Settings(data_dir=tmp_path, min_free_bytes=0, demo_stage_seconds=0.01))
    with TestClient(app) as client:
        response = client.post("/api/jobs/batch", json={"urls": URLS, "mode": "remove_guitar",
                    "execution_kind": "demo", "idempotency_key": "example-demo"})
        ids = [i["job_id"] for i in response.json()["items"]]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            jobs = [client.get("/api/jobs/" + i).json() for i in ids]
            assert sum(j["state"] in ("running", "publishing") for j in jobs) <= 1
            if all(j["state"] == "completed" for j in jobs):
                break
            time.sleep(0.05)
        assert all(j["state"] == "completed" for j in jobs), jobs
        first_events = [j["attempts"][0]["started_at"] for j in jobs]
        assert first_events == sorted(first_events)
        manifest_url = next(a["url"] for a in jobs[0]["artifacts"] if a["kind"] == "manifest")
        assert client.get(manifest_url).json()["simulated"] is True

def test_download_adapter_without_live_source(tmp_path, monkeypatch):
    from music_stem_lab.download_task import download
    class FakeYoutubeDL:
        def __init__(self, opts):
            self.opts = opts
            assert opts["cachedir"] is False and opts["noplaylist"]
            assert "cookiefile" not in opts and "cookiesfrombrowser" not in opts
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def extract_info(self, url, download=False):
            return {"duration": 1, "is_live": False}
        def download(self, urls):
            (tmp_path / "source.wav").write_bytes(demo_audio())
    monkeypatch.setattr("yt_dlp.YoutubeDL", FakeYoutubeDL)
    assert download(URLS[0], tmp_path, 1000000, 1200) == 0

def test_service_lock_prevents_second_coordinator(tmp_path):
    from music_stem_lab.maintenance import ServiceLock
    with ServiceLock(tmp_path):
        with pytest.raises(Problem):
            with ServiceLock(tmp_path):
                pass

def test_backup_restore_roundtrip(client, app, tmp_path):
    from music_stem_lab.maintenance import backup, restore
    submit(client, mode="download_audio")
    job = claim(client); fill(client, job)
    complete(client, job)
    snapshot, destination = tmp_path / "snapshot", tmp_path / "restored"
    with pytest.raises(Problem):
        backup(app.state.store.root, snapshot)  # Website must be stopped first.
    # Exercise the same release that occurs at actual server shutdown.
    app.state.service_lock.__exit__()
    backup(app.state.store.root, snapshot)
    restore(snapshot, destination)
    restored = create_app(Settings(data_dir=destination, local_workers=False, min_free_bytes=0))
    with TestClient(restored) as other:
        detail = other.get("/api/jobs/" + job["id"]).json()
        assert detail["state"] == "completed"
        assert all(a["available"] for a in detail["artifacts"])
    with pytest.raises(Problem):
        restore(snapshot, destination)
    manifest = json.loads((snapshot / "backup.json").read_text())
    file = snapshot / manifest["files"][0]["path"]
    file.write_bytes(b"corrupt")
    with pytest.raises(Problem):
        restore(snapshot, tmp_path / "should-not-exist")

def test_upload_size_limit(client, app):
    submit(client)
    job = claim(client)
    app.state.settings.max_upload_bytes = 100
    response = upload(client, job, "source", demo_audio())
    assert response.status_code == 413
    with app.state.store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0] == 0

def test_real_ffmpeg_container_decode(client, app, tmp_path):
    import subprocess
    from imageio_ffmpeg import get_ffmpeg_exe
    from music_stem_lab.decode import validate_decode
    wav = tmp_path / "example.wav"
    webm = tmp_path / "example.webm"
    wav.write_bytes(demo_audio())
    subprocess.run([get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", str(wav),
                    "-c:a", "libopus", str(webm)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    metadata = validate_decode(webm, 1200)
    assert metadata["validation"] == "ffmpeg_decode"
    assert 0.99 < metadata["decoded_duration_seconds"] < 1.02
    submit(client, mode="download_audio")
    job = claim(client)
    response = client.put("/api/worker/jobs/" + job["id"] + "/uploads/source?extension=.webm",
                headers={**headers(job), "Content-Type": "application/octet-stream"}, content=webm.read_bytes())
    assert response.status_code == 200
    assert response.json()["metadata"]["validation"] == "ffmpeg_decode"
    assert complete(client, job).status_code == 200

def test_decoder_rejects_fake_header_and_actual_overlength(tmp_path):
    from music_stem_lab.decode import validate_decode
    fake = tmp_path / "invalid.webm"
    fake.write_bytes(b"\x1aE\xdf\xa3" + b"fake" * 30)
    with pytest.raises(Problem) as failure:
        validate_decode(fake, 1)
    assert failure.value.code == "INVALID_AUDIO"
    audio = tmp_path / "long.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\x00\x00" * 32000)
    with pytest.raises(Problem) as failure:
        validate_decode(audio, 1)
    assert failure.value.code == "SOURCE_LIMIT"

def test_decoder_honors_cancel_checkpoint(tmp_path):
    from music_stem_lab.decode import validate_decode
    path = tmp_path / "example.wav"
    path.write_bytes(demo_audio())
    def cancelled():
        raise Problem("CANCEL_REQUESTED", "example cancellation")
    with pytest.raises(Problem) as failure:
        validate_decode(path, 1200, checkpoint=cancelled)
    assert failure.value.code == "CANCEL_REQUESTED"
