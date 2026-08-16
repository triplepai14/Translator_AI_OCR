"""Settings dialog: mode, languages, capture window, appearance."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QCheckBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from ..config import ENGINES, LC_SOURCES, LC_TARGETS, AppMode, OverlayMode, valid_lc_pair


class SettingsDialog(QDialog):
    """Compact settings dialog. Emits signals when the user changes things."""

    mode_changed = Signal(object)  # AppMode
    lc_pair_changed = Signal(str, str)  # (source, target)
    lc_engine_changed = Signal()  # engine selection or API settings applied
    show_live_captions_changed = Signal(bool)
    overlay_sentences_changed = Signal(int)
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
        self._lc_group = QGroupBox("Live Captions")
        lc_outer = QVBoxLayout(self._lc_group)

        # Engine selection
        engine_row = QHBoxLayout()
        engine_row.addWidget(QLabel("Engine:"))
        self._engine_combo = QComboBox()
        for code, label in ENGINES.items():
            self._engine_combo.addItem(label, code)
        idx = self._engine_combo.findData(self._config.translation_engine)
        if idx >= 0:
            self._engine_combo.setCurrentIndex(idx)
        self._engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        engine_row.addWidget(self._engine_combo, 1)
        lc_outer.addLayout(engine_row)

        # Per-engine API settings (shown/hidden by engine)
        self._api_form = QFormLayout()
        self._deepl_key = self._api_field("deepl_api_key", password=True)
        self._openai_base = self._api_field("openai_base_url")
        self._openai_key = self._api_field("openai_api_key", password=True)
        self._openai_model = self._api_field("openai_model")
        self._ollama_base = self._api_field("ollama_base_url")
        self._ollama_model = self._api_field("ollama_model")
        self._lt_url = self._api_field("libretranslate_url")
        self._lt_key = self._api_field("libretranslate_api_key", password=True)
        self._api_rows = {
            "deepl": [("API key:", self._deepl_key)],
            "openai": [
                ("Base URL:", self._openai_base),
                ("API key:", self._openai_key),
                ("Model:", self._openai_model),
            ],
            "ollama": [("Server:", self._ollama_base), ("Model:", self._ollama_model)],
            "libretranslate": [("Server URL:", self._lt_url), ("API key:", self._lt_key)],
        }
        for rows in self._api_rows.values():
            for label, field in rows:
                self._api_form.addRow(label, field)
        lc_outer.addLayout(self._api_form)

        self._apply_engine_btn = QPushButton("Apply engine settings")
        self._apply_engine_btn.clicked.connect(self.lc_engine_changed.emit)
        lc_outer.addWidget(self._apply_engine_btn)

        # Languages
        lc_layout = QHBoxLayout()
        lc_layout.addWidget(QLabel("Caption language:"))
        self._lc_source_combo = QComboBox()
        for code, label in LC_SOURCES.items():
            self._lc_source_combo.addItem(label, code)
        idx = self._lc_source_combo.findData(self._config.lc_source)
        if idx >= 0:
            self._lc_source_combo.setCurrentIndex(idx)
        self._lc_source_combo.currentIndexChanged.connect(self._on_lc_source_changed)
        lc_layout.addWidget(self._lc_source_combo)

        lc_layout.addWidget(QLabel("Translate to:"))
        self._lc_target_combo = QComboBox()
        self._rebuild_lc_targets()
        self._lc_target_combo.currentIndexChanged.connect(self._emit_lc_pair)
        lc_layout.addWidget(self._lc_target_combo)
        lc_layout.addStretch()
        lc_outer.addLayout(lc_layout)

        # Display options
        opt_row2 = QHBoxLayout()
        self._show_lc_check = QCheckBox("Show Live Captions window")
        self._show_lc_check.setChecked(self._config.show_live_captions)
        self._show_lc_check.toggled.connect(self.show_live_captions_changed.emit)
        opt_row2.addWidget(self._show_lc_check)
        opt_row2.addWidget(QLabel("Sentences shown:"))
        self._sentences_spin = QSpinBox()
        self._sentences_spin.setRange(1, 5)
        self._sentences_spin.setValue(self._config.overlay_sentences)
        self._sentences_spin.valueChanged.connect(self.overlay_sentences_changed.emit)
        opt_row2.addWidget(self._sentences_spin)
        opt_row2.addStretch()
        lc_outer.addLayout(opt_row2)

        lc_hint = QLabel(
            "The caption language must also be set inside Live Captions itself\n"
            "(gear icon on the Live Captions bar → Caption language)."
        )
        lc_hint.setStyleSheet("color: #888; font-size: 11px;")
        lc_outer.addWidget(lc_hint)
        layout.addWidget(self._lc_group)
        self._update_api_rows()

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

    def _api_field(self, config_attr: str, password: bool = False) -> QLineEdit:
        """Create a QLineEdit bound to a config attribute."""
        field = QLineEdit(getattr(self._config, config_attr, ""))
        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        field.editingFinished.connect(lambda: setattr(self._config, config_attr, field.text().strip()))
        return field

    def _update_api_rows(self):
        """Show only the API fields relevant to the selected engine."""
        engine = self._engine_combo.currentData()
        for eng, rows in self._api_rows.items():
            visible = eng == engine
            for label, field in rows:
                field.setVisible(visible)
                lbl = self._api_form.labelForField(field)
                if lbl:
                    lbl.setVisible(visible)
        self._apply_engine_btn.setVisible(engine != "offline")

    def _on_engine_changed(self, _index: int):
        self._config.translation_engine = self._engine_combo.currentData()
        self._update_api_rows()
        self._rebuild_lc_targets()
        self._emit_lc_pair()
        self.lc_engine_changed.emit()

    def _rebuild_lc_targets(self):
        """Fill the target combo with languages valid for the engine + source."""
        engine = self._engine_combo.currentData()
        source = self._lc_source_combo.currentData()
        self._lc_target_combo.blockSignals(True)
        self._lc_target_combo.clear()
        for code, label in LC_TARGETS.items():
            if valid_lc_pair(engine, source, code):
                self._lc_target_combo.addItem(label, code)
        idx = self._lc_target_combo.findData(self._config.lc_target)
        self._lc_target_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._lc_target_combo.blockSignals(False)

    def _on_lc_source_changed(self, _index: int):
        self._rebuild_lc_targets()
        self._emit_lc_pair()

    def _emit_lc_pair(self, _index: int = 0):
        source = self._lc_source_combo.currentData()
        target = self._lc_target_combo.currentData()
        if source and target:
            self.lc_pair_changed.emit(source, target)

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
