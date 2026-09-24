import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio_registry.cli import build_parser, main
from audio_registry.database import ProjectDatabase
from audio_registry.dialogs import ProcessDialogResult
from audio_registry.models import Segment


class CommandTests(unittest.TestCase):
    def test_process_and_webui_audio_are_optional_for_picker_workflows(self):
        self.assertIsNone(build_parser().parse_args(["start"]).audio)
        self.assertIsNone(build_parser().parse_args(["process"]).audio)
        self.assertIsNone(build_parser().parse_args(["webui1"]).audio)
        self.assertIsNone(build_parser().parse_args(["webui"]).audio)

    def test_project_center_replaces_database_command(self):
        self.assertEqual(build_parser().parse_args(["project"]).command, "project")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["database"])

    def test_project_and_segment_dialogs_are_separate(self):
        source = (
            Path(__file__).resolve().parents[1] / "src/audio_registry/project_window.py"
        ).read_text(encoding="utf-8")
        for label in (
            "dialogs.new_project", "dialogs.save_queue",
            "dialogs.project_queue", "dialogs.remove_selected", "dialogs.add_audio_batch",
            "dialogs.create_batch", "dialogs.next_step", "build_database_panel",
        ):
            self.assertIn(label, source)
        segment = (
            Path(__file__).resolve().parents[1] / "src/audio_registry/workflow_dialogs.py"
        ).read_text(encoding="utf-8")
        self.assertIn("dialogs.segment_projects", segment)
        self.assertIn("dialogs.skip_segment", segment)
        self.assertIn("dialogs.start_segment", segment)
        legacy = (
            Path(__file__).resolve().parents[1] / "src/audio_registry/dialogs.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("def show_process_dialog(", legacy)

    def test_webui2_opens_without_project_arguments(self):
        args = build_parser().parse_args(["webui2", "--no-open"])
        self.assertEqual(args.command, "webui2")
        self.assertEqual(args.port, 8766)
        self.assertTrue(args.no_open)

    def test_combined_webui_has_independent_ports(self):
        args = build_parser().parse_args([
            "webui", "movie.wav", "--project", "movie",
            "--webui1-port", "9001", "--webui2-port", "9002", "--no-open",
        ])
        self.assertEqual((args.webui1_port, args.webui2_port), (9001, 9002))
        self.assertTrue(args.no_open)

    def test_process_defaults_to_auto_and_accepts_language_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.wav"
            audio.touch()
            config = root / "config.yaml"
            config.write_text(
                "paths:\n  data_dir: data\n  output_dir: output\nasr:\n  language: ja\n",
                encoding="utf-8",
            )
            ProjectDatabase(root / "data/audio-registry.sqlite3").create_project("sample", audio)
            result = SimpleNamespace(
                segments=[],
                database_path=root / "data/audio-registry.sqlite3",
                workspace_path=root / "output/sample",
                project_name="sample",
            )
            for flags, expected in (([], "ja"), (["--language", "zh"], "zh"),
                                    (["--language", "en"], "en")):
                with (
                    patch("sys.argv", ["main", "--config", str(config), "process",
                                       str(audio), "--project", "sample", *flags]),
                    patch("audio_registry.pipeline.prepare_review", return_value=result) as run,
                    patch("audio_registry.combined_webui.serve_both_webuis") as webuis,
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(main(), 0)
                    self.assertEqual(run.call_args.args[1].asr.language, expected)
                    self.assertEqual(run.call_args.kwargs["start_padding"], 0.0)
                    self.assertEqual(run.call_args.kwargs["end_padding"], 0.2)
                    webuis.assert_not_called()

    def test_project_command_only_opens_project_center(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.yaml"
            config.write_text("paths:\n  data_dir: data\n  output_dir: output\n", encoding="utf-8")
            with (
                patch("sys.argv", ["main", "--config", str(config), "project"]),
                patch("audio_registry.project_window.show_project_dialog", return_value=[]) as center,
                patch("audio_registry.workflow_dialogs.show_segment_dialog") as segment,
                patch("audio_registry.combined_webui.serve_both_webuis") as webuis,
            ):
                self.assertEqual(main(), 0)
            center.assert_called_once()
            segment.assert_not_called()
            webuis.assert_not_called()

    def test_start_runs_processing_then_opens_prefilled_webuis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.wav"
            audio.touch()
            config = root / "config.yaml"
            config.write_text("paths:\n  data_dir: data\n  output_dir: output\n", encoding="utf-8")
            result = SimpleNamespace(
                segments=[], database_path=root / "output/audio-registry.sqlite3",
                workspace_path=root / "output/sample", project_name="sample",
            )
            with (
                patch("sys.argv", ["main", "--config", str(config), "start",
                                   str(audio), "--project", "sample"]),
                patch("audio_registry.pipeline.prepare_review", return_value=result) as run,
                patch("audio_registry.combined_webui.serve_both_webuis") as webuis,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)
            run.assert_called_once()
            self.assertEqual(webuis.call_args.kwargs["project_name"], "sample")
            self.assertEqual(webuis.call_args.kwargs["assembly_project_name"], ["sample"])

    def test_interactive_start_processes_queued_projects_with_individual_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_audio = root / "first.wav"
            second_audio = root / "second.wav"
            subtitle = root / "first.srt"
            for path in (first_audio, second_audio, subtitle):
                path.touch()
            config = root / "config.yaml"
            config.write_text("paths:\n  data_dir: data\n  output_dir: output\n", encoding="utf-8")
            def create_projects(database, **kwargs):
                self.assertTrue(kwargs["advance"])
                database.create_project("first", first_audio)
                database.create_project("second", second_audio)
                return ["first", "second"]
            requests = [
                ProcessDialogResult("first", first_audio, "zh", 0.1, 0.25, subtitle),
                ProcessDialogResult("second", second_audio, "auto", 0.0, 0.4, None),
            ]

            def prepared(audio, _config, *, project_name, **_kwargs):
                return SimpleNamespace(
                    segments=[], database_path=root / "output/audio-registry.sqlite3",
                    workspace_path=root / "output" / project_name, project_name=project_name,
                )

            with (
                patch("sys.argv", ["main", "--config", str(config), "start"]),
                patch("audio_registry.project_window.show_project_dialog", side_effect=create_projects),
                patch("audio_registry.workflow_dialogs.show_segment_dialog", return_value=requests) as segment,
                patch("audio_registry.pipeline.prepare_review", side_effect=prepared) as run,
                patch("audio_registry.combined_webui.serve_both_webuis") as webuis,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)

            self.assertEqual(run.call_count, 2)
            self.assertEqual(segment.call_args.kwargs["preferred_projects"], ["first", "second"])
            first_call, second_call = run.call_args_list
            self.assertEqual(first_call.args[1].asr.language, "zh")
            self.assertEqual(first_call.kwargs["start_padding"], 0.1)
            self.assertEqual(first_call.kwargs["end_padding"], 0.25)
            self.assertEqual(first_call.kwargs["subtitle"], subtitle)
            self.assertIsNone(second_call.args[1].asr.language)
            self.assertEqual(second_call.kwargs["end_padding"], 0.4)
            self.assertEqual(webuis.call_args.args[0], second_audio.resolve())
            self.assertEqual(webuis.call_args.kwargs["project_name"], "second")
            self.assertEqual(webuis.call_args.kwargs["assembly_project_name"], ["first", "second"])

    def test_start_can_skip_segmentation_and_open_empty_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "empty.wav"
            audio.touch()
            config = root / "config.yaml"
            config.write_text(
                "paths:\n  data_dir: data\n  output_dir: output\n", encoding="utf-8"
            )
            with (
                patch("sys.argv", ["main", "--config", str(config), "start"]),
                patch("audio_registry.project_window.show_project_dialog", side_effect=lambda database, **_kwargs: (database.create_project("empty", audio), ["empty"])[1]),
                patch("audio_registry.workflow_dialogs.show_segment_dialog", return_value=[]),
                patch("audio_registry.pipeline.prepare_review") as run,
                patch("audio_registry.combined_webui.serve_both_webuis") as webuis,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)
            run.assert_not_called()
            self.assertTrue(webuis.call_args.args[0].samefile(audio))
            self.assertEqual(webuis.call_args.kwargs["project_name"], "empty")
            document = ProjectDatabase(root / "data/audio-registry.sqlite3").load_review("empty")
            self.assertEqual(document["segments"], [])

    def test_start_next_without_new_projects_still_opens_processing_step(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("paths:\n  data_dir: data\n  output_dir: output\n", encoding="utf-8")
            with (
                patch("sys.argv", ["main", "--config", str(config), "start"]),
                patch("audio_registry.project_window.show_project_dialog", return_value=[]),
                patch("audio_registry.workflow_dialogs.show_segment_dialog", return_value=[]) as segment,
                patch("audio_registry.combined_webui.serve_both_webuis") as webuis,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)
            segment.assert_called_once()
            self.assertEqual(segment.call_args.kwargs["preferred_projects"], [])
            webuis.assert_called_once()

    def test_closing_project_step_cancels_start(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("paths:\n  data_dir: data\n  output_dir: output\n", encoding="utf-8")
            with (
                patch("sys.argv", ["main", "--config", str(config), "start"]),
                patch("audio_registry.project_window.show_project_dialog", return_value=None),
                patch("audio_registry.workflow_dialogs.show_segment_dialog") as segment,
                patch("audio_registry.combined_webui.serve_both_webuis") as webuis,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 1)
            segment.assert_not_called()
            webuis.assert_not_called()

    def test_same_audio_can_be_processed_under_another_project_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "movie.wav"
            audio.touch()
            config = root / "config.yaml"
            config.write_text("paths:\n  data_dir: data\n  output_dir: output\n", encoding="utf-8")
            database = ProjectDatabase(root / "data/audio-registry.sqlite3")
            database.create_review("已有项目", audio, [Segment(0, 1)])
            database.create_project("另一个项目", audio)
            result = SimpleNamespace(
                segments=[], database_path=root / "output/audio-registry.sqlite3",
                workspace_path=root / "output/另一个项目", project_name="另一个项目",
            )
            with (
                patch("sys.argv", ["main", "--config", str(config), "process", str(audio),
                                   "--project", "另一个项目"]),
                patch("audio_registry.pipeline.prepare_review", return_value=result) as run,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(main(), 0)
            run.assert_called_once()

    def test_process_accepts_padding_and_subtitle_options(self):
        args = build_parser().parse_args([
            "process", "movie.wav", "--project", "movie", "--subtitle", "movie.srt",
            "--start-padding", "0.1", "--end-padding", "0.35",
        ])
        self.assertEqual((args.start_padding, args.end_padding), (0.1, 0.35))
        self.assertEqual(args.subtitle, Path("movie.srt"))

    def test_removed_file_export_commands_are_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["transcribe", "movie.wav"])
        for old_command in ("review", "assemble", "finalize"):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                build_parser().parse_args([old_command])

    def test_invalid_language_rejected_by_cli(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["process", "movie.wav", "--language", "invalid"])

    def test_negative_padding_is_rejected_by_cli(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_parser().parse_args(["process", "movie.wav", "--end-padding", "-0.1"])


if __name__ == "__main__":
    unittest.main()
