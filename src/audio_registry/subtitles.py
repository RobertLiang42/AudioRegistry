from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from .i18n import t
from .models import Segment


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start: float
    end: float
    text: str


_CLOCK = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})"
)
_TAG = re.compile(r"<[^>]+>")
_ASS_TAG = re.compile(r"\{[^}]*\}")


def _seconds(value: str) -> float:
    match = _CLOCK.fullmatch(value.strip())
    if not match:
        raise ValueError(t("errors.subtitle_time", value=value))
    milliseconds = match["ms"].ljust(3, "0")
    return (
        int(match["h"]) * 3600
        + int(match["m"]) * 60
        + int(match["s"])
        + int(milliseconds) / 1000
    )


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError(t("errors.subtitle_encoding", name=path.name))


def _clean_text(lines: list[str]) -> str:
    text = " ".join(lines).strip()
    return _TAG.sub("", text).replace("&nbsp;", " ").strip()


def _parse_srt_or_vtt(content: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.replace("\ufeff", "").strip())
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start_text, end_text = lines[timing_index].split("-->", 1)
        # WebVTT may append positioning settings after the end timestamp.
        end_text = end_text.strip().split()[0]
        text = _clean_text(lines[timing_index + 1 :])
        if not text:
            continue
        start, end = _seconds(start_text), _seconds(end_text)
        if end > start:
            cues.append(SubtitleCue(start, end, text))
    return cues


def _parse_ass(content: str) -> list[SubtitleCue]:
    cues: list[SubtitleCue] = []
    fields = ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
    in_events = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("["):
            in_events = line.casefold() == "[events]"
            continue
        if not in_events:
            continue
        if line.casefold().startswith("format:"):
            fields = [part.strip().casefold() for part in line.split(":", 1)[1].split(",")]
            continue
        if not line.casefold().startswith("dialogue:"):
            continue
        values = line.split(":", 1)[1].split(",", len(fields) - 1)
        if len(values) != len(fields):
            continue
        row = dict(zip(fields, (value.strip() for value in values), strict=True))
        text = _ASS_TAG.sub("", row.get("text", ""))
        text = text.replace(r"\N", " ").replace(r"\n", " ").replace(r"\h", " ").strip()
        if not text:
            continue
        start, end = _seconds(row["start"]), _seconds(row["end"])
        if end > start:
            cues.append(SubtitleCue(start, end, text))
    return cues


def load_subtitles(path: str | Path) -> list[SubtitleCue]:
    subtitle_path = Path(path).resolve()
    if not subtitle_path.is_file():
        raise FileNotFoundError(subtitle_path)
    suffix = subtitle_path.suffix.casefold()
    content = _read_text(subtitle_path)
    if suffix in {".srt", ".vtt"}:
        cues = _parse_srt_or_vtt(content)
    elif suffix in {".ass", ".ssa"}:
        cues = _parse_ass(content)
    else:
        raise ValueError(t("errors.subtitle_type"))
    if not cues:
        raise ValueError(t("errors.subtitle_empty", name=subtitle_path.name))
    return sorted(cues, key=lambda cue: (cue.start, cue.end))


def _normalized(text: str) -> str:
    return "".join(character.casefold() for character in text if character.isalnum())


def _original_cut(text: str, normalized_count: int) -> int:
    positions: list[int] = []
    for index, character in enumerate(text):
        if character.isalnum():
            positions.extend([index] * len(character.casefold()))
    if normalized_count <= 0:
        return 0
    if normalized_count >= len(positions):
        return len(text)
    cut = positions[normalized_count - 1] + 1
    while cut < positions[normalized_count] and cut < len(text):
        cut += 1
    return cut


def _project_boundary(source_position: int, source: str, target: str) -> tuple[float, float]:
    matcher = SequenceMatcher(None, source, target, autojunk=False)
    blocks = [block for block in matcher.get_matching_blocks() if block.size]
    matched = sum(block.size for block in blocks)
    confidence = matched / max(1, min(len(source), len(target)))
    anchors = [(0, 0), (len(source), len(target))]
    for block in blocks:
        anchors.extend(((block.a, block.b), (block.a + block.size, block.b + block.size)))
    anchors = sorted(set(anchors))
    left = max((anchor for anchor in anchors if anchor[0] <= source_position), default=anchors[0])
    right = min((anchor for anchor in anchors if anchor[0] >= source_position), default=anchors[-1])
    if right[0] == left[0]:
        projected = float(left[1])
    else:
        fraction = (source_position - left[0]) / (right[0] - left[0])
        projected = left[1] + fraction * (right[1] - left[1])
    return projected, confidence


def _split_cue(
    cue: SubtitleCue,
    indices: list[int],
    diarization: list[Segment],
    transcribed: list[Segment],
) -> list[str]:
    if len(indices) == 1:
        return [cue.text]
    target = _normalized(cue.text)
    source_parts = [_normalized(transcribed[index].text) for index in indices]
    source = "".join(source_parts)
    overlaps = [
        max(0.0, min(cue.end, diarization[index].end) - max(cue.start, diarization[index].start))
        for index in indices
    ]
    total_overlap = sum(overlaps)
    cuts = [0]
    source_position = 0
    elapsed_overlap = 0.0
    for part, overlap in zip(source_parts[:-1], overlaps[:-1], strict=True):
        source_position += len(part)
        elapsed_overlap += overlap
        temporal = len(target) * elapsed_overlap / total_overlap if total_overlap else 0.0
        projected, confidence = _project_boundary(source_position, source, target)
        estimate = projected if source and target and confidence >= 0.2 else temporal
        cuts.append(max(cuts[-1], min(len(target), round(estimate))))
    cuts.append(len(target))
    original_cuts = [_original_cut(cue.text, cut) for cut in cuts]
    return [
        cue.text[original_cuts[index] : original_cuts[index + 1]].strip()
        for index in range(len(indices))
    ]


def correct_transcripts_with_subtitles(
    diarization: list[Segment],
    transcribed: list[Segment],
    cues: list[SubtitleCue],
) -> list[Segment]:
    """Replace ASR text on time-overlapping rows while retaining their coordinates."""
    if len(diarization) != len(transcribed):
        raise ValueError(t("errors.subtitle_mismatch"))
    pieces: list[list[str]] = [[] for _ in transcribed]
    covered = [False] * len(transcribed)
    for cue in cues:
        indices = [
            index
            for index, segment in enumerate(diarization)
            if min(segment.end, cue.end) > max(segment.start, cue.start)
        ]
        if not indices:
            continue
        fragments = _split_cue(cue, indices, diarization, transcribed)
        for index, fragment in zip(indices, fragments, strict=True):
            covered[index] = True
            if fragment:
                pieces[index].append(fragment)
    return [
        segment.with_text(" ".join(pieces[index]) if covered[index] else segment.text)
        for index, segment in enumerate(transcribed)
    ]
