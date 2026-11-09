"""Bounded downloader subprocess. Never loads browser cookies or user CLI configuration."""
import argparse
from pathlib import Path
import sys

def download(url, target, max_bytes, max_seconds):
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
    target = Path(target)

    class Quiet:
        def debug(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass
        def warning(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass

    def match(info, *, incomplete=False):
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            return "Unsupported live source"
        if info.get("duration") is not None and info["duration"] > max_seconds:
            return "Source limit"
        return None

    def progress(info):
        actual = sum(p.stat().st_size for p in target.iterdir() if p.is_file())
        if actual > max_bytes or info.get("downloaded_bytes", 0) > max_bytes:
            raise DownloadError("Source limit")

    opts = {
        "format": "bestaudio[protocol=https]",
        "outtmpl": str(target / "source.%(ext)s"), "noplaylist": True,
        "max_filesize": max_bytes, "match_filter": match,
        "progress_hooks": [progress], "socket_timeout": 15,
        "retries": 2, "fragment_retries": 2, "concurrent_fragment_downloads": 1,
        "cachedir": False, "quiet": True, "no_warnings": True,
        "logger": Quiet(), "js_runtimes": {"node": {}},
        "overwrites": False, "postprocessors": [],
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if not info or match(info) or info.get("_type") in ("playlist", "multi_video"):
            return 2
        if info.get("duration") is None:
            return 2
        ydl.download([url])
    candidates = [p for p in target.iterdir() if p.name.startswith("source.") and p.suffix not in (".part", ".ytdl")]
    if len(candidates) != 1 or not 0 < candidates[0].stat().st_size <= max_bytes:
        return 2
    title = info.get("title")
    if isinstance(title, str) and title.strip():
        (target / "title.txt").write_text(title[:300], encoding="utf-8")
    return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--max-seconds", type=int, required=True)
    args = parser.parse_args()
    try:
        return download(args.url, args.target, args.max_bytes, args.max_seconds)
    except Exception:
        return 1  # Do not echo upstream URLs, local paths, or raw error text.

if __name__ == "__main__":
    sys.exit(main())
