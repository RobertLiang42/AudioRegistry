from __future__ import annotations

import json
import sys

from audio_registry.dialogs import choose_output_directory
from audio_registry.i18n import t


def main() -> int:
    title = sys.argv[1] if len(sys.argv) > 1 else t("dialogs.select_output_folder")
    selected = choose_output_directory(title)
    print(json.dumps(str(selected) if selected is not None else None, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
