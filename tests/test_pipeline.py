import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from audio_registry.config import ClipExportConfig, load_config
from audio_registry.cutting import AudioFormat
from audio_registry.database import ProjectDatabase
from audio_registry.models import Segment
from audio_registry.pipeline import export_assembly_selection, pad_segments, prepare_review


class FakeDiarizer:
    def __init__(self) -> None:
        self.closed = False

    def diarize(self, audio: str | Path) -> list[Segment]:
        return [Segment(0, 1, "Speaker_1"), Segment(1, 2, "Speaker_2")]

    def prepare(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeAsr:
    def __init__(self) -> None:
        self.closed = False

    def transcribe_segments(
        self, audio: str | Path, segments: list[Segment]
    ) -> list[Segment]:
        return [
            segment.with_text(text)
            for segment, text in zip(segments, ("こん", "にちは"), strict=True)
        ]

    def prepare(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class PipelineTests(unittest.TestCase):
    def test_list_only_export_matches_clip_names_and_never_touches_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            audio = root / "shared.wav"
            audio.touch()
            config_file = root / "config.yaml"
            config_file.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            config = load_config(config_file)
            ffmpeg = root / "ffmpeg.exe"
            ffmpeg.touch()
            config = replace(config, paths=replace(config.paths, ffmpeg=ffmpeg))
            database = ProjectDatabase(root / "output/projects.sqlite3")
            database.create_review("alpha", audio, [Segment(1, 2, "甲", "第一|行\n第二"), Segment(1, 2, "甲", "重复时间")])
            database.create_review("beta", audio, [Segment(1, 2, "乙", "另一个项目")])
            database.set_audio_offset("alpha", audio, 0.125)
            database.set_audio_offset("beta", audio, 0.125)
            with patch("audio_registry.pipeline.cut_segments") as cut, \
                 patch("audio_registry.pipeline.probe_audio_format") as probe:
                listed = export_assembly_selection(database, config, ["alpha", "beta"], write_list=True)
            cut.assert_not_called()
            probe.assert_not_called()
            self.assertFalse(listed.clips_dir.exists())
            self.assertEqual(listed.list_path, config.paths.output_dir / "asr_opt" / "slicer_opt.list")
            self.assertFalse((config.paths.output_dir / "slicer_opt.list").exists())
            lines = listed.list_path.read_text(encoding="utf-8").splitlines()
            listed_names = [Path(line.split("|")[0]).name for line in lines]
            self.assertEqual(listed_names, ["shared-00.00.01.125-00.00.02.125.wav",
                                           "shared-00.00.01.125-00.00.02.125-2.wav",
                                           "shared-00.00.01.125-00.00.02.125-3.wav"])
            self.assertTrue(lines[0].endswith("|slicer_opt|ZH|第一｜行 第二"))

            def fake_ffmpeg(command, **kwargs):
                Path(command[-1]).write_bytes(b"exported clip")
            with patch("audio_registry.pipeline.probe_audio_format", return_value=AudioFormat(2, 48000, "pcm_s24le")), \
                 patch("audio_registry.cutting.subprocess.run", side_effect=fake_ffmpeg):
                clips = export_assembly_selection(database, config, ["beta", "alpha"], write_list=False,
                                                  export_settings=ClipExportConfig())
            self.assertEqual(clips.count, listed.count)
            self.assertEqual(sorted(path.name for path in clips.clips_dir.iterdir()), sorted(listed_names))
            self.assertEqual(listed.list_path.read_text(encoding="utf-8").splitlines(), lines)
            before = {path.name:(path.read_bytes(), path.stat().st_mtime_ns) for path in clips.clips_dir.iterdir()}
            # A list can still be generated with source audio / FFmpeg unavailable.
            audio.unlink()
            ffmpeg.unlink()
            counters = database.project_update_counters(["alpha", "beta"])
            with patch("audio_registry.pipeline.cut_segments") as cut, \
                 patch("audio_registry.pipeline.probe_audio_format") as probe:
                export_assembly_selection(database, config, ["alpha", "beta"], write_list=True)
            cut.assert_not_called()
            probe.assert_not_called()
            self.assertEqual(before, {path.name:(path.read_bytes(), path.stat().st_mtime_ns) for path in clips.clips_dir.iterdir()})
            self.assertEqual(database.project_update_counters(["alpha", "beta"]), counters)
            with patch("audio_registry.pipeline.cut_segments") as cut:
                empty = export_assembly_selection(database, config, ["alpha", "beta"], write_list=True, selected_tags=[])
            cut.assert_not_called()
            self.assertEqual(empty.count, 0)
            self.assertEqual(empty.list_path.read_text(encoding="utf-8"), "")
            self.assertEqual(before, {path.name:(path.read_bytes(), path.stat().st_mtime_ns) for path in clips.clips_dir.iterdir()})

    def test_assembly_export_uses_current_filters_and_selected_variant_offset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.wav"
            processed = root / "processed.wav"
            raw.touch()
            processed.touch()
            config_file = root / "config.yaml"
            config_file.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            config = load_config(config_file)
            database = ProjectDatabase(root / "output/audio-registry.sqlite3")
            database.create_review("movie", raw, [Segment(1, 2, "甲", "保留"), Segment(3, 4, "甲", "排除")])
            variant = database.register_audio_asset("movie", processed, duration_seconds=10)
            database.set_audio_offset("movie", processed, 0.125)
            project = database.load_assembly(["movie"])["projects"][0]
            database.save_assembly([{"project_name":"movie", "revision":1, "tags":["训练集", "低质量"], "offsets":{}, "items":[
                {"id":project["segments"][0]["id"], "text":"保留", "tag":"训练集", "note":"", "selected_variant_id":variant["id"]},
                {"id":project["segments"][1]["id"], "text":"排除", "tag":"低质量", "note":"", "selected_variant_id":project["variants"][0]["id"]},
            ]}])

            calls = []
            def fake_cut(source, segments, output_dir, ffmpeg, **kwargs):
                calls.append((Path(source), list(segments), kwargs))
                return [segments[0].with_output_file(Path(output_dir) / "processed-00.00.01.125-00.00.02.125.wav")]
            with patch("audio_registry.pipeline.cut_segments", side_effect=fake_cut) as cutting:
                result = export_assembly_selection(database, config, ["movie"], write_list=True)
            self.assertEqual(result.count, 1)
            cutting.assert_not_called()
            self.assertFalse(result.clips_dir.exists())
            self.assertIn(
                "output/slicer_opt/processed-00.00.01.125-00.00.02.125.wav|slicer_opt|ZH|保留",
                result.list_path.read_text(encoding="utf-8"),
            )

            calls.clear()
            with patch("audio_registry.pipeline.cut_segments", side_effect=fake_cut):
                selected = export_assembly_selection(
                    database, config, ["movie"], write_list=False,
                    selected_speakers=["甲"], selected_tags=["低质量"],
                )
            self.assertEqual(selected.count, 1)
            self.assertEqual(calls[0][0], raw.resolve())
            self.assertEqual(calls[0][1][0].text, "排除")
            self.assertEqual(calls[0][2]["time_offset"], 0.0)

    def test_prepare_review_registers_the_source_as_default_audio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.wav"
            audio.touch()
            config_file = root / "config.yaml"
            config_file.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            config = load_config(config_file)
            with (
                patch("audio_registry.pipeline.torch.cuda.is_available", return_value=False),
                patch("audio_registry.pipeline._audio_duration_seconds", return_value=3.0),
            ):
                result = prepare_review(
                    audio, config, diarizer=FakeDiarizer(), asr_backend=FakeAsr()
                )
            assembly = ProjectDatabase(result.database_path).load_assembly(["sample"])["projects"][0]
            self.assertTrue(Path(assembly["variants"][0]["audio_path"]).samefile(audio))
            self.assertTrue(all(
                row["selected_variant_id"] == assembly["variants"][0]["id"]
                for row in assembly["segments"]
            ))

    def test_prepare_review_stops_before_cutting_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.wav"
            audio.touch()
            config_file = root / "config.yaml"
            config_file.write_text("paths:\n  output_dir: output\n", encoding="utf-8")
            config = load_config(config_file)
            with (
                patch("audio_registry.pipeline.torch.cuda.is_available", return_value=False),
                patch("audio_registry.pipeline.cut_segments") as cutting,
                patch("audio_registry.pipeline._audio_duration_seconds", return_value=3.0),
            ):
                result = prepare_review(
                    audio, config, diarizer=FakeDiarizer(), asr_backend=FakeAsr()
                )
            cutting.assert_not_called()
            document = ProjectDatabase(result.database_path).load_review(audio)
            self.assertEqual([row["id"] for row in document["segments"]], ["SEG-000001", "SEG-000002"])
            self.assertEqual([row["text"] for row in document["segments"]], ["こん", "にちは"])
            self.assertFalse((root / "output/sample/segments.csv").exists())

    def test_orchestration_preserves_speaker_boundaries_in_database(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.wav"
            audio.touch()
            config_file = root / "config.yaml"
            config_file.write_text(
                "paths:\n"
                "  output_dir: output\n",
                encoding="utf-8",
            )
            config = load_config(config_file)
            diarizer = FakeDiarizer()
            asr = FakeAsr()

            with (
                patch("audio_registry.pipeline.torch.cuda.is_available", return_value=False),
                patch("audio_registry.pipeline._audio_duration_seconds", return_value=3.0),
            ):
                result = prepare_review(
                    audio,
                    config,
                    diarizer=diarizer,
                    asr_backend=asr,
                    project_name="sample",
                )

            self.assertTrue(diarizer.closed)
            self.assertTrue(asr.closed)
            self.assertEqual([s.text for s in result.segments], ["こん", "にちは"])
            self.assertEqual([s.speaker for s in result.segments], ["Speaker_1", "Speaker_2"])
            saved = ProjectDatabase(result.database_path).load_review("sample")
            self.assertEqual([row["speaker"] for row in saved["segments"]], ["Speaker_1", "Speaker_2"])
            self.assertEqual([row["text"] for row in saved["segments"]], ["こん", "にちは"])
            self.assertFalse((root / "output/sample/segments.csv").exists())
            self.assertFalse((root / "output/sample/segments.json").exists())

    def test_process_preserves_exact_diarization_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.wav"
            audio.touch()
            config_file = root / "config.yaml"
            config_file.write_text(
                "paths:\n"
                "  output_dir: output\n",
                encoding="utf-8",
            )
            config = load_config(config_file)
            diarizer = FakeDiarizer()
            asr = FakeAsr()

            with (
                patch("audio_registry.pipeline.torch.cuda.is_available", return_value=False),
                patch("audio_registry.pipeline._audio_duration_seconds", return_value=3.0),
            ):
                result = prepare_review(
                    audio,
                    config,
                    diarizer=diarizer,
                    asr_backend=asr,
                    project_name="sample",
                )

            self.assertEqual(
                [(row.start, row.end) for row in result.segments], [(0, 1.2), (1, 2.2)]
            )

    def test_padding_is_applied_after_diarization_and_clipped_to_audio(self) -> None:
        padded = pad_segments(
            [Segment(0.1, 1.0, "A"), Segment(1.0, 2.95, "B")],
            3.0,
            start_padding=0.25,
            end_padding=0.3,
        )
        self.assertEqual([(row.start, row.end) for row in padded], [(0.0, 1.3), (0.75, 3.0)])
        self.assertEqual([row.speaker for row in padded], ["A", "B"])

    def test_negative_padding_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            pad_segments([Segment(0, 1)], 2, start_padding=-0.1)


if __name__ == "__main__":
    unittest.main()
