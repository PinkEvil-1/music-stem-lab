"""Decode local containers to bounded PCM for validation. No model or GPU is involved."""
import subprocess
import time
from imageio_ffmpeg import get_ffmpeg_exe, get_ffmpeg_version
from .domain import Problem

def pcm_command(path, max_seconds, channels, rate):
    # Decode one extra second to distinguish an overlong source from a valid one.
    return [get_ffmpeg_exe(), "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror",
            "-protocol_whitelist", "file,pipe", "-i", str(path),
            "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", str(max_seconds + 1),
            "-ac", str(channels), "-ar", str(rate), "-c:a", "pcm_s16le"]


def validate_decode(path, max_seconds, timeout_seconds=120, checkpoint=None):
    command = [*pcm_command(path, max_seconds, 1, 16000), "-f", "s16le", "pipe:1"]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    start = time.monotonic()
    try:
        while True:
            if checkpoint:
                checkpoint()
            try:
                pcm, _ = process.communicate(timeout=0.25)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - start > timeout_seconds:
                    raise Problem("DECODE_TIMEOUT", "來源解碼逾時。", 422)
        if process.returncode or not pcm or len(pcm) % 2:
            raise Problem("INVALID_AUDIO", "音訊無法完整解碼。", 422)
        seconds = len(pcm) / 32000
        if seconds > max_seconds:
            raise Problem("SOURCE_LIMIT", "來源實際時長超出限制。", 422)
        return {"validation": "ffmpeg_decode", "decoded_duration_seconds": seconds,
                "validator_sample_rate": 16000, "ffmpeg_version": get_ffmpeg_version()}
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
