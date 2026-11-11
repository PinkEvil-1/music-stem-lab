import subprocess
from types import SimpleNamespace

from fastapi.testclient import TestClient

from music_stem_lab import hardware
from music_stem_lab.app import create_app
from music_stem_lab.domain import Settings


def test_gpu_probe_uses_model_device_and_reports_mib(monkeypatch):
    def smi(command, **kwargs):
        assert command[:3] == ["nvidia-smi", "--id", "GPU-example-device"]
        return SimpleNamespace(stdout="Example GPU, 8192, 6144\n")

    monkeypatch.setattr(hardware.subprocess, "run", smi)
    assert hardware.read_gpu("example-device") == {
        "name": "Example GPU", "total_mib": 8192, "available_mib": 6144,
    }


def test_hardware_is_available_only_for_local_model_and_handles_missing_gpu(tmp_path, monkeypatch):
    def no_smi(*args, **kwargs):
        raise subprocess.TimeoutExpired("nvidia-smi", 3)

    monkeypatch.setattr(hardware.subprocess, "run", no_smi)
    monkeypatch.setattr(hardware, "read_ram", lambda: {"total_mib": 16384, "available_mib": 8192})
    with TestClient(create_app(Settings(data_dir=tmp_path / "default"))) as client:
        assert client.get("/api/hardware").status_code == 404

    settings = Settings(data_dir=tmp_path / "local", model_checkpoint=tmp_path / "model.th",
                        model_device_uuid="unreadable-fixture-device")
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/hardware")
        assert response.status_code == 200
        assert response.json() == {"gpu": None, "ram": {"total_mib": 16384, "available_mib": 8192}}
        presets = client.get("/api/capabilities").json()["model_presets"]
        assert [(p["vram_gib"], p["ram_gib"]) for p in presets] == [(3, 4), (5, 6), (7, 8)]
