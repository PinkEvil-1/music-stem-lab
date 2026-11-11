import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uvicorn
from .app import create_app
from .domain import Settings

def main():
    parser = argparse.ArgumentParser(description="Music Stem Lab local coordinator")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--enable-download", action="store_true",
                        help="Enable real source downloading for download_audio jobs")
    parser.add_argument("--model-checkpoint", type=Path,
                        help="Enable local CUDA separation with the verified Demucs six-stem checkpoint")
    parser.add_argument("--enable-local-folder", action="store_true",
                        help="Allow the local UI to open completed job folders in Windows Explorer")
    args = parser.parse_args()
    job_name = os.environ.pop("MUSIC_STEM_WINDOWS_JOB", "")
    if job_name:
        from .windows_job import join_service_job
        join_service_job(job_name)
    checkpoint = args.model_checkpoint.resolve() if args.model_checkpoint else None
    device_uuid = None
    if checkpoint:
        try:
            check = subprocess.run(
                [sys.executable, "-m", "music_stem_lab.model_task", str(checkpoint), "--check"],
                stdout=subprocess.PIPE, encoding="utf-8", check=True, timeout=60,
            )
            device_uuid = json.loads(check.stdout)["device_uuid"]
        except (subprocess.SubprocessError, OSError, ValueError, KeyError):
            parser.exit(2, "無法啟用本機 CUDA 模型，請檢查權重與 PyTorch 環境。\n")
    settings = Settings(enable_download=args.enable_download, model_checkpoint=checkpoint,
                        enable_local_folder=args.enable_local_folder, model_device_uuid=device_uuid)

    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)

if __name__ == "__main__":
    main()
