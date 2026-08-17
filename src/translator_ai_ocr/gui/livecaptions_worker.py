"""Background worker: read Live Captions transcript and translate it."""

import threading
import time

from PySide6.QtCore import QObject, Signal

from .. import log
from ..engines import CachedEngine
from ..livecaptions import LiveCaptionsReader, launch_live_captions, split_transcript

logger = log.get_logger()

POLL_INTERVAL = 0.25  # seconds between transcript reads
PARTIAL_TRANSLATE_AFTER = 0.9  # translate an unchanged partial sentence after this long
MIN_PARTIAL_CHARS = {"en": 12, "ja": 6, "zh": 6, "ko": 6}  # don't translate very short partials


class LiveCaptionsWorker(QObject):
    """Polls Live Captions via UI Automation and translates new sentences.

    Signals:
        original_changed: latest original text (partial or complete sentence)
        translation_ready: (original sentence, translated text)
        status_changed: "loading_model" | "connecting" | "needs_setup" |
                        "running" | "stopped" | "error:<msg>"
    """

    original_changed = Signal(str)
    translation_ready = Signal(str, str)
    status_changed = Signal(str)

    def __init__(self, engine: CachedEngine, source_lang: str = "en"):
        super().__init__()
        self._engine = engine
        self._source_lang = source_lang
        self._thread: threading.Thread | None = None
        self._running = False
        self.paused = False  # set from the GUI thread; worker only reads it

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
        logger.debug("live captions worker starting", source=self._source_lang)

        # Prepare the engine (offline engines may download models on first use)
        progress_stop = threading.Event()
        if self._engine.requires_download:
            self.status_changed.emit("loading_model")
            threading.Thread(
                target=self._report_download_progress, args=(progress_stop,), daemon=True
            ).start()
        try:
            self._engine.load()
        except Exception as e:
            logger.error("failed to prepare translation engine", error=str(e))
            self.status_changed.emit(f"error:{e}")
            return
        finally:
            progress_stop.set()

        try:
            import uiautomation as auto

            with auto.UIAutomationInitializerInThread():
                self._poll_loop()
        except Exception as e:
            logger.error("live captions worker crashed", error=repr(e))
            self.status_changed.emit(f"error:{e}")
            return

        self.status_changed.emit("stopped")
        logger.debug("live captions worker stopped")

    def _report_download_progress(self, stop_event: threading.Event):
        """Emit download percentage while the engine loads (first run)."""
        last_done = -1
        last_change = time.monotonic()
        while not stop_event.wait(1.0):
            try:
                progress = self._engine.download_progress()
            except Exception:
                return
            if not progress:
                return
            done, total = progress
            now = time.monotonic()
            if done != last_done:
                last_done = done
                last_change = now
            if now - last_change > 90:
                # No bytes for 90s: likely a network problem
                self.status_changed.emit("download_stalled")
                continue
            pct = min(99, done * 100 // max(1, total))
            self.status_changed.emit(f"downloading:{pct}:{done // 1048576}:{total // 1048576}")

    def _poll_loop(self):
        reader = LiveCaptionsReader()
        launched = False
        connected = False
        error_streak = 0

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

            if self.paused:
                time.sleep(POLL_INTERVAL)
                continue

            transcript = reader.read()
            if transcript is None:
                connected = False
                continue

            complete, partial = split_transcript(transcript, lang=self._source_lang)
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
                and len(partial) >= MIN_PARTIAL_CHARS.get(self._source_lang, 12)
                and partial != last_translated_source
                and (now - last_partial_time) >= PARTIAL_TRANSLATE_AFTER
            ):
                source = partial

            if source:
                try:
                    translated, _cached = self._engine.translate(source)
                    error_streak = 0
                    if translated:
                        last_translated_source = source
                        self.translation_ready.emit(source, translated)
                except Exception as e:
                    error_streak += 1
                    logger.warning("translation error", error=str(e))
                    if error_streak >= 3:
                        self.status_changed.emit(f"error:{str(e)[:120]}")
                        error_streak = 0

            time.sleep(POLL_INTERVAL)
