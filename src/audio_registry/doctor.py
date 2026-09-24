from __future__ import annotations

import importlib
import importlib.metadata
import subprocess
import sys
from dataclasses import dataclass

from .config import AppConfig
from .i18n import t


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str


def _package_check(distribution: str, module: str) -> Check:
    try:
        importlib.import_module(module)
        version = importlib.metadata.version(distribution)
    except Exception as error:  # report the concrete native/import error
        return Check(distribution, False, f"{type(error).__name__}: {error}")
    return Check(distribution, True, version)


def run_checks(config: AppConfig) -> list[Check]:
    try:
        torch = importlib.import_module("torch")
    except Exception:
        torch = None
    checks = [
        Check("python", sys.version_info >= (3, 12), sys.version.split()[0]),
        _package_check("torch", "torch"),
        _package_check("torchaudio", "torchaudio"),
        _package_check("torchcodec", "torchcodec"),
        _package_check("pyannote.audio", "pyannote.audio"),
        _package_check("faster-whisper", "faster_whisper"),
        _package_check("ctranslate2", "ctranslate2"),
        Check(
            "cuda",
            bool(torch and torch.cuda.is_available()),
            (torch.version.cuda if torch else None) or t("doctor.unavailable"),
        ),
    ]
    if torch and torch.cuda.is_available():
        checks.append(Check("gpu", True, torch.cuda.get_device_name(0)))

    ffmpeg = config.paths.ffmpeg
    if not ffmpeg.is_file():
        checks.append(Check(t("doctor.ffmpeg"), False, t("doctor.not_found", path=ffmpeg)))
    else:
        result = subprocess.run(
            [str(ffmpeg), "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else result.stderr.strip()
        checks.append(Check("cutting ffmpeg", result.returncode == 0, first_line))
    return checks


def print_checks(checks: list[Check]) -> bool:
    for check in checks:
        marker = t("doctor.ok") if check.ok else t("doctor.fail")
        print(f"[{marker:<4}] {check.name}: {check.detail}")
    return all(check.ok for check in checks)
