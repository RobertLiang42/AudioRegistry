from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
import threading
import uuid
import webbrowser
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ..config import AppConfig, load_config, parse_clip_export_settings, update_local_config
from ..database import ProjectDatabase, database_path_for
from ..i18n import t
from ..pipeline import _audio_duration_seconds, export_assembly_selection
from ..spreadsheet_export import export_assembly_spreadsheet

ASSET_DIR = Path(__file__).with_name("assets")
SHARED_UI_DIR = Path(__file__).parents[1] / "ui"
LOCALE_DIR = Path(__file__).parents[1] / "locales"
PICKER_SCRIPT = Path(__file__).parents[1] / "audio_picker_process.py"
DIRECTORY_PICKER_SCRIPT = Path(__file__).parents[1] / "directory_picker_process.py"


def choose_audio_variants_isolated(project_name: str, *, relocate_path: str | None = None) -> list[Path]:
    """Run Tk in a separate process so a native dialog crash cannot stop WebUI2."""
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    source_root = str(PICKER_SCRIPT.parents[1])
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
            [sys.executable, str(PICKER_SCRIPT), project_name] + ([relocate_path] if relocate_path is not None else []),
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            **kwargs,
        )
    except subprocess.CalledProcessError as error:
        detail = str(error.stderr or error.stdout or "").strip()
        fallback = t("common.process_exit_code", code=error.returncode)
        raise RuntimeError(t("errors.picker_launch", detail=detail or fallback)) from error
    try:
        values = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(t("errors.picker_return")) from error
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise RuntimeError(t("errors.picker_format"))
    return [Path(value).resolve() for value in values]


def choose_output_directory_isolated(title: str) -> Path | None:
    """Run the native folder picker outside the WebUI server process."""
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
            [sys.executable, str(DIRECTORY_PICKER_SCRIPT), title],
            check=True, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=environment, **kwargs,
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


