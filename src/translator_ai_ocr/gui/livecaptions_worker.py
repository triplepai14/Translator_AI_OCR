"""Background worker: read Live Captions transcript and translate it."""

import threading
import time

from PySide6.QtCore import QObject, Signal

from .. import log
from ..livecaptions import LiveCaptionsReader, launch_live_captions, split_transcript
from ..translate import Translator

logger = log.get_logger()

POLL_INTERVAL = 0.25  # seconds between transcript reads
PARTIAL_TRANSLATE_AFTER = 0.9  # translate an unchanged partial sentence after this long
MIN_PARTIAL_CHARS = 12  # don't translate very short partials


class LiveCaptionsWorker(QObject):
    """Polls Live Captions via UI Automation and translates new sentences.

    Signals:
        original_changed: latest original text (partial or complete sentence)
        translation_ready: translated text for the latest sentence
        status_changed: "loading_model" | "connecting" | "needs_setup" |
                        "running" | "stopped" | "error:<msg>"
    """

    original_changed = Signal(str)
    translation_ready = Signal(str)
    status_changed = Signal(str)

    def __init__(self, target_lang: str = "ja"):
        super().__init__()
        self._target_lang = target_lang
        self._thread: threading.Thread | None = None
        self._running = False
        self._translator: Translator | None = None

    def start(self):
        if self._thread is not None:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread = None

    def _run(self):
        logger.debug("live captions worker starting", target=self._target_lang)

        # Load the translation model first (downloads on first use)
        self.status_changed.emit("loading_model")
        try:
            self._translator = Translator(direction=f"en-{self._target_lang}")
            self._translator.load()
        except Exception as e:
            logger.error("failed to load translation model", error=str(e))
            self.status_changed.emit(f"error:{e}")
            return

        import uiautomation as auto

        with auto.UIAutomationInitializerInThread():
            self._poll_loop()

        self.status_changed.emit("stopped")
        logger.debug("live captions worker stopped")

    def _poll_loop(self):
        reader = LiveCaptionsReader()
        launched = False
        connected = False

        last_partial = ""
        last_partial_time = 0.0
        last_translated_source = ""
        last_shown_original = ""

        while self._running:
            if not connected:
                self.status_changed.emit("connecting")
                state = reader.connect()
                if state == LiveCaptionsReader.NOT_RUNNING:
                    if not launched:
                        launch_live_captions()
                        launched = True
                    time.sleep(1.5)
                    continue
                if state == LiveCaptionsReader.NEEDS_SETUP:
                    self.status_changed.emit("needs_setup")
                    time.sleep(2.0)
                    continue
                connected = True
                self.status_changed.emit("running")

            transcript = reader.read()
            if transcript is None:
                connected = False
                continue

            complete, partial = split_transcript(transcript)
            now = time.monotonic()

            # Show the freshest original text
            display = partial or complete
            if display and display != last_shown_original:
                last_shown_original = display
                self.original_changed.emit(display)

            # Track partial stability
            if partial != last_partial:
                last_partial = partial
                last_partial_time = now

            # Decide what to translate:
            # 1) a newly completed sentence -> translate immediately
            # 2) a partial that has been stable for a while -> translate it
            source = None
            if complete and complete != last_translated_source and not partial:
                source = complete
            elif (
                partial
                and len(partial) >= MIN_PARTIAL_CHARS
                and partial != last_translated_source
                and (now - last_partial_time) >= PARTIAL_TRANSLATE_AFTER
            ):
                source = partial

            if source:
                try:
                    translated, _cached = self._translator.translate(source)
                    if translated:
                        last_translated_source = source
                        self.translation_ready.emit(translated)
                except Exception as e:
                    logger.warning("translation error", error=str(e))

            time.sleep(POLL_INTERVAL)
