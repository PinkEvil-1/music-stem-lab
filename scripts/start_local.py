"""Start the Windows loopback GPU workspace."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from music_stem_lab.windows_job import service_job

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000/"
OPENER = build_opener(ProxyHandler({}))
REQUIRED = ("download_enabled", "model_inference_available", "local_folder_enabled")


def ready():
    try:
        with OPENER.open(URL + "api/capabilities", timeout=1) as response:
            capabilities = json.load(response)
    except (URLError, TimeoutError, ValueError, OSError):
        return False
    if not isinstance(capabilities, dict) or not all(capabilities.get(key) is True for key in REQUIRED):
        raise RuntimeError("Port 8000 is already running a different configuration. Close it and try again.")
    if capabilities.get("remote_worker_configured"):
        raise RuntimeError("Close the existing remote-enabled service and try again.")
    return True


def start(job_name):
    config_path = ROOT / ".env.local.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig")) if config_path.exists() else {}
    python = ROOT / config.get("python", ".venv/Scripts/python.exe")
    checkpoint = ROOT / config.get("checkpoint", "models/5c90dfd2-34c22ccb.th")
    if not python.is_file() or not checkpoint.is_file():
        raise RuntimeError("Missing CUDA Python environment or checkpoint. See README.md and .env.local.json.")

    log_path = ROOT / ".tmp" / "local-launch.log"
    log_path.parent.mkdir(exist_ok=True)
    environment = {**os.environ, "MUSIC_STEM_WORKER_TOKEN": "",
                   "MUSIC_STEM_WINDOWS_JOB": job_name}
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [str(python), "-m", "music_stem_lab", "--enable-download", "--enable-local-folder",
             "--model-checkpoint", str(checkpoint)],
            cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        )
    deadline = time.monotonic() + 75
    while time.monotonic() < deadline:
        if ready():
            return process
        if process.poll() is not None:
            break
        time.sleep(.5)
    raise RuntimeError(f"Music Stem Lab did not become ready. See {log_path}.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        if ready():
            if not args.no_browser:
                os.startfile(URL)
            print(f"Music Stem Lab is already running at {URL}")
            return 0
        print("Starting Music Stem Lab...", flush=True)
        with service_job() as job_name:
            process = start(job_name)
            print(URL, flush=True)
            print("Keep this window open. Close it to stop Music Stem Lab.", flush=True)
            if not args.no_browser:
                os.startfile(URL)
            try:
                return process.wait()
            except KeyboardInterrupt:
                try:
                    return process.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    return 0
    except (OSError, RuntimeError, ValueError, TypeError, subprocess.SubprocessError) as error:
        print(f"Music Stem Lab: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
