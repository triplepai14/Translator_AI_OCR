"""Read Windows 11 Live Captions text directly via UI Automation.

No OCR involved: the Live Captions window exposes its transcript as a
UI Automation text element (AutomationId "CaptionsTextBlock"), so the
text is read programmatically with 100% fidelity.
"""

import re
import subprocess
import sys

from . import log

logger = log.get_logger()

WINDOW_CLASS = "LiveCaptionsDesktopWindow"
CAPTIONS_TEXT_ID = "CaptionsTextBlock"
SETUP_TEXT_ID = "SetupToContinueText"
READY_TEXT_ID = "ReadyToCaptionTextBlock"

# Sentence terminators for splitting the rolling transcript
_SENTENCE_END = re.compile(r"[.!?…]+[\s\"')\]]*\s")


def is_supported() -> bool:
    """Live Captions reading is only available on Windows 11."""
    return sys.platform == "win32"


def launch_live_captions() -> bool:
    """Start LiveCaptions.exe if it is not already running.

    Returns:
        True if launched or already running, False if unavailable.
    """
    if not is_supported():
        return False
    try:
        subprocess.Popen(
            ["LiveCaptions.exe"],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return True
    except OSError as e:
        logger.error("failed to launch Live Captions", error=str(e))
        return False


class LiveCaptionsReader:
    """Polls the Live Captions transcript via UI Automation.

    All methods must be called from the same (non-main) thread, inside a
    UIAutomationInitializerInThread context (see LiveCaptionsWorker).
    """

    # Connection states
    OK = "ok"
    NOT_RUNNING = "not_running"
    NEEDS_SETUP = "needs_setup"

    def __init__(self):
        self._auto = None
        self._win = None
        self._text_ctrl = None

    def _ensure_auto(self):
        if self._auto is None:
            import uiautomation

            self._auto = uiautomation

    def connect(self) -> str:
        """Locate the Live Captions window and transcript element.

        Returns:
            One of OK, NOT_RUNNING, NEEDS_SETUP.
        """
        self._ensure_auto()
        auto = self._auto

        win = auto.WindowControl(searchDepth=1, ClassName=WINDOW_CLASS)
        if not win.Exists(1, 0.2):
            self._win = None
            self._text_ctrl = None
            return self.NOT_RUNNING
        self._win = win

        text_ctrl = win.TextControl(AutomationId=CAPTIONS_TEXT_ID)
        if text_ctrl.Exists(1, 0.2):
            self._text_ctrl = text_ctrl
            return self.OK

        # "Ready to caption" state: set up and waiting for audio - the
        # transcript element appears once captioning starts.
        ready = win.TextControl(AutomationId=READY_TEXT_ID)
        if ready.Exists(1, 0.2):
            self._text_ctrl = None
            return self.OK

        # Window exists but no transcript element: first-run consent screen
        setup = win.TextControl(AutomationId=SETUP_TEXT_ID)
        if setup.Exists(1, 0.2):
            return self.NEEDS_SETUP
        # Neither transcript nor setup: window may still be initializing
        return self.NEEDS_SETUP

    def read(self) -> str | None:
        """Read the current transcript text.

        Returns:
            Transcript string ("" while waiting for audio), or None if the
            window is gone (reconnect needed).
        """
        if self._text_ctrl is None:
            # Transcript element may appear after audio starts
            if self._win is None:
                return None
            try:
                if not self._win.Exists(0, 0):
                    self._win = None
                    return None
                cand = self._win.TextControl(AutomationId=CAPTIONS_TEXT_ID)
                if cand.Exists(0, 0):
                    self._text_ctrl = cand
                else:
                    return ""
            except Exception:
                self._win = None
                return None
        try:
            return self._text_ctrl.Name or ""
        except Exception:
            # Element went stale (window closed/recreated)
            self._text_ctrl = None
            return ""


def split_transcript(transcript: str) -> tuple[str, str]:
    """Split a rolling transcript into (last complete sentence, current partial).

    Args:
        transcript: Raw transcript text from Live Captions.

    Returns:
        Tuple of (last_complete_sentence, current_partial_sentence).
        Either may be empty.
    """
    text = " ".join(transcript.split())
    if not text:
        return "", ""

    ends = list(_SENTENCE_END.finditer(text + " "))
    if not ends:
        return "", text

    last_end = ends[-1].end()
    if last_end >= len(text) + 1:
        # Transcript currently ends exactly at a sentence boundary
        start = ends[-2].end() if len(ends) >= 2 else 0
        return text[start:last_end].strip(), ""

    start = ends[-1].end()
    prev_start = ends[-2].end() if len(ends) >= 2 else 0
    return text[prev_start : ends[-1].end()].strip(), text[start:].strip()
