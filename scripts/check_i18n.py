from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "src" / "audio_registry" / "locales"


def flatten(value: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for name, child in value.items():
        key = f"{prefix}.{name}" if prefix else name
        if isinstance(child, dict):
            keys.update(flatten(child, key))
        elif isinstance(child, str):
            keys.add(key)
        else:
            raise TypeError(f"Locale value must be a string: {key}")
    return keys


manifest = json.loads((LOCALES / "manifest.json").read_text(encoding="utf-8"))
catalogs = {
    path.stem: flatten(json.loads(path.read_text(encoding="utf-8")))
    for path in sorted(LOCALES.glob("*.json")) if path.name != "manifest.json"
}
if set(catalogs) != set(manifest["locales"]) or manifest["fallback"] not in catalogs:
    raise SystemExit(f"Unexpected locale set: {sorted(catalogs)}")
reference = catalogs["en-US"]
for language, keys in catalogs.items():
    if keys != reference:
        raise SystemExit(
            f"Locale key mismatch for {language}: missing={sorted(reference - keys)}, extra={sorted(keys - reference)}"
        )

used: set[str] = set()
for path in (ROOT / "src" / "audio_registry").rglob("*"):
    if path.suffix not in {".py", ".js", ".html"} or "locales" in path.parts:
        continue
    text = path.read_text(encoding="utf-8")
    used.update(re.findall(r"\bt\([\"']([a-z0-9_.-]+)[\"']", text))
    used.update(re.findall(r"data-i18n(?:-[a-z-]+)?=[\"']([a-z0-9_.-]+)[\"']", text))
missing = used - reference
if missing:
    raise SystemExit(f"Missing i18n keys: {sorted(missing)}")
print(f"i18n OK: {len(catalogs)} locales, {len(reference)} keys, {len(used)} referenced keys")
