from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from .config import ClipExportConfig
from .i18n import t
from .models import Segment


@dataclass(frozen=True, slots=True)
class AudioFormat:
    channels: int
    sample_rate: int
    codec: str


def probe_audio_format(source: Path, ffmpeg: Path) -> AudioFormat:
    """Use bundled ffprobe when available, otherwise FFmpeg itself; no new runtime."""
    ffprobe = ffmpeg.with_name("ffprobe" + ffmpeg.suffix)
    bits = 0
    if ffprobe.is_file():
        result = subprocess.run([
            str(ffprobe), "-v", "error", "-select_streams", "a:0", "-show_entries",
            "stream=channels,sample_rate,sample_fmt,bits_per_raw_sample,bits_per_sample",
            "-of", "json", str(source),
        ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        streams = json.loads(result.stdout).get("streams", [])
        if not streams:
            raise ValueError(t("errors.no_audio_stream", path=source))
        stream = streams[0]
        channels, rate, fmt = int(stream["channels"]), int(stream["sample_rate"]), stream["sample_fmt"]
        bits = int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 0)
    else:
        result = subprocess.run([
            str(ffmpeg), "-hide_banner", "-nostats", "-i", str(source), "-map", "0:a:0",
            "-af", "ashowinfo", "-frames:a", "1", "-f", "null", "-",
        ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
        match = re.search(r"fmt:(\w+) channels:(\d+) chlayout:\S+ rate:(\d+)", result.stderr)
        if not match:
            raise ValueError(t("errors.audio_format", path=source))
        fmt, channels, rate = match[1], int(match[2]), int(match[3])
        bit_match = re.search(r"Audio:.*?\((\d+) bit\)", result.stderr)
        bits = int(bit_match[1]) if bit_match else 0
    if fmt.startswith("dbl"):
        codec = "pcm_f64le"
    elif fmt.startswith("flt"):
        codec = "pcm_f32le"
    else:
        bits = bits or {"u8": 8, "s16": 16, "s32": 32, "s64": 64}.get(fmt.rstrip("p"), 16)
        if bits > 32:
            raise ValueError(t("errors.pcm_bits"))
        codec = "pcm_u8" if bits <= 8 else f"pcm_s{16 if bits <= 16 else 24 if bits <= 24 else 32}le"
    return AudioFormat(channels, rate, codec)


def measure_loudness(source: Path, ffmpeg: Path) -> tuple[float, float]:
    # loudnorm is used ONLY for input measurements. Its processed output is discarded.
    result = subprocess.run([
        str(ffmpeg), "-hide_banner", "-nostats", "-i", str(source), "-map", "0:a:0",
        "-af", "loudnorm=I=-24:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-",
    ], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    match = re.search(r'\{\s*"input_i".*?\}', result.stderr, re.DOTALL)
    if not match:
        raise ValueError(t("errors.loudness_result", path=source))
    values = json.loads(match[0])
    return float(values["input_i"]), float(values["input_tp"])


def loudness_gain(measured_lufs: float, true_peak: float, settings: ClipExportConfig) -> float:
    # Silence / ungated very short clips have no reliable Integrated LUFS: do not boost.
    gain = (settings.target_lufs - measured_lufs) * settings.normalization_strength if math.isfinite(measured_lufs) else 0.0
    gain = max(-settings.gain_limit_db, min(settings.gain_limit_db, gain))
    if math.isfinite(true_peak):
        gain = min(gain, settings.true_peak_ceiling_dbtp - true_peak)
    return gain


def _encode_audio(source: Path, output: Path, ffmpeg: Path, audio_format: AudioFormat, gain: float | None = None) -> None:
    command = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-i", str(source),
               "-map", "0:a:0", "-map_metadata", "-1", "-ac", str(audio_format.channels),
               "-ar", str(audio_format.sample_rate), "-c:a", audio_format.codec]
    if gain is not None:
        command.extend(["-af", f"volume={gain:.8f}dB:precision=double"])
    subprocess.run(command + ["-y", str(output)], check=True)


def _process_clip(raw: Path, output: Path, ffmpeg: Path, source_format: AudioFormat, settings: ClipExportConfig, temporary: Path) -> None:
    current, final_format = raw, source_format
    if settings.convert_format:
        final_format = AudioFormat(1, min(source_format.sample_rate, 48000), source_format.codec)
        current = temporary / "converted.wav"
        _encode_audio(raw, current, ffmpeg, final_format)
    if settings.loudness_balance:
        measured, peak = measure_loudness(current, ffmpeg)
        gain = loudness_gain(measured, peak, settings)
        final = temporary / "final.wav"
        _encode_audio(current, final, ffmpeg, final_format, gain)
        # Verify the actual encoded PCM. Rounding / quantization must not violate TP.
        for attempt in range(4):
            _, final_peak = measure_loudness(final, ffmpeg)
            if not math.isfinite(final_peak) or final_peak <= settings.true_peak_ceiling_dbtp:
                break
            if attempt == 3:
                raise ValueError(t("errors.true_peak"))
            gain += settings.true_peak_ceiling_dbtp - final_peak - 0.02
            _encode_audio(current, final, ffmpeg, final_format, gain)
        current = final
    current.replace(output)


def _safe_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or "unnamed"


def _time_component(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}.{minutes:02d}.{secs:02d}.{millis:03d}"


def clip_filename(source: str | Path, start: float, end: float, used_names: set[str]) -> str:
    """Shared deterministic naming for audio exports and list-only exports."""
    if start < -1e-9:
        raise ValueError(t("errors.clip_before_audio"))
    base = f"{_safe_component(Path(source).stem)}-{_time_component(start)}-{_time_component(end)}"
    filename = f"{base}.wav"
    duplicate = 2
    while filename.casefold() in used_names:
        filename = f"{base}-{duplicate}.wav"
        duplicate += 1
    used_names.add(filename.casefold())
    return filename


def cut_segments(
    source: str | Path,
    segments: Sequence[Segment],
    output_dir: str | Path,
    ffmpeg: str | Path,
    *,
    channels: int = 1,
    sample_rate: int | None = None,
    codec: str = "pcm_s16le",
    time_offset: float = 0.0,
    on_progress: Callable[[int, int], None] | None = None,
    used_names: set[str] | None = None,
    source_format: AudioFormat | None = None,
    export_settings: ClipExportConfig | None = None,
) -> list[Segment]:
    """Decode exact intervals as PCM WAV, preserving source rate by default."""
    source_path = Path(source).resolve()
    ffmpeg_path = Path(ffmpeg).resolve()
    destination = Path(output_dir).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if not ffmpeg_path.is_file():
        raise FileNotFoundError(ffmpeg_path)
    if channels < 1:
        raise ValueError(t("errors.channels"))
    if sample_rate is not None and sample_rate <= 0:
        raise ValueError(t("errors.sample_rate"))
    if any(segment.start + time_offset < -1e-9 for segment in segments):
        raise ValueError(t("errors.clip_before_audio"))
    destination.mkdir(parents=True, exist_ok=True)
    if export_settings is not None:
        source_format = source_format or probe_audio_format(source_path, ffmpeg_path)
        channels, sample_rate, codec = source_format.channels, source_format.sample_rate, source_format.codec

    completed: list[Segment] = []
    total = len(segments)
    if on_progress is not None:
        on_progress(0, total)
    used_names = used_names if used_names is not None else set()
    for segment in tqdm(segments, desc="WAV clips", unit="clip", ascii=True):
        actual_start = segment.start + time_offset
        actual_end = segment.end + time_offset
        filename = clip_filename(source_path, actual_start, actual_end, used_names)
        output_path = destination / filename
        # Optional processing is staged atomically before replacing the final clip.
        staging = tempfile.TemporaryDirectory(prefix=".clip-", dir=destination) if export_settings is not None else nullcontext(str(destination))
        with staging as temporary_name:
            temporary = Path(temporary_name)
            raw_path = temporary / "raw.wav" if export_settings is not None else output_path
            command = [
                str(ffmpeg_path), "-hide_banner", "-loglevel", "error",
                # Input seeking avoids decoding the prefix; accurate seeking stays on.
                "-ss", f"{actual_start:.6f}", "-accurate_seek", "-i", str(source_path),
                "-map", "0:a:0", "-t", f"{segment.duration:.6f}",
                "-map_metadata", "-1", "-ac", str(channels), "-c:a", codec,
            ]
            if sample_rate is not None:
                command.extend(["-ar", str(sample_rate)])
            command.extend(["-y", str(raw_path)])
            subprocess.run(command, check=True)
            if export_settings is not None and source_format is not None:
                _process_clip(raw_path, output_path, ffmpeg_path, source_format, export_settings, temporary)
        completed.append(segment.with_output_file(output_path))
        if on_progress is not None:
            on_progress(len(completed), total)
    return completed
