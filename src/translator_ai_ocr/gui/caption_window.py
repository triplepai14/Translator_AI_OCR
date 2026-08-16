"""Caption bar window: dark rounded always-on-top bar with original + translation."""

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizeGrip,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_WIDTH_FRACTION = 0.55
MIN_WIDTH = 420
MIN_HEIGHT = 96


class CaptionWindow(QWidget):
    """Frameless, draggable caption bar showing original text and translation."""

    settings_requested = Signal()
    hide_requested = Signal()  # close button -> hide to tray
    quit_requested = Signal()

    def __init__(self, config):
        super().__init__()
        self._config = config
        self._drag_pos: QPoint | None = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMinimumSize(MIN_WIDTH, MIN_HEIGHT)

        self._setup_ui()
        self._apply_style()
        self._restore_geometry()

    # ---------- UI ----------

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._frame = QFrame()
        outer.addWidget(self._frame)

        root = QHBoxLayout(self._frame)
        root.setContentsMargins(16, 10, 6, 6)
        root.setSpacing(8)

        # Text column
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        self._original_label = QLabel("")
        self._original_label.setWordWrap(True)
        self._original_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        self._translated_label = QLabel("")
        self._translated_label.setWordWrap(True)
        self._translated_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        text_col.addWidget(self._original_label)
        text_col.addWidget(self._translated_label, 1)
        root.addLayout(text_col, 1)

        # Button column
        btn_col = QVBoxLayout()
        btn_col.setSpacing(0)
        btn_col.setContentsMargins(0, 0, 0, 0)

        self._settings_btn = self._tool_button("⚙", "Settings")  # gear
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        self._hide_btn = self._tool_button("─", "Hide to tray")  # minus
        self._hide_btn.clicked.connect(self.hide_requested.emit)
        self._close_btn = self._tool_button("✕", "Hide to tray (right-click tray icon to quit)")
        self._close_btn.clicked.connect(self.hide_requested.emit)

        btn_col.addWidget(self._close_btn)
        btn_col.addWidget(self._hide_btn)
        btn_col.addWidget(self._settings_btn)
        btn_col.addStretch()

        # Size grip in the bottom-right corner
        grip_row = QHBoxLayout()
        grip_row.addStretch()
        grip_row.addWidget(QSizeGrip(self._frame))
        btn_col.addLayout(grip_row)

        root.addLayout(btn_col)

    def _tool_button(self, text: str, tooltip: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setAutoRaise(True)
        btn.setFixedSize(26, 22)
        return btn

    def _apply_style(self):
        cfg = self._config
        bg = cfg.background_color.lstrip("#")
        r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
        a = int(cfg.background_opacity * 255)

        self._frame.setStyleSheet(
            f"QFrame {{ background-color: rgba({r},{g},{b},{a}); border-radius: 12px; }}"
            "QToolButton { color: #9aa0a6; border: none; font-size: 12px; }"
            "QToolButton:hover { color: #ffffff; }"
        )

        family = cfg.font_family
        original_font = QFont(family) if family else QFont()
        original_font.setPointSize(max(8, int(cfg.font_size * 0.62)))
        self._original_label.setFont(original_font)
        self._original_label.setStyleSheet("color: #9aa0a6; background: transparent;")

        translated_font = QFont(family) if family else QFont()
        translated_font.setPointSize(cfg.font_size)
        translated_font.setWeight(QFont.Weight.DemiBold)
        self._translated_label.setFont(translated_font)
        self._translated_label.setStyleSheet(f"color: {cfg.font_color}; background: transparent;")

    def refresh_style(self):
        """Re-apply fonts/colors after settings change."""
        self._apply_style()

    def _restore_geometry(self):
        screen = QApplication.primaryScreen().availableGeometry()
        width = self._config.caption_width or max(MIN_WIDTH, int(screen.width() * DEFAULT_WIDTH_FRACTION))
        self.resize(width, MIN_HEIGHT + 30)

        if self._config.caption_x is not None and self._config.caption_y is not None:
            x, y = self._config.caption_x, self._config.caption_y
            # Clamp to visible area
            if x + 100 > screen.right() or y + 40 > screen.bottom() or x < screen.left() - 100 or y < screen.top() - 10:
                x, y = None, None
            if x is not None:
                self.move(x, y)
                return
        # Default: bottom center
        self.move(
            screen.left() + (screen.width() - width) // 2,
            screen.bottom() - self.height() - 60,
        )

    def save_geometry(self):
        self._config.caption_x = self.x()
        self._config.caption_y = self.y()
        self._config.caption_width = self.width()

    # ---------- content ----------

    def set_original(self, text: str):
        self._original_label.setText(text)

    def set_translation(self, text: str):
        self._translated_label.setText(text)

    def set_status(self, text: str):
        """Show a status message in the original (small) row."""
        self._original_label.setText(text)

    # ---------- dragging ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_pos is not None:
            self._drag_pos = None
            self.save_geometry()
            event.accept()
