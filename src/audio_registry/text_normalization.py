from functools import lru_cache


@lru_cache(maxsize=1)
def _converter():
    from opencc import OpenCC

    return OpenCC("t2s")


def simplify_chinese(text: str, language: str | None) -> str:
    """Only Chinese is normalized; Japanese kanji and other languages stay intact."""
    return _converter().convert(text) if language == "zh" else text
