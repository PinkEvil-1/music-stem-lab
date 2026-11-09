import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import stat
import threading
import wave

from .domain import MODES, Problem, required_artifacts
from .store import Store, timestamp, uid
from .decode import validate_decode

class Artifacts:
    def __init__(self, store: Store):
        self.store = store
        self.settings = store.settings
        self.root = store.root
        self.lock = threading.RLock()
        (self.root / "jobs").mkdir(exist_ok=True)

    def safe(self, path: Path):
        path = Path(path)
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root) or resolved == self.root:
            raise Problem("UNSAFE_PATH", "檔案路徑不在工作資料目錄。", 400)
        current = path
        while current != self.root and current != current.parent:
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise Problem("UNSAFE_PATH", "工作資料目錄不可包含連結。", 400)
            current = current.parent
        return path

    def usage(self):
        used = 0
        for path in self.root.rglob("*"):
            try:
                info = path.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue  # SQLite sidecars and attempt files can disappear during this scan.
            if stat.S_ISREG(info.st_mode):
                used += info.st_size
        disk = shutil.disk_usage(self.root)
        return {"used_bytes": used, "quota_bytes": self.settings.quota_bytes,
                "free_bytes": disk.free, "minimum_free_bytes": self.settings.min_free_bytes}

    def capacity(self, extra=0):
        info = self.usage()
        if info["used_bytes"] + extra > info["quota_bytes"] or info["free_bytes"] - extra < info["minimum_free_bytes"]:
            raise Problem("STORAGE_LIMIT", "儲存空間不足，請刪除不需要的工作。", 507)

    def directory(self, job):
        return self.safe(self.root / "jobs" / job["id"] / "attempts" / job["attempt_id"])

    def new_upload(self, job_id, token, kind, extension):
        if extension not in (".wav", ".webm", ".m4a", ".mp3", ".opus", ".ogg", ".flac"):
            raise Problem("INVALID_FORMAT", "不支援此音訊格式。", 422)
        with self.store.transaction() as c:
            job = self.store.owned(c, job_id, token)
            if job["state"] != "running" or kind not in required_artifacts(job):
                raise Problem("INVALID_ARTIFACT", "此階段不接受此輸出檔案。", 422)
            if kind != "source" and extension != ".wav":
                raise Problem("INVALID_FORMAT", "分離輸出需為 PCM WAV。", 422)
            self.capacity()
            directory = self.directory(job) / "work"
            self.safe(directory).mkdir(parents=True, exist_ok=True)
            return self.safe(directory / (kind + "-" + uid() + extension))

    @staticmethod
    def digest(path):
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def inspect(self, path, checkpoint=None):
        size = path.stat().st_size
        if not 0 < size <= self.settings.max_upload_bytes:
            raise Problem("SOURCE_LIMIT", "音訊檔案大小超出限制。", 422)
        with path.open("rb") as f:
            header = f.read(16)
        ext = path.suffix.lower()
        if ext == ".wav":
            try:
                with wave.open(str(path), "rb") as wav:
                    rate, frames = wav.getframerate(), wav.getnframes()
                    channels, width = wav.getnchannels(), wav.getsampwidth()
                    if channels not in (1, 2) or not 8000 <= rate <= 192000 or width not in (2, 3, 4):
                        raise ValueError
                    if not 0 < frames <= rate * self.settings.max_duration_seconds:
                        raise ValueError
                    expected = frames * channels * width
                    actual = 0
                    while chunk := wav.readframes(16384):
                        actual += len(chunk)
                    if actual != expected:
                        raise ValueError
                    metadata = {"sample_rate": rate, "frames": frames, "channels": channels,
                                "sample_width": width, "duration_seconds": frames / rate,
                                "validation": "pcm_wav"}
            except (wave.Error, EOFError, ValueError):
                raise Problem("INVALID_AUDIO", "WAV 音訊格式、長度或內容無效。", 422) from None
        else:
            valid = {
                ".webm": header.startswith(b"\x1aE\xdf\xa3"),
                ".m4a": len(header) >= 8 and header[4:8] == b"ftyp",
                ".mp3": header.startswith(b"ID3") or (len(header) >= 2 and header[0] == 255 and header[1] & 224 == 224),
                ".ogg": header.startswith(b"OggS"),
                ".opus": header.startswith(b"OggS"),
                ".flac": header.startswith(b"fLaC"),
            }.get(ext, False)
            if not valid:
                raise Problem("INVALID_AUDIO", "來源容器格式無效。", 422)
            metadata = validate_decode(path, self.settings.max_duration_seconds, checkpoint=checkpoint)
        media = {".wav": "audio/wav", ".webm": "audio/webm", ".m4a": "audio/mp4",
                 ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".opus": "audio/ogg",
                 ".flac": "audio/flac"}[ext]
        return {"size": size, "sha256": self.digest(path), "metadata": metadata, "media_type": media}

    def register_upload(self, job_id, token, kind, path, checkpoint=None):
        self.safe(path)
        metadata = self.inspect(path, checkpoint=checkpoint)
        with self.store.transaction() as c:
            job = self.store.owned(c, job_id, token)
            if job["state"] != "running":
                raise Problem("STATE_CONFLICT", "此工作已進入發布階段。")
            previous = c.execute("SELECT path FROM artifacts WHERE attempt_id=? AND kind=?",
                                 (job["attempt_id"], kind)).fetchone()
            c.execute("DELETE FROM artifacts WHERE attempt_id=? AND kind=?", (job["attempt_id"], kind))
            artifact_id = uid()
            c.execute("""INSERT INTO artifacts
                (id,job_id,attempt_id,kind,path,size,sha256,media_type,metadata)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (artifact_id, job_id, job["attempt_id"], kind, path.relative_to(self.root).as_posix(),
                 metadata["size"], metadata["sha256"], metadata["media_type"], json.dumps(metadata["metadata"])))
            if previous:
                self.safe(self.root / previous["path"]).unlink(missing_ok=True)
        return {"artifact_id": artifact_id, "kind": kind, **metadata}

    def put(self, job_id, token, kind, extension, data):
        with self.lock:
            self.capacity(len(data))
            path = self.new_upload(job_id, token, kind, extension)
            try:
                path.write_bytes(data)
                return self.register_upload(job_id, token, kind, path)
            except BaseException:
                path.unlink(missing_ok=True)
                raise

    def publish(self, job_id, token, profile):
        with self.store.transaction() as c:
            job = self.store.owned(c, job_id, token)
            if job["state"] != "running":
                raise Problem("STATE_CONFLICT", "工作不在可發布狀態。")
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM artifacts WHERE attempt_id=?", (job["attempt_id"],))]
            if {r["kind"] for r in rows} != set(required_artifacts(job)):
                raise Problem("MISSING_ARTIFACTS", "必要輸出尚未上傳完整。", 422)
            wav_specs = []
            for row in rows:
                path = self.safe(self.root / row["path"])
                if not path.is_file() or self.digest(path) != row["sha256"]:
                    raise Problem("INVALID_AUDIO", "產物已遺失或損毀。", 422)
                meta = json.loads(row["metadata"])
                if path.suffix == ".wav":
                    wav_specs.append(tuple(meta[k] for k in ("sample_rate", "frames", "channels")))
            if len(set(wav_specs)) > 1:
                raise Problem("AUDIO_MISMATCH", "各軌取樣率、聲道或長度不一致。", 422)
            manifest = {
                "schema_version": 1, "job_id": job_id, "attempt_id": job["attempt_id"],
                "video_id": job["video_id"], "mode": job["mode"],
                "execution_kind": job["execution_kind"], "simulated": job["execution_kind"] == "demo",
                "extra_exports": json.loads(job["extra_exports"]),
                "native_stems": json.loads(job["native_stems"]),
                "profile": profile, "completed_at": timestamp(),
                "artifacts": [{"id": r["id"], "kind": r["kind"], "filename": Path(r["path"]).name,
                               "size": r["size"], "sha256": r["sha256"],
                               "metadata": json.loads(r["metadata"])} for r in rows],
            }
            work = self.directory(job) / "work"
            self.capacity(65536)
            self.safe(work / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            c.execute("UPDATE jobs SET state='publishing',publish_json=?,updated_at=? WHERE id=?",
                      (json.dumps(manifest), timestamp(), job_id))
            self.store.event(c, job_id, "publishing", "已驗證產物，提交發布意圖")
        self._commit_publish(job_id, token)

    def _commit_publish(self, job_id, token, *, already_renamed=False):
        with self.store.transaction() as c:
            job = self.store.row(c, job_id)
            if job["state"] == "completed":
                return
            job = self.store.owned(c, job_id, token, allow_recovering=already_renamed)
            if job["state"] != "publishing":
                raise Problem("STATE_CONFLICT", "發布意圖不存在。")
            parent = self.directory(job)
            work, published = parent / "work", parent / "published"
            if not already_renamed:
                os.replace(self.safe(work), self.safe(published))
            manifest_path = self.safe(published / "manifest.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest != json.loads(job["publish_json"]):
                raise Problem("INVALID_MANIFEST", "發布資料與工作紀錄不一致。")
            for artifact in manifest["artifacts"]:
                path = self.safe(published / artifact["filename"])
                if not path.is_file() or path.stat().st_size != artifact["size"] or self.digest(path) != artifact["sha256"]:
                    raise Problem("INVALID_AUDIO", "發布檔案遺失或損毀。", 422)
                c.execute("UPDATE artifacts SET path=?,published=1 WHERE id=?",
                          (path.relative_to(self.root).as_posix(), artifact["id"]))
            c.execute("""INSERT INTO artifacts
                (id,job_id,attempt_id,kind,path,size,sha256,media_type,metadata,published)
                VALUES (?,?,?,'manifest',?,?,?,'application/json','{}',1)""",
                (uid(), job_id, job["attempt_id"], manifest_path.relative_to(self.root).as_posix(),
                 manifest_path.stat().st_size, self.digest(manifest_path)))
            c.execute("""UPDATE jobs SET state='completed',stage=NULL,progress=100,
                token=NULL,lease_until=NULL,updated_at=? WHERE id=?""", (timestamp(), job_id))
            c.execute("UPDATE attempts SET finished_at=?,outcome='completed' WHERE id=?",
                      (timestamp(), job["attempt_id"]))
            self.store.event(c, job_id, "completed", "示範流程完成；非真實分軌" if job["execution_kind"] == "demo" else "檔案已儲存")

    def reconcile(self):
        with self.store.connect() as c:
            pending = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE state='publishing'")]
            deleting = [r["id"] for r in c.execute("SELECT id FROM jobs WHERE state='deleting'")]
        for job in pending:
            if job["cancel_requested"]:
                continue
            if (self.directory(job) / "published" / "manifest.json").is_file():
                try:
                    self._commit_publish(job["id"], job["token"], already_renamed=True)
                except (Problem, OSError, ValueError):
                    # An incomplete publication remains held until lease expiry and operator recovery.
                    pass
        for job_id in deleting:
            self.delete(job_id)

    def content(self, artifact_id):
        with self.store.connect() as c:
            row = c.execute("""SELECT a.*,j.state FROM artifacts a JOIN jobs j ON j.id=a.job_id
                WHERE a.id=? AND a.published=1 AND j.state='completed' AND a.attempt_id=j.attempt_id""",
                (artifact_id,)).fetchone()
        if not row:
            raise Problem("NOT_FOUND", "找不到可下載檔案。", 404)
        path = self.safe(self.root / row["path"])
        if not path.is_file() or path.stat().st_size != row["size"] or self.digest(path) != row["sha256"]:
            raise Problem("ARTIFACT_UNAVAILABLE", "檔案已遺失或損毀。", 410)
        return path, row["media_type"], row["kind"] + path.suffix

    def delete(self, job_id):
        with self.store.transaction() as c:
            job = self.store.row(c, job_id)
            if job["state"] not in ("queued", "completed", "failed", "cancelled", "deleting"):
                raise Problem("STATE_CONFLICT", "請先取消並確認執行器停止，再刪除。")
            c.execute("UPDATE jobs SET state='deleting',updated_at=? WHERE id=?", (timestamp(), job_id))
        directory = self.safe(self.root / "jobs" / job_id)
        if directory.exists():
            for child in directory.rglob("*"):
                self.safe(child)
            shutil.rmtree(directory)
        with self.store.transaction() as c:
            c.execute("DELETE FROM jobs WHERE id=? AND state='deleting'", (job_id,))
