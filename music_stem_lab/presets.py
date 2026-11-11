"""Supported settings for the local Demucs six-stem model."""
from dataclasses import dataclass
from enum import StrEnum


class PresetId(StrEnum):
    FAST = "fast"
    BALANCED = "balanced"
    DETAILED = "detailed"


DEFAULT_PRESET = PresetId.BALANCED
MODEL_NAME = "Demucs htdemucs_6s"


@dataclass(frozen=True)
class Preset:
    label: str
    description: str
    segment_seconds: int
    overlap: float
    shifts: int
    vram_gib: int
    ram_gib: int
    timeout_seconds: int = 900


PRESETS = {
    PresetId.FAST: Preset("快速", "較短分段與較少推論次數，適合快速試聽。", 4, 0.25, 1, vram_gib=3, ram_gib=4),
    PresetId.BALANCED: Preset("均衡", "兼顧處理時間與分離細節，沿用原本的分軌參數。", 6, 0.25, 3, vram_gib=5, ram_gib=6),
    PresetId.DETAILED: Preset("精細", "較長分段、更多重疊與時移平均，適合願意等待的完整分軌。", 7, 0.5, 5,
                             vram_gib=7, ram_gib=8, timeout_seconds=1800),
}
