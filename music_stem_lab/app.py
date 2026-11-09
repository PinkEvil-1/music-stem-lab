import asyncio
from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .artifacts import Artifacts
from .domain import MODES, EXPORT_SOURCES, Problem, Settings
from .local_worker import LocalWorker
from .store import Store
from .maintenance import ServiceLock

class Batch(BaseModel):
    urls: list[Annotated[str, Field(max_length=2048)]] = Field(min_length=1, max_length=20)
    mode: Literal["download_audio", "separate", "remove_vocals", "remove_guitar"]
    execution_kind: Literal["real", "demo"] = "real"
    extra_exports: list[Literal["no_vocals", "no_guitar"]] = Field(default_factory=list, max_length=2)
    idempotency_key: str = Field(min_length=8, max_length=128)

class Claim(BaseModel):
    worker_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    modes: list[Literal["download_audio", "separate", "remove_vocals", "remove_guitar"]] = Field(min_length=1, max_length=4)
    native_stems: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=32)

class Heartbeat(BaseModel):
    stage: Literal["fetching", "decoding", "separating", "mixing", "verifying"]
    progress: float | None = Field(default=None, ge=0, le=100)

class Outcome(BaseModel):
    state: Literal["failed", "cancelled"]
    error_code: Literal["SOURCE_UNAVAILABLE", "SOURCE_LIMIT", "DOWNLOAD_TIMEOUT", "STORAGE_LIMIT",
                        "INVALID_AUDIO", "MODEL_NOT_CONFIGURED", "WORKER_ERROR"] | None = None

class Profile(BaseModel):
    profile_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    weights_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

class Recover(BaseModel):
    old_worker_stopped: bool = False

class BodyLimit:
    def __init__(self, app, upload_limit):
        self.app, self.upload_limit = app, upload_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        maximum = self.upload_limit if "/uploads/" in scope["path"] else 128 * 1024
        total = 0
        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > maximum:
                    raise Problem("BODY_TOO_LARGE", "請求內容超出限制。", 413)
            return message
        return await self.app(scope, bounded_receive, send)

