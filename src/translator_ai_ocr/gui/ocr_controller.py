"""Screen OCR mode controller: capture -> OCR -> translate -> display.

Ports the optimized pipeline from interpreter-v2: fast tick, unchanged-frame
skipping, scroll/shift detection with stale-result discarding, batched
translation. Results go to the caption bar (banner) or the inplace overlay.
"""

import time

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from .. import log
from ..capture import WindowCapture
from ..config import OverlayMode
from .workers import ProcessWorker

logger = log.get_logger()

PROCESS_INTERVAL_MS = 150
FORCE_REPROCESS_MS = 2000
CHANGE_DETECT_STRIDE = 8
SCROLL_CHANGE_FRACTION = 0.4
SCROLL_MIN_CHANGE_FRACTION = 0.02


class OcrController(QObject):
    """Drives the Screen OCR pipeline for a selected window."""

    text_ready = Signal(str)  # banner-mode translated text
    regions_ready = Signal(list, object)  # inplace-mode regions + content offset
    status_changed = Signal(str)  # "loading" | "ready" | "capturing" | "error:<msg>" | "window_closed"

    def __init__(self, config, inplace_overlay):
        super().__init__()
        self._config = config
        self._inplace_overlay = inplace_overlay
        self._capture: WindowCapture | None = None
        self._capturing = False

        self._worker = ProcessWorker()
        self._worker.text_ready.connect(self._on_text_ready)
        self._worker.regions_ready.connect(self._on_regions_ready)
        self._worker.models_ready.connect(lambda: self.status_changed.emit("ready"))
        self._worker.models_failed.connect(lambda msg: self.status_changed.emit(f"error:{msg}"))

        self._timer = QTimer()
        self._timer.timeout.connect(self._capture_and_process)

        self._last_frame = None
        self._last_bounds = {}
        self._last_frame_sample = None
        self._last_process_time = 0.0
        self._prev_tick_sample = None

    # ---------- lifecycle ----------

    def load_models(self):
        """Start the worker thread (loads models in background)."""
        self.status_changed.emit("loading")
        self._worker.set_mode(self._config.overlay_mode)
        self._worker.set_direction(self._config.ocr_direction)
        self._worker.start(self._config.ocr_confidence)

    def list_windows(self) -> list[dict]:
        return WindowCapture.list_windows()

    def start_capture(self, title: str, window_id=None, bounds=None) -> bool:
        """Start capturing the given window."""
        self.stop_capture()
        capture = WindowCapture(title, window_id=window_id, bounds=bounds)
        if not capture.find_window():
            self.status_changed.emit("error:Window not found")
            return False
        try:
            if not capture.start_stream():
                self.status_changed.emit("error:Failed to start capture")
                return False
        except Exception as e:
            logger.error("capture failed", error=str(e))
            self.status_changed.emit(f"error:{str(e).splitlines()[0][:80]}")
            return False

        self._capture = capture
        self._capturing = True
        self._config.window_title = title
        self._last_frame_sample = None
        self._prev_tick_sample = None
        self._timer.setInterval(PROCESS_INTERVAL_MS)
        self._timer.start()
        self.status_changed.emit("capturing")
        if self._config.overlay_mode == OverlayMode.INPLACE:
            self._inplace_overlay.show()
        return True

    def stop_capture(self):
        self._timer.stop()
        if self._capture:
            self._capture.stop()
            self._capture = None
        self._capturing = False
        self._inplace_overlay.clear_regions()
        self._inplace_overlay.hide()

    @property
    def capturing(self) -> bool:
        return self._capturing

    def set_overlay_mode(self, mode: OverlayMode):
        self._worker.set_mode(mode)
        if mode == OverlayMode.BANNER:
            self._inplace_overlay.clear_regions()
            self._inplace_overlay.hide()
        elif self._capturing:
            self._inplace_overlay.show()

    def set_direction(self, direction: str):
        self._worker.set_direction(direction)

    def set_confidence(self, value: float):
        self._worker.set_confidence_threshold(value)

    # ---------- pipeline (ported from interpreter-v2) ----------

    def _capture_and_process(self):
        if not self._capture:
            return

        frame = self._capture.get_frame()

        if self._capture.window_invalid:
            logger.info("window closed, stopping capture")
            self.stop_capture()
            self.status_changed.emit("window_closed")
            return

        bounds = self._capture.bounds or {}
        if frame is None:
            return

        self._last_frame = frame
        self._last_bounds = bounds

        if self._config.overlay_mode == OverlayMode.INPLACE and bounds:
            self._inplace_overlay.position_over_window(bounds)

        sample = frame[::CHANGE_DETECT_STRIDE, ::CHANGE_DETECT_STRIDE].copy()

        # Clear stale inplace labels while content is scrolling
        if self._config.overlay_mode == OverlayMode.INPLACE and self._content_moved(self._prev_tick_sample, sample):
            self._inplace_overlay.clear_regions()
        self._prev_tick_sample = sample

        # Skip unchanged frames (with periodic force-reprocess)
        now = time.monotonic()
        unchanged = (
            self._last_frame_sample is not None
            and sample.shape == self._last_frame_sample.shape
            and np.array_equal(sample, self._last_frame_sample)
        )
        if unchanged and (now - self._last_process_time) * 1000 < FORCE_REPROCESS_MS:
            return
        self._last_frame_sample = sample
        self._last_process_time = now

        self._worker.submit_frame(frame, sample)

    def _content_moved(self, old_sample, new_sample) -> bool:
        if old_sample is None or new_sample is None:
            return False
        if old_sample.shape != new_sample.shape:
            return True
        changed = float(np.mean(np.any(old_sample != new_sample, axis=2)))
        if changed >= SCROLL_CHANGE_FRACTION:
            return True
        if changed < SCROLL_MIN_CHANGE_FRACTION:
            return False
        return self._detect_vertical_shift(old_sample, new_sample)

    @staticmethod
    def _detect_vertical_shift(old_sample, new_sample) -> bool:
        old_profile = old_sample.astype(np.float32).mean(axis=(1, 2))
        new_profile = new_sample.astype(np.float32).mean(axis=(1, 2))
        n = len(old_profile)
        max_shift = n // 2
        if max_shift < 2:
            return False
        zero_error = float(np.mean(np.abs(old_profile - new_profile)))
        if zero_error < 1.0:
            return False
        best_error = None
        for shift in range(-max_shift, max_shift + 1):
            if shift == 0:
                continue
            if shift > 0:
                a, b = old_profile[shift:], new_profile[: n - shift]
            else:
                a, b = old_profile[: n + shift], new_profile[-shift:]
            error = float(np.mean(np.abs(a - b)))
            if best_error is None or error < best_error:
                best_error = error
        return best_error is not None and best_error < zero_error * 0.5

    # ---------- results ----------

    def _on_text_ready(self, translated: str):
        if self._config.overlay_mode == OverlayMode.BANNER:
            self.text_ready.emit(translated)

    def _on_regions_ready(self, regions: list, result_sample=None):
        if self._config.overlay_mode != OverlayMode.INPLACE:
            return
        # Discard results whose source frame no longer matches the screen
        if result_sample is not None and self._last_frame is not None:
            current = self._last_frame[::CHANGE_DETECT_STRIDE, ::CHANGE_DETECT_STRIDE]
            if self._content_moved(result_sample, current):
                self._inplace_overlay.clear_regions()
                return
        content_offset = (0, 0)
        if self._capture:
            content_offset = self._capture.get_content_offset()
        self._inplace_overlay.set_vertical_text(self._config.vertical_text)
        self._inplace_overlay.set_regions(regions, content_offset)
