from __future__ import annotations

from importlib import import_module

from ..config import AppConfig
from ..i18n import t
from .base import AsrBackend


def create_asr_backend(config: AppConfig) -> AsrBackend:
    if config.asr.backend in {"whisperx", "faster-whisper", "builtin:faster-whisper"}:
        from .faster_whisper_backend import FasterWhisperBackend

        return FasterWhisperBackend(config)
    module_name, separator, attribute = config.asr.backend.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError(t("errors.asr_backend"))
    backend = getattr(import_module(module_name), attribute)(config)
    if not callable(getattr(backend, "prepare", None)) or not callable(
        getattr(backend, "transcribe_segments", None)
    ):
        raise TypeError(t("errors.custom_asr"))
    return backend
