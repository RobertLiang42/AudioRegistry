# Development guide

[English README](README.md) · [Installation](installation.md) · [Model backend contracts](model-backends.md)

AudioRegistry targets Python 3.12. Work on focused `feature/*` branches, integrate reviewed changes into `dev`, and promote tested releases to `main`. Update the version and `CHANGELOG.md` using semantic versioning when preparing a release.

Install the development dependencies and run the checks from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Dev
$env:PYTHONPATH = "$PWD/src"
& .\.venv\Scripts\python.exe -m compileall -q main.py src tests
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe scripts/check_i18n.py
& .\.venv\Scripts\python.exe -m ruff check src tests
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\audit-repository.ps1
```

The suite uses standard-library `unittest`. Keep Ruff clean for `E`, `F`, `I`, `UP`, and `B`. Add regression coverage for database migrations, staged saves, and UI state changes. GitHub Actions runs compile, unit, locale, and repository-safety checks.

All user-visible UI and Python messages use semantic i18n keys. Keep `src/audio_registry/locales/zh-CN.json`, `en-US.json`, and `ja-JP.json` structurally identical, and run `scripts/check_i18n.py` after changing text. The README landing pages are translated; detailed technical guides under `docs/en/` are in English.

Never commit user databases, media, subtitles, spreadsheets, model weights, caches, exports, logs, tokens, `.env`, or local configuration. Before publishing, inspect staged files and Git history for secrets and large binaries. Review [security guidance](../../SECURITY.md) and [third-party notices](../../THIRD_PARTY_NOTICES.md) before redistributing a build or models.

The [model backend contracts](model-backends.md) describe custom ASR and diarization integrations. Coding agents should also follow [AGENTS.md](../../AGENTS.md).
