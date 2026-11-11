"""Run a pinned Demucs checkpoint in a cancellable local subprocess."""
import argparse
import hashlib
import io
import math
from pathlib import Path

from .domain import EXPORT_SOURCES
from .presets import DEFAULT_PRESET, PRESETS

STEMS = ("drums", "bass", "other", "vocals", "guitar", "piano")
SAMPLE_RATE = 44100
WEIGHTS_SHA256 = "34c22ccb381c6f9fdbf324f04e1e2fe21aaaf293f5ded163a162697ff9a02ddd"
def model_profile(preset_id):
    preset = PRESETS[preset_id]
    profile_id = "demucs-htdemucs-6s-cuda"
    if preset_id != DEFAULT_PRESET:
        profile_id += "-" + preset_id
    return {
        "profile_id": profile_id,
        "version": "demucs-4.0.1",
        "description": (f"Demucs 六軌 CUDA，{preset.segment_seconds} 秒分段、{preset.overlap:.0%} 重疊、"
                        f"shifts={preset.shifts}；伴奏由其餘音軌相加。"),
        "weights_sha256": WEIGHTS_SHA256,
    }


def load(checkpoint):
    import torch
    from demucs.states import load_model

    with checkpoint.open("rb") as stream:
        weights = stream.read(56 * 1024**2)
    if hashlib.sha256(weights).hexdigest() != WEIGHTS_SHA256:
        raise ValueError("Demucs 權重不符合已驗證版本。")
    if not torch.cuda.is_available():
        raise RuntimeError("PyTorch 無法使用 CUDA。")
    torch.ones(1, device="cuda").square().item()
    torch.set_num_threads(4)
    model = load_model(torch.load(io.BytesIO(weights), map_location="cpu", weights_only=False))
    if tuple(model.sources) != STEMS or model.samplerate != SAMPLE_RATE or model.audio_channels != 2:
        raise ValueError("Demucs 權重的音軌或音訊規格不符。")
    return model


def separate(model, source, target, kinds, rate, frames, channels, preset):
    import soundfile
    import torch
    from demucs.apply import apply_model
    from julius import resample_frac
    from torch.nn.functional import pad

    mix, actual_rate = soundfile.read(source, dtype="float32", always_2d=True)
    if actual_rate != SAMPLE_RATE or mix.shape[1] != 2:
        raise ValueError("模型輸入需為 44.1 kHz 雙聲道。")
    stems = apply_model(model, torch.from_numpy(mix.T)[None], device="cuda",
                        segment=preset.segment_seconds, overlap=preset.overlap, shifts=preset.shifts)[0]
    # A WAV source keeps its original format. Align every derived WAV with it.
    def format_track(track):
        if channels == 1:
            track = track.mean(dim=0, keepdim=True)
        if rate != SAMPLE_RATE:
            track = resample_frac(track, SAMPLE_RATE, rate)
        if track.shape[-1] < frames:
            return pad(track, (0, frames - track.shape[-1]))
        return track[..., :frames]

    def track(kind):
        if kind in STEMS:
            return format_track(stems[STEMS.index(kind)])
        removed = EXPORT_SOURCES[kind]
        accompaniment = torch.zeros_like(stems[0])
        for name, stem in zip(STEMS, stems):
            if name != removed:
                accompaniment.add_(stem)
        return format_track(accompaniment)

    # Use one gain for every stem and accompaniment so loud tracks do not clip
    # and the relative levels remain intact.
    peak = 0.0
    for kind in kinds:
        value = track(kind).abs().amax().item()
        if not math.isfinite(value):
            raise ValueError("模型輸出含有無效樣本。")
        peak = max(peak, value)
    gain = 1.0 / max(1.0, peak)
    for kind in kinds:
        soundfile.write(target / f"{kind}.wav", (track(kind) * gain).numpy().T,
                        rate, subtype="PCM_16")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--preset", choices=PRESETS, default=DEFAULT_PRESET)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--kinds", nargs="+", choices=(*STEMS, *EXPORT_SOURCES))
    parser.add_argument("--rate", type=int)
    parser.add_argument("--frames", type=int)
    parser.add_argument("--channels", type=int)
    args = parser.parse_args()
    model = load(args.checkpoint)
    if not args.check:
        separate(model, args.source, args.target, args.kinds, args.rate, args.frames, args.channels,
                 PRESETS[args.preset])


if __name__ == "__main__":
    main()
