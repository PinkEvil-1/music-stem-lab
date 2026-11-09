import argparse
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
    if checkpoint:
        try:
            subprocess.run([sys.executable, "-m", "music_stem_lab.model_task", str(checkpoint), "--check"],
                           check=True, timeout=60)
        except (subprocess.SubprocessError, OSError):
            parser.exit(2, "無法啟用本機 CUDA 模型，請檢查權重與 PyTorch 環境。\n")
    settings = Settings(enable_download=args.enable_download, model_checkpoint=checkpoint,
                        enable_local_folder=args.enable_local_folder)

    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, access_log=False)

if __name__ == "__main__":
    main()
