"""Application entry: caption bar + system tray + mode controllers."""

import signal
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import __version__, log
from ..config import AppMode, Config, OverlayMode
from ..engines import create_engine
from ..livecaptions import set_live_captions_visible
from ..overlay import InplaceOverlay
from .caption_window import CaptionWindow
from .history_dialog import HistoryDialog, TranslationHistory
from .livecaptions_worker import LiveCaptionsWorker
from .ocr_controller import OcrController
from .settings_dialog import SettingsDialog

logger = log.get_logger()


def _icon_path() -> str | None:
    """Locate the app icon (PyInstaller bundle or package resources)."""
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "icon.png" if getattr(sys, "_MEIPASS", None) else None,
        Path(__file__).resolve().parents[1] / "resources" / "icon.png",
    ]
    for c in candidates:
        if c and c.exists():
            return str(c)
    return None


class TranslatorApp:
    """Owns the caption window, tray icon, and the two mode pipelines."""

    def __init__(self, app: QApplication, config: Config):
        self._app = app
        self._config = config

        icon = QIcon(_icon_path()) if _icon_path() else QIcon()
        app.setWindowIcon(icon)

        # Caption bar
        self._caption = CaptionWindow(config)
        self._caption.hide_requested.connect(self._hide_to_tray)
        self._caption.settings_requested.connect(self._show_settings)
        self._caption.pause_toggled.connect(self._on_pause_toggled)
        self._caption.copy_requested.connect(self._copy_latest)
        self._caption.history_requested.connect(self._show_history)

        # Translation history + recent-sentences display buffer
        self._history = TranslationHistory()
        self._history_dialog: HistoryDialog | None = None
        self._recent_translations: deque[str] = deque(maxlen=config.overlay_sentences)
        self._paused = False
        self._lc_running_key: tuple | None = None

        # Inplace overlay (Screen OCR mode)
        self._inplace_overlay = InplaceOverlay(
            font_family=config.font_family,
            font_size=config.font_size,
            font_color=config.font_color,
            background_color=config.background_color,
            background_opacity=config.background_opacity,
        )

        # Mode pipelines
        self._lc_worker: LiveCaptionsWorker | None = None
        self._ocr = OcrController(config, self._inplace_overlay)
        self._ocr.text_ready.connect(self._caption.set_translation)
        self._ocr.status_changed.connect(self._on_ocr_status)

        # Settings dialog (created lazily)
        self._settings: SettingsDialog | None = None

        # Tray
        self._tray = QSystemTrayIcon(icon)
        self._tray.setToolTip(f"Translator AI OCR v{__version__}")
        menu = QMenu()
        show_action = QAction("Show / Hide", menu)
        show_action.triggered.connect(self._toggle_visible)
        self._pause_action = QAction("Pause translation", menu)
        self._pause_action.setCheckable(True)
        self._pause_action.toggled.connect(self._caption.set_paused)
        self._show_lc_action = QAction("Show Live Captions window", menu)
        self._show_lc_action.setCheckable(True)
        self._show_lc_action.setChecked(config.show_live_captions)
        self._show_lc_action.toggled.connect(self._on_show_lc_toggled)
        history_action = QAction("Translation history...", menu)
        history_action.triggered.connect(self._show_history)
        settings_action = QAction("Settings...", menu)
        settings_action.triggered.connect(self._show_settings)
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self._quit)
        menu.addAction(show_action)
        menu.addAction(self._pause_action)
        menu.addAction(self._show_lc_action)
        menu.addAction(history_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

        self._caption.show()
        self._start_mode(config.app_mode)

    # ---------- mode management ----------

    def _start_mode(self, mode: AppMode):
        self._stop_pipelines()
        self._config.app_mode = mode
        if mode == AppMode.LIVE_CAPTIONS:
            self._caption.set_translation("")
            self._caption.set_status("Starting Live Captions mode...")
            self._recent_translations = deque(
                self._recent_translations, maxlen=self._config.overlay_sentences
            )
            try:
                engine = create_engine(self._config)
            except Exception as e:
                self._caption.set_status(f"Engine error: {str(e)[:100]}")
                return
            self._lc_running_key = (
                self._config.translation_engine,
                self._config.lc_source,
                self._config.lc_target,
            )
            self._lc_worker = LiveCaptionsWorker(engine, source_lang=self._config.lc_source)
            self._lc_worker.paused = self._paused
            self._lc_worker.original_changed.connect(self._caption.set_original)
            self._lc_worker.translation_ready.connect(self._on_translation_ready)
            self._lc_worker.status_changed.connect(self._on_lc_status)
            self._lc_worker.start()
        else:
            self._caption.set_translation("")
            self._caption.set_status("Screen OCR mode - open Settings (⚙) and pick a window")
            self._ocr.load_models()

    def _stop_pipelines(self):
        import gc

        if self._lc_worker is not None:
            self._lc_worker.stop()
            self._lc_worker = None
        # Fully release Screen OCR models when leaving that mode (frees ~500MB+)
        self._ocr.shutdown()
        gc.collect()

    # ---------- status handlers ----------

    def _on_lc_status(self, status: str):
        messages = {
            "loading_model": "Loading translation model... (first run downloads ~2.4GB)",
            "connecting": "Looking for the Live Captions window...",
            "needs_setup": 'Live Captions needs setup: click "Yes, continue" / "Continue" on its window',
            "running": "",  # transcript will replace this
            "stopped": "",
        }
        if status == "needs_setup":
            # The user must see the window to click the consent buttons
            set_live_captions_visible(True)
        elif status == "running" and not self._config.show_live_captions:
            set_live_captions_visible(False)
        if status == "download_stalled":
            self._caption.set_status(
                "Download stalled - check your internet connection, or switch to the "
                "Google engine in Settings (⚙) which needs no download."
            )
            return
        if status.startswith("downloading:"):
            try:
                pct, done_mb, total_mb = (int(x) for x in status.split(":")[1:4])
                if pct >= 99:
                    self._caption.set_status("Preparing translation model... (almost done)")
                else:
                    self._caption.set_status(
                        f"Downloading translation model... {pct}% ({done_mb}/{total_mb} MB) - "
                        "one-time only. Tip: Google engine in Settings (⚙) needs no download."
                    )
            except ValueError:
                pass
            return
        if status.startswith("error:"):
            self._caption.set_status(f"Error: {status[6:][:120]}")
        elif messages.get(status):
            self._caption.set_status(messages[status])

    def _on_translation_ready(self, original: str, translated: str):
        self._history.add(original, translated)
        if self._history_dialog and self._history_dialog.isVisible():
            self._history_dialog.refresh()
        # If this is the same sentence grown longer (partial -> complete),
        # replace the last line instead of appending a near-duplicate.
        last = getattr(self, "_last_original", None)
        if self._recent_translations and last and (original.startswith(last) or last.startswith(original)):
            self._recent_translations[-1] = translated
        else:
            self._recent_translations.append(translated)
        self._last_original = original
        self._caption.set_translation("\n".join(self._recent_translations))

    def _on_ocr_status(self, status: str):
        if status == "loading":
            self._caption.set_status("Loading OCR/translation models... (first run downloads up to ~1.2GB)")
        elif status == "ready":
            self._caption.set_status("Models ready - open Settings (⚙) and pick a window")
        elif status == "capturing":
            self._caption.set_status(f"Capturing: {self._config.window_title[:60]}")
        elif status == "window_closed":
            self._caption.set_status("Window closed - capture stopped")
            if self._settings:
                self._settings.set_capturing(False)
        elif status.startswith("error:"):
            self._caption.set_status(f"Error: {status[6:][:120]}")

    # ---------- settings ----------

    def _show_settings(self):
        if self._settings is None:
            self._settings = SettingsDialog(self._config, self._ocr.list_windows)
            s = self._settings
            s.mode_changed.connect(self._start_mode)
            s.lc_pair_changed.connect(self._on_lc_pair_changed)
            s.lc_engine_changed.connect(self._restart_lc_if_needed)
            s.show_live_captions_changed.connect(self._on_show_lc_toggled)
            s.overlay_sentences_changed.connect(self._on_overlay_sentences_changed)
            s.ocr_direction_changed.connect(self._on_ocr_direction_changed)
            s.overlay_mode_changed.connect(self._on_overlay_mode_changed)
            s.vertical_text_changed.connect(self._on_vertical_text_changed)
            s.confidence_changed.connect(self._on_confidence_changed)
            s.font_size_changed.connect(self._on_font_size_changed)
            s.opacity_changed.connect(self._on_opacity_changed)
            s.capture_window_requested.connect(self._on_capture_window)
            s.stop_capture_requested.connect(self._ocr.stop_capture)
        self._settings.refresh_windows()
        self._settings.show()
        self._settings.raise_()
        self._settings.activateWindow()

    def _on_lc_pair_changed(self, source: str, target: str):
        self._config.lc_source = source
        self._config.lc_target = target
        self._restart_lc_if_needed()

    def _restart_lc_if_needed(self):
        """Restart Live Captions mode only if engine/languages actually changed."""
        if self._config.app_mode != AppMode.LIVE_CAPTIONS:
            return
        key = (self._config.translation_engine, self._config.lc_source, self._config.lc_target)
        if key != self._lc_running_key:
            self._start_mode(AppMode.LIVE_CAPTIONS)

    def _on_pause_toggled(self, paused: bool):
        self._paused = paused
        if self._lc_worker is not None:
            self._lc_worker.paused = paused
        self._pause_action.setChecked(paused)
        if paused:
            self._caption.set_status("Paused")

    def _on_show_lc_toggled(self, show: bool):
        self._config.show_live_captions = show
        self._show_lc_action.setChecked(show)
        set_live_captions_visible(show)

    def _on_overlay_sentences_changed(self, count: int):
        self._config.overlay_sentences = count
        self._recent_translations = deque(self._recent_translations, maxlen=count)
        self._caption.set_translation("\n".join(self._recent_translations))

    def _copy_latest(self):
        if self._recent_translations:
            QGuiApplication.clipboard().setText(self._recent_translations[-1])

    def _show_history(self):
        if self._history_dialog is None:
            self._history_dialog = HistoryDialog(self._history)
        self._history_dialog.refresh()
        self._history_dialog.show()
        self._history_dialog.raise_()
        self._history_dialog.activateWindow()

    def _on_ocr_direction_changed(self, direction: str):
        self._config.ocr_direction = direction
        self._ocr.set_direction(direction)

    def _on_overlay_mode_changed(self, mode: OverlayMode):
        self._config.overlay_mode = mode
        self._ocr.set_overlay_mode(mode)

    def _on_vertical_text_changed(self, checked: bool):
        self._config.vertical_text = checked

    def _on_confidence_changed(self, value: float):
        self._config.ocr_confidence = value
        self._ocr.set_confidence(value)

    def _on_font_size_changed(self, value: int):
        self._config.font_size = value
        self._caption.refresh_style()
        self._inplace_overlay.set_font_size(value)

    def _on_opacity_changed(self, value: float):
        self._config.background_opacity = value
        self._caption.refresh_style()
        self._inplace_overlay.set_opacity(value)

    def _on_capture_window(self, info: dict):
        ok = self._ocr.start_capture(
            info.get("title", ""), window_id=info.get("id"), bounds=info.get("bounds")
        )
        if self._settings:
            self._settings.set_capturing(ok)

    # ---------- tray ----------

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visible()

    def _toggle_visible(self):
        if self._caption.isVisible():
            self._caption.hide()
        else:
            self._caption.show()

    def _hide_to_tray(self):
        self._caption.hide()
        self._tray.showMessage(
            "Translator AI OCR",
            "Still running in the system tray. Right-click the icon to quit.",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def _quit(self):
        import os
        import threading

        try:
            self._stop_pipelines()
            set_live_captions_visible(True)  # don't leave Live Captions stranded off-screen
            self._caption.save_geometry()
            self._config.save()
        except Exception as e:
            logger.error("error during shutdown", error=str(e))
        self._tray.hide()
        self._app.quit()
        # Non-daemon library threads (e.g. an in-progress model download)
        # can keep the interpreter alive after the event loop exits - make
        # sure the process really terminates.
        threading.Timer(1.5, lambda: os._exit(0)).start()


def run() -> int:
    """Run the application."""
    log.configure()  # must run before any log call (windowed builds log to file)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # keep running in tray
    app.setApplicationName("Translator AI OCR")

    config = Config.load()
    translator_app = TranslatorApp(app, config)

    # Allow Ctrl+C to quit when run from a terminal
    signal.signal(signal.SIGINT, lambda *_: translator_app._quit())
    timer = QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    logger.info("translator-ai-ocr started", version=__version__)
    return app.exec()
