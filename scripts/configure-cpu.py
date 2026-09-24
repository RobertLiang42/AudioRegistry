"""Save CPU settings while preserving other machine-local configuration."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from audio_registry.config import update_local_config  # noqa: E402


def main() -> None:
    update_local_config(
        PROJECT_ROOT / "config" / "default.yaml",
        {"device": "cpu", "asr": {"compute_type": "int8"}},
    )


if __name__ == "__main__":
    main()
