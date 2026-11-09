"""Offline backup/restore. Archives contain database and published artifacts, never credentials."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from .domain import Problem

class ServiceLock:
    def __init__(self, root):
        self.path = Path(root) / "coordinator.lock"
        self.stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("a+b")
        self.stream.seek(0, 2)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if __import__("os").name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise Problem("SERVICE_IN_USE", "資料目錄正在使用中，請先停止網站服務。") from None
        return self

    def __exit__(self, *args):
        if self.stream:
            if __import__("os").name == "nt":
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            self.stream.close()
            self.stream = None

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def contained(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise Problem("INVALID_BACKUP", "備份路徑超出資料目錄。")
    current = path
    while current != root and current != current.parent:
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise Problem("INVALID_BACKUP", "備份不可包含檔案系統連結。")
        current = current.parent
    return path

def empty_target(target):
    if target.exists() and any(target.iterdir()):
        raise Problem("TARGET_NOT_EMPTY", "目標目錄必須為空，避免覆寫既有資料。")
    target.mkdir(parents=True, exist_ok=True)

def backup(root, target):
    root, target = Path(root).resolve(), Path(target).resolve()
    if target.is_relative_to(root) or root.is_relative_to(target):
        raise Problem("INVALID_BACKUP", "備份與資料目錄不可互相包含。")
    if not (root / "jobs.sqlite3").is_file():
        raise Problem("MISSING_DATABASE", "找不到工作資料庫。")
    with ServiceLock(root):
        empty_target(target)
        source = sqlite3.connect(root / "jobs.sqlite3")
        destination = sqlite3.connect(target / "jobs.sqlite3")
        try:
            if source.execute("SELECT 1 FROM jobs WHERE state IN ('running','publishing','recovering')").fetchone():
                raise Problem("ACTIVE_WORK", "請先停止或恢復所有執行中的工作。")
            source.backup(destination)
            destination.execute("DELETE FROM artifacts WHERE published=0")
            destination.commit()
            rows = destination.execute("SELECT path,sha256 FROM artifacts WHERE published=1").fetchall()
        finally:
            destination.close()
            source.close()
        entries = []
        for relative, sha in rows:
            src, dst = contained(root, relative), contained(target, relative)
            if not src.is_file() or digest(src) != sha:
                raise Problem("INVALID_BACKUP", "來源檔案遺失或損毀，備份未完成。")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            entries.append({"path": relative, "sha256": sha})
        entries.append({"path": "jobs.sqlite3", "sha256": digest(target / "jobs.sqlite3")})
        (target / "backup.json").write_text(json.dumps({"schema_version": 1, "files": entries}, indent=2), encoding="utf-8")

def restore(snapshot, target):
    snapshot, target = Path(snapshot).resolve(), Path(target).resolve()
    if target.is_relative_to(snapshot) or snapshot.is_relative_to(target):
        raise Problem("INVALID_BACKUP", "還原與備份目錄不可互相包含。")
    manifest = json.loads((snapshot / "backup.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise Problem("INVALID_BACKUP", "不支援此備份版本。")
    if not any(entry["path"] == "jobs.sqlite3" for entry in manifest["files"]):
        raise Problem("INVALID_BACKUP", "備份缺少資料庫。")
    for entry in manifest["files"]:
        src = contained(snapshot, entry["path"])
        contained(target, entry["path"])
        if not src.is_file() or digest(src) != entry["sha256"]:
            raise Problem("INVALID_BACKUP", "備份檔案遺失或雜湊不符。")
    empty_target(target)
    for entry in manifest["files"]:
        dst = contained(target, entry["path"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(contained(snapshot, entry["path"]), dst)

def main():
    parser = argparse.ArgumentParser(description="Offline Music Stem Lab backup and restore")
    commands = parser.add_subparsers(dest="operation", required=True)
    save = commands.add_parser("backup")
    save.add_argument("--data-dir", type=Path, default=Path("data"))
    save.add_argument("--output", type=Path, required=True)
    load = commands.add_parser("restore")
    load.add_argument("--snapshot", type=Path, required=True)
    load.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.operation == "backup":
            backup(args.data_dir, args.output)
        else:
            restore(args.snapshot, args.data_dir)
    except (Problem, OSError, ValueError, KeyError) as error:
        print(error.message if isinstance(error, Problem) else "備份／還原失敗，請檢查輸入與檔案完整性。")
        return 1
    print("完成。")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
