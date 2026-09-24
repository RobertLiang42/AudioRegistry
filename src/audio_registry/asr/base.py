from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..models import Segment


class AsrBackend(Protocol):
    """ASR backend used for the frozen speaker intervals."""

    def prepare(self) -> None: ...

    def transcribe_segments(
        self, audio: str | Path, segments: list[Segment]
    ) -> list[Segment]: ...
