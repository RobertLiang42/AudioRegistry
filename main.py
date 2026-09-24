from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

# Keep writable caches inside the project.
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".cache" / "matplotlib"))
# Standard HTTPS supports resume and avoids optional Xet runtime issues.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from audio_registry.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