class AssemblyApplication:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.database = ProjectDatabase(database_path_for(
            config.paths.data_dir, legacy_directories=(config.paths.output_dir,)
        ))
        self.export_lock = threading.Lock()
        self.picker_lock = threading.Lock()
        self.pending_audio: dict[str, dict[str, object]] = {}
        self.export_status: dict[str, object] = {"state": "idle"}

    def state(self, project_names: list[str]) -> dict[str, object]:
        payload = self.database.load_assembly(project_names)
        for project in payload["projects"]:
            project["speakers"] = sorted({
                str(row.get("speaker") or "Unassigned") for row in project["segments"]
            })
            for index, variant in enumerate(project["variants"]):
                variant["label"] = self._variant_label(index)
                variant["available"] = Path(str(variant["audio_path"])).is_file()
        payload["available_projects"] = self.database.list_projects()
        payload["update_counters"] = self.database.project_update_counters(project_names)
        payload["clip_export"] = asdict(load_config(self.config.config_path).clip_export)
        return payload

    def save_export_settings(self, payload: dict[str, object]) -> dict[str, object]:
        settings = parse_clip_export_settings(payload, load_config(self.config.config_path).clip_export)
        update_local_config(self.config.config_path, {"clip_export": asdict(settings)})
        return {"clip_export": asdict(settings)}

    @staticmethod
    def _variant_label(index: int) -> str:
        value = index + 1
        label = ""
        while value:
            value, remainder = divmod(value - 1, 26)
            label = chr(65 + remainder) + label
        return label

    def save(self, payload: dict[str, object]) -> dict[str, object]:
        projects = payload.get("projects")
        if not isinstance(projects, list):
            raise ValueError(t("errors.projects_list"))
        revisions = self.database.save_assembly(projects)
        saved_pending_ids = {
            str(asset.get("id", ""))
            for project in projects
            for asset in (project.get("added_audio") or [])
            if isinstance(asset, dict)
        }
        saved_pending_ids.update(
            str(asset.get("id", ""))
            for project in projects
            for asset in (project.get("relocated_audio") or [])
            if isinstance(asset, dict)
        )
        for asset_id in saved_pending_ids:
            self.pending_audio.pop(asset_id, None)
        return {"revisions": revisions, "update_counters": self.database.project_update_counters([str(project["project_name"]) for project in projects])}

    def add_audio(self, payload: dict[str, object]) -> dict[str, object]:
        project_name = str(payload.get("project_name", ""))
        active_ids = payload.get("active_asset_ids") or []
        deleted_ids = payload.get("deleted_audio_ids") or []
        if not isinstance(active_ids, list) or not isinstance(deleted_ids, list):
            raise ValueError(t("errors.invalid_audio_state"))
        active_id_set = {str(value) for value in active_ids}
        deleted_id_set = {str(value) for value in deleted_ids}
        with self.picker_lock:
            selected = choose_audio_variants_isolated(project_name)
        existing_paths = {
            str(Path(str(asset["audio_path"])).resolve()).casefold()
            for asset in self.database.list_audio_assets(project_name)
            if str(asset["id"]) not in deleted_id_set
        }
        existing_paths.update(
            str(Path(str(asset["audio_path"])).resolve()).casefold()
            for asset_id, asset in self.pending_audio.items()
            if asset.get("project_name") == project_name and asset_id in active_id_set
        )
        added: list[dict[str, object]] = []
        for path in selected:
            resolved = path.resolve()
            if str(resolved).casefold() in existing_paths:
                continue
            asset_id = f"pending:{uuid.uuid4()}"
            asset = {
                "id": asset_id, "project_name": project_name, "name": resolved.stem,
                "audio_path": str(resolved), "offset_seconds": 0.0,
                "duration_seconds": _audio_duration_seconds(resolved),
                "available": True, "pending": True,
            }
            self.pending_audio[asset_id] = asset
            added.append(asset)
            existing_paths.add(str(resolved).casefold())
        return {"count": len(added), "assets": added}

    def audio_path(self, asset_id: str) -> Path:
        asset = self.pending_audio.get(asset_id)
        if asset is None:
            asset = self.database.get_audio_asset_by_id(asset_id)
        path = Path(str(asset["audio_path"]))
        if not path.is_file():
            raise FileNotFoundError(t("errors.audio_file_missing", path=path))
        return path

    def relocate_audio(self, payload: dict[str, object]) -> dict[str, object]:
        project_name = str(payload.get("project_name", ""))
        asset_id = str(payload.get("asset_id", ""))
        asset = self.pending_audio.get(asset_id)
        if asset is None:
            asset = self.database.get_audio_asset_by_id(asset_id)
        if asset["project_name"] != project_name:
            raise ValueError(t("errors.audio_not_project"))
        with self.picker_lock:
            selected = choose_audio_variants_isolated(project_name, relocate_path=str(asset["audio_path"]))
        if not selected:
            return {"relocated": False}
        if len(selected) != 1:
            raise ValueError(t("errors.relocate_one"))
        replacement = selected[0].resolve()
        updated = {
            **asset, "audio_path": str(replacement),
            "duration_seconds": _audio_duration_seconds(replacement),
            "available": True,
        }
        self.pending_audio[asset_id] = updated
        return {"relocated": True, "asset": updated}

    def start_export(self, payload: dict[str, object]) -> dict[str, object]:
        names = payload.get("projects")
        if not isinstance(names, list) or not names:
            raise ValueError(t("errors.select_project"))
        selected_speakers = payload.get("selected_speakers")
        selected_tags = payload.get("selected_tags")
        if not isinstance(selected_speakers, list) or any(not isinstance(value, str) for value in selected_speakers):
            raise ValueError(t("errors.invalid_speaker_filter"))
        if not isinstance(selected_tags, list) or any(not isinstance(value, str) for value in selected_tags):
            raise ValueError(t("errors.invalid_tag_filter"))
        mode = str(payload.get("mode") or "")
        write_list = mode == "list"
        write_table = mode == "table"
        if mode not in {"list", "clips", "table"}:
            raise ValueError(t("errors.invalid_export_type"))
        settings = None
        if mode == "clips":
            settings_payload = payload.get("clip_export", {})
            if not isinstance(settings_payload, dict):
                raise ValueError(t("errors.invalid_export_settings"))
            settings = parse_clip_export_settings(settings_payload, load_config(self.config.config_path).clip_export)
        destination = None
        if write_table:
            with self.picker_lock:
                destination = choose_output_directory_isolated(t("backend.table_folder"))
            if destination is None:
                self.export_status = {"state":"cancelled", "message":t("backend.export_cancelled"), "mode":"table", "cancelled":True}
                return dict(self.export_status)
        with self.export_lock:
            if self.export_status.get("state") == "running":
                raise ValueError(t("errors.export_busy"))
            self.export_status = {"state":"running", "message":t("backend.export_preparing"), "completed":0, "total":0, "progress":0, "mode":mode}

        def progress(completed: int, total: int) -> None:
            action = t("backend.export_table_action" if write_table else ("backend.export_list_action" if write_list else "backend.export_clips_action"))
            self.export_status = {**self.export_status, "state":"running", "message":t("backend.export_progress", action=action, completed=completed, total=total) if total else t("backend.export_empty"), "completed":completed, "total":total, "progress":round(completed * 100 / total) if total else 100}

        def work() -> None:
            try:
                if write_table:
                    result = export_assembly_spreadsheet(
                        self.database, [str(name) for name in names], destination,
                        selected_speakers=[str(name) for name in selected_speakers],
                        selected_tags=[str(name) for name in selected_tags],
                        on_progress=progress,
                    )
                    self.export_status = {"state":"complete", "message":t("backend.table_complete", count=result.count), "completed":result.count, "total":result.count, "progress":100, "table":str(result.path), "mode":mode}
                else:
                    result = export_assembly_selection(
                        self.database, self.config, [str(name) for name in names],
                        write_list=write_list,
                        selected_speakers=[str(name) for name in selected_speakers],
                        selected_tags=[str(name) for name in selected_tags],
                        on_clip_progress=progress,
                        **({"export_settings": settings} if mode == "clips" else {}),
                    )
                    self.export_status = {"state":"complete", "message":t("backend.export_complete_count", count=result.count), "completed":result.count, "total":result.count, "progress":100, "clips":None if write_list else str(result.clips_dir), "list":str(result.list_path) if write_list else None, "mode":mode}
            except BaseException as error:
                self.export_status = {"state":"error", "message":str(error), "mode":mode}
        threading.Thread(target=work, name="assembly-export", daemon=True).start()
        return dict(self.export_status)


