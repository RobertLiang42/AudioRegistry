from __future__ import annotations

import argparse
import math
import re
from dataclasses import replace
from pathlib import Path

from .config import load_config, update_local_config
from .doctor import print_checks, run_checks
from .i18n import SUPPORTED_LOCALES, set_locale, t

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _language_code(value: str) -> str:
    value = value.strip().lower()
    if value != "auto" and not re.fullmatch(r"[a-z]{2,3}(?:-[a-z]{2})?", value):
        raise argparse.ArgumentTypeError(t("cli.invalid_language"))
    return value


def _padding_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError(t("cli.invalid_padding"))
    return seconds


def _add_processing_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("audio", nargs="?", type=Path, help=t("cli.audio_help"))
    command.add_argument("--project", help=t("cli.project_help"))
    command.add_argument("--subtitle", type=Path, help=t("cli.subtitle_help"))
    command.add_argument(
        "--start-padding", type=_padding_seconds, default=None, help=t("cli.start_padding_help")
    )
    command.add_argument(
        "--end-padding", type=_padding_seconds, default=None, help=t("cli.end_padding_help")
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="audio-registry")
    parser.add_argument(
        "--config",
        type=Path,
        default=PROJECT_ROOT / "config" / "default.yaml",
        help=t("cli.config_help"),
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor", help=t("cli.doctor_help"))
    subcommands.add_parser("project", help=t("cli.project_command_help"))
    language = subcommands.add_parser("language", help=t("cli.language_help"))
    language.add_argument("locale", nargs="?", choices=SUPPORTED_LOCALES)
    start = subcommands.add_parser("start", help=t("cli.start_help"))
    process = subcommands.add_parser("process", help=t("cli.process_help"))
    for command in (start, process):
        _add_processing_arguments(command)
    webui1 = subcommands.add_parser("webui1", help=t("cli.webui1_help"))
    webui1.add_argument("audio", nargs="?", type=Path, help=t("cli.webui1_audio_help"))
    webui1.add_argument("--project", help=t("cli.review_project_help"))
    webui1.add_argument("--port", type=int, default=8765, help=t("cli.port_help"))
    webui1.add_argument("--no-open", action="store_true", help=t("cli.no_open_help"))
    webui2 = subcommands.add_parser("webui2", help=t("cli.webui2_help"))
    webui2.add_argument("--port", type=int, default=8766, help=t("cli.port_help"))
    webui2.add_argument("--no-open", action="store_true", help=t("cli.no_open_help"))
    webui = subcommands.add_parser("webui", help=t("cli.webui_help"))
    webui.add_argument("audio", nargs="?", type=Path, help=t("cli.webui_audio_help"))
    webui.add_argument("--project", help=t("cli.review_project_help"))
    webui.add_argument("--webui1-port", type=int, default=8765, help=t("cli.webui1_port_help"))
    webui.add_argument("--webui2-port", type=int, default=8766, help=t("cli.webui2_port_help"))
    webui.add_argument("--no-open", action="store_true", help=t("cli.no_browsers_help"))
    for command in (start, process, webui1, webui):
        command.add_argument(
            "--language", default=None, type=_language_code, help=t("cli.asr_language_help")
        )
    return parser


def _project_assets(database) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for project in database.list_projects():
        name = str(project["project_name"])
        for asset in database.list_audio_assets(name):
            rows.append({**asset, "project_name": name})
    return rows


def _audio_is_bound(database, project_name: str, audio: Path) -> bool:
    resolved = audio.resolve()
    return any(
        Path(str(asset["audio_path"])).resolve() == resolved
        for asset in database.list_audio_assets(project_name)
    )


def _run_processing(requests, config):
    from .pipeline import prepare_review

    results = []
    current_config = config
    for request in requests:
        job_config = replace(
            current_config,
            asr=replace(
                current_config.asr,
                language=None if request.language == "auto" else request.language,
            ),
        )
        result = prepare_review(
            request.audio,
            job_config,
            project_name=request.project_name,
            start_padding=request.start_padding,
            end_padding=request.end_padding,
            subtitle=request.subtitle,
        )
        current_config = job_config
        results.append((request, result))
        print(t("cli.project_result", name=result.project_name))
        print(t("cli.segments_result", count=len(result.segments)))
        print(t("cli.database_result", path=result.database_path))
        print(t("cli.workspace_result", path=result.workspace_path))
    return results, current_config


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    set_locale(config.language)
    default_language = config.asr.language or "auto"

    if args.command == "language":
        if args.locale:
            update_local_config(config.config_path, {"ui": {"language": args.locale}})
            set_locale(args.locale)
        print(set_locale(args.locale or config.language))
        return 0
    if args.command == "doctor":
        return 0 if print_checks(run_checks(config)) else 1
    if args.command == "project":
        from .database import ProjectDatabase, database_path_for
        from .project_window import show_project_dialog

        show_project_dialog(
            ProjectDatabase(
                database_path_for(config.paths.data_dir, legacy_directories=(config.paths.output_dir,))
            )
        )
        return 0

    if args.command in {"webui1", "webui"}:
        language = args.language or default_language
        config = replace(
            config,
            asr=replace(config.asr, language=None if language == "auto" else language),
        )

    if args.command in {"start", "process"}:
        from .database import ProjectDatabase, database_path_for
        from .dialogs import ProcessDialogResult
        from .project_window import show_project_dialog
        from .workflow_dialogs import show_segment_dialog

        database = ProjectDatabase(
            database_path_for(
                config.paths.data_dir, legacy_directories=(config.paths.output_dir,)
            )
        )
        start_padding = (
            config.process.start_padding if args.start_padding is None else args.start_padding
        )
        end_padding = config.process.end_padding if args.end_padding is None else args.end_padding
        requested_language = args.language or default_language

        def persist_defaults(language: str, start: float, end: float) -> None:
            update_local_config(
                config.config_path,
                {
                    "asr": {"language": language},
                    "process": {"start_padding": start, "end_padding": end},
                },
            )

        selected_projects: list[tuple[str, Path | None]] = []
        if args.command == "start":
            if args.audio is not None:
                audio = args.audio.resolve()
                project_name = args.project or audio.stem
                if not database.has_project(project_name):
                    database.create_project(project_name, audio)
                    selected_projects.append((project_name, audio))
                elif not _audio_is_bound(database, project_name, audio):
                    raise ValueError(t("errors.project_audio_unbound", name=project_name))
            else:
                selected_names = show_project_dialog(
                    database, initial_project=args.project or "", advance=True,
                )
                if selected_names is None:
                    print(t("cli.cancelled"))
                    return 1
                for name in selected_names:
                    assets = database.list_audio_assets(name)
                    selected_projects.append((name, Path(str(assets[0]["audio_path"])) if assets else None))

        if args.audio is not None:
            audio = args.audio.resolve()
            project_name = args.project
            if project_name is None:
                project_name = database.project_name_for_audio(audio)
            if not database.has_project(project_name):
                raise FileNotFoundError(t("errors.project_not_found", name=project_name))
            if not _audio_is_bound(database, project_name, audio):
                raise ValueError(t("errors.project_audio_unbound", name=project_name))
            requests = [
                ProcessDialogResult(
                    project_name,
                    audio,
                    requested_language,
                    start_padding,
                    end_padding,
                    args.subtitle.resolve() if args.subtitle else None,
                )
            ]
        else:
            requests = show_segment_dialog(
                _project_assets(database),
                preferred_projects=(
                    [name for name, _audio in selected_projects]
                    if args.command == "start"
                    else ([args.project] if args.project else [])
                ),
                initial_language=requested_language,
                initial_start_padding=start_padding,
                initial_end_padding=end_padding,
                initial_subtitle=args.subtitle,
                on_defaults_change=persist_defaults,
            )
            if requests is None:
                print(t("cli.cancelled"))
                return 1

        processed, config = _run_processing(requests, config)
        if args.command == "process":
            if not processed:
                print(t("cli.segment_skipped"))
            return 0

        initial_project: str | None = None
        initial_audio: Path | None = None
        project_names: list[str] = []
        for name, audio in selected_projects:
            if name not in project_names:
                project_names.append(name)
            initial_project, initial_audio = name, audio
        for request, result in processed:
            if result.project_name not in project_names:
                project_names.append(result.project_name)
            initial_project, initial_audio = result.project_name, request.audio.resolve()

        print(t("cli.opening_webuis"))
        from .combined_webui import serve_both_webuis

        serve_both_webuis(
            initial_audio,
            config,
            project_name=initial_project,
            assembly_project_name=project_names or None,
        )
        return 0

    if args.command in {"webui1", "webui"}:
        from .database import ProjectDatabase, database_path_for

        database = ProjectDatabase(
            database_path_for(
                config.paths.data_dir, legacy_directories=(config.paths.output_dir,)
            )
        )
        project_name = args.project
        audio = args.audio.resolve() if args.audio else None
        if project_name is None and audio is not None:
            try:
                project_name = database.project_name_for_audio(audio)
            except FileNotFoundError:
                raise ValueError(t("errors.bound_audio_project_required")) from None
        if args.command == "webui1":
            from .webui.server import serve_review

            serve_review(
                audio,
                config,
                port=args.port,
                open_browser=not args.no_open,
                project_name=project_name,
            )
        else:
            from .combined_webui import serve_both_webuis

            serve_both_webuis(
                audio,
                config,
                project_name=project_name,
                webui1_port=args.webui1_port,
                webui2_port=args.webui2_port,
                open_browser=not args.no_open,
            )
        return 0
    if args.command == "webui2":
        from .assembly_webui.server import serve_assembly

        serve_assembly(config, port=args.port, open_browser=not args.no_open)
        return 0
    raise AssertionError(f"unhandled command: {args.command}")
