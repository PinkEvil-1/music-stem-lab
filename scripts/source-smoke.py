"""Run one explicitly provided, permitted source through the real download pipeline."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient

from music_stem_lab.app import create_app
from music_stem_lab.domain import Settings, video_id

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    vid = video_id(args.url)
    root = Path(__file__).resolve().parent.parent
    run = "source-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = root / "data" / run
    settings = Settings(data_dir=directory, enable_download=True, worker_token="")
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post("/api/jobs/batch", json={
            "urls": ["https://www.youtube.com/watch?v=" + vid],
            "mode": "download_audio", "execution_kind": "real",
            "idempotency_key": run,
        })
        if response.status_code != 202:
            print(json.dumps({"result": "FAIL", "stage": "submit", "status": response.status_code}))
            return 1
        job_id = response.json()["items"][0]["job_id"]
        last = None
        deadline = time.monotonic() + settings.download_timeout_seconds + 150
        while time.monotonic() < deadline:
            job = client.get("/api/jobs/" + job_id).json()
            marker = (job["state"], job["stage"], job["error_code"])
            if marker != last:
                print(json.dumps({"job_id": job_id, "state": job["state"],
                                  "stage": job["stage"], "error_code": job["error_code"]}), flush=True)
                last = marker
            if job["state"] == "completed":
                source = next(a for a in job["artifacts"] if a["kind"] == "source")
                manifest = client.get(next(a for a in job["artifacts"] if a["kind"] == "manifest")["url"]).json()
                streamed = client.get(source["url"], headers={"Range": "bytes=0-31"})
                assert streamed.status_code == 206
                assert manifest["simulated"] is False
                result = {"result": "PASS", "video_id": vid, "job_id": job_id,
                          "source_bytes": source["size"], "media_type": source["media_type"],
                          "validation": manifest["artifacts"][0]["metadata"],
                          "range_status": streamed.status_code,
                          "data_directory": str(directory.relative_to(root))}
                (directory / "source-validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result), flush=True)
                return 0
            if job["state"] in ("failed", "cancelled", "recovering"):
                result = {"result": "FAIL", "video_id": vid, "job_id": job_id,
                          "error_code": job["error_code"],
                          "data_directory": str(directory.relative_to(root))}
                (directory / "source-validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result), flush=True)
                return 1
            time.sleep(0.5)
        print(json.dumps({"result": "FAIL", "error_code": "TEST_TIMEOUT", "job_id": job_id}))
        return 1

if __name__ == "__main__":
    sys.exit(main())
