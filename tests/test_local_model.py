"""Exercise the local queue with an actual WAV source and a stand-in model."""
from pathlib import Path
from urllib.parse import unquote
import time
import wave

import pytest

from fastapi.testclient import TestClient

from music_stem_lab.app import create_app
from music_stem_lab.domain import Settings
from music_stem_lab.local_worker import LocalWorker, demo_audio
from music_stem_lab.model_task import STEMS, model_profile
from music_stem_lab.presets import DEFAULT_PRESET, PRESETS


@pytest.mark.parametrize("preset", [None, *PRESETS])
def test_real_job_uses_local_model_and_publishes_requested_wavs(tmp_path, monkeypatch, preset):
    def fixture_source(self, job, target):
        source = target / "source.wav"
        source.write_bytes(demo_audio())
        (target / "title.txt").write_text('測試歌曲 / Live? 2026.', encoding="utf-8")
        return source

    run_process = LocalWorker.run_process

    def fixture_model(self, job, command, stage, *args, **kwargs):
        if stage != "separating":
            return run_process(self, job, command, stage, *args, **kwargs)
        assert command[command.index("--preset") + 1] == (preset or DEFAULT_PRESET)
        assert args[0] == PRESETS[preset or DEFAULT_PRESET].timeout_seconds
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
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["model_inference_available"]
        assert [item["id"] for item in capabilities["model_presets"]] == list(PRESETS)
        response = client.post("/api/jobs/batch", json={
            "urls": ["https://youtu.be/EXAMPLE0001"], "mode": "separate",
            "execution_kind": "real", "extra_exports": ["no_guitar", "no_vocals"],
            "idempotency_key": "local-model-fixture", "model_preset": preset,
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
        assert job["model_preset"] == preset
        urls = {artifact["kind"]: artifact["url"] for artifact in job["artifacts"]}
        assert set(urls) == {"source", *STEMS, "no_guitar", "no_vocals", "manifest"}
        manifest = client.get(urls["manifest"]).json()
        assert manifest["profile"] == model_profile(preset or DEFAULT_PRESET)
        guitar = next(item for item in manifest["artifacts"] if item["kind"] == "guitar")
        assert guitar["filename"] == "吉他 - 測試歌曲 Live 2026.wav"
        response = client.get(urls["guitar"] + "?download=true", headers={"Range": "bytes=0-15"})
        assert response.status_code == 206
        assert unquote(response.headers["content-disposition"]).endswith(guitar["filename"])
