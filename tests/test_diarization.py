import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from audio_registry.config import load_config
from audio_registry.diarization import Community1Diarizer, create_diarizer
from audio_registry.models import Segment


class _FakeAnnotation:
    def itertracks(self, *, yield_label: bool = False):
        self.yield_label = yield_label
        turns = [
            (Segment(0, 0.5), "track-a", "MODEL_SPEAKER_17"),
            (Segment(0.5, 2), "track-b", "MODEL_SPEAKER_03"),
            (Segment(2, 3.5), "track-c", "MODEL_SPEAKER_17"),
            (Segment(3.5, 5), "track-d", "MODEL_SPEAKER_03"),
        ]
        return iter(turns)


class _FakeCommunityOutput:
    def __init__(self) -> None:
        self.exclusive_speaker_diarization = _FakeAnnotation()


class _FakeModels:
    def __init__(self, pipeline) -> None:
        self._pipeline = pipeline

    def pipeline(self):
        return self._pipeline

    def close(self) -> None:
        pass


class DiarizationTests(unittest.TestCase):
    def _config(self, root: Path):
        path = root / "config.yaml"
        path.write_text("", encoding="utf-8")
        return load_config(path)

    def test_community_uses_annotation_labels_not_track_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "sample.wav"
            audio.touch()
            config = self._config(root)
            pipeline = Mock(return_value=_FakeCommunityOutput())
            diarizer = Community1Diarizer(config, models=_FakeModels(pipeline))

            audio_data = {"waveform": object(), "sample_rate": 16000, "uri": "sample"}
            with patch("audio_registry.diarization._load_diarization_audio", return_value=audio_data) as load:
                result = diarizer.diarize(audio)
            load.assert_called_once_with(audio.resolve())
            self.assertIs(pipeline.call_args.args[0], audio_data)

            self.assertEqual(
                [segment.speaker for segment in result],
                ["Speaker_1", "Speaker_2", "Speaker_1", "Speaker_2"],
            )

    def test_factory_always_creates_community_diarizer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsInstance(create_diarizer(self._config(root)), Community1Diarizer)


if __name__ == "__main__":
    unittest.main()
