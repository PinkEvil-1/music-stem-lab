from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .domain import ACTIVE, MODES, STAGES, EXPORT_SOURCES, Problem, Settings, video_id, normalize_exports, normalize_stems

def uid():
    return uuid.uuid4().hex

def timestamp():
    return time.time()

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "jobs.sqlite3"
        with self.connect() as c:
            c.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
                INSERT OR IGNORE INTO counters VALUES ('queue', 0);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, video_id TEXT NOT NULL,
                    mode TEXT NOT NULL, execution_kind TEXT NOT NULL,
                    state TEXT NOT NULL, stage TEXT, sequence INTEGER NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0, attempt_id TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0, error_code TEXT, error_message TEXT,
                    progress REAL, worker_id TEXT, lease_until REAL, token TEXT,
                    publish_json TEXT
                );
                CREATE INDEX IF NOT EXISTS queue_idx ON jobs(state, sequence);
                CREATE TABLE IF NOT EXISTS batches (
                    key TEXT PRIMARY KEY, payload TEXT NOT NULL, result TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    worker_id TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
                    outcome TEXT, execution_kind TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    attempt_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
                    size INTEGER NOT NULL, sha256 TEXT NOT NULL, media_type TEXT NOT NULL,
                    metadata TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(attempt_id, kind)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    time REAL NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL
                );
            """)
            c.execute("BEGIN IMMEDIATE")
            for table, columns in {
                "jobs": ("extra_exports", "native_stems"),
                "attempts": ("native_stems",),
            }.items():
                existing = {row["name"] for row in c.execute("PRAGMA table_info(" + table + ")")}
                for column in columns:
                    if column not in existing:
                        c.execute("ALTER TABLE " + table + " ADD COLUMN " + column + " TEXT NOT NULL DEFAULT '[]'")
            c.execute("PRAGMA user_version=2")

    def connect(self):
        c = sqlite3.connect(self.path, timeout=15, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def transaction(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def event(c, job_id, state, message):
        c.execute("INSERT INTO events(job_id,time,state,message) VALUES (?,?,?,?)",
                  (job_id, timestamp(), state, message))

    @staticmethod
    def row(c, job_id):
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise Problem("NOT_FOUND", "找不到工作。", 404)
        return dict(row)

    @staticmethod
    def next_sequence(c):
        c.execute("UPDATE counters SET value=value+1 WHERE name='queue'")
        return c.execute("SELECT value FROM counters WHERE name='queue'").fetchone()[0]

    def submit(self, urls, mode, execution_kind, key, extra_exports=None):
        if mode not in MODES or execution_kind not in ("real", "demo"):
            raise Problem("INVALID_MODE", "此處理模式尚未支援。", 422)
        if not 1 <= len(urls) <= self.settings.max_batch:
            raise Problem("BATCH_LIMIT", "每批需有 1 至 20 筆網址。", 422)
        exports = normalize_exports(mode, extra_exports)
        # Preserve legacy idempotency payloads for existing jobs.
        payload_fields = [urls, mode, execution_kind]
        if mode == "separate":
            payload_fields.append(exports)
        payload = json.dumps(payload_fields, ensure_ascii=False)
        with self.transaction() as c:
            existing = c.execute("SELECT * FROM batches WHERE key=?", (key,)).fetchone()
            if existing:
                if existing["payload"] != payload:
                    raise Problem("IDEMPOTENCY_CONFLICT", "此請求識別碼已用於不同內容。")
                return json.loads(existing["result"])
            batch, items = uid(), []
            for index, url in enumerate(urls):
                try:
                    vid = video_id(url)
                except Problem as error:
                    items.append({"index": index, "error": {"code": error.code, "message": error.message}})
                    continue
                job_id, now = uid(), timestamp()
                c.execute("""INSERT INTO jobs
                    (id,batch_id,video_id,mode,execution_kind,state,sequence,created_at,updated_at)
                    VALUES (?,?,?,?,?,'queued',?,?,?)""",
                    (job_id, batch, vid, mode, execution_kind, self.next_sequence(c), now, now))
                c.execute("UPDATE jobs SET extra_exports=? WHERE id=?", (json.dumps(exports), job_id))
                self.event(c, job_id, "queued", "已加入佇列")
                items.append({"index": index, "job_id": job_id})
            result = {"batch_id": batch, "items": items}
            c.execute("INSERT INTO batches VALUES (?,?,?)", (key, payload, json.dumps(result)))
            return result

    def sweep_expired(self):
        with self.transaction() as c:
            rows = c.execute("""SELECT id FROM jobs WHERE state IN ('running','publishing')
                AND lease_until < ?""", (timestamp(),)).fetchall()
            for row in rows:
                c.execute("""UPDATE jobs SET state='recovering',updated_at=?,
                    error_code='WORKER_UNREACHABLE',
                    error_message='執行器心跳逾時；請先確認舊執行器已停止再恢復。'
                    WHERE id=?""", (timestamp(), row["id"]))
                self.event(c, row["id"], "recovering", "心跳逾時，保留執行權以免重複處理")

    def claim(self, worker_id, execution_kind, modes, native_stems=None):
        stems = normalize_stems(native_stems)
        self.sweep_expired()
        with self.transaction() as c:
            if c.execute("SELECT 1 FROM jobs WHERE state IN ('running','publishing','recovering')").fetchone():
                return None
            row = c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY sequence LIMIT 1").fetchone()
            # Never skip a FIFO head just because this worker cannot execute it.
            if not row or row["execution_kind"] != execution_kind or row["mode"] not in modes:
                return None
            job = dict(row)
            if job["mode"] == "separate":
                exports = json.loads(job["extra_exports"])
                if not stems or any(EXPORT_SOURCES[value] not in stems for value in exports):
                    return None
            else:
                stems = []
            attempt_id, token, now = uid(), uid(), timestamp()
            c.execute("""UPDATE jobs SET state='running',stage='fetching',updated_at=?,
                attempt_count=attempt_count+1,attempt_id=?,token=?,worker_id=?,
                lease_until=?,progress=NULL,error_code=NULL,error_message=NULL,publish_json=NULL WHERE id=?""",
                (now, attempt_id, token, worker_id, now + self.settings.lease_seconds, job["id"]))
            c.execute("UPDATE jobs SET native_stems=? WHERE id=?", (json.dumps(stems), job["id"]))
            c.execute("""INSERT INTO attempts(id,job_id,worker_id,started_at,execution_kind,native_stems)
                VALUES (?,?,?,?,?,?)""", (attempt_id, job["id"], worker_id, now, execution_kind, json.dumps(stems)))
            self.event(c, job["id"], "running", "執行器已領取工作")
            job = self.row(c, job["id"])
            return {**self.public(job), "attempt_token": token}

    def owned(self, c, job_id, token, *, allow_cancel=False, allow_recovering=False):
        job = self.row(c, job_id)
        allowed = ("running", "publishing", "recovering") if allow_recovering else ("running", "publishing")
        if job["token"] != token or job["state"] not in allowed:
            raise Problem("STALE_ATTEMPT", "此執行嘗試已失效。")
        if not allow_recovering and (job["lease_until"] or 0) < timestamp():
            raise Problem("LEASE_EXPIRED", "執行權已逾時，需人工確認後恢復。")
        if job["cancel_requested"] and not allow_cancel:
            raise Problem("CANCEL_REQUESTED", "工作已要求取消。")
        return job

    def heartbeat(self, job_id, token, stage, progress):
        if stage not in STAGES:
            raise Problem("INVALID_STAGE", "不支援此執行階段。", 422)
        with self.transaction() as c:
            job = self.owned(c, job_id, token, allow_cancel=True)
            if job["stage"] != stage and STAGES.index(stage) < STAGES.index(job["stage"]):
                raise Problem("STAGE_REGRESSION", "階段不可倒退。")
            c.execute("""UPDATE jobs SET stage=?,progress=?,lease_until=?,updated_at=? WHERE id=?""",
                      (stage, progress, timestamp() + self.settings.lease_seconds, timestamp(), job_id))
            return {"cancel_requested": bool(job["cancel_requested"]), "lease_seconds": self.settings.lease_seconds}

    def finish(self, job_id, token, state, code=None):
        if state not in ("failed", "cancelled"):
            raise Problem("INVALID_OUTCOME", "不支援此結束狀態。", 422)
        with self.transaction() as c:
            job = self.owned(c, job_id, token, allow_cancel=True, allow_recovering=True)
            if job["cancel_requested"]:
                state, code = "cancelled", None
            message = "工作已取消。" if state == "cancelled" else {
                "SOURCE_UNAVAILABLE": "無法取得來源，請確認影片可用與下載條件。",
                "SOURCE_LIMIT": "來源超出大小或時長限制。",
                "DOWNLOAD_TIMEOUT": "來源下載逾時。",
                "STORAGE_LIMIT": "儲存空間不足。",
                "INVALID_AUDIO": "輸出音訊驗證失敗。",
                "MODEL_FAILED": "本機 CUDA 分軌失敗，請檢查模型和顯示卡狀態後重試。",
                "MODEL_TIMEOUT": "本機 CUDA 分軌逾時。",
                "DECODE_TIMEOUT": "來源解碼逾時。",
                "MODEL_NOT_CONFIGURED": "模型執行器尚未配置。",
            }.get(code, "執行器回報處理失敗。")
            c.execute("""UPDATE jobs SET state=?,stage=NULL,token=NULL,lease_until=NULL,
                updated_at=?,error_code=?,error_message=? WHERE id=?""",
                (state, timestamp(), code if state == "failed" else None, message, job_id))
            c.execute("UPDATE attempts SET finished_at=?,outcome=? WHERE id=?",
                      (timestamp(), state, job["attempt_id"]))
            self.event(c, job_id, state, message)

    def cancel(self, job_id):
        with self.transaction() as c:
            job = self.row(c, job_id)
            if job["state"] == "queued":
                c.execute("UPDATE jobs SET state='cancelled',cancel_requested=1,updated_at=? WHERE id=?",
                          (timestamp(), job_id))
                self.event(c, job_id, "cancelled", "排隊工作已取消")
            elif job["state"] in ACTIVE:
                c.execute("UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=?", (timestamp(), job_id))
                self.event(c, job_id, job["state"], "已要求取消，等待執行器確認")
        return self.detail(job_id)

    def retry(self, job_id):
        with self.transaction() as c:
            job = self.row(c, job_id)
            if job["state"] not in ("failed", "cancelled"):
                raise Problem("STATE_CONFLICT", "只有失敗或已取消的工作可以重試。")
            c.execute("""UPDATE jobs SET state='queued',stage=NULL,sequence=?,updated_at=?,
                cancel_requested=0,error_code=NULL,error_message=NULL,progress=NULL,worker_id=NULL,
                token=NULL,lease_until=NULL,publish_json=NULL WHERE id=?""",
                (self.next_sequence(c), timestamp(), job_id))
            self.event(c, job_id, "queued", "手動重試，已排至佇列尾端")
        return self.detail(job_id)

    def recover(self, job_id, old_worker_stopped):
        if not old_worker_stopped:
            raise Problem("STOP_CONFIRMATION_REQUIRED", "請先確認舊執行器及其子程序已停止。", 422)
        with self.transaction() as c:
            job = self.row(c, job_id)
            if job["state"] != "recovering":
                raise Problem("STATE_CONFLICT", "此工作不需要人工恢復。")
            state = "cancelled" if job["cancel_requested"] else "queued"
            c.execute("""UPDATE jobs SET state=?,stage=NULL,token=NULL,worker_id=NULL,
                lease_until=NULL,error_code=NULL,error_message=NULL,progress=NULL,
                publish_json=NULL,updated_at=? WHERE id=?""", (state, timestamp(), job_id))
            c.execute("UPDATE attempts SET finished_at=?,outcome='interrupted' WHERE id=?",
                      (timestamp(), job["attempt_id"]))
            self.event(c, job_id, state, "使用者確認舊執行器已停止，撤銷舊執行權")
        return self.detail(job_id)

    @staticmethod
    def public(job):
        fields = ("id", "batch_id", "video_id", "mode", "execution_kind", "state", "stage",
                  "sequence", "created_at", "updated_at", "attempt_count", "attempt_id",
                  "cancel_requested", "error_code", "error_message", "progress", "lease_until")
        result = {key: job[key] for key in fields}
        result["cancel_requested"] = bool(result["cancel_requested"])
        result["extra_exports"] = json.loads(job.get("extra_exports", "[]"))
        result["native_stems"] = json.loads(job.get("native_stems", "[]"))
        result["source_url"] = "https://www.youtube.com/watch?v=" + job["video_id"]
        return result

    def detail(self, job_id):
        with self.connect() as c:
            job = self.row(c, job_id)
            result = self.public(job)
            result["queue_position"] = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE state='queued' AND sequence<=?", (job["sequence"],)
            ).fetchone()[0] if job["state"] == "queued" else None
            artifacts = c.execute("""SELECT * FROM artifacts WHERE job_id=?
                AND attempt_id=? AND published=1 ORDER BY kind""",
                (job_id, job["attempt_id"])).fetchall()
            result["artifacts"] = []
            for artifact in artifacts:
                path = self.root / artifact["path"]
                result["artifacts"].append({
                    "id": artifact["id"], "kind": artifact["kind"], "size": artifact["size"],
                    "media_type": artifact["media_type"], "sha256": artifact["sha256"],
                    "available": path.is_file() and path.stat().st_size == artifact["size"],
                    "url": "/api/artifacts/" + artifact["id"] + "/content",
                })
            result["events"] = [dict(e) for e in c.execute(
                "SELECT time,state,message FROM events WHERE job_id=? ORDER BY id DESC LIMIT 30", (job_id,))]
            result["attempts"] = [dict(a) for a in c.execute(
                "SELECT id,worker_id,started_at,finished_at,outcome,execution_kind,native_stems FROM attempts WHERE job_id=? ORDER BY started_at",
                (job_id,))]
            for attempt in result["attempts"]:
                attempt["native_stems"] = json.loads(attempt["native_stems"])
            return result

    def listing(self, state=None, limit=50, offset=0):
        self.sweep_expired()
        with self.connect() as c:
            clause, args = (" WHERE state=?", [state]) if state else ("", [])
            total = c.execute("SELECT COUNT(*) FROM jobs" + clause, args).fetchone()[0]
            ids = c.execute("SELECT id FROM jobs" + clause +
                            " ORDER BY created_at DESC,id LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
            counts = {row["state"]: row["n"] for row in c.execute(
                "SELECT state,COUNT(*) AS n FROM jobs GROUP BY state")}
        return {"items": [self.detail(r["id"]) for r in ids], "total": total,
                "counts": counts, "limit": limit, "offset": offset}
