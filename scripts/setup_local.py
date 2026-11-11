"""Prepare the Windows CUDA environment used by the desktop launcher."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import NamedTemporaryFile
import time
from urllib.request import urlopen

from music_stem_lab.model_task import WEIGHTS_SHA256

CHECKPOINT = "models/5c90dfd2-34c22ccb.th"
WEIGHTS_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th"
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
IMPORT_CHECK = """
import fastapi, uvicorn, yt_dlp, imageio_ffmpeg, torch, torchaudio, soundfile
from demucs.apply import apply_model
from demucs.states import load_model
assert torch.version.cuda, "需要 CUDA 版 PyTorch"
"""
CUDA_CHECK = """
import torch
assert torch.cuda.is_available(), "找不到可用的 NVIDIA CUDA 顯示卡"
torch.ones(1, device="cuda").square().item()
"""


def progress(percent, message):
    print(f"[{percent:3d}%] {message}", flush=True)


def checked(python, code):
    if not python.is_file():
        return False
    try:
        return subprocess.run([str(python), "-c", code], capture_output=True,
                              timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def checkpoint_valid(path):
    if not path.is_file():
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == WEIGHTS_SHA256


def confirm(message):
    while True:
        try:
            answer = input(f"{message} [Y/N]：").strip().casefold()
        except EOFError:
            return False
        if answer in {"y", "n", ""}:
            return answer == "y"
        print("請輸入 Y 或 N。", flush=True)


def install(python, root, percent, message, *args):
    # Let pip report each file's byte progress and package installation output.
    progress(percent, message)
    command = [str(python), "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
               "--no-input", "--progress-bar", "on", *map(str, args)]
    with subprocess.Popen(command, cwd=root) as process:
        while True:
            try:
                status = process.wait(timeout=20)
                break
            except subprocess.TimeoutExpired:
                progress(percent, f"{message}（仍在進行）")
        if status:
            raise subprocess.CalledProcessError(status, command)


def download_checkpoint(path):
    progress(75, "下載 Demucs 六軌權重")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = None
    digest = hashlib.sha256()
    try:
        with urlopen(WEIGHTS_URL, timeout=60) as response, NamedTemporaryFile(
            dir=path.parent, prefix=path.name + ".", suffix=".part", delete=False
        ) as output:
            partial = Path(output.name)
            total = int(response.headers.get("Content-Length", "0"))
            received = 0
            previous = 75
            last_update = time.monotonic()
            while chunk := response.read(256 * 1024):
                output.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                percent = 75 + min(19, 19 * received // total) if total else 75
                if percent > previous or time.monotonic() - last_update >= 2:
                    progress(percent, f"已下載權重 {received / 1024**2:.1f} MiB")
                    previous = percent
                    last_update = time.monotonic()
        if digest.hexdigest() != WEIGHTS_SHA256:
            raise RuntimeError("下載的 Demucs 權重 SHA-256 不符，請重新啟動重試。")
        partial.replace(path)
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)


def prepare(root):
    progress(0, "檢查本機 Python、套件及模型權重")
    config_path = root / ".env.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError(".env.local.json 必須是 JSON 物件。")
    default_python = root / ".venv/Scripts/python.exe"
    python = (root / config.get("python", default_python)).resolve()
    default_checkpoint = (root / CHECKPOINT).resolve()
    checkpoint = (root / config.get("checkpoint", default_checkpoint)).resolve()

    has_packages = checked(python, IMPORT_CHECK)
    has_checkpoint = checkpoint_valid(checkpoint)
    if not has_packages or not has_checkpoint:
        missing = []
        if not has_packages:
            missing.append("本機 Python 環境或必要套件")
        if not has_checkpoint:
            missing.append("Demucs 六軌權重（缺少或驗證失敗）")
        print("需要準備：" + "、".join(missing), flush=True)
        if not confirm("是否下載缺少的檔案並自動建置環境？"):
            print("已取消建置。", flush=True)
            return None

        if not has_packages:
            if not checked(python, "import sys; assert (3, 11) <= sys.version_info[:2] <= (3, 13)"):
                if python != default_python.resolve():
                    raise RuntimeError("請修正 .env.local.json 的 python 路徑，或移除該設定以建立專案環境。")
                progress(10, "建立專案 Python 虛擬環境")
                subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True)
            if not checked(python, "import pip"):
                subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)
            wheels = root / "models/wheels"
            if (wheels / "environment.lock").is_file():
                try:
                    install(python, root, 15, "從本機備份安裝套件", "--no-index",
                            "--find-links", wheels, "-r", wheels / "environment.lock")
                except subprocess.CalledProcessError:
                    progress(15, "離線備份不完整或不相容，改用線上套件來源")
            if not checked(python, IMPORT_CHECK):
                install(python, root, 20, "安裝 PyTorch CUDA 與 TorchAudio",
                        "--index-url", CUDA_INDEX, "torch==2.8.0+cu128", "torchaudio==2.8.0+cu128")
                install(python, root, 55, "安裝網站與分軌套件", "--index-url", "https://pypi.org/simple",
                        "-r", root / "requirements.lock", "demucs==4.0.1", "soundfile==0.14.0")
            if not checked(python, IMPORT_CHECK):
                raise RuntimeError("套件安裝後仍無法載入，請查看上方安裝輸出。")

        if not has_checkpoint:
            if checkpoint != default_checkpoint and checkpoint.exists():
                raise RuntimeError("自訂權重驗證失敗。請修正 checkpoint 路徑或移除該設定。")
            download_checkpoint(checkpoint)

    progress(95, "驗證 CUDA 運算")
    if not checked(python, CUDA_CHECK):
        raise RuntimeError("無法執行 CUDA 運算。請確認 NVIDIA 顯示卡及其驅動程式支援 PyTorch CUDA。")
    progress(100, "本機環境已就緒")
    return python, checkpoint
