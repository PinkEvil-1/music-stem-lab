from dataclasses import dataclass, field
from pathlib import Path
import os
import re
from urllib.parse import parse_qs, urlsplit

MODES = {
    "separate": (),
    "download_audio": ("source",),
    "remove_vocals": ("source", "vocals", "no_vocals"),
    "remove_guitar": ("source", "guitar", "no_guitar"),
}
ACTIVE = ("running", "publishing", "recovering")
STAGES = ("fetching", "decoding", "separating", "mixing", "verifying")

class Problem(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)

def video_id(value: str) -> str:
    try:
        u = urlsplit(value.strip())
        if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
            raise ValueError
        q = parse_qs(u.query)
        host = (u.hostname or "").lower()
        if host == "youtu.be":
            candidate = u.path.removeprefix("/")
        elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
            if u.path == "/watch":
                values = q.get("v", [])
                if len(values) != 1:
                    raise ValueError
                candidate = values[0]
            elif u.path.startswith("/shorts/"):
                candidate = u.path[len("/shorts/"):]
            else:
                raise ValueError
        else:
            raise ValueError
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            raise ValueError
        return candidate
    except (ValueError, TypeError):
        raise Problem("INVALID_URL", "請提供單一影片的 HTTPS YouTube 網址。", 422) from None


EXPORT_SOURCES = {"no_vocals": "vocals", "no_guitar": "guitar"}
DEMO_STEMS = ("vocals", "drums", "bass", "guitar", "piano", "other")

def normalize_exports(mode, values):
    values = list(values or [])
    if any(value not in EXPORT_SOURCES for value in values) or (values and mode != "separate"):
        raise Problem("INVALID_EXPORTS", "額外伴奏選項僅適用模型分軌工作。", 422)
    return sorted(set(values))

def normalize_stems(values):
    values = list(values or [])
    reserved = {"source", "manifest", *EXPORT_SOURCES}
    if len(values) > 32 or len(set(values)) != len(values) or any(
        not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value)
        or value in reserved for value in values
    ):
        raise Problem("INVALID_STEMS", "模型原生音軌名稱或數量無效。", 422)
    return values

def required_artifacts(job):
    if job["mode"] != "separate":
        return MODES[job["mode"]]
    stems, exports = job.get("native_stems", []), job.get("extra_exports", [])
    # Database records store JSON; public worker jobs carry arrays.
    import json
    stems = json.loads(stems) if isinstance(stems, str) else stems
    exports = json.loads(exports) if isinstance(exports, str) else exports
    if not stems:
        raise Problem("MISSING_MODEL_CAPABILITIES", "執行器尚未提供模型音軌能力。", 422)
    return ("source", *stems, *exports)

@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get(
        "MUSIC_STEM_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))))
    worker_token: str = field(default_factory=lambda: os.environ.get("MUSIC_STEM_WORKER_TOKEN", ""))
    enable_download: bool = False
    model_checkpoint: Path | None = None
    local_workers: bool = True
    lease_seconds: int = 60
    max_batch: int = 20
    max_upload_bytes: int = 500 * 1024 * 1024
    quota_bytes: int = 20 * 1024 ** 3
    min_free_bytes: int = 1024 ** 3
    max_duration_seconds: int = 1200
    download_timeout_seconds: int = 900
    demo_stage_seconds: float = 0.5
