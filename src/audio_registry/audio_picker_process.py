from __future__ import annotations

import json
import sys

from audio_registry.dialogs import choose_audio_variants


def main() -> int:
    project_name = sys.argv[1] if len(sys.argv) > 1 else ""
    relocate_path = sys.argv[2] if len(sys.argv) > 2 else None
    paths = choose_audio_variants(project_name, relocate_path=relocate_path)
    # ASCII-only JSON avoids depending on the parent console code page.
    print(json.dumps([str(path) for path in paths], ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
