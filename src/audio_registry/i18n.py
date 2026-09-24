from __future__ import annotations

import json
import locale
import os
from pathlib import Path
from threading import RLock
from typing import Any

LOCALE_DIR = Path(__file__).with_name("locales")
_manifest = json.loads((LOCALE_DIR / "manifest.json").read_text(encoding="utf-8"))
SUPPORTED_LOCALES = tuple(str(value) for value in _manifest["locales"])
FALLBACK_LOCALE = str(_manifest["fallback"])
_lock = RLock()
_locale: str | None = None
_catalogs: dict[str, dict[str, Any]] = {}


def normalize_locale(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().replace("_", "-").lower()
    exact = next((item for item in SUPPORTED_LOCALES if item.lower() == normalized), None)
    if exact:
        return exact
    language = normalized.split("-", 1)[0]
    return next(
        (item for item in SUPPORTED_LOCALES if item.lower().split("-", 1)[0] == language),
        None,
    )


def _system_locale_candidates() -> tuple[str | None, ...]:
    windows_locale = None
    if os.name == "nt":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                windows_locale = buffer.value
        except (AttributeError, OSError):
            pass
    return windows_locale, locale.getlocale()[0], os.environ.get("LANG")


def detect_locale(saved: str | None = None) -> str:
    for candidate in (
        saved,
        os.environ.get("AUDIOREGISTRY_LANGUAGE"),
        *_system_locale_candidates(),
    ):
        supported = normalize_locale(candidate)
        if supported:
            return supported
    return FALLBACK_LOCALE


def set_locale(value: str | None = None) -> str:
    global _locale
    with _lock:
        _locale = detect_locale(value)
        _load_catalog(_locale)
        if _locale != FALLBACK_LOCALE:
            _load_catalog(FALLBACK_LOCALE)
        return _locale


def get_locale() -> str:
    return _locale or set_locale()


def _load_catalog(language: str) -> dict[str, Any]:
    if language not in SUPPORTED_LOCALES:
        language = FALLBACK_LOCALE
    if language not in _catalogs:
        path = LOCALE_DIR / f"{language}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"Locale file must contain a JSON object: {path}")
        _catalogs[language] = value
    return _catalogs[language]


def _lookup(catalog: dict[str, Any], key: str) -> str | None:
    value: Any = catalog
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value if isinstance(value, str) else None


def t(message_key: str, **values: object) -> str:
    language = get_locale()
    template = _lookup(_load_catalog(language), message_key)
    if template is None:
        template = _lookup(_load_catalog(FALLBACK_LOCALE), message_key)
    if template is None:
        return message_key
    return template.format_map({name: str(value) for name, value in values.items()})
