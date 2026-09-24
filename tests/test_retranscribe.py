import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from audio_registry.asr.faster_whisper_backend import FasterWhisperBackend
from audio_registry.config import load_config
from audio_registry.models import Segment


class RetranscriptionTests(unittest.TestCase):
    def setUp(self):
        whisper = ModuleType("faster_whisper")
        audio = ModuleType("faster_whisper.audio")
        whisper.audio = audio
        whisper.WhisperModel = Mock()
        whisper.BatchedInferencePipeline = object
        audio.decode_audio = Mock()
        modules = patch.dict("sys.modules", {
            "faster_whisper": whisper,
            "faster_whisper.audio": audio,
        })
        modules.start()
        self.addCleanup(modules.stop)

    def test_short_rows_stay_blank_without_loading_model(self):
        config = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
        rows = [Segment(0, 0.49, "A", "Thank you", "a.wav"),
                Segment(100, 100.5, "B", "字幕组", "b.wav")]
        with (patch("faster_whisper.WhisperModel") as model,
              patch("faster_whisper.audio.decode_audio") as decode):
            out = FasterWhisperBackend(config).transcribe_segments("unused.wav", rows)
        model.assert_not_called()
        decode.assert_not_called()
        self.assertEqual(out, [s.with_text("") for s in rows])

    def test_skipped_rows_do_not_shift_transcription_assignment(self):
        config = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
        backend = FasterWhisperBackend(config)
        backend._segment_model = SimpleNamespace(frames_per_second=100)
        rows = [Segment(0, .49, "A"), Segment(1, 1.5, "B"), Segment(2, 2.501, "C")]

        class Pipeline:
            def __init__(self, model):
                pass

            def transcribe(self, audio, **kwargs):
                assert len(kwargs["clip_timestamps"]) == 1
                return iter([SimpleNamespace(seek=0, text="Hello", no_speech_prob=0,
                                              avg_logprob=0)]), None

        with (patch("faster_whisper.audio.decode_audio", return_value=np.zeros(3 * 16000)),
              patch("faster_whisper.BatchedInferencePipeline", Pipeline)):
            out = backend.transcribe_segments("unused.wav", rows)
        self.assertEqual(out, [rows[0].with_text(""), rows[1].with_text(""), rows[2].with_text("Hello")])

    def test_independent_languages_long_segments_and_silence(self):
        config = load_config(Path(__file__).resolve().parents[1] / "config.example.yaml")
        calls = []

        class Pipeline:
            def __init__(self, model):
                pass

            def transcribe(self, audio, **kwargs):
                calls.append(kwargs)
                # Two chunks belong to row 1, followed by English and silence.
                texts = ["你好", "世界", "I know you", "hallucination"]
                return iter([SimpleNamespace(
                    seek=i * 3000, text=text, no_speech_prob=0.9 if i == 3 else 0.1,
                    avg_logprob=-2 if i == 3 else -0.2,
                ) for i, text in enumerate(texts)]), None

        backend = FasterWhisperBackend(config)
        backend._segment_model = SimpleNamespace(frames_per_second=100)
        segments = [Segment(0, 31, "A"), Segment(32, 34, "B"), Segment(35, 36, "A")]
        with (patch("faster_whisper.audio.decode_audio", return_value=np.zeros(40 * 16000)),
              patch("faster_whisper.BatchedInferencePipeline", Pipeline)):
            result = backend.transcribe_segments("unused.wav", segments)
            self.assertEqual([s.text for s in result], ["你好 世界", "I know you", ""])
            self.assertEqual([(s.start, s.end, s.speaker) for s in result],
                             [(s.start, s.end, s.speaker) for s in segments])
            self.assertTrue(calls[0]["multilingual"])
            self.assertEqual(calls[0]["task"], "transcribe")
            self.assertFalse(calls[0]["condition_on_previous_text"])
            self.assertEqual([c["end"] - c["start"] for c in calls[0]["clip_timestamps"]], [30, 1, 2, 1])
            backend.config = replace(config, asr=replace(config.asr, language="zh"))
            backend.transcribe_segments("unused.wav", segments)
            self.assertFalse(calls[-1]["multilingual"])
            self.assertEqual(calls[-1]["language"], "zh")

if __name__ == "__main__":
    unittest.main()
