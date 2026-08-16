"""Settings dialog: mode, languages, capture window, appearance."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
)

from ..config import LC_TARGETS, AppMode, OverlayMode


class SettingsDialog(QDialog):
    """Compact settings dialog. Emits signals when the user changes things."""

    mode_changed = Signal(object)  # AppMode
    lc_target_changed = Signal(str)
    ocr_direction_changed = Signal(str)
    overlay_mode_changed = Signal(object)  # OverlayMode
    vertical_text_changed = Signal(bool)
    confidence_changed = Signal(float)
    font_size_changed = Signal(int)
    opacity_changed = Signal(float)
    capture_window_requested = Signal(dict)  # window info dict
    stop_capture_requested = Signal()

    def __init__(self, config, list_windows_fn, parent=None):
        super().__init__(parent)
        self._config = config
        self._list_windows_fn = list_windows_fn
        self._windows: list[dict] = []

        self.setWindowTitle("Translator AI OCR - Settings")
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # ----- Mode -----
        mode_group = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_group)
        self._lc_radio = QRadioButton("Live Captions  (read Windows 11 captions, no OCR)")
        self._ocr_radio = QRadioButton("Screen OCR  (capture a window: games / manga)")
        if self._config.app_mode == AppMode.LIVE_CAPTIONS:
            self._lc_radio.setChecked(True)
        else:
            self._ocr_radio.setChecked(True)
        self._lc_radio.toggled.connect(self._on_mode_toggled)
        mode_layout.addWidget(self._lc_radio)
        mode_layout.addWidget(self._ocr_radio)
        layout.addWidget(mode_group)

        # ----- Live Captions options -----
        self._lc_group = QGroupBox("Live Captions: translate English to")
        lc_layout = QHBoxLayout(self._lc_group)
        self._lc_target_combo = QComboBox()
        for code, (_token, label) in LC_TARGETS.items():
            self._lc_target_combo.addItem(label, code)
        idx = self._lc_target_combo.findData(self._config.lc_target)
        if idx >= 0:
            self._lc_target_combo.setCurrentIndex(idx)
        self._lc_target_combo.currentIndexChanged.connect(
            lambda _: self.lc_target_changed.emit(self._lc_target_combo.currentData())
        )
        lc_layout.addWidget(self._lc_target_combo)
        layout.addWidget(self._lc_group)

        # ----- Screen OCR options -----
        self._ocr_group = QGroupBox("Screen OCR")
        ocr_layout = QVBoxLayout(self._ocr_group)

        win_row = QHBoxLayout()
        self._window_combo = QComboBox()
        self._window_combo.setMinimumWidth(200)
        win_row.addWidget(self._window_combo, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_windows)
        win_row.addWidget(refresh_btn)
        self._capture_btn = QPushButton("Start")
        self._capture_btn.clicked.connect(self._on_capture_clicked)
        win_row.addWidget(self._capture_btn)
        ocr_layout.addLayout(win_row)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Direction:"))
        self._direction_combo = QComboBox()
        self._direction_combo.addItem("JA → EN (games/manga)", "ja-en")
        self._direction_combo.addItem("EN → JA", "en-ja")
        if self._config.ocr_direction == "en-ja":
            self._direction_combo.setCurrentIndex(1)
        self._direction_combo.currentIndexChanged.connect(
            lambda _: self.ocr_direction_changed.emit(self._direction_combo.currentData())
        )
        dir_row.addWidget(self._direction_combo)

        dir_row.addWidget(QLabel("Overlay:"))
        self._overlay_combo = QComboBox()
        self._overlay_combo.addItem("Caption bar", OverlayMode.BANNER)
        self._overlay_combo.addItem("Inplace (over text)", OverlayMode.INPLACE)
        if self._config.overlay_mode == OverlayMode.INPLACE:
            self._overlay_combo.setCurrentIndex(1)
        self._overlay_combo.currentIndexChanged.connect(
            lambda _: self.overlay_mode_changed.emit(self._overlay_combo.currentData())
        )
        dir_row.addWidget(self._overlay_combo)
        dir_row.addStretch()
        ocr_layout.addLayout(dir_row)

        opt_row = QHBoxLayout()
        self._vertical_check = QCheckBox("Vertical text (manga)")
        self._vertical_check.setChecked(self._config.vertical_text)
        self._vertical_check.toggled.connect(self.vertical_text_changed.emit)
        opt_row.addWidget(self._vertical_check)

        opt_row.addWidget(QLabel("OCR confidence:"))
        self._conf_slider = QSlider(Qt.Orientation.Horizontal)
        self._conf_slider.setRange(10, 95)
        self._conf_slider.setValue(int(self._config.ocr_confidence * 100))
        self._conf_label = QLabel(f"{int(self._config.ocr_confidence * 100)}%")
        self._conf_slider.valueChanged.connect(self._on_conf_changed)
        opt_row.addWidget(self._conf_slider, 1)
        opt_row.addWidget(self._conf_label)
        ocr_layout.addLayout(opt_row)

        layout.addWidget(self._ocr_group)

        # ----- Appearance -----
        appearance_group = QGroupBox("Appearance")
        app_layout = QVBoxLayout(appearance_group)

        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Font size:"))
        self._font_slider = QSlider(Qt.Orientation.Horizontal)
        self._font_slider.setRange(10, 48)
        self._font_slider.setValue(self._config.font_size)
        self._font_label = QLabel(f"{self._config.font_size}pt")
        self._font_slider.valueChanged.connect(self._on_font_changed)
        font_row.addWidget(self._font_slider, 1)
        font_row.addWidget(self._font_label)
        app_layout.addLayout(font_row)

        op_row = QHBoxLayout()
        op_row.addWidget(QLabel("Background opacity:"))
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(int(self._config.background_opacity * 100))
        self._opacity_label = QLabel(f"{int(self._config.background_opacity * 100)}%")
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self._opacity_slider, 1)
        op_row.addWidget(self._opacity_label)
        app_layout.addLayout(op_row)

        layout.addWidget(appearance_group)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888;")
        layout.addWidget(self._status_label)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

        self._update_group_states()
        self.refresh_windows()

    # ---------- handlers ----------

    def _on_mode_toggled(self, lc_checked: bool):
        mode = AppMode.LIVE_CAPTIONS if lc_checked else AppMode.SCREEN_OCR
        self._update_group_states()
        self.mode_changed.emit(mode)

    def _update_group_states(self):
        lc = self._lc_radio.isChecked()
        self._lc_group.setEnabled(lc)
        self._ocr_group.setEnabled(not lc)

    def _on_conf_changed(self, value: int):
        self._conf_label.setText(f"{value}%")
        self.confidence_changed.emit(value / 100.0)

    def _on_font_changed(self, value: int):
        self._font_label.setText(f"{value}pt")
        self.font_size_changed.emit(value)

    def _on_opacity_changed(self, value: int):
        self._opacity_label.setText(f"{value}%")
        self.opacity_changed.emit(value / 100.0)

    def refresh_windows(self):
        self._windows = self._list_windows_fn() or []
        self._window_combo.clear()
        for w in self._windows:
            title = w.get("title", "")
            self._window_combo.addItem(title[:60], w)
        # Preselect previously used window
        if self._config.window_title:
            for i, w in enumerate(self._windows):
                if self._config.window_title in w.get("title", ""):
                    self._window_combo.setCurrentIndex(i)
                    break

    def _on_capture_clicked(self):
        if self._capture_btn.text() == "Stop":
            self.stop_capture_requested.emit()
            self.set_capturing(False)
            return
        info = self._window_combo.currentData()
        if info:
            self.capture_window_requested.emit(info)

    def set_capturing(self, capturing: bool):
        self._capture_btn.setText("Stop" if capturing else "Start")

    def set_status(self, text: str):
        self._status_label.setText(text)
