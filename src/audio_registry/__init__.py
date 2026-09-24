"""AudioRegistry core package."""

__version__ = "0.1.0"

from .runtime import configure_windows_dll_search

configure_windows_dll_search()

from .models import Segment  # noqa: E402

__all__ = ["Segment", "__version__"]
