from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from audio_registry.i18n import detect_locale, normalize_locale


class I18nTests(unittest.TestCase):
    def test_normalize_locale_accepts_common_codes(self) -> None:
        self.assertEqual(normalize_locale("zh_CN"), "zh-CN")
        self.assertEqual(normalize_locale("ja"), "ja-JP")

    def test_saved_language_precedes_environment_and_system(self) -> None:
        with (
            patch.dict(os.environ, {"AUDIOREGISTRY_LANGUAGE": "ja-JP"}, clear=False),
            patch("audio_registry.i18n._system_locale_candidates", return_value=("zh-CN",)),
        ):
            self.assertEqual(detect_locale("en-US"), "en-US")

    def test_windows_system_locale_is_selected_before_lang(self) -> None:
        with (
            patch.dict(os.environ, {"LANG": "C.UTF-8"}, clear=True),
            patch("audio_registry.i18n._system_locale_candidates", return_value=("zh-CN", "C.UTF-8")),
        ):
            self.assertEqual(detect_locale(), "zh-CN")


if __name__ == "__main__":
    unittest.main()
