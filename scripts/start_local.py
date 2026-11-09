"""Start or stop the Windows loopback GPU workspace."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from music_stem_lab.windows_job import service_job

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000/"
OPENER = build_opener(ProxyHandler({}))
REQUIRED = ("download_enabled", "model_inference_available", "local_folder_enabled", "local_shutdown_enabled")
TOKEN_FILE = ROOT / ".tmp" / "local-shutdown.token"


def shutdown_token(create=False):
    if create:
        TOKEN_FILE.parent.mkdir(exist_ok=True)
        try:
            with TOKEN_FILE.open("x", encoding="ascii") as file:
                file.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
    try:
        token = TOKEN_FILE.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        raise RuntimeError("Start the workspace with Start Music Stem Lab.cmd first.") from None
    if not token:
        raise RuntimeError("The local shutdown token could not be read. Try again.")
    return token


def listening():
    report = subprocess.run(["netstat.exe", "-ano", "-p", "TCP"], check=True, timeout=5,
                            capture_output=True, encoding="ascii", errors="ignore")
    return any(line.split()[:4] == ["TCP", "127.0.0.1:8000", "0.0.0.0:0", "LISTENING"]
               for line in report.stdout.splitlines())


def stop():
    if not listening():
        print("Music Stem Lab is already stopped.")
        return
    if not ready():
        raise RuntimeError("Could not verify the Music Stem Lab service on port 8000.")
    request = Request(URL + "api/local/shutdown", data=b"", method="POST",
                      headers={"X-Music-Stem-Shutdown": shutdown_token()})
    try:
        with OPENER.open(request, timeout=5) as response:
            if response.status != 204:
                raise RuntimeError("The local service did not accept the shutdown request.")
    except HTTPError as error:
        if error.code == 409:
            raise RuntimeError("A job is active. Wait for it to finish or cancel it in the workspace.") from None
        raise RuntimeError("The service on port 8000 could not be verified as this workspace.") from None
    except (URLError, TimeoutError):
        # The listener can close while the client is receiving the response.
        if listening():
            raise RuntimeError("Could not confirm that the service accepted the shutdown request.") from None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if not listening():
            print("Music Stem Lab stopped.")
            return
        time.sleep(.25)
    raise RuntimeError("The workspace is still shutting down. Try again in a moment.")


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
                   "MUSIC_STEM_LOCAL_SHUTDOWN_TOKEN": shutdown_token(create=True),
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
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    try:
        if args.stop:
            stop()
            return 0
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
