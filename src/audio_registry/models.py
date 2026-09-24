from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from .i18n import t


@dataclass(frozen=True, slots=True)
class Segment:
    """A half-open audio interval ``[start, end)`` in seconds."""

    start: float
    end: float
    speaker: str | None = None
    text: str = ""
    output_file: str | None = None

    def __post_init__(self) -> None:
        if not isfinite(self.start) or not isfinite(self.end):
            raise ValueError(t("errors.segment_times"))
        if self.start < 0:
            raise ValueError(t("errors.segment_start"))
        if self.end <= self.start:
            raise ValueError(t("errors.segment_end"))

    @property
    def duration(self) -> float:
        return self.end - self.start

    def with_output_file(self, path: str | Path) -> Segment:
        return Segment(
            start=self.start,
            end=self.end,
            speaker=self.speaker,
            text=self.text,
            output_file=str(path),
        )

    def with_text(self, text: str) -> Segment:
        return Segment(
            start=self.start,
            end=self.end,
            speaker=self.speaker,
            text=text,
            output_file=self.output_file,
        )
