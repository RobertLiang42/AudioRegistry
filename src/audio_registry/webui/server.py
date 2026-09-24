from __future__ import annotations

import csv
import json
import math
import mimetypes
import os
import subprocess
import sys
import threading
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from ..asr import create_asr_backend
from ..assembly_webui.server import choose_audio_variants_isolated
from ..config import AppConfig, load_config, update_local_config
from ..database import (
    DEFAULT_TAG,
    ProjectDatabase,
    database_path_for,
    project_workspace_for,
    validate_project_name,
)
from ..i18n import t
from ..models import Segment
from ..pipeline import _audio_duration_seconds, export_audio_clip
from ..waveform import PeakCache

ASSET_DIR = Path(__file__).with_name("assets")
SHARED_UI_DIR = Path(__file__).parents[1] / "ui"
LOCALE_DIR = Path(__file__).parents[1] / "locales"
DIRECTORY_PICKER_SCRIPT = Path(__file__).parents[1] / "directory_picker_process.py"
PROJECT_DIALOG_SCRIPT = Path(__file__).parents[1] / "project_dialog_process.py"


def create_projects_isolated(config_path: Path) -> list[str]:
    """Open the native project dialog outside the threaded WebUI server."""
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    source_root = str(PROJECT_DIALOG_SCRIPT.parents[1])
    inherited_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        source_root + os.pathsep + inherited_pythonpath
        if inherited_pythonpath else source_root
    )
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [sys.executable, str(PROJECT_DIALOG_SCRIPT), str(config_path)],
            check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=environment, **kwargs,
        )
    except subprocess.CalledProcessError as error:
        detail = str(error.stderr or error.stdout or "").strip()
        fallback = t("common.process_exit_code", code=error.returncode)
        raise RuntimeError(t("errors.picker_launch", detail=detail or fallback)) from error
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(t("errors.picker_return")) from error
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise RuntimeError(t("errors.picker_format"))
    return value


def choose_output_directory_isolated(title: str | None = None) -> Path | None:
    """Run the native directory picker outside the WebUI server process."""
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    source_root = str(DIRECTORY_PICKER_SCRIPT.parents[1])
    inherited_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        source_root + os.pathsep + inherited_pythonpath
        if inherited_pythonpath else source_root
    )
    kwargs: dict[str, object] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [sys.executable, str(DIRECTORY_PICKER_SCRIPT), title or t("backend.clip_folder")], check=True,
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=environment, **kwargs,
        )
    except subprocess.CalledProcessError as error:
        detail = str(error.stderr or error.stdout or "").strip()
        fallback = t("common.process_exit_code", code=error.returncode)
        raise RuntimeError(t("errors.picker_launch", detail=detail or fallback)) from error
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(t("errors.picker_return")) from error
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(t("errors.picker_format"))
    directory = Path(value).resolve()
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    return directory


