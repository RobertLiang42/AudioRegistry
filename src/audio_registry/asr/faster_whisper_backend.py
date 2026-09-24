from __future__ import annotations

from pathlib import Path

from ..config import AppConfig
from ..i18n import t
from ..text_normalization import simplify_chinese


class FasterWhisperBackend:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._segment_model = None
        self._audio_path = None
        self._audio_waveform = None

    def _load_segment_model(self):
        if self._segment_model is None:
            from faster_whisper import WhisperModel

            self._segment_model = WhisperModel(
                self.config.asr.whisper_model,
                device=self.config.device,
                compute_type=self.config.asr.compute_type,
                download_root=str(self.config.paths.model_dir / "whisper"),
                revision=self.config.asr.revision,
            )
        return self._segment_model

    def transcribe_segments(self, audio, segments, *, on_batch=None):
        """Detect language independently for each frozen speaker interval."""
        import numpy as np
        from faster_whisper import BatchedInferencePipeline
        from faster_whisper.audio import decode_audio
        from rich.console import Console
        from tqdm import tqdm

        if not segments:
            return []
        console = Console(stderr=True)
        # Compare at ASR sample precision so 0.5s stays excluded even when
        # subtracting floating-point timestamps yields 0.5000000000001.
        eligible = [round(s.duration * 16000) > 8000 for s in segments]
        skipped = len(segments) - sum(eligible)
        console.print(t("progress.asr_skipped", count=skipped))
        if not any(eligible):
            return [s.with_text("") for s in segments]
        with console.status(t("progress.asr_loading"), spinner="line"):
            segment_model = self._load_segment_model()
            audio_path = str(Path(audio).resolve())
            if self._audio_waveform is None or self._audio_path != audio_path:
                self._audio_waveform = decode_audio(audio_path, sampling_rate=16000)
                self._audio_path = audio_path
            waveform = self._audio_waveform
        chunks = []
        for row, segment in enumerate(segments):
            if not eligible[row]:
                continue
            start = round(segment.start * 16000)
            end = min(round(segment.end * 16000), len(waveform))
            if start >= end:
                raise ValueError(t("errors.segment_outside_audio", index=row + 1))
            # Whisper accepts at most 30 seconds per independently detected chunk.
            for offset in range(start, end, 480000):
                stop = min(offset + 480000, end)
                chunks.append((row, offset, stop))
        console.print(t("progress.asr_chunks", rows=len(segments), chunks=len(chunks)))
        texts = [[] for _ in segments]
        class LanguageAwarePipeline(BatchedInferencePipeline):
            def generate_segment_batched(self, features, tokenizer, options):
                encoded, outputs = super().generate_segment_batched(features, tokenizer, options)
                # Reuse encoder output: no second audio encoding or decoding.
                self.chunk_languages = (
                    [candidates[0][0][2:-2] for candidates in self.model.model.detect_language(encoded)]
                    if options.multilingual else [tokenizer.language_code] * len(outputs)
                )
                return encoded, outputs

        pipeline = LanguageAwarePipeline(segment_model)
        size = self.config.asr.batch_size
        with tqdm(total=len(chunks), desc=t("progress.asr_segments"), unit=t("progress.segment_unit"), ascii=True) as progress:
            for first in range(0, len(chunks), size):
                batch = chunks[first:first + size]
                # Separate, regular offsets preserve row identity even for tiny clips.
                packed = np.zeros(len(batch) * 480000, dtype=np.float32)
                clips = []
                for index, (_, start, end) in enumerate(batch):
                    packed[index * 480000:index * 480000 + end - start] = waveform[start:end]
                    clips.append({"start": index * 30, "end": index * 30 + (end - start) / 16000})
                generated, _ = pipeline.transcribe(
                    packed, language=self.config.asr.language, task="transcribe",
                    multilingual=self.config.asr.language is None,
                    condition_on_previous_text=False, vad_filter=False,
                    clip_timestamps=clips, batch_size=size, without_timestamps=True,
                )
                for item in generated:
                    index = item.seek // (30 * segment_model.frames_per_second)
                    if not 0 <= index < len(batch):
                        raise RuntimeError(t("errors.asr_chunk_offset"))
                    # Batched inference does not apply the sequential decoder's
                    # no-speech gate, so apply the same joint criterion here.
                    if item.no_speech_prob > 0.6 and item.avg_logprob < -1.0:
                        continue
                    languages = getattr(pipeline, "chunk_languages", [])
                    language = languages[index] if languages else self.config.asr.language
                    texts[batch[index][0]].append(simplify_chinese(item.text.strip(), language))
                progress.update(len(batch))
                if on_batch is not None:
                    on_batch(first + len(batch), len(chunks), texts)
        return [s.with_text(" ".join(parts).strip()) for s, parts in zip(segments, texts, strict=True)]

    def prepare(self) -> None:
        self._load_segment_model()

    def close(self) -> None:
        self._segment_model = None
        self._audio_path = None
        self._audio_waveform = None
