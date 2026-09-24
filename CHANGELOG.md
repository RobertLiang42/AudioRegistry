# Changelog

All notable changes to AudioRegistry are documented here. Versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-24

### Initial release

- Create and manage audio projects in a local SQLite registry, including single
  and batch creation, a pending queue, and projects without segments.
- Run the guided `start` workflow from project management through optional
  segmentation and transcription to both WebUIs. Open each step separately with
  `project`, `process`, or `webui`.
- Review and edit project timelines, speakers, tags, text, and notes in WebUI1,
  with explicit saving and refresh conflict detection.
- Assemble datasets from multiple projects in WebUI2, with filtering, audio
  variants, clip processing, and list and spreadsheet export.
- Use subtitle-assisted alignment, pluggable ASR and diarization backends, and
  Chinese, English, and Japanese interfaces.
- Keep source media at its original path and store local databases, models,
  caches, and generated output outside Git.
