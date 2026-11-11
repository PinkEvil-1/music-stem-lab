import io
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import wave

from .artifacts import Artifacts
from .decode import pcm_command
from .domain import MODES, STAGES, DEMO_STEMS, Problem, required_artifacts
from .model_task import SAMPLE_RATE, STEMS, model_profile
from .presets import DEFAULT_PRESET, PRESETS
from .store import Store, uid

def demo_audio(frequency=440):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"".join(struct.pack("<h", int(1800 * math.sin(2 * math.pi * frequency * n / 16000)))
                                 for n in range(16000)))
    return output.getvalue()

class LocalWorker:
    def __init__(self, store: Store, files: Artifacts):
        self.store, self.files = store, files
        self.settings = store.settings
        self.stop = threading.Event()
        self.worker_id = "local-" + uid()
        self.thread = None
        self.real_modes = ["download_audio"] if self.settings.enable_download else []
        if self.settings.model_checkpoint is not None:
            self.real_modes.extend(mode for mode in MODES if mode != "download_audio")

    def start(self):
        self.thread = threading.Thread(target=self.loop, name="music-local-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=10)

    def checkpoint(self, job, stage, progress=None):
        if self.stop.is_set():
            raise Problem("LOCAL_SHUTDOWN", "本機執行器停止。")
        reply = self.store.heartbeat(job["id"], job["attempt_token"], stage, progress)
        if reply["cancel_requested"]:
            raise Problem("CANCEL_REQUESTED", "工作已要求取消。")

    def loop(self):
        while not self.stop.is_set():
            job = None
            try:
                self.files.capacity()
                job = self.store.claim(self.worker_id, "demo", list(MODES), DEMO_STEMS)
                if job is None and self.real_modes:
                    job = self.store.claim(self.worker_id, "real", self.real_modes, STEMS,
                                           supports_local_preset=self.settings.model_checkpoint is not None)
                if job:
                    self.execute(job)
                else:
                    self.stop.wait(0.25)
            except (Problem, OSError):
                self.stop.wait(0.5)

    def execute(self, job):
        try:
            if job["execution_kind"] == "demo":
                for i, stage in enumerate(STAGES):
                    self.checkpoint(job, stage, (i / len(STAGES)) * 100)
                    if self.stop.wait(self.settings.demo_stage_seconds):
                        raise Problem("LOCAL_SHUTDOWN", "執行器停止。")
                for i, kind in enumerate(required_artifacts(job)):
                    self.files.put(job["id"], job["attempt_token"], kind, ".wav", demo_audio(330 + i * 110))
                self.files.publish(job["id"], job["attempt_token"],
                                   {"profile_id": "synthetic-demo-v1", "version": "1",
                                    "description": "合成測試音，沒有下載 YouTube 或執行音源分離"})
            else:
                self.process_source(job)
        except (Problem, OSError) as error:
            code = error.code if isinstance(error, Problem) else "STORAGE_LIMIT"
            state = "cancelled" if code == "CANCEL_REQUESTED" else "failed"
            try:
                self.store.finish(job["id"], job["attempt_token"], state, code)
            except Problem:
                pass
        except Exception:
            try:
                self.store.finish(job["id"], job["attempt_token"], "failed", "WORKER_ERROR")
            except Problem:
                pass

    def run_process(self, job, command, stage, timeout, failure_code, timeout_code, monitor=None):
        self.checkpoint(job, stage)
        process = subprocess.Popen(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        start = time.monotonic()
        try:
            while process.poll() is None:
                self.checkpoint(job, stage)
                self.files.capacity()
                if monitor:
                    monitor()
                if time.monotonic() - start > timeout:
                    raise Problem(timeout_code, "本機處理逾時。")
                self.stop.wait(0.25)
            self.checkpoint(job, stage)
            self.files.capacity()
            if monitor:
                monitor()
            if process.returncode:
                raise Problem(failure_code, "本機子程序執行失敗。")
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    # The Windows venv launcher starts a separate Python process.
                    # Terminate its tree before releasing the attempt.
                    try:
                        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    def process_source(self, job):
        token = job["attempt_token"]
        with self.store.connect() as c:
            private = self.store.row(c, job["id"])
        attempt = self.files.directory(private)
        attempt.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="local-", dir=attempt) as temporary:
            target = Path(temporary)
            downloaded = self.download(job, target)
            title_file = target / "title.txt"
            title = title_file.read_text(encoding="utf-8") if title_file.is_file() else job["video_id"]
            source = self.files.new_upload(job["id"], token, "source", downloaded.suffix, title=title)
            shutil.move(downloaded, source)
            source_info = self.files.register_upload(
                job["id"], token, "source", source,
                checkpoint=lambda: self.checkpoint(job, "decoding"),
            )
            profile = {"profile_id": "source-download", "version": "1",
                       "description": "保存原始來源格式"}
            if job["mode"] != "download_audio":
                self.separate(job, source, source_info["metadata"], target, title)
                profile = model_profile(job.get("model_preset") or DEFAULT_PRESET)
            self.checkpoint(job, "verifying")
        self.files.publish(job["id"], token, profile)

    def download(self, job, target):
        command = [sys.executable, "-m", "music_stem_lab.download_task",
                   "--url", job["source_url"], "--target", str(target),
                   "--max-bytes", str(self.settings.max_upload_bytes),
                   "--max-seconds", str(self.settings.max_duration_seconds)]

        def check_size():
            if sum(p.stat().st_size for p in target.iterdir() if p.name.startswith("source.") and p.is_file()) > self.settings.max_upload_bytes:
                raise Problem("SOURCE_LIMIT", "來源超出限制。")

        self.run_process(job, command, "fetching", self.settings.download_timeout_seconds,
                         "SOURCE_UNAVAILABLE", "DOWNLOAD_TIMEOUT", check_size)
        candidates = [p for p in target.iterdir() if p.name.startswith("source.")
                      and p.suffix not in (".part", ".ytdl")]
        if len(candidates) != 1:
            raise Problem("SOURCE_UNAVAILABLE", "未取得單一來源。")
        self.checkpoint(job, "decoding")
        return candidates[0]

    def separate(self, job, source, metadata, target, title):
        duration = self.settings.max_duration_seconds
        pcm = target / "input.wav"
        self.files.capacity((duration + 1) * SAMPLE_RATE * 4 + 4096)
        command = [*pcm_command(source, duration, 2, SAMPLE_RATE), str(pcm)]
        self.run_process(job, command, "decoding", 120, "INVALID_AUDIO", "DECODE_TIMEOUT")
        with wave.open(str(pcm), "rb") as wav:
            frames = wav.getnframes()
        if not 0 < frames <= duration * SAMPLE_RATE:
            raise Problem("SOURCE_LIMIT", "來源實際時長超出限制。")
        rate = metadata.get("sample_rate", SAMPLE_RATE)
        frames = metadata.get("frames", frames)
        channels = metadata.get("channels", 2)
        kinds = required_artifacts(job)[1:]
        output_bytes = frames * channels * 2 + 4096
        if output_bytes > self.settings.max_upload_bytes:
            raise Problem("SOURCE_LIMIT", "分軌後的 WAV 超出檔案大小限制。")
        self.files.capacity(output_bytes * len(kinds))
        preset_id = job.get("model_preset") or DEFAULT_PRESET
        command = [sys.executable, "-m", "music_stem_lab.model_task", str(self.settings.model_checkpoint),
                   "--preset", preset_id,
                   "--source", str(pcm), "--target", str(target), "--kinds", *kinds,
                   "--rate", str(rate), "--frames", str(frames), "--channels", str(channels)]
        self.run_process(job, command, "separating", PRESETS[preset_id].timeout_seconds,
                         "MODEL_FAILED", "MODEL_TIMEOUT")
        token = job["attempt_token"]
        for kind in kinds:
            self.checkpoint(job, "verifying")
            path = self.files.new_upload(job["id"], token, kind, ".wav", title=title)
            shutil.move(target / (kind + ".wav"), path)
            self.files.register_upload(job["id"], token, kind, path)
