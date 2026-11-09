import io
import math
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave

from .artifacts import Artifacts
from .domain import MODES, STAGES, Problem
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
                job = self.store.claim(self.worker_id, "demo", list(MODES))
                if job is None and self.settings.enable_download:
                    job = self.store.claim(self.worker_id, "real", ["download_audio"])
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
                for i, kind in enumerate(MODES[job["mode"]]):
                    self.files.put(job["id"], job["attempt_token"], kind, ".wav", demo_audio(330 + i * 110))
                self.files.publish(job["id"], job["attempt_token"],
                                   {"profile_id": "synthetic-demo-v1", "version": "1",
                                    "description": "合成測試音，沒有下載 YouTube 或執行音源分離"})
            else:
                self.download(job)
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

    def download(self, job):
        token = job["attempt_token"]
        with self.store.connect() as c:
            private = self.store.row(c, job["id"])
        target = self.files.directory(private) / "download"
        self.files.safe(target).mkdir(parents=True, exist_ok=True)
        command = [sys.executable, "-m", "music_stem_lab.download_task",
                   "--url", job["source_url"], "--target", str(target),
                   "--max-bytes", str(self.settings.max_upload_bytes),
                   "--max-seconds", str(self.settings.max_duration_seconds)]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        start = time.monotonic()
        try:
            while process.poll() is None:
                self.checkpoint(job, "fetching")
                self.files.capacity()
                if time.monotonic() - start > self.settings.download_timeout_seconds:
                    raise Problem("DOWNLOAD_TIMEOUT", "下載逾時。")
                if sum(p.stat().st_size for p in target.iterdir() if p.is_file()) > self.settings.max_upload_bytes:
                    raise Problem("SOURCE_LIMIT", "來源超出限制。")
                self.stop.wait(0.25)
            if process.returncode:
                raise Problem("SOURCE_UNAVAILABLE", "來源無法取得。")
            self.checkpoint(job, "decoding")
            candidates = [p for p in target.iterdir() if p.name.startswith("source.") and p.suffix not in (".part", ".ytdl")]
            if len(candidates) != 1:
                raise Problem("SOURCE_UNAVAILABLE", "未取得單一來源。")
            source = candidates[0]
            path = self.files.new_upload(job["id"], token, "source", source.suffix)
            shutil.move(str(source), str(path))
            self.files.register_upload(job["id"], token, "source", path, checkpoint=lambda: self.checkpoint(job, "decoding"))
            self.checkpoint(job, "verifying")
            self.files.publish(job["id"], token, {"profile_id": "source-download", "version": "1",
                                                 "description": "原始來源格式，未執行分軌"})
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
