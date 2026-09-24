import tempfile
import unittest
from pathlib import Path

from audio_registry.models import Segment
from audio_registry.subtitles import (
    SubtitleCue,
    correct_transcripts_with_subtitles,
    load_subtitles,
)


class SubtitleTests(unittest.TestCase):
    def test_loads_srt_and_multiline_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "movie.srt"
            path.write_text(
                "1\n00:00:01,250 --> 00:00:03,500\n你好\n世界\n\n"
                "2\n00:00:04,000 --> 00:00:05,000\n<i>再见</i>\n",
                encoding="utf-8",
            )
            cues = load_subtitles(path)
        self.assertEqual(cues, [
            SubtitleCue(1.25, 3.5, "你好 世界"),
            SubtitleCue(4.0, 5.0, "再见"),
        ])

    def test_multiple_subtitle_cues_on_one_row_are_joined_with_a_space(self) -> None:
        diarization = [Segment(0, 4, "A")]
        transcribed = [Segment(0, 4.2, "A", "ASR")]
        corrected = correct_transcripts_with_subtitles(
            diarization,
            transcribed,
            [SubtitleCue(0.2, 1.5, "第一句"), SubtitleCue(1.7, 3.5, "第二句")],
        )
        self.assertEqual(corrected[0].text, "第一句 第二句")

    def test_long_subtitle_is_split_at_asr_aligned_speaker_boundary(self) -> None:
        diarization = [Segment(0, 2, "A"), Segment(2, 4, "B")]
        transcribed = [
            Segment(0, 2.2, "A", "你好"),
            Segment(2, 4.2, "B", "世界"),
        ]
        corrected = correct_transcripts_with_subtitles(
            diarization,
            transcribed,
            [SubtitleCue(0.5, 3.5, "你好，世界！")],
        )
        self.assertEqual([row.text for row in corrected], ["你好，", "世界！"])
        self.assertEqual([(row.start, row.end) for row in corrected], [(0, 2.2), (2, 4.2)])

    def test_overlapping_rows_use_subtitles_and_uncovered_rows_keep_asr(self) -> None:
        diarization = [Segment(0, 1, "A"), Segment(2, 3, "A")]
        transcribed = [Segment(0, 1.2, "A", "wrong"), Segment(2, 3.2, "A", "ASR only")]
        corrected = correct_transcripts_with_subtitles(
            diarization, transcribed, [SubtitleCue(0.1, 0.9, "电影原文")]
        )
        self.assertEqual([row.text for row in corrected], ["电影原文", "ASR only"])


if __name__ == "__main__":
    unittest.main()
