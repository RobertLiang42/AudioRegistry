import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from audio_registry.config import (
    load_config,
    local_config_path,
    parse_clip_export_settings,
    update_local_config,
)


class ConfigTests(unittest.TestCase):
    def test_clip_export_defaults_and_invalid_values(self):
        settings = parse_clip_export_settings({})
        self.assertEqual(settings.target_lufs, -24)
        self.assertEqual(settings.normalization_strength, 0.7)
        self.assertEqual(settings.gain_limit_db, 8)
        self.assertEqual(settings.true_peak_ceiling_dbtp, -1.5)
        for values in ({"target_lufs":float("nan")}, {"gain_limit_db":-1},
                       {"normalization_strength":1.1}, {"true_peak_ceiling_dbtp":1},
                       {"convert_format":"true"}, {"target_lufs":True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                parse_clip_export_settings(values)
    def test_relative_paths_are_resolved_from_config_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.yaml"
            config_file.write_text(
                "paths:\n  output_dir: results\n",
                encoding="utf-8",
            )
            with patch("audio_registry.config.sys.prefix", str(root / "empty-environment")):
                config = load_config(config_file)

            self.assertTrue(config.paths.output_dir.parent.samefile(root))
            self.assertEqual(config.paths.output_dir.name, "results")
            self.assertEqual(config.audio_export.sample_rate, "source")
            self.assertEqual(config.asr.backend, "builtin:faster-whisper")
            self.assertEqual(config.paths.ffmpeg, (root / ".runtime" / "ffmpeg" / "bin" / "ffmpeg.exe").resolve())
            self.assertEqual(
                config.speaker.model, "pyannote/speaker-diarization-community-1"
            )

    def test_active_environment_ffmpeg_precedes_managed_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.yaml"
            config_file.write_text("{}", encoding="utf-8")
            environment = root / "environment"
            environment_ffmpeg = environment / "Library" / "bin" / "ffmpeg.exe"
            environment_ffmpeg.parent.mkdir(parents=True)
            environment_ffmpeg.touch()
            managed_ffmpeg = root / ".runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
            managed_ffmpeg.parent.mkdir(parents=True)
            managed_ffmpeg.touch()

            with patch("audio_registry.config.sys.prefix", str(environment)):
                config = load_config(config_file)

            self.assertEqual(config.paths.ffmpeg, environment_ffmpeg)

    def test_machine_local_config_is_merged_and_updated_without_rewriting_main_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_file = root / "config.yaml"
            original = "asr:\n  language: auto\nprocess:\n  end_padding: 0.2\n"
            config_file.write_text(original, encoding="utf-8")

            update_local_config(config_file, {"process": {"end_padding": 0.35}})
            update_local_config(config_file, {"webui": {"min_duration": 0.1, "show_hidden": False}})

            self.assertEqual(config_file.read_text(encoding="utf-8"), original)
            local = yaml.safe_load(local_config_path(config_file).read_text(encoding="utf-8"))
            self.assertEqual(local["process"]["end_padding"], 0.35)
            self.assertEqual(local["webui"], {"min_duration": 0.1, "show_hidden": False})
            config = load_config(config_file)
            self.assertEqual(config.process.end_padding, 0.35)
            self.assertEqual(config.webui.min_duration, 0.1)
            self.assertFalse(config.webui.show_hidden)



if __name__ == "__main__":
    unittest.main()
