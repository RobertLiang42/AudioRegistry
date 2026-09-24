from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path
from typing import Protocol

from .config import AppConfig
from .i18n import t
from .models import Segment


class Diarizer(Protocol):
    def prepare(self) -> None: ...

    def diarize(self, audio: str | Path) -> list[Segment]: ...


def _load_diarization_audio(audio: Path) -> dict:
    """Decode/downmix/resample once; all model windows slice the CPU tensor."""
    from pyannote.audio import Audio

    waveform, sample_rate = Audio(sample_rate=16000, mono="downmix")(str(audio))
    return {"waveform": waveform, "sample_rate": sample_rate, "uri": audio.stem}


class PyannoteModelBundle:
    """Lazy holder for the Community-1 pipeline."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._pipeline = None

    def pipeline(self):
        if self._pipeline is None:
            import torch
            from huggingface_hub import get_token
            from pyannote.audio import Pipeline

            cache_dir = self.config.paths.model_dir / "pyannote"
            cache_dir.mkdir(parents=True, exist_ok=True)
            token = os.environ.get("HF_TOKEN") or get_token()
            if not token:
                raise RuntimeError(t("errors.hf_login"))
            pipeline = Pipeline.from_pretrained(
                self.config.speaker.model,
                token=token,
                cache_dir=str(cache_dir),
                revision=self.config.speaker.revision,
            )
            if pipeline is None:
                raise RuntimeError(t("errors.pyannote_load"))
            pipeline.segmentation_batch_size = self.config.speaker.segmentation_batch_size
            pipeline.embedding_batch_size = self.config.speaker.embedding_batch_size
            pipeline.to(torch.device(self.config.device))
            self._pipeline = pipeline
        return self._pipeline

    def close(self) -> None:
        self._pipeline = None


class Community1Diarizer:
    def __init__(self, config: AppConfig, models: PyannoteModelBundle | None = None) -> None:
        self.config = config
        self.models = models or PyannoteModelBundle(config)

    def prepare(self) -> None:
        self.models.pipeline()

    def diarize(self, audio: str | Path) -> list[Segment]:
        audio_path = Path(audio).resolve()
        if not audio_path.is_file():
            raise FileNotFoundError(audio_path)
        from .progress import DiarizationProgress

        with DiarizationProgress() as hook:
            pipeline = self.models.pipeline()
            hook(t("progress.decode_audio"))
            audio_data = _load_diarization_audio(audio_path)
            output = pipeline(audio_data, hook=hook)
        annotation = output.exclusive_speaker_diarization
        turns = list(annotation.itertracks(yield_label=True))
        canonical: dict[object, str] = {}
        segments: list[Segment] = []
        for turn, _, model_label in turns:
            if model_label not in canonical:
                canonical[model_label] = f"Speaker_{len(canonical) + 1}"
            segments.append(
                Segment(
                    float(turn.start),
                    float(turn.end),
                    speaker=canonical[model_label],
                )
            )
        return segments

    def close(self) -> None:
        self.models.close()


def create_diarizer(config: AppConfig) -> Diarizer:
    backend = config.speaker.backend
    if backend in {"pyannote", "builtin:pyannote"}:
        return Community1Diarizer(config)
    module_name, separator, attribute = backend.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(t("errors.speaker_backend"))
    diarizer = getattr(import_module(module_name), attribute)(config)
    if not callable(getattr(diarizer, "prepare", None)) or not callable(
        getattr(diarizer, "diarize", None)
    ):
        raise TypeError(t("errors.custom_diarizer"))
    return diarizer
