from __future__ import annotations

import math
import os
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .i18n import t


@dataclass(frozen=True, slots=True)
class PathsConfig:
    ffmpeg: Path
    data_dir: Path
    model_dir: Path
    output_dir: Path


@dataclass(frozen=True, slots=True)
class AudioExportConfig:
    channels: int
    sample_rate: int | Literal["source"]
    codec: str


@dataclass(frozen=True, slots=True)
class SpeakerConfig:
    backend: str
    model: str
    revision: str | None
    segmentation_batch_size: int
    embedding_batch_size: int


@dataclass(frozen=True, slots=True)
class AsrConfig:
    backend: str
    whisper_model: str
    revision: str | None
    language: str | None
    batch_size: int
    compute_type: str


@dataclass(frozen=True, slots=True)
class ProcessConfig:
    start_padding: float
    end_padding: float


@dataclass(frozen=True, slots=True)
class WebUiConfig:
    min_duration: float
    show_hidden: bool
    min_duration_empty_only: bool = False
    duration_filter_enabled: bool = True


@dataclass(frozen=True, slots=True)
class ClipExportConfig:
    convert_format: bool = False
    loudness_balance: bool = False
    target_lufs: float = -24.0
    normalization_strength: float = 0.70
    gain_limit_db: float = 8.0
    true_peak_ceiling_dbtp: float = -1.5


def parse_clip_export_settings(
    values: dict[str, Any], defaults: ClipExportConfig | None = None
) -> ClipExportConfig:
    defaults = defaults or ClipExportConfig()
    parsed = {}
    for key in ("convert_format", "loudness_balance"):
        value = values.get(key, getattr(defaults, key))
        if not isinstance(value, bool):
            raise ValueError(t("errors.config_boolean", key=key))
        parsed[key] = value
    for key, minimum, maximum in (
        ("target_lufs", -70, 0), ("normalization_strength", 0, 1),
        ("gain_limit_db", 0, 60), ("true_peak_ceiling_dbtp", -60, 0),
    ):
        value = values.get(key, getattr(defaults, key))
        if isinstance(value, bool):
            raise ValueError(t("errors.loudness_parameter", key=key))
        try:
            value = float(value)
        except (ValueError, TypeError) as error:
            raise ValueError(t("errors.loudness_parameter", key=key)) from error
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(t("errors.config_range", key=key, minimum=minimum, maximum=maximum))
        parsed[key] = value
    return ClipExportConfig(**parsed)


@dataclass(frozen=True, slots=True)
class AppConfig:
    config_path: Path
    device: str
    audio_export: AudioExportConfig
    speaker: SpeakerConfig
    asr: AsrConfig
    paths: PathsConfig
    process: ProcessConfig
    webui: WebUiConfig
    clip_export: ClipExportConfig = ClipExportConfig()
    language: str | None = None


_CONFIG_WRITE_LOCK = threading.Lock()


def local_config_path(path: str | Path) -> Path:
    source = Path(path).resolve()
    return source.with_name(f"{source.stem}.local{source.suffix}")