def _audition_decimal_time(seconds: float) -> str:
    """Format seconds as Audition's decimal marker time (minutes:seconds.millis)."""
    milliseconds = round(float(seconds) * 1000)
    if milliseconds < 0:
        raise ValueError(t("errors.marker_before_audio"))
    minutes, remainder = divmod(milliseconds, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{minutes}:{whole_seconds:02d}.{millis:03d}"


def _srt_time(seconds: float) -> str:
    """Format non-negative seconds as an SRT timestamp."""
    milliseconds = round(float(seconds) * 1000)
    if milliseconds < 0:
        raise ValueError(t("errors.subtitle_before_audio"))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


class ReviewApplication:
    def __init__(self, audio: Path | None, config: AppConfig, project_name: str | None = None) -> None:
        self.config = config
        self.database_path = database_path_for(
            config.paths.data_dir, legacy_directories=(config.paths.output_dir,)
        )
        self.database = ProjectDatabase(self.database_path)
        self.project_name: str | None = None
        self.audio: Path | None = None
        self.audio_asset: dict[str, object] | None = None
        self.audio_offset = 0.0
        self.duration = 0.0
        self.peaks: PeakCache | None = None
        self.pending_audio: dict[str, dict[str, object]] = {}
        self.asr = None
        self.asr_lock = threading.Lock()
        self.picker_lock = threading.Lock()
        self.global_min_duration = config.webui.min_duration
        self.global_min_duration_empty_only = config.webui.min_duration_empty_only
        self.global_duration_filter_enabled = config.webui.duration_filter_enabled
        self.global_show_hidden = config.webui.show_hidden
        if audio is not None or project_name is not None:
            resolved_audio = Path(audio).resolve() if audio is not None else None
            selected_project = project_name
            if selected_project is None and resolved_audio is not None:
                selected_project = self.database.project_name_for_audio(resolved_audio)
            self.select(str(selected_project), audio_path=resolved_audio)

    def _available_projects(self) -> list[dict[str, object]]:
        return self.database.list_projects()

    def _variants(self) -> list[dict[str, object]]:
        if self.project_name is None:
            return []
        variants = [
            dict(row, pending=False, available=Path(str(row["audio_path"])).is_file())
            for row in self.database.list_audio_assets(self.project_name)
        ]
        variants.extend(
            dict(row) for row in self.pending_audio.values()
            if row["project_name"] == self.project_name
        )
        return variants

    def _activate(self, asset: dict[str, object] | None) -> None:
        self.audio_asset = asset
        if asset is None:
            self.audio = None
            self.audio_offset = 0.0
            self.duration = 0.0
            self.peaks = None
            return
        audio = Path(str(asset["audio_path"])).resolve()
        if not audio.is_file():
            raise FileNotFoundError(audio)
        previous_audio, previous_duration = self.audio, self.duration
        self.audio = audio
        self.audio_offset = float(asset.get("offset_seconds", 0.0))
        stored_duration = asset.get("duration_seconds")
        if stored_duration is not None:
            self.duration = float(stored_duration)
        elif previous_duration > 0 and previous_audio == audio:
            self.duration = float(previous_duration)
        else:
            self.duration = _audio_duration_seconds(audio)
        cache_name = f"review-peaks-{str(asset['id']).replace(':', '-')}.npz"
        self.peaks = PeakCache(
            audio,
            project_workspace_for(str(self.project_name), self.database_path.parent) / cache_name,
            self.config.paths.ffmpeg,
        )

    def select(
        self,
        project_name: str,
        *,
        asset_id: str | None = None,
        audio_path: Path | None = None,
        discard_pending: bool = False,
    ) -> dict[str, object]:
        name = validate_project_name(project_name)
        self.database.load_review(name)
        if discard_pending:
            self.pending_audio.clear()
        self.project_name = name
        variants = self._variants()
        if audio_path is not None:
            audio_path = audio_path.resolve()
            asset = next((row for row in variants if Path(str(row["audio_path"])).resolve() == audio_path), None)
            if asset is None:
                asset = self._stage_path(name, audio_path)
                variants = self._variants()
            asset_id = str(asset["id"])
        selected = next(
            (row for row in variants if str(row["id"]) == str(asset_id) and row.get("available", True)),
            None,
        )
        if selected is None:
            selected = next((row for row in variants if row.get("available", True)), None)
        self._activate(selected)
        return self.state()

    def _stage_path(self, project_name: str, path: Path) -> dict[str, object]:
        resolved = path.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        existing = next(
            (row for row in self.database.list_audio_assets(project_name)
             if Path(str(row["audio_path"])).resolve() == resolved),
            None,
        )
        if existing is not None:
            return dict(existing, pending=False)
        staged = next(
            (row for row in self.pending_audio.values()
             if row["project_name"] == project_name and Path(str(row["audio_path"])).resolve() == resolved),
            None,
        )
        if staged is not None:
            return staged
        duration = _audio_duration_seconds(resolved)
        asset_id = f"pending:{uuid.uuid4()}"
        staged = {
            "id": asset_id, "project_name": project_name, "name": resolved.stem,
            "audio_path": str(resolved), "offset_seconds": 0.0,
            "duration_seconds": duration, "pending": True, "available": True,
        }
        self.pending_audio[asset_id] = staged
        return staged

    def add_audio(self) -> dict[str, object]:
        if self.project_name is None:
            raise ValueError(t("common.select_project"))
        selected = choose_audio_variants_isolated(self.project_name)
        added = [self._stage_path(self.project_name, path) for path in selected]
        if self.audio is None and added:
            self._activate(added[0])
        return {"count": len(added), "state": self.state()}

    def create_projects(self) -> dict[str, object]:
        created = create_projects_isolated(self.config.config_path)
        if created:
            self.pending_audio.clear()
            self.select(created[-1], discard_pending=True)
        return {"count": len(created), "created": created, "state": self.state()}


    def state(self) -> dict[str, object]:
        global_preferences = {
            "min_duration": self.global_min_duration,
            "min_duration_empty_only": self.global_min_duration_empty_only,
            "duration_filter_enabled": self.global_duration_filter_enabled,
            "show_hidden": self.global_show_hidden,
        }
        if self.project_name is None:
            return {
                "available_projects": self._available_projects(), "project_name": None,
                "audio_variants": [], "selected_audio_id": None,
                "global_ui_preferences": global_preferences,
            }
        document = self.database.load_review(self.project_name)
        assembly = self.database.load_assembly([self.project_name])["projects"][0]
        annotations = {row["id"]: row for row in assembly["segments"]}
        for row in document["segments"]:
            annotation = annotations.get(row["id"], {})
            row["tag"] = str(annotation.get("tag") or DEFAULT_TAG)
            row["note"] = str(annotation.get("note") or "")
            row["selected_variant_id"] = annotation.get("selected_variant_id")
        active_rows = [row for row in document["segments"] if not row.get("deleted", False)]
        active_starts = [float(row["start"]) for row in active_rows]
        active_ends = [float(row["end"]) for row in active_rows]
        coverage_start = min(active_starts, default=0.0) + self.audio_offset
        coverage_end = max(active_ends, default=0.0) + self.audio_offset
        alignment_warning = None
        if self.audio is not None and (coverage_start < -0.05 or coverage_end > self.duration + 0.05):
            alignment_warning = t("backend.alignment_warning")
        return {
            **document,
            "update_counters": self.database.project_update_counters([self.project_name]),
            "available_projects": self._available_projects(),
            "project_name": self.project_name,
            "audio_name": self.audio.name if self.audio is not None else "",
            "audio_variants": self._variants(),
            "selected_audio_id": self.audio_asset["id"] if self.audio_asset else None,
            "duration": self.duration,
            "audio_offset": self.audio_offset,
            "alignment_warning": alignment_warning,
            "global_ui_preferences": global_preferences,
            "tags": list(assembly["tags"]),
            "speakers": sorted(
                {
                    row.get("speaker") or "Unassigned"
                    for row in document["segments"]
                    if not row.get("deleted", False)
                }
            ),
        }

    def save_global_ui_preferences(self, payload: dict[str, object]) -> dict[str, object]:
        min_duration = float(payload.get("min_duration", self.global_min_duration))
        show_hidden = bool(payload.get("show_hidden", self.global_show_hidden))
        empty_only = payload.get("min_duration_empty_only", self.global_min_duration_empty_only)
        enabled = payload.get("duration_filter_enabled", self.global_duration_filter_enabled)
        if not isinstance(enabled, bool):
            raise ValueError(t("errors.filter_enabled_boolean"))
        if not isinstance(empty_only, bool):
            raise ValueError(t("errors.filter_empty_boolean"))
        if not math.isfinite(min_duration) or min_duration < 0:
            raise ValueError(t("errors.filter_duration"))
        update_local_config(
            self.config.config_path,
            {"webui": {"min_duration": min_duration, "show_hidden": show_hidden, "min_duration_empty_only": empty_only, "duration_filter_enabled": enabled}},
        )
        self.global_min_duration = min_duration
        self.global_show_hidden = show_hidden
        self.global_min_duration_empty_only = empty_only
        self.global_duration_filter_enabled = enabled
        return {"min_duration": min_duration, "show_hidden": show_hidden, "min_duration_empty_only": empty_only, "duration_filter_enabled": enabled}

    def save(self, payload: dict[str, object]) -> dict[str, object]:
        if self.project_name is None:
            raise ValueError(t("common.select_project"))
        current = self.database.load_review(self.project_name)
        expected_revision = int(payload.get("revision", 0))
        if int(current["revision"]) != expected_revision:
            raise ValueError(t("errors.stale_project", name=self.project_name))
        document = {**current, "segments": payload.get("segments")}
        offsets = payload.get("audio_offsets") or {}
        if not isinstance(offsets, dict):
            raise ValueError(t("errors.invalid_audio_offset"))
        if "audio_offset" in payload and self.audio_asset is not None:
            offsets[str(self.audio_asset["id"])] = float(payload["audio_offset"])
        deleted_ids = {str(value) for value in (payload.get("deleted_audio_ids") or [])}
        pending_map: dict[str, str] = {}
        for pending_id, staged in list(self.pending_audio.items()):
            if staged["project_name"] != self.project_name:
                continue
            if pending_id in deleted_ids:
                del self.pending_audio[pending_id]
                continue
            asset = self.database.register_audio_asset(
                self.project_name, str(staged["audio_path"]), name=str(staged["name"]),
                duration_seconds=float(staged["duration_seconds"]),
            )
            pending_map[pending_id] = str(asset["id"])
            self.database.set_audio_offset(
                self.project_name, str(staged["audio_path"]), float(offsets.get(pending_id, 0.0))
            )
            del self.pending_audio[pending_id]
        for asset in self.database.list_audio_assets(self.project_name):
            asset_id = str(asset["id"])
            if asset_id in deleted_ids:
                self.database.delete_audio_asset(self.project_name, asset_id)
            elif asset_id in offsets:
                self.database.set_audio_offset(
                    self.project_name, str(asset["audio_path"]), float(offsets[asset_id])
                )
        saved = self.database.save_review(
            self.project_name,
            document,
            expected_revision=expected_revision,
        )
        active_segments = [
            row for row in (payload.get("segments") or [])
            if isinstance(row, dict) and not row.get("deleted", False)
        ]
        assembly_current = self.database.load_assembly([self.project_name])["projects"][0]
        assembly_rows = {row["id"]: row for row in assembly_current["segments"]}
        assembly_revisions = self.database.save_assembly([{
            "project_name": self.project_name,
            "revision": saved["revision"],
            "items": [{
                "id": row["id"], "speaker": row.get("speaker"), "text": row.get("text", ""),
                "tag": row.get("tag") or DEFAULT_TAG, "note": row.get("note", ""),
                "selected_variant_id": assembly_rows.get(str(row["id"]), {}).get("selected_variant_id"),
            } for row in active_segments],
        }])
        selected_id = str(payload.get("selected_audio_id") or "")
        selected_id = pending_map.get(selected_id, selected_id)
        variants = self.database.list_audio_assets(self.project_name)
        selected = next((row for row in variants if str(row["id"]) == selected_id), None)
        self._activate(selected or (variants[0] if variants else None))
        return {**self.state(), "revision": assembly_revisions[self.project_name]}

    def retranscribe(self, payload: dict[str, object]) -> dict[str, object]:
        if self.audio is None:
            raise ValueError(t("errors.select_audio"))
        start = float(payload["start"])
        end = float(payload["end"])
        segment = Segment(
            start + self.audio_offset,
            end + self.audio_offset,
            str(payload.get("speaker") or "") or None,
        )
        if round(segment.duration * 16000) <= 8000:
            raise ValueError(t("errors.short_retranscribe"))
        with self.asr_lock:
            if self.asr is None:
                self.asr = create_asr_backend(self.config)
            result = self.asr.transcribe_segments(self.audio, [segment])
        return {"text": result[0].text}

    def export_clip(self, payload: dict[str, object]) -> dict[str, object]:
        if self.project_name is None or self.audio is None or self.audio_asset is None:
            raise ValueError(t("errors.select_project_audio"))
        segment_id = str(payload.get("id", ""))
        if not segment_id:
            raise ValueError(t("errors.select_row"))
        start = float(payload["start"])
        end = float(payload["end"])
        offset = float(payload.get("audio_offset", self.audio_offset))
        if not math.isfinite(offset) or not -86400 <= offset <= 86400:
            raise ValueError(t("errors.offset_range"))
        segment = Segment(start, end, str(payload.get("speaker") or "") or None, str(payload.get("text") or ""))
        if segment.start + offset < -1e-9 or segment.end + offset > self.duration + 0.001:
            raise ValueError(t("errors.row_outside_audio"))
        with self.picker_lock:
            destination = choose_output_directory_isolated()
        if destination is None:
            return {"cancelled": True}
        runtime_config = load_config(self.config.config_path)
        completed = export_audio_clip(
            runtime_config, self.audio, segment,
            time_offset=offset,
            export_settings=runtime_config.clip_export,
            output_dir=destination,
        )
        output = Path(str(completed.output_file)).resolve()
        return {"cancelled": False, "path": str(output), "name": output.name}

    def _filtered_export_rows(self, payload: dict[str, object]) -> tuple[list[dict[str, Any]], float]:
        if self.project_name is None or self.audio is None:
            raise ValueError(t("errors.select_project_audio"))
        raw_speakers = payload.get("selected_speakers")
        if not isinstance(raw_speakers, list) or any(not isinstance(value, str) for value in raw_speakers):
            raise ValueError(t("errors.invalid_speaker_filter"))
        selected_speakers = set(raw_speakers)
        raw_tags = payload.get("selected_tags")
        if raw_tags is not None and (not isinstance(raw_tags, list) or any(not isinstance(value, str) for value in raw_tags)):
            raise ValueError(t("errors.invalid_tag_filter"))
        selected_tags = set(raw_tags) if raw_tags is not None else None
        min_duration = float(payload.get("min_duration", 0.0))
        empty_only = bool(payload.get("min_duration_empty_only", False))
        offset = float(payload.get("audio_offset", self.audio_offset))
        if not math.isfinite(min_duration) or min_duration < 0:
            raise ValueError(t("errors.duration_nonnegative"))
        if not math.isfinite(offset) or not -86400 <= offset <= 86400:
            raise ValueError(t("errors.offset_range"))

        document = self.database.load_assembly([self.project_name])["projects"][0]
        rows = sorted(
            (
                row for row in document["segments"]
                if not row.get("deleted", False)
                and str(row.get("speaker") or "Unassigned") in selected_speakers
                and (selected_tags is None or str(row.get("tag") or DEFAULT_TAG) in selected_tags)
                and not (float(row["end"]) - float(row["start"]) < min_duration - 1e-9
                         and (not empty_only or not str(row.get("text") or "").strip()))
            ),
            key=lambda row: (float(row["start"]), float(row["end"]), str(row["id"])),
        )
        return rows, offset

    def export_subtitles(self, payload: dict[str, object]) -> dict[str, object]:
        rows, offset = self._filtered_export_rows(payload)
        subtitles = []
        for row in rows:
            text = "\r\n".join(
                line.strip()
                for line in str(row.get("text") or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
                if line.strip()
            )
            if not text:
                continue
            start = float(row["start"]) + offset
            end = float(row["end"]) + offset
            subtitles.append((start, end, text))

        output_path = self.audio.with_name(t("backend.subtitle_filename", stem=self.audio.stem))
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            for index, (start, end, text) in enumerate(subtitles, start=1):
                handle.write(f"{index}\r\n{_srt_time(start)} --> {_srt_time(end)}\r\n{text}\r\n\r\n")
        return {"path": str(output_path), "count": len(subtitles)}

    def export_audition_markers(self, payload: dict[str, object]) -> dict[str, object]:
        rows, offset = self._filtered_export_rows(payload)
        output_path = self.audio.with_name(t("backend.audition_filename", stem=self.audio.stem))
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\r\n")
            writer.writerow(("Name", "Start", "Duration", "Time Format", "Type", "Description"))
            for row in rows:
                start = float(row["start"]) + offset
                duration = float(row["end"]) - float(row["start"])
                speaker = str(row.get("speaker") or "Unassigned")
                text = " ".join(str(row.get("text") or "").replace("\t", " ").splitlines()).strip()
                description = f"{speaker} · {text}" if text else speaker
                writer.writerow((
                    text, _audition_decimal_time(start),
                    _audition_decimal_time(duration), "decimal", "Cue", description,
                ))
        return {"path": str(output_path), "count": len(rows)}

    def close(self) -> None:
        if self.asr is not None:
            close = getattr(self.asr, "close", None)
            if callable(close):
                close()
            self.asr = None


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "AudioRegistryReview/1.0"

    @property
    def app(self) -> ReviewApplication:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = urlsplit(self.path)
        try:
            if path.path == "/api/state":
                self._json(self.app.state())
            elif path.path == "/api/locale":
                self._json({"locale": self.app.config.language})
            elif path.path == "/api/update-counters":
                query = parse_qs(path.query)
                self._json({"update_counters": self.app.database.project_update_counters(query.get("project", []))})
            elif path.path == "/api/peaks":
                if self.app.peaks is None:
                    raise ValueError(t("errors.select_audio"))
                query = parse_qs(path.query)
                start = float(query.get("start", [0])[0])
                end = float(query.get("end", [self.app.duration])[0])
                points = int(query.get("points", [1600])[0])
                if not 0 <= start < end <= self.app.duration + 0.001:
                    raise ValueError(t("errors.peak_range"))
                minimum, maximum = self.app.peaks.get(start, end, points)
                self._json({"start": start, "end": end, "minimum": minimum, "maximum": maximum})
            elif path.path == "/api/audio":
                self._audio()
            elif path.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
            elif path.path in {"/", "/index.html", "/styles.css", "/app.js"}:
                name = "index.html" if path.path in {"/", "/index.html"} else path.path[1:]
                self._asset(name)
            elif path.path == "/i18n.js":
                self._file(SHARED_UI_DIR / "i18n.js")
            elif path.path.startswith("/locales/"):
                name = path.path.removeprefix("/locales/")
                if not name.endswith(".json") or not name[:-5].replace("-", "").isalnum():
                    self.send_error(HTTPStatus.NOT_FOUND)
                else:
                    self._file(LOCALE_DIR / name)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, TypeError, ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def do_HEAD(self) -> None:
        if urlsplit(self.path).path == "/api/audio":
            self._audio(head_only=True)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        try:
            if urlsplit(self.path).path != "/api/review":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            saved = self.app.save(self._read_json())
            self._json(saved)
        except (KeyError, TypeError, ValueError, FileNotFoundError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.CONFLICT)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/retranscribe":
                self._json(self.app.retranscribe(payload))
            elif path == "/api/export-clip":
                self._json(self.app.export_clip(payload))
            elif path == "/api/export-subtitles":
                self._json(self.app.export_subtitles(payload))
            elif path == "/api/export-audition":
                self._json(self.app.export_audition_markers(payload))
            elif path == "/api/select":
                self._json(self.app.select(
                    str(payload.get("project_name", "")),
                    asset_id=str(payload["asset_id"]) if payload.get("asset_id") else None,
                    discard_pending=bool(payload.get("discard_pending", False)),
                ))
            elif path == "/api/add-audio":
                self._json(self.app.add_audio())
            elif path == "/api/create-projects":
                self._json(self.app.create_projects())
            elif path == "/api/global-ui-preferences":
                self._json(self.app.save_global_ui_preferences(payload))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, TypeError, ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        if args and str(args[1]) >= "400":
            super().log_message(format, *args)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 20_000_000:
            raise ValueError(t("errors.request_size"))
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(t("errors.json_object"))
        return data

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _asset(self, name: str) -> None:
        self._file(ASSET_DIR / name)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _audio(self, head_only: bool = False) -> None:
        if self.app.audio is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        size = self.app.audio.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        value = self.headers.get("Range")
        if value:
            if not value.startswith("bytes=") or "," in value:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            left, right = value[6:].split("-", 1)
            if left:
                start = int(left)
                end = min(int(right), size - 1) if right else size - 1
            else:
                length = int(right)
                start = max(0, size - length)
            if start < 0 or start > end or start >= size:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", mimetypes.guess_type(self.app.audio.name)[0] or "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        try:
            with self.app.audio.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Browsers routinely cancel an earlier byte range after seeking.
            return


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: ReviewApplication) -> None:
        super().__init__(address, ReviewHandler)
        self.app = app


def serve_review(
    audio: str | Path | None,
    config: AppConfig,
    *,
    port: int = 8765,
    open_browser: bool = True,
    project_name: str | None = None,
) -> None:
    if not 1 <= port <= 65535:
        raise ValueError(t("errors.port_range"))
    app = ReviewApplication(Path(audio) if audio is not None else None, config, project_name=project_name)
    server = ReviewServer(("127.0.0.1", port), app)
    url = f"http://127.0.0.1:{server.server_port}/"
    print(t("server.review_url", url=url))
    print(t("server.stop"))
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()
