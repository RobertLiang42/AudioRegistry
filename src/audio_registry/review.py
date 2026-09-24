from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from .i18n import t
from .models import Segment

REVIEW_SCHEMA_VERSION = 1


def build_review_document(
    audio: str | Path | None,
    segments: Iterable[Segment],
) -> dict[str, Any]:
    """Build the stable review document exchanged with the local WebUI."""
    audio_path = str(Path(audio).resolve()) if audio else ""
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for number, segment in enumerate(segments, start=1):
        rows.append(
            {
                "id": f"SEG-{number:06d}",
                "start": segment.start,
                "end": segment.end,
                "speaker": segment.speaker,
                "text": segment.text,
                "deleted": False,
                "manual_text": False,
                "needs_asr": False,
                "origin_ids": [],
            }
        )
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "revision": 1,
        "audio_path": audio_path,
        "created_at": now,
        "updated_at": now,
        "segments": rows,
    }


def validate_review(document: dict[str, Any]) -> None:
    if int(document.get("schema_version", 0)) != REVIEW_SCHEMA_VERSION:
        raise ValueError(t("errors.review_schema"))
    if int(document.get("revision", 0)) < 1:
        raise ValueError(t("errors.review_revision"))
    audio_path = document.get("audio_path")
    if not isinstance(audio_path, str) or (audio_path and not Path(audio_path).is_absolute()):
        raise ValueError(t("errors.review_audio_path"))
    rows = document.get("segments")
    if not isinstance(rows, list):
        raise ValueError(t("errors.review_segments"))
    # Older documents may include browser state; it is not project data.
    document.pop("ui_preferences", None)
    seen: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(t("errors.review_row_object", index=index))
        row_id = str(row.get("id", "")).strip()
        if not row_id or row_id in seen:
            raise ValueError(t("errors.review_row_id", index=index))
        seen.add(row_id)
        try:
            segment = Segment(
                float(row["start"]),
                float(row["end"]),
                row.get("speaker") or None,
                str(row.get("text", "")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(t("errors.review_row_invalid", id=row_id, error=error)) from error
        row["start"] = segment.start
        row["end"] = segment.end
        row["speaker"] = segment.speaker
        row["text"] = segment.text
        row["deleted"] = bool(row.get("deleted", False))
        row["manual_text"] = bool(row.get("manual_text", False))
        row["needs_asr"] = bool(row.get("needs_asr", False))
        origins = row.get("origin_ids", [])
        if not isinstance(origins, list) or any(not isinstance(value, str) for value in origins):
            raise ValueError(t("errors.origin_ids", id=row_id))
        row["origin_ids"] = origins
