# Model backend contracts

AudioRegistry keeps model-specific code behind small factories so another model
can be connected without changing pipeline or UI logic.

## ASR

Set `asr.backend` to `package.module:factory`. The factory receives `AppConfig`
and returns an object with:

```python
def prepare() -> None: ...
def transcribe_segments(audio: str | Path, segments: list[Segment]) -> list[Segment]: ...
```

The result must preserve segment count, order, coordinates, and speakers; only
transcription text should change. An optional `close()` method releases resources.

## Diarization

Set `speaker.backend` to `package.module:factory`. The returned object implements:

```python
def prepare() -> None: ...
def diarize(audio: str | Path) -> list[Segment]: ...
```

Coordinates must be finite, non-negative, ordered, and have positive duration.
An optional `close()` method releases resources.

Model identifiers and revisions belong in local or public YAML configuration;
credentials belong only in environment variables or provider-native stores.
