"""Exercise the local queue with an actual WAV source and a stand-in model."""
from pathlib import Path
import time
import wave

from fastapi.testclient import TestClient

from music_stem_lab.app import create_app
from music_stem_lab.domain import Settings
from music_stem_lab.local_worker import LocalWorker, demo_audio
from music_stem_lab.model_task import PROFILE, STEMS


def test_real_job_uses_local_model_and_publishes_requested_wavs(tmp_path, monkeypatch):
    def fixture_source(self, job, target):
        source = target / "source.wav"
        source.write_bytes(demo_audio())
        return source

    run_process = LocalWorker.run_process

    def fixture_model(self, job, command, stage, *args, **kwargs):
        if stage != "separating":
            return run_process(self, job, command, stage, *args, **kwargs)
        with wave.open(command[command.index("--source") + 1]) as pcm:
            assert (pcm.getframerate(), pcm.getnchannels()) == (44100, 2)
        target = Path(command[command.index("--target") + 1])
        kinds = command[command.index("--kinds") + 1:command.index("--rate")]
        for kind in kinds:
            (target / f"{kind}.wav").write_bytes(demo_audio())

    monkeypatch.setattr(LocalWorker, "download", fixture_source)
    monkeypatch.setattr(LocalWorker, "run_process", fixture_model)
    settings = Settings(data_dir=tmp_path / "data", worker_token="", model_checkpoint=tmp_path / "model.th")
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/capabilities").json()["model_inference_available"]
        response = client.post("/api/jobs/batch", json={
            "urls": ["https://youtu.be/EXAMPLE0001"], "mode": "separate",
            "execution_kind": "real", "extra_exports": ["no_guitar", "no_vocals"],
            "idempotency_key": "local-model-fixture",
        })
        assert response.status_code == 202, response.text
        job_id = response.json()["items"][0]["job_id"]
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = client.get(f"/api/jobs/{job_id}").json()
            if job["state"] in ("completed", "failed"):
                break
            time.sleep(.05)
        assert job["state"] == "completed", job
        urls = {artifact["kind"]: artifact["url"] for artifact in job["artifacts"]}
        assert set(urls) == {"source", *STEMS, "no_guitar", "no_vocals", "manifest"}
        assert client.get(urls["manifest"]).json()["profile"] == PROFILE
        assert client.get(urls["guitar"], headers={"Range": "bytes=0-15"}).status_code == 206
