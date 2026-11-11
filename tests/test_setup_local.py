import hashlib
import io

import pytest

from scripts import setup_local as setup


def test_missing_environment_requires_consent_before_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt: "N")
    assert setup.prepare(tmp_path) is None
    assert not list(tmp_path.iterdir())
    assert "已取消建置" in capsys.readouterr().out


def test_clean_clone_can_prepare_and_reuse_its_environment(tmp_path, monkeypatch, capsys):
    python = tmp_path / ".venv/Scripts/python.exe"
    checkpoint = tmp_path / setup.CHECKPOINT
    installed = set()
    weights = b"fixture checkpoint"

    def create_venv(command, *, check):
        assert command[1:3] == ["-m", "venv"]
        python.parent.mkdir(parents=True)
        python.touch()

    def check(path, code):
        assert path == python
        if code == setup.IMPORT_CHECK:
            return installed == {20, 55}
        if code == setup.CUDA_CHECK:
            return installed == {20, 55}
        return path.exists()

    def install(path, root, percent, message, *args):
        assert path == python and root == tmp_path
        installed.add(percent)

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(weights))}

    monkeypatch.setattr("builtins.input", lambda prompt: "Y")
    monkeypatch.setattr(setup, "checked", check)
    monkeypatch.setattr(setup.subprocess, "run", create_venv)
    monkeypatch.setattr(setup, "install", install)
    monkeypatch.setattr(setup, "WEIGHTS_SHA256", hashlib.sha256(weights).hexdigest())
    monkeypatch.setattr(setup, "urlopen", lambda url, timeout: Response(weights))
    assert setup.prepare(tmp_path) == (python, checkpoint)
    assert checkpoint.read_bytes() == weights
    output = capsys.readouterr().out
    assert output.index(" 10%") < output.index(" 75%") < output.index(" 94%") < output.index("100%")
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("完整環境不應要求確認"))
    assert setup.prepare(tmp_path) == (python, checkpoint)


def test_unverified_download_is_discarded(tmp_path, monkeypatch):
    checkpoint = tmp_path / setup.CHECKPOINT
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b"previous checkpoint")

    class Response(io.BytesIO):
        headers = {}

    monkeypatch.setattr(setup, "urlopen", lambda url, timeout: Response(b"bad download"))
    with pytest.raises(RuntimeError, match="SHA-256"):
        setup.download_checkpoint(checkpoint)
    assert checkpoint.read_bytes() == b"previous checkpoint"
    assert not list(checkpoint.parent.glob("*.part"))
