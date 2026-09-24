from __future__ import annotations

import subprocess
import threading
from pathlib import Path

import numpy as np

from .i18n import t


class PeakCache:
    """A compact 10 ms min/max envelope generated once from the source audio."""

    sample_rate = 1000
    samples_per_peak = 10

    def __init__(self, audio: Path, cache_path: Path, ffmpeg: Path) -> None:
        self.audio = audio
        self.cache_path = cache_path
        self.ffmpeg = ffmpeg
        self.minimum: np.ndarray | None = None
        self.maximum: np.ndarray | None = None
        self._lock = threading.Lock()

    def prepare(self) -> None:
        """Load a valid cache or generate it before the review UI starts."""
        self._ensure()

    def get(self, start: float, end: float, points: int) -> tuple[list[float], list[float]]:
        self._ensure()
        assert self.minimum is not None and self.maximum is not None
        rate = self.sample_rate / self.samples_per_peak
        first = max(0, min(len(self.minimum), int(start * rate)))
        last = max(first + 1, min(len(self.minimum), int(np.ceil(end * rate))))
        minimum = self.minimum[first:last]
        maximum = self.maximum[first:last]
        points = max(32, min(5000, points))
        if len(minimum) <= points:
            return minimum.astype(float).tolist(), maximum.astype(float).tolist()
        edges = np.linspace(0, len(minimum), points + 1, dtype=np.int64)
        low = [float(np.min(minimum[edges[i] : max(edges[i] + 1, edges[i + 1])])) for i in range(points)]
        high = [float(np.max(maximum[edges[i] : max(edges[i] + 1, edges[i + 1])])) for i in range(points)]
        return low, high

    def _ensure(self) -> None:
        with self._lock:
            if self.minimum is not None:
                return
            stat = self.audio.stat()
            if self.cache_path.is_file():
                try:
                    with np.load(self.cache_path, allow_pickle=False) as cached:
                        if (
                            int(cached["source_size"]) == stat.st_size
                            and int(cached["source_mtime_ns"]) == stat.st_mtime_ns
                        ):
                            self.minimum = cached["minimum"].astype(np.float32, copy=True)
                            self.maximum = cached["maximum"].astype(np.float32, copy=True)
                            return
                except (OSError, ValueError, KeyError):
                    pass
            self._generate(stat.st_size, stat.st_mtime_ns)

    def _generate(self, source_size: int, source_mtime_ns: int) -> None:
        if not self.ffmpeg.is_file():
            raise FileNotFoundError(self.ffmpeg)
        command = [
            str(self.ffmpeg),
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(self.audio),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(self.sample_rate),
            "-f",
            "f32le",
            "-",
        ]
        result = subprocess.run(command, check=True, capture_output=True)
        waveform = np.frombuffer(result.stdout, dtype="<f4")
        usable = len(waveform) - len(waveform) % self.samples_per_peak
        if usable <= 0:
            raise ValueError(t("errors.waveform_empty"))
        buckets = waveform[:usable].reshape(-1, self.samples_per_peak)
        self.minimum = buckets.min(axis=1).astype(np.float32)
        self.maximum = buckets.max(axis=1).astype(np.float32)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(".tmp.npz")
        try:
            np.savez_compressed(
                temporary,
                minimum=self.minimum,
                maximum=self.maximum,
                source_size=np.int64(source_size),
                source_mtime_ns=np.int64(source_mtime_ns),
            )
            temporary.replace(self.cache_path)
        finally:
            temporary.unlink(missing_ok=True)
