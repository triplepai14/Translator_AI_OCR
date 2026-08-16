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

# Sentence terminators for splitting the rolling transcript.
# Latin: needs trailing whitespace so "3.5" doesn't split.
# CJK: 。！？ end a sentence with no space after.
_SENTENCE_END_LATIN = re.compile(r"[.!?…]+[\s\"')\]]*\s")
_SENTENCE_END_CJK = re.compile(r"[。！？…]+|[.!?]+\s")


def is_supported() -> bool:
    """Live Captions reading is only available on Windows 11."""
    return sys.platform == "win32"


def set_live_captions_visible(visible: bool) -> bool:
    """Move the Live Captions window on/off screen.

    Off-screen it keeps transcribing but stays out of the user's way
    (the same trick LiveCaptions-Translator uses).

    Returns:
        True if the window was found and moved.
    """
    if not is_supported():
        return False
    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(WINDOW_CLASS, None)
    if not hwnd:
        return False
    SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x4, 0x10
    flags = SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
    if visible:
        user32.SetWindowPos(hwnd, 0, 60, 60, 0, 0, flags)
    else:
        user32.SetWindowPos(hwnd, 0, -32000, -32000, 0, 0, flags)
    return True


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
        self._hwnd = 0
        self._text_ctrl = None

    def _ensure_auto(self):
        if self._auto is None:
            import uiautomation

            self._auto = uiautomation

    def connect(self) -> str:
        """Locate the Live Captions window and transcript element.

        Uses Win32 FindWindow to locate the window (reliable in frozen
        builds where UIA root enumeration can miss windows), then attaches
        a UIA control from the native handle.

        Returns:
            One of OK, NOT_RUNNING, NEEDS_SETUP.
        """
        self._ensure_auto()
        auto = self._auto

        import ctypes

        hwnd = ctypes.windll.user32.FindWindowW(WINDOW_CLASS, None)
        if not hwnd:
            self._win = None
            self._text_ctrl = None
            return self.NOT_RUNNING
        try:
            win = auto.ControlFromHandle(hwnd)
        except Exception:
            self._win = None
            self._text_ctrl = None
            return self.NOT_RUNNING
        if win is None:
            self._win = None
            self._text_ctrl = None
            return self.NOT_RUNNING
        self._win = win
        self._hwnd = hwnd

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
            import ctypes

            if not ctypes.windll.user32.IsWindow(self._hwnd):
                self._win = None
                return None
            try:
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


def split_transcript(transcript: str, lang: str = "en") -> tuple[str, str]:
    """Split a rolling transcript into (last complete sentence, current partial).

    Args:
        transcript: Raw transcript text from Live Captions.
        lang: Caption language code ("en", "ja", ...) - selects sentence rules.

    Returns:
        Tuple of (last_complete_sentence, current_partial_sentence).
        Either may be empty.
    """
    text = " ".join(transcript.split())
    if not text:
        return "", ""

    pattern = _SENTENCE_END_CJK if lang in ("ja", "zh") else _SENTENCE_END_LATIN
    ends = [min(m.end(), len(text)) for m in pattern.finditer(text + " ")]
    if not ends:
        return "", text

    if ends[-1] >= len(text):
        # Transcript currently ends exactly at a sentence boundary
        start = ends[-2] if len(ends) >= 2 else 0
        return text[start:].strip(), ""

    start = ends[-1]
    prev_start = ends[-2] if len(ends) >= 2 else 0
    return text[prev_start:start].strip(), text[start:].strip()
