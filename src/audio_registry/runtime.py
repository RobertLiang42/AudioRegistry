from __future__ import annotations

import os
import sys
from pathlib import Path

_DLL_HANDLES: list[object] = []


def configure_windows_dll_search() -> None:
    """Register project and environment DLL directories before ML imports."""
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    project_root = Path(__file__).resolve().parents[2]
    configured_ffmpeg = os.environ.get("AUDIOREGISTRY_FFMPEG", "").strip()
    candidates = [
        Path(configured_ffmpeg).expanduser().parent if configured_ffmpeg else None,
        Path(sys.prefix) / "Library" / "bin",
        Path(sys.prefix) / "Scripts",
        project_root / ".runtime" / "ffmpeg" / "bin",
    ]
    for candidate in candidates:
        if candidate is None or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        _DLL_HANDLES.append(os.add_dll_directory(str(resolved)))
