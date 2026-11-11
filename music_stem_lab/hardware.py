"""Read memory availability on the machine running the local model."""
import csv
import ctypes
from ctypes import wintypes
from functools import lru_cache
import os
import subprocess
import time


class MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("memory_load", wintypes.DWORD),
        ("total_physical", ctypes.c_uint64),
        ("available_physical", ctypes.c_uint64),
        ("total_pagefile", ctypes.c_uint64),
        ("available_pagefile", ctypes.c_uint64),
        ("total_virtual", ctypes.c_uint64),
        ("available_virtual", ctypes.c_uint64),
        ("available_extended_virtual", ctypes.c_uint64),
    ]


def read_ram():
    if os.name != "nt":
        return None
    memory = MemoryStatus(length=ctypes.sizeof(MemoryStatus))
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        return None
    return {
        "total_mib": memory.total_physical // 1024**2,
        "available_mib": memory.available_physical // 1024**2,
    }


def read_gpu(device_uuid):
    if not device_uuid:
        return None
    command = [
        "nvidia-smi", "--id", f"GPU-{device_uuid}",
        "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, encoding="utf-8", errors="replace",
            timeout=3, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        name, total, available = next(csv.reader(result.stdout.splitlines(), skipinitialspace=True))
        total, available = int(total), int(available)
    except (OSError, subprocess.SubprocessError, StopIteration, ValueError):
        return None
    if not 0 <= available <= total or total == 0:
        return None
    return {"name": name, "total_mib": total, "available_mib": available}


@lru_cache(maxsize=1)
def scan(device_uuid, interval):
    return {"gpu": read_gpu(device_uuid), "ram": read_ram()}


def hardware_status(device_uuid):
    return scan(device_uuid, int(time.monotonic() // 10))