class AssemblyHandler(BaseHTTPRequestHandler):
    server_version = "AudioRegistryAssembly/1.0"

    @property
    def app(self) -> AssemblyApplication:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        path = urlsplit(self.path)
        try:
            if path.path == "/api/state":
                query = parse_qs(path.query)
                self._json(self.app.state(query.get("project", [])))
            elif path.path == "/api/locale":
                self._json({"locale": self.app.config.language})
            elif path.path == "/api/update-counters":
                query = parse_qs(path.query)
                self._json({"update_counters": self.app.database.project_update_counters(query.get("project", []))})
            elif path.path == "/api/audio":
                query = parse_qs(path.query)
                self._audio(self.app.audio_path(query.get("id", [""])[0]))
            elif path.path == "/api/export":
                self._json(dict(self.app.export_status))
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
        except (KeyError, TypeError, ValueError, FileNotFoundError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def do_HEAD(self) -> None:
        path = urlsplit(self.path)
        if path.path != "/api/audio":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            query = parse_qs(path.query)
            self._audio(self.app.audio_path(query.get("id", [""])[0]), head_only=True)
        except (KeyError, ValueError, FileNotFoundError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        try:
            payload = self._read_json()
            if path == "/api/save":
                self._json(self.app.save(payload))
            elif path == "/api/add-audio":
                self._json(self.app.add_audio(payload))
            elif path == "/api/relocate-audio":
                self._json(self.app.relocate_audio(payload))
            elif path == "/api/export":
                self._json(self.app.start_export(payload))
            elif path == "/api/export-settings":
                self._json(self.app.save_export_settings(payload))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except (KeyError, TypeError, ValueError, FileNotFoundError, RuntimeError, subprocess.SubprocessError) as error:
            self._json({"error": str(error)}, status=HTTPStatus.CONFLICT)

    def log_message(self, format: str, *args: object) -> None:
        if args and str(args[1]) >= "400":
            super().log_message(format, *args)

    def _read_json(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 50_000_000:
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

    def _audio(self, path: Path, head_only: bool = False) -> None:
        size = path.stat().st_size
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
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "audio/wav")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(length))
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return


class AssemblyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], app: AssemblyApplication) -> None:
        super().__init__(address, AssemblyHandler)
        self.app = app


def serve_assembly(
    config: AppConfig,
    *,
    port: int = 8766,
    open_browser: bool = True,
) -> None:
    if not 1 <= port <= 65535:
        raise ValueError(t("errors.port_range"))
    app = AssemblyApplication(config)
    server = AssemblyServer(("127.0.0.1", port), app)
    url = f"http://127.0.0.1:{server.server_port}/?initial_blank=1"
    print(t("server.assembly_url", url=url))
    print(t("server.stop"))
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