def _merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def update_local_config(path: str | Path, updates: dict[str, Any]) -> Path:
    """Atomically merge machine-local defaults without rewriting the main config."""
    target = local_config_path(path)
    with _CONFIG_WRITE_LOCK:
        current: dict[str, Any] = {}
        if target.is_file():
            loaded = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError(t("errors.local_config_mapping", path=target))
            current = loaded
        merged = _merge(current, updates)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                yaml.safe_dump(merged, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


def _project_path(project_root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else project_root / path


def _environment_ffmpeg(project_root: Path) -> Path:
    """Resolve an explicit, project-local, environment, or PATH FFmpeg."""
    executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    explicit = os.environ.get("AUDIOREGISTRY_FFMPEG", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_absolute() else (project_root / path).resolve()
    candidates = [
        Path(sys.prefix) / "Library" / "bin" / executable,
        Path(sys.prefix) / "Scripts" / executable,
        Path(sys.prefix) / "bin" / executable,
        project_root / ".runtime" / "ffmpeg" / "bin" / executable,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    system_ffmpeg = shutil.which("ffmpeg")
    return Path(system_ffmpeg) if system_ffmpeg else candidates[-1]


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    override_path = local_config_path(config_path)
    # Preserve settings from releases that kept config.local.yaml at the
    # repository root. New installations use config/default.local.yaml.
    legacy_override = config_path.parent.parent / "config.local.yaml"
    if (
        not override_path.is_file()
        and config_path.name == "default.yaml"
        and legacy_override.is_file()
    ):
        override_path = legacy_override
    if override_path.is_file():
        overrides = yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
        if not isinstance(overrides, dict):
            raise ValueError(t("errors.local_config_mapping", path=override_path))
        raw = _merge(raw, overrides)
    project_root = config_path.parent
    for candidate in (config_path.parent, *config_path.parents):
        if (candidate / "pyproject.toml").is_file() or (candidate / "main.py").is_file():
            project_root = candidate
            break

    device = str(raw.get("device", "cuda"))
    audio_export = raw.get("audio_export") or {}
    speaker = raw.get("speaker") or {}
    asr = raw.get("asr") or {}
    paths = raw.get("paths") or {}
    process = raw.get("process") or {}
    webui = raw.get("webui") or {}
    ui = raw.get("ui") or {}

    channels = int(audio_export.get("channels", 1))
    sample_rate_raw = audio_export.get("sample_rate", "source")
    sample_rate: int | Literal["source"]
    if isinstance(sample_rate_raw, str) and sample_rate_raw.lower() == "source":
        sample_rate = "source"
    else:
        sample_rate = int(sample_rate_raw)
    codec = str(audio_export.get("codec", "pcm_s16le"))
    language_raw = str(asr.get("language", "auto")).strip().lower()
    language = None if language_raw in {"", "auto", "none"} else language_raw

    if device not in {"cuda", "cpu"}:
        raise ValueError(t("errors.device"))
    if channels < 1:
        raise ValueError(t("errors.channels"))
    if sample_rate != "source" and sample_rate <= 0:
        raise ValueError(t("errors.sample_rate"))
    if codec not in {"pcm_s16le", "pcm_s24le", "pcm_f32le"}:
        raise ValueError(t("errors.codec"))

    segmentation_batch_size = int(speaker.get("segmentation_batch_size", 8))
    embedding_batch_size = int(speaker.get("embedding_batch_size", 16))
    if segmentation_batch_size < 1 or embedding_batch_size < 1:
        raise ValueError(t("errors.speaker_batch"))

    asr_backend = str(asr.get("backend", "builtin:faster-whisper"))
    asr_batch_size = int(asr.get("batch_size", 16))
    if asr_batch_size < 1:
        raise ValueError(t("errors.asr_batch"))
    start_padding = float(process.get("start_padding", 0.0))
    end_padding = float(process.get("end_padding", 0.2))
    min_duration = float(webui.get("min_duration", 0.0))
    if start_padding < 0 or end_padding < 0 or min_duration < 0:
        raise ValueError(t("errors.padding_webui"))

    return AppConfig(
        config_path=config_path,
        device=device,
        audio_export=AudioExportConfig(
            channels=channels,
            sample_rate=sample_rate,
            codec=codec,
        ),
        speaker=SpeakerConfig(
            backend=str(speaker.get("backend", "builtin:pyannote")),
            model=str(
                speaker.get(
                    "model", "pyannote/speaker-diarization-community-1"
                )
            ),
            revision=(str(speaker["revision"]).strip() or None) if speaker.get("revision") else None,
            segmentation_batch_size=segmentation_batch_size,
            embedding_batch_size=embedding_batch_size,
        ),
        asr=AsrConfig(
            backend=asr_backend,
            whisper_model=str(asr.get("whisper_model", "large-v3")),
            revision=(str(asr["revision"]).strip() or None) if asr.get("revision") else None,
            language=language,
            batch_size=asr_batch_size,
            compute_type=str(asr.get("compute_type", "float16")),
        ),
        paths=PathsConfig(
            ffmpeg=_environment_ffmpeg(project_root),
            data_dir=_project_path(project_root, str(paths.get("data_dir", "data"))),
            model_dir=_project_path(project_root, str(paths.get("model_dir", "models"))),
            output_dir=_project_path(project_root, str(paths.get("output_dir", "output"))),
        ),
        process=ProcessConfig(start_padding=start_padding, end_padding=end_padding),
        webui=WebUiConfig(
            min_duration=min_duration,
            show_hidden=bool(webui.get("show_hidden", True)),
            min_duration_empty_only=bool(webui.get("min_duration_empty_only", False)),
            duration_filter_enabled=bool(webui.get("duration_filter_enabled", True)),
        ),
        clip_export=parse_clip_export_settings(raw.get("clip_export") or {}),
        language=(str(ui["language"]).strip() or None) if ui.get("language") else None,
    )
