from __future__ import annotations

import gc
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path

import torch

from .asr import AsrBackend, create_asr_backend
from .config import AppConfig, ClipExportConfig
from .cutting import clip_filename, cut_segments, probe_audio_format
from .database import (
    DEFAULT_TAG,
    ProjectDatabase,
    database_path_for,
    project_workspace_for,
    validate_project_name,
)
from .diarization import Diarizer, create_diarizer
from .i18n import t
from .models import Segment
from .progress import timed_stage


@dataclass(frozen=True, slots=True)
class ReviewPreparation:
    segments: tuple[Segment, ...]
    database_path: Path
    workspace_path: Path
    project_name: str


@dataclass(frozen=True, slots=True)
class GptSovitsExport:
    clips_dir: Path
    list_path: Path
    count: int


def export_audio_clip(
    config: AppConfig,
    source: str | Path,
    segment: Segment,
    *,
    time_offset: float = 0.0,
    export_settings: ClipExportConfig | None = None,
    used_names: set[str] | None = None,
    source_format = None,
    output_dir: str | Path | None = None,
) -> Segment:
    """Export one clip with the same naming and processing used by WebUI2."""
    sample_rate = None if config.audio_export.sample_rate == "source" else config.audio_export.sample_rate
    options = {}
    if export_settings is not None:
        source_path = Path(source).resolve()
        source_format = source_format or probe_audio_format(source_path, config.paths.ffmpeg)
        options = {"source_format": source_format, "export_settings": export_settings}
    return cut_segments(
        source, [segment], output_dir or config.paths.output_dir / "slicer_opt", config.paths.ffmpeg,
        channels=config.audio_export.channels, sample_rate=sample_rate,
        codec=config.audio_export.codec, time_offset=time_offset,
        used_names=used_names, **options,
    )[0]


def export_assembly_selection(
    database: ProjectDatabase,
    config: AppConfig,
    project_names: Collection[str],
    *,
    write_list: bool,
    selected_speakers: Collection[str] | None = None,
    selected_tags: Collection[str] | None = None,
    on_clip_progress: Callable[[int, int], None] | None = None,
    export_settings: ClipExportConfig | None = None,
) -> GptSovitsExport:
    """Export either clips OR a list using identical saved items and naming rules."""
    projects = database.load_assembly(sorted(project_names, key=str.casefold))["projects"]
    allowed_speakers = set(selected_speakers) if selected_speakers is not None else None
    # Keep old projects exportable when no explicit tag filter was supplied.
    allowed_tags = set(selected_tags) if selected_tags is not None else {DEFAULT_TAG, "训练集"}
    jobs: list[tuple[dict, Segment, float]] = []
    for project in projects:
        assets = {str(asset["id"]): asset for asset in project["variants"]}
        for row in project["segments"]:
            if row["tag"] not in allowed_tags:
                continue
            if allowed_speakers is not None and row["speaker"] not in allowed_speakers:
                continue
            asset = assets.get(str(row["selected_variant_id"]))
            if not asset:
                raise ValueError(t("errors.row_audio_missing", project=project["project_name"], row=row["id"]))
            jobs.append((asset, Segment(row["start"], row["end"], row["speaker"], row["text"]), float(asset.get("offset_seconds") or 0)))
    clips_dir = config.paths.output_dir / "slicer_opt"
    completed: list[Segment] = []
    used_names: set[str] = set()
    total = len(jobs)
    if on_clip_progress:
        on_clip_progress(0, total)
    source_formats = {}
    for index, (asset, segment, offset) in enumerate(jobs, 1):
        if write_list:
            filename = clip_filename(asset["audio_path"], segment.start + offset, segment.end + offset, used_names)
            completed.append(segment.with_output_file(clips_dir / filename))
            if on_clip_progress:
                on_clip_progress(index, total)
            continue
        source_format = None
        if export_settings is not None:
            source = Path(asset["audio_path"]).resolve()
            if source not in source_formats:
                source_formats[source] = probe_audio_format(source, config.paths.ffmpeg)
            source_format = source_formats[source]
        completed.append(export_audio_clip(
            config, asset["audio_path"], segment, time_offset=offset,
            export_settings=export_settings, used_names=used_names,
            source_format=source_format,
        ))
        if on_clip_progress:
            on_clip_progress(index, total)
    list_path = config.paths.output_dir / "asr_opt" / "slicer_opt.list"
    if write_list:
        list_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = (config.paths.output_dir.name + "/slicer_opt").replace("\\", "/")
        lines = []
        for segment in completed:
            filename = Path(str(segment.output_file)).name
            text = " ".join(segment.text.replace("|", "｜").splitlines()).strip()
            lines.append(f"{prefix}/{filename}|slicer_opt|ZH|{text}")
        list_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return GptSovitsExport(clips_dir, list_path, len(completed))


def _audio_duration_seconds(audio: Path) -> float:
    from torchcodec.decoders import AudioDecoder

    duration = AudioDecoder(audio).metadata.duration_seconds_from_header
    if duration is None or duration <= 0:
        raise RuntimeError(t("errors.audio_duration_unknown", audio=audio))
    return float(duration)


def _release_backend(backend: object) -> None:
    with timed_stage(t("runtime.releasing_model")):
        close = getattr(backend, "close", None)
        if callable(close):
            close()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def pad_segments(
    segments: list[Segment],
    audio_duration: float,
    *,
    start_padding: float = 0.0,
    end_padding: float = 0.2,
) -> list[Segment]:
    """Add transcription padding without crossing the source audio bounds."""
    if start_padding < 0 or end_padding < 0:
        raise ValueError(t("errors.padding_nonnegative"))
    if audio_duration <= 0:
        raise ValueError(t("errors.audio_duration_positive"))
    return [
        Segment(
            max(0.0, segment.start - start_padding),
            min(audio_duration, segment.end + end_padding),
            segment.speaker,
            segment.text,
            segment.output_file,
        )
        for segment in segments
    ]


def prepare_review(
    audio: str | Path,
    config: AppConfig,
    *,
    diarizer: Diarizer | None = None,
    asr_backend: AsrBackend | None = None,
    project_name: str | None = None,
    start_padding: float = 0.0,
    end_padding: float = 0.2,
    subtitle: str | Path | None = None,
) -> ReviewPreparation:
    """Run diarization and ASR, then stop before clip export."""
    audio_path = Path(audio).resolve()
    if not audio_path.is_file():
        raise FileNotFoundError(audio_path)

    diarizer = diarizer or create_diarizer(config)
    try:
        raw_segments = diarizer.diarize(audio_path)
    finally:
        _release_backend(diarizer)

    padded_segments = pad_segments(
        raw_segments,
        _audio_duration_seconds(audio_path),
        start_padding=start_padding,
        end_padding=end_padding,
    )

    asr_backend = asr_backend or create_asr_backend(config)
    try:
        segments = asr_backend.transcribe_segments(audio_path, padded_segments)
    finally:
        _release_backend(asr_backend)

    if subtitle is not None:
        from .subtitles import correct_transcripts_with_subtitles, load_subtitles

        segments = correct_transcripts_with_subtitles(
            raw_segments, segments, load_subtitles(subtitle)
        )

    project_name = validate_project_name(project_name or audio_path.stem)
    database_path = database_path_for(
        config.paths.data_dir, legacy_directories=(config.paths.output_dir,)
    )
    ProjectDatabase(database_path).create_review(project_name, audio_path, segments)
    workspace_path = project_workspace_for(project_name, database_path.parent)
    return ReviewPreparation(tuple(segments), database_path, workspace_path, project_name)
