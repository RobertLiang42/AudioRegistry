# Installation and environment setup

[English README](README.md) · [User guide](user-guide.md)

AudioRegistry currently targets Windows 10/11 and PowerShell 5.1 or newer. Run the commands below from the repository root. The built-in processing pipeline needs Python 3.12, FFmpeg 7.1, both ML backends, and the ASR and speaker model weights. The default configuration uses an NVIDIA GPU; CPU setup is supported separately.

The commands launch `.ps1` files with `-ExecutionPolicy Bypass`, so they also work when direct script execution is blocked in the current PowerShell session.

## NVIDIA GPU: managed environment

Accept the terms for the gated `pyannote/speaker-diarization-community-1` model on Hugging Face before signing in. Keep tokens outside tracked files.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
& .\.venv\Scripts\hf.exe auth login
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\download-models.ps1 -Target all
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 start
```

`setup.ps1` creates `.venv` and installs the pinned core and ML dependencies. If Python 3.12 is unavailable, it downloads a signed, SHA-256-verified Python 3.12.10 runtime into `.runtime/python`. It also downloads a pinned, SHA-256-verified FFmpeg 7.1 shared build into `.runtime/ffmpeg` when needed. NVIDIA CUDA support must be available separately.

The model download command fetches both pinned models into the ignored `models/` directory. Python packages alone do not include model weights.

## CPU: managed environment

The CPU option installs the full ML stack with CPU builds of PyTorch, torchaudio, and TorchCodec. It merges `device: cpu` and `asr.compute_type: int8` into the ignored `config/default.local.yaml`, preserving unrelated local settings.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Cpu
& .\.venv\Scripts\hf.exe auth login
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\download-models.ps1 -Target all
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 start
```

Accept the pyannote model terms before logging in. CPU diarization and transcription may be substantially slower than GPU processing; both model downloads are still required.

## Bring your own Python and FFmpeg

`setup.ps1 -Python <path>` uses an existing Python 3.12 interpreter to create a new `.venv` **inside** the repository. If you want the packages outside the repository, install them into your own environment instead. We recommend installing both Python 3.12 and FFmpeg 7.1 in one Conda environment; another environment manager works too.

In an Anaconda PowerShell Prompt, run the following from the repository root:

```powershell
conda create -n audio-registry -c conda-forge python=3.12 'ffmpeg>=7.1,<8' -y
conda activate audio-registry
```

If you already have a suitable Conda environment, activate it and run `conda install -c conda-forge 'ffmpeg>=7.1,<8' -y` instead of creating a new one. In a regular PowerShell session, run `conda init powershell` and reopen the shell before activating Conda. With another environment manager, activate its Python 3.12 environment and provide FFmpeg separately. The launchers use the active environment automatically, even if this repository also contains `.venv`.

For the default NVIDIA setup, continue with:

```powershell
python -m pip install -r .\requirements.txt
python -c 'from huggingface_hub import login; login()'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\download-models.ps1 -Target all
.\start.bat
```

For an external CPU environment, replace the `requirements.txt` line with the following commands. The last command saves the CPU overrides automatically:

```powershell
python -m pip install -r .\requirements-core.txt
python -m pip install torch==2.8.0 torchaudio==2.8.0 torchcodec==0.7.0 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r .\requirements-ml.txt
python .\scripts\configure-cpu.py
```

Accept the pyannote terms before authenticating. Python's `login()` uses the same Hugging Face authentication as `hf auth login`; alternatively, set `HF_TOKEN` in the process environment. FFmpeg installed in the active Conda environment is selected automatically. With another environment manager, install FFmpeg separately and make it available on PATH, or set `AUDIOREGISTRY_FFMPEG` to its absolute executable path. To launch on later occasions, activate the same environment and run `.\start.bat` from the repository root. A `.bat` file is a Windows batch script, so do not prefix it with `python`.

`requirements.txt` includes `requirements-core.txt` and `requirements-ml.txt`; install it once for the default NVIDIA environment. `requirements-dev.txt` adds development tools and is not needed for normal use. `run.ps1` starts `main.py` directly, so an editable install of AudioRegistry is not required in an external environment.

If you prefer launching without activating the environment, copy `.env.example` to the ignored `.env` and set `AUDIOREGISTRY_PYTHON` to its absolute executable path; `run.ps1` reads that file. The model download script also accepts `-Python <path>` when no environment is active. You can keep `AUDIOREGISTRY_FFMPEG` in `.env` for later sessions. In `run.ps1`, the interpreter priority is an explicit `AUDIOREGISTRY_PYTHON`, then an active Conda or virtual environment, then the repository's `.venv`, then Python on PATH. Process environment variables take priority over `.env`.

## Starting after installation

From the repository root, run one of these commands in PowerShell, or double-click the corresponding batch file in Explorer:

```powershell
.\start.bat
.\webui.bat
```

Run one command at a time. `start.bat` opens the project center, offers an optional segmentation and transcription step, then opens both WebUIs. `webui.bat` directly opens WebUI1 for reviewing a single project and WebUI2 for assembling and exporting across projects; it does not open the project center or run segmentation and transcription. Keep the console window open while using either WebUI. If you installed dependencies in your own Conda or virtual environment, activate that environment before running a batch file from PowerShell; for Explorer double-clicks without activation, set `AUDIOREGISTRY_PYTHON` in the local `.env`.

For every `run.ps1` command, its arguments, and the data passed between `start` steps, see the [user guide](user-guide.md#commands-and-options).

## Configuration and local files

Portable defaults live in `config/default.yaml`. Copy only the values you want to override into the ignored `config/default.local.yaml`; `config.example.yaml` lists the supported fields. Store credentials in the environment or the Hugging Face credential store, never in YAML.

| Directory | Contents | In Git |
| --- | --- | --- |
| `src/` | Application source | Yes |
| `config/` | Public defaults and ignored local overrides | Defaults only |
| `models/` | Downloaded model weights | No |
| `data/` | SQLite registry and runtime project data | No |
| `.cache/` | Temporary caches | No |
| `.runtime/` | Setup-managed Python and FFmpeg | No |
| `output/` | Exports and tool backups | No |

The default registry is `data/audio-registry.sqlite3`. Audio files stay at their existing paths rather than being copied into the repository. The supplied model download script uses `models/`; if you override `paths.model_dir`, provision the models at that location yourself.

Once installed, continue with the [user guide](user-guide.md). See [third-party notices](../../THIRD_PARTY_NOTICES.md) for the model terms and binary licenses.
