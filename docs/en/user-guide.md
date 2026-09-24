# User guide

[English README](README.md) · [简体中文](../cn/user-guide.md) · [日本語](../jp/user-guide.md) · [Installation](installation.md)

Use `start.bat` for the guided project and processing workflow, or `webui.bat` to open both WebUIs directly. The commands below are for users who want to invoke individual steps or control their options. Run them from the repository root in PowerShell. Both batch launchers call `run.ps1` with the corresponding command.

## Commands and options

| Command | What it does |
| --- | --- |
| `start` | Open the project center, optionally segment and transcribe selected projects, then open both WebUIs. |
| `project` | Open only the project center for creation and database management. |
| `process` | Segment and transcribe audio already bound to existing projects; create no projects and open no WebUI. |
| `webui` | Open both WebUIs without first selecting or processing a project. |
| `webui1` | Open only the single-project timeline review UI. |
| `webui2` | Open only the multi-project assembly UI. |
| `language [zh-CN\|en-US\|ja-JP]` | Show the current UI locale, or save a chosen UI locale. |
| `doctor` | Report environment checks. |

For example:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 start
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 project
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 process
```

`run.ps1` resolves its own project directory, so a full path can be used from another working directory. Use `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --help` for the built-in help, or place a command before `--help` to see its options, for example `start --help`.

Put the global `--config PATH` option before the command to use a different main YAML file. The default is `config/default.yaml`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 --config .\config\default.yaml doctor
```

| Applies to | Argument | Effect |
| --- | --- | --- |
| `start`, `process` | `AUDIO` | Process one audio file directly instead of opening the processing dialog. |
| `start`, `process` | `--project NAME` | With `AUDIO`, specify the project. Without `AUDIO`, fill the project field in `start` or prefer this project in `process`. |
| `start`, `process` | `--subtitle PATH` | Provide an optional subtitle file. In the dialog, subtitles require exactly one selected project. |
| `start`, `process` | `--start-padding SECONDS`, `--end-padding SECONDS` | Set nonnegative segment padding values for this invocation; otherwise use configured defaults. |
| `start`, `process`, `webui1`, `webui` | `--language CODE` | Set the ASR language for this invocation, such as `auto`, `zh`, `en`, or `ja`. This differs from the saved UI locale set by `language`. |
| `webui1`, `webui` | `AUDIO`, `--project NAME` | Open a bound audio file or project in WebUI1. If only `AUDIO` is given, infer its project from the database. |
| `webui1`, `webui2` | `--port NUMBER` | Override the listening port; defaults are 8765 and 8766 respectively. |
| `webui` | `--webui1-port NUMBER`, `--webui2-port NUMBER` | Override the two listening ports, which must differ; defaults are 8765 and 8766. |
| `webui1`, `webui2`, `webui` | `--no-open` | Start the local server without opening browser tabs automatically. |

For example:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 process --project "Example Project"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 webui1 --project "Example Project"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 webui --webui1-port 8875 --webui2-port 8876 --no-open
```

## Projects and processing

The project center combines single and batch creation, a pending queue, and database management. Creating a project commits its name and audio binding immediately, even when it has no segments, and refreshes the database list. WebUI1 can open the same center from its project menu.

In `start`, choose **Next** to open the segmentation and transcription step. Newly created projects are checked in the database list by default. The currently checked projects, including any existing projects you select, are passed to the next dialog as its initial selection. Uncheck a project to leave it out of that initial selection. You can change the processing selection, leave all projects unchecked, or choose **Skip** to open the WebUIs without processing. Only projects with a usable bound audio file can be processed.

`start` passes the last processed project to WebUI1 when processing occurred. If nothing was processed, WebUI1 receives the last project checked in the project center; with none checked, it opens without an initial project. WebUI2 receives all checked project names plus any processed project names. Closing either dialog instead of using **Next** or **Skip** cancels `start`.

With `start AUDIO [--project NAME]`, the command skips both dialogs: it creates and binds a project if needed, processes the audio, then opens both WebUIs. If the project exists, the audio must already be bound to it. Without `--project`, a newly created project uses the audio filename stem as its name.

`process` is for existing projects and bound audio only. It does not create projects or open the WebUIs. Without `AUDIO`, it opens the processing dialog; with `AUDIO`, the audio must already be bound to an existing project, which can be inferred from the binding or specified with `--project`. Processing needs both downloaded models; see [installation](installation.md).

## Review and assembly

WebUI1 is the single-project timeline editor. Review coordinates, speakers, transcript text, tags, and notes; preview audio, retranscribe, and export subtitles or clips. Edits to existing project data stay in the page until you click **Save**. Refresh detection uses project update counters.

WebUI2 assembles data from multiple projects. It supports audio variants and offsets, filters, clip processing, list export, and spreadsheet export. Generated output goes under the ignored `output/` directory by default; the list export is written to `output/asr_opt/slicer_opt.list`.

The source audio remains at its original path. The local registry defaults to `data/audio-registry.sqlite3`; do not remove it when updating or cleaning the source checkout.

## Language and settings

With no saved choice, the interface uses the browser or system language when supported, then falls back to English. Save a UI language choice with:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 language zh-CN
```

Use `en-US` or `ja-JP` in place of `zh-CN` for English or Japanese. Application defaults are in `config/default.yaml`; machine-specific overrides belong in the ignored `config/default.local.yaml`. See [installation](installation.md) for Python, FFmpeg, and model setup.
