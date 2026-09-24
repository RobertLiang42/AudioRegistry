# AudioRegistry contributor guide

This file is the working reference for coding agents and maintainers. Keep it
in sync with architecture or workflow changes.

## Project purpose

AudioRegistry is a local-first audio material registry. It combines speaker
diarization, ASR, subtitle-assisted text alignment, timeline review,
annotation, multi-project dataset assembly, and export. User media stays at its
original path; project metadata is stored in SQLite.

## Repository map

- `src/audio_registry/`: Python package and application logic.
- `src/audio_registry/project_window.py`: shared project creation and management window.
- `src/audio_registry/workflow_dialogs.py`: optional segmentation/transcription dialog.
- `src/audio_registry/webui/`: single-project timeline review server and UI.
- `src/audio_registry/assembly_webui/`: multi-project assembly server and UI.
- `src/audio_registry/locales/`: `zh-CN.json`, `en-US.json`, and `ja-JP.json`.
- `README.md`: Simplified Chinese landing page; English and Japanese translations
  are `docs/en/README.md` and `docs/jp/README.md`. Apply future README content
  changes to all three versions and keep their meaning aligned.
- `docs/cn/`, `docs/en/`, `docs/jp/`: language directories. The user guide is
  translated into all three languages; other detailed technical guides are in English.
- `config/default.yaml`: tracked, portable defaults.
- `config/*.local.yaml`: ignored machine-local overrides.
- `models/`: ignored model weights and download caches.
- `.runtime/`: ignored setup-managed Python, FFmpeg, and other local runtimes.
- `data/`: ignored SQLite registry and runtime data.
- `output/`: ignored exports, backups, and waveform caches.
- `tests/`: standard-library `unittest` suite.

## Commands

```powershell
./setup.ps1
./run.ps1 start
./run.ps1 webui
./run.ps1 project
$env:PYTHONPATH = "$PWD/src"
python -m unittest discover -s tests -v
python scripts/check_i18n.py
python -m ruff check .
powershell -ExecutionPolicy Bypass -File scripts/audit-repository.ps1
```

Clickable entry points are `start.bat` and `webui.bat`.
Both batch launchers invoke `run.ps1` directly.
`run.ps1` prefers an explicit `AUDIOREGISTRY_PYTHON`, then an active Conda or
virtual environment, then the repository `.venv`, then Python on PATH. Model
downloads use the active environment before `.venv` unless `-Python` is given.
FFmpeg resolution prefers an explicit `AUDIOREGISTRY_FFMPEG`, then the selected
Python environment, then the setup-managed copy and PATH.
`start` opens the project center, then optionally processes selected existing project
audio before opening both WebUIs. `project` opens only the project center.
`process` never creates a project; it only
segments/transcribes audio already bound to an existing project.
Project creation commits the project and audio binding immediately, including
projects with no segments. The project center refreshes its database list after
changes. New single/batch creations are selected in the database list by default.
In `start`, Next passes the currently selected database projects to segmentation;
the segmentation dialog must allow an empty selection and Skip.
WebUI1 opens the shared center from its project menu.

## Data and migration safety

- Never commit databases, media, subtitles, spreadsheets, model weights,
  waveform caches, exports, logs, tokens, `.env`, or local configuration.
- The default registry is `data/audio-registry.sqlite3`.
- Current database schema version is 9. Schema migrations must preserve rows,
  IDs, coordinates, annotations, audio bindings, and update counters.
- `DEFAULT_TAG` is `1` for newly created or empty tag values. Historical tag
  strings such as `训练集` and `1训练集` are valid user data and must not be
  silently renamed.
- WebUI edits are staged in the page until Save unless a feature explicitly
  documents otherwise. Project update counters drive refresh detection.

## Internationalization

- All user-visible UI and Python messages use semantic keys via `t("...")`.
- Keep all three locale files structurally identical. Run
  `scripts/check_i18n.py` after every text change.
- Language priority is saved user choice, then browser/system language, then
  `en-US`. Do not add a language dropdown unless product requirements change.
- Adding a language should require only a locale file and registration; do not
  place language-specific branches in business logic.
- Legacy storage keys and historical database values are compatibility data,
  not untranslated UI literals.

## Models and backends

- Built-ins are `builtin:pyannote` and `builtin:faster-whisper` with pinned
  revisions in public configuration and the download script.
- Custom integrations use `package.module:factory`; keep backend interfaces
  independent from model vendor details. See `docs/en/model-backends.md`.
- Do not download or redistribute weights through Git. Respect gated model
  terms and third-party licenses in `THIRD_PARTY_NOTICES.md`.

## Code and release discipline

- Target Python 3.12 and keep Ruff clean (`E`, `F`, `I`, `UP`, `B`).
- Prefer focused modules, typed data boundaries, and explicit transactions.
- Add regression tests for database migrations, staged-save behavior, and UI
  state changes. Run the full suite before handoff.
- `main` is stable, `dev` is integration, and `feature/*` holds focused work.
  Update the version and `CHANGELOG.md` using semantic versioning.
- Do not commit, create releases, or push unless the user explicitly requests
  it. Before publication, inspect staged files and Git history for secrets and
  large binaries.

