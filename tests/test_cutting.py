import math
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audio_registry.config import ClipExportConfig, load_config
from audio_registry.cutting import cut_segments, loudness_gain, measure_loudness, probe_audio_format
from audio_registry.models import Segment


class CuttingTests(unittest.TestCase):
    def test_partial_loudness_gain_and_peak_protection(self):
        settings = ClipExportConfig()
        self.assertAlmostEqual(loudness_gain(-30, -12, settings), 4.2)
        self.assertEqual(loudness_gain(-60, -20, settings), 8)
        self.assertEqual(loudness_gain(-5, -1, settings), -8)
        self.assertAlmostEqual(loudness_gain(-40, -2, settings), 0.5)
        self.assertAlmostEqual(loudness_gain(-40, 10, settings), -11.5)
        self.assertEqual(loudness_gain(-math.inf, -math.inf, settings), 0)
        self.assertEqual(loudness_gain(-math.inf, 0, settings), -1.5)

    def test_real_ffmpeg_optional_steps_preserve_precision_and_clean_temporary_audio(self):
        ffmpeg = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml").paths.ffmpeg
        if not ffmpeg.is_file():
            self.skipTest("FFmpeg is not installed in this Python environment")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                            "sine=frequency=440:duration=1:sample_rate=96000", "-af", "volume=0.02",
                            "-ac", "2", "-c:a", "pcm_s24le", "-y", str(source)], check=True)
            source_format = probe_audio_format(source, ffmpeg)
            original_is_file = Path.is_file
            with patch.object(Path, "is_file", lambda path: False if path.name.startswith("ffprobe") else original_is_file(path)):
                self.assertEqual(probe_audio_format(source, ffmpeg), source_format)
            source_i, source_tp = measure_loudness(source, ffmpeg)
            for convert in (False, True):
                for balance in (False, True):
                    with self.subTest(convert=convert, balance=balance):
                        out = root / f"out-{convert}-{balance}"
                        settings = ClipExportConfig(convert_format=convert, loudness_balance=balance)
                        clips = cut_segments(source, [Segment(0, 1)], out, ffmpeg, export_settings=settings)
                        path = Path(clips[0].output_file)
                        actual = probe_audio_format(path, ffmpeg)
                        self.assertEqual(actual.channels, 1 if convert else 2)
                        self.assertEqual(actual.sample_rate, 48000 if convert else 96000)
                        self.assertEqual(actual.codec, "pcm_s24le")
                        self.assertEqual([item.resolve() for item in out.iterdir()], [path])
                        final_i, final_tp = measure_loudness(path, ffmpeg)
                        self.assertLessEqual(final_tp, settings.true_peak_ceiling_dbtp)
                        if not convert:
                            expected_gain = loudness_gain(source_i, source_tp, settings) if balance else 0
                            self.assertAlmostEqual(final_i - source_i, expected_gain, delta=0.12)

            quiet_source = root / "silence.wav"
            subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=44100:cl=stereo", "-t", "0.1", "-c:a", "pcm_f32le",
                            "-y", str(quiet_source)], check=True)
            quiet_out = root / "quiet-out"
            quiet = cut_segments(quiet_source, [Segment(0, 0.1)], quiet_out, ffmpeg,
                                 export_settings=ClipExportConfig(convert_format=True, loudness_balance=True))
            quiet_path = Path(quiet[0].output_file)
            quiet_format = probe_audio_format(quiet_path, ffmpeg)
            self.assertEqual((quiet_format.channels, quiet_format.sample_rate, quiet_format.codec), (1, 44100, "pcm_f32le"))
            self.assertEqual(measure_loudness(quiet_path, ffmpeg), (-math.inf, -math.inf))
            self.assertEqual([item.resolve() for item in quiet_out.iterdir()], [quiet_path])

    def test_failed_processing_cleans_staging_and_preserves_existing_output(self):
        from audio_registry.cutting import AudioFormat
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, ffmpeg = root / "source.wav", root / "ffmpeg.exe"
            source.touch()
            ffmpeg.touch()
            out = root / "out"
            out.mkdir()
            existing = out / "source-00.00.00.000-00.00.01.000.wav"
            existing.write_bytes(b"existing")
            with patch("audio_registry.cutting.subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
                with self.assertRaises(subprocess.CalledProcessError):
                    cut_segments(source, [Segment(0, 1)], out, ffmpeg,
                                 source_format=AudioFormat(2, 96000, "pcm_s24le"), export_settings=ClipExportConfig())
            self.assertEqual(list(out.iterdir()), [existing])
            self.assertEqual(existing.read_bytes(), b"existing")

    def test_default_is_mono_and_preserves_source_sample_rate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            ffmpeg = root / "ffmpeg.exe"
            source.touch()
            ffmpeg.touch()

            with patch("audio_registry.cutting.subprocess.run") as run:
                cut_segments(source, [Segment(1.0, 2.0)], root / "out", ffmpeg)

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-ac") + 1], "1")
            self.assertNotIn("-ar", command)
            self.assertEqual(command[command.index("-c:a") + 1], "pcm_s16le")
            self.assertLess(command.index("-ss"), command.index("-i"))
            self.assertIn("-accurate_seek", command)
            self.assertEqual(command[command.index("-ss") + 1], "1.000000")
            self.assertEqual(command[command.index("-t") + 1], "1.000000")
            self.assertEqual(Path(command[-1]).name, "source-00.00.01.000-00.00.02.000.wav")

    def test_explicit_sample_rate_is_passed_to_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            ffmpeg = root / "ffmpeg.exe"
            source.touch()
            ffmpeg.touch()

            with patch("audio_registry.cutting.subprocess.run") as run:
                cut_segments(
                    source,
                    [Segment(0.0, 1.0)],
                    root / "out",
                    ffmpeg,
                    sample_rate=32_000,
                )

            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-ar") + 1], "32000")

    def test_offset_changes_decode_position_and_output_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "processed.wav"
            ffmpeg = root / "ffmpeg.exe"
            source.touch()
            ffmpeg.touch()
            with patch("audio_registry.cutting.subprocess.run") as run:
                cut_segments(
                    source,
                    [Segment(10, 12)],
                    root / "out",
                    ffmpeg,
                    time_offset=0.125,
                )
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-ss") + 1], "10.125000")
            self.assertEqual(
                Path(command[-1]).name,
                "processed-00.00.10.125-00.00.12.125.wav",
            )

    def test_progress_reports_each_completed_clip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.wav"
            ffmpeg = root / "ffmpeg.exe"
            source.touch()
            ffmpeg.touch()
            updates = []

            with patch("audio_registry.cutting.subprocess.run"):
                cut_segments(
                    source,
                    [Segment(0, 1), Segment(1, 2), Segment(2, 3)],
                    root / "out",
                    ffmpeg,
                    on_progress=lambda completed, total: updates.append(
                        (completed, total)
                    ),
                )

            self.assertEqual(updates, [(0, 3), (1, 3), (2, 3), (3, 3)])


if __name__ == "__main__":
    unittest.main()
