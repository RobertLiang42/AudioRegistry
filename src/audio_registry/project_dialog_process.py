from __future__ import annotations

import json
import sys
from pathlib import Path

from audio_registry.config import load_config
from audio_registry.i18n import set_locale


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    config = load_config(Path(sys.argv[1]))
    set_locale(config.language)
    from audio_registry.database import ProjectDatabase, database_path_for
    from audio_registry.project_window import show_project_dialog
    database = ProjectDatabase(
        database_path_for(
            config.paths.data_dir, legacy_directories=(config.paths.output_dir,)
        )
    )
    created = show_project_dialog(database)
    print(json.dumps(created or [], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