def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    store, worker = Store(settings), None
    files = Artifacts(store)
    open_folder = getattr(os, 'startfile', None) if settings.enable_local_folder else None
    local_model_enabled = settings.local_workers and settings.model_checkpoint is not None
    worker = LocalWorker(store, files)

    @asynccontextmanager
    async def lifespan(app):
        with ServiceLock(store.root) as service_lock:
            app.state.service_lock = service_lock
            files.reconcile()
            if settings.local_workers:
                worker.start()
            try:
                yield
            finally:
                worker.close()

    app = FastAPI(title="Music Stem Lab", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.store, app.state.files, app.state.settings = store, files, settings
    app.state.upload_lock = asyncio.Lock()
    app.add_middleware(BodyLimit, upload_limit=settings.max_upload_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.exception_handler(Problem)
    async def problem_handler(request, error):
        return JSONResponse({"error": {"code": error.code, "message": error.message}}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        return JSONResponse({"error": {"code": "INVALID_REQUEST", "message": "請求欄位或格式不正確。"}}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected_handler(request, error):
        return JSONResponse({"error": {"code": "INTERNAL_ERROR", "message": "操作失敗，請稍後重試。"}}, status_code=500)

    @app.middleware("http")
    async def request_policy(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlsplit(origin).netloc != request.headers.get("host")
            ):
                return JSONResponse({"error": {"code": "ORIGIN_REJECTED", "message": "不接受跨來源操作。"}}, status_code=403)
        length = request.headers.get("content-length", "0")
        maximum = settings.max_upload_bytes if "/uploads/" in request.url.path else 128 * 1024
        if not length.isdigit() or int(length) > maximum:
            return JSONResponse({"error": {"code": "BODY_TOO_LARGE", "message": "請求內容長度無效或超出限制。"}}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; media-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def worker_auth(authorization: Annotated[str | None, Header()] = None):
        if not settings.worker_token:
            raise Problem("WORKER_DISABLED", "遠端執行器介面尚未設定。", 503)
        if not authorization or not hmac.compare_digest(authorization, "Bearer " + settings.worker_token):
            raise Problem("UNAUTHORIZED", "執行器驗證失敗。", 401)

    worker_dependency = Depends(worker_auth)

    @app.get("/api/capabilities")
    def capabilities():
        return {
            "version": "0.1.0", "model_inference_available": local_model_enabled,
            "remote_worker_configured": bool(settings.worker_token),
            "download_enabled": settings.enable_download,
            "local_folder_enabled": open_folder is not None,
            "modes": [
                {"id": "download_audio", "label": "僅下載音訊", "execution": "local_download" if settings.enable_download else "waiting_worker"},
                {"id": "separate", "label": "模型分軌", "execution": "local_model" if local_model_enabled else "waiting_model_worker"},
            ],
            "extra_exports": [{"id": key, "required_stem": value} for key, value in EXPORT_SOURCES.items()],
            "demo_available": settings.local_workers,
            "limits": {"max_batch": settings.max_batch, "max_duration_seconds": settings.max_duration_seconds,
                       "max_file_bytes": settings.max_upload_bytes, "quota_bytes": settings.quota_bytes},
            "storage": files.usage(),
        }

    @app.post("/api/jobs/batch")
    def batch(body: Batch):
        if body.execution_kind == "demo" and not settings.local_workers:
            raise Problem("DEMO_DISABLED", "此服務未啟用示範執行器。", 422)
        files.capacity()
        result = store.submit(body.urls, body.mode, body.execution_kind, body.idempotency_key, body.extra_exports)
        return JSONResponse(result, status_code=202 if any("job_id" in i for i in result["items"]) else 422)

    @app.get("/api/jobs")
    def jobs(state: Literal["queued", "running", "publishing", "recovering", "completed", "failed", "cancelled", "deleting"] | None = None,
             limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        return store.listing(state, limit, offset)

    @app.get("/api/jobs/{job_id}")
    def detail(job_id: str):
        store.sweep_expired()
        return store.detail(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        return store.cancel(job_id)

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str):
        files.capacity()
        return store.retry(job_id)

    @app.post("/api/jobs/{job_id}/recover")
    def recover(job_id: str, body: Recover):
        files.capacity()
        return store.recover(job_id, body.old_worker_stopped)

    @app.post("/api/jobs/{job_id}/open-folder", status_code=204)
    def open_job_folder(job_id: str, x_music_stem_local: Annotated[str | None, Header()] = None):
        if open_folder is None:
            raise Problem("LOCAL_FOLDER_DISABLED", "此服務未啟用開啟本機資料夾。", 404)
        if x_music_stem_local != "1":
            raise Problem("ORIGIN_REJECTED", "請從本機工作室開啟資料夾。", 403)
        with store.connect() as c:
            job = store.row(c, job_id)
        if job["state"] != "completed":
            raise Problem("STATE_CONFLICT", "工作完成後才能開啟結果資料夾。")
        folder = files.safe(files.directory(job) / "published")
        if not folder.is_dir():
            raise Problem("ARTIFACT_UNAVAILABLE", "找不到已發布的結果資料夾。", 410)
        try:
            open_folder(str(folder), "explore")
        except OSError:
            raise Problem("LOCAL_FOLDER_ERROR", "無法開啟 Windows 檔案總管。", 500) from None

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete(job_id: str):
        files.delete(job_id)

    @app.get("/api/artifacts/{artifact_id}/content")
    def content(artifact_id: str, download: bool = False):
        path, media_type, name = files.content(artifact_id)
        return FileResponse(path, media_type=media_type, filename=name if download else None,
                            content_disposition_type="attachment" if download else "inline")

    @app.post("/api/worker/claim", dependencies=[worker_dependency])
    def claim(body: Claim):
        files.capacity()
        return {"job": store.claim(body.worker_id, "real", body.modes, body.native_stems), "lease_seconds": settings.lease_seconds}

    @app.post("/api/worker/jobs/{job_id}/heartbeat", dependencies=[worker_dependency])
    def heartbeat(job_id: str, body: Heartbeat, x_attempt_token: Annotated[str, Header()]):
        return store.heartbeat(job_id, x_attempt_token, body.stage, body.progress)

    @app.put("/api/worker/jobs/{job_id}/uploads/{kind}", dependencies=[worker_dependency])
    async def upload(job_id: str, kind: str, request: Request,
                     x_attempt_token: Annotated[str, Header()], extension: str = ".wav"):
        if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
            raise Problem("INVALID_CONTENT_TYPE", "上傳需使用 application/octet-stream。", 415)
        async with app.state.upload_lock:
            path = files.new_upload(job_id, x_attempt_token, kind, extension)
            size = 0
            try:
                with path.open("xb") as stream:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > settings.max_upload_bytes:
                            raise Problem("SOURCE_LIMIT", "上傳檔案超出限制。", 413)
                        files.capacity(len(chunk))
                        stream.write(chunk)
                return await run_in_threadpool(files.register_upload, job_id, x_attempt_token, kind, path)
            except BaseException:
                path.unlink(missing_ok=True)
                raise

    @app.post("/api/worker/jobs/{job_id}/complete", dependencies=[worker_dependency])
    def complete(job_id: str, body: Profile, x_attempt_token: Annotated[str, Header()]):
        files.publish(job_id, x_attempt_token, body.model_dump(exclude_none=True))
        return store.detail(job_id)

    @app.post("/api/worker/jobs/{job_id}/finish", dependencies=[worker_dependency])
    def finish(job_id: str, body: Outcome, x_attempt_token: Annotated[str, Header()]):
        store.finish(job_id, x_attempt_token, body.state, body.error_code)
        return store.detail(job_id)

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html", media_type="text/html")

    return app
