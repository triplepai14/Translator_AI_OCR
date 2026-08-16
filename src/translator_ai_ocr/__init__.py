"""Translator AI OCR - screen & Live Captions translator.

Two modes:
- Live Captions: reads the Windows 11 Live Captions bar directly via
  UI Automation (no OCR) and translates it offline.
- Screen OCR: captures a window, OCRs the text (MeikiOCR / RapidOCR),
  translates offline (Sugoi V4 / NLLB-200) and shows an overlay.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("translator-ai-ocr")
except PackageNotFoundError:  # running from source without install
    __version__ = "0.0.0-dev"


def main():
    """Entry point for the application."""
    from .gui.app import run

    return run()


__all__ = ["__version__", "main"]
