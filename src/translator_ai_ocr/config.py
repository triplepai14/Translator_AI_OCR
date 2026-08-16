"""Configuration management for Translator AI OCR."""

import os
from enum import Enum
from pathlib import Path

import yaml

from . import log

logger = log.get_logger()


class OverlayMode(str, Enum):
    """Overlay display mode for Screen OCR."""

    BANNER = "banner"
    INPLACE = "inplace"


class AppMode(str, Enum):
    """Application mode."""

    LIVE_CAPTIONS = "live_captions"
    SCREEN_OCR = "screen_ocr"


CONFIG_DIR = Path.home() / ".translator_ai_ocr"

# Live Captions caption (source) languages. The user must set the same
# caption language inside Live Captions itself (its gear menu).
LC_SOURCES = {
    "en": "English",
    "ja": "日本語 (Japanese)",
}

# Live Captions translation target languages
LC_TARGETS = {
    "en": "English",
    "ja": "日本語 (Japanese)",
    "th": "ไทย (Thai)",
}

# Valid source->target pairs (must have a model in translate.MODEL_SPECS)
LC_PAIRS = {
    ("en", "ja"),
    ("en", "th"),
    ("ja", "en"),
    ("ja", "th"),
}


class Config:
    """Application configuration persisted to ~/.translator_ai_ocr/config.yml."""

    def __init__(
        self,
        app_mode: AppMode = AppMode.LIVE_CAPTIONS,
        lc_source: str = "en",
        lc_target: str = "ja",
        ocr_direction: str = "ja-en",
        overlay_mode: OverlayMode = OverlayMode.BANNER,
        window_title: str = "",
        ocr_confidence: float = 0.6,
        vertical_text: bool = False,
        font_family: str | None = None,
        font_size: int = 18,
        font_color: str = "#FFFFFF",
        background_color: str = "#202124",
        background_opacity: float = 0.92,
        caption_x: int | None = None,
        caption_y: int | None = None,
        caption_width: int | None = None,
        config_path: str | None = None,
    ):
        self.app_mode = app_mode
        self.lc_source = lc_source if lc_source in LC_SOURCES else "en"
        self.lc_target = lc_target if lc_target in LC_TARGETS else "ja"
        if (self.lc_source, self.lc_target) not in LC_PAIRS:
            self.lc_target = "ja" if self.lc_source == "en" else "en"
        self.ocr_direction = ocr_direction if ocr_direction in ("ja-en", "en-ja") else "ja-en"
        self.overlay_mode = overlay_mode
        self.window_title = window_title
        self.ocr_confidence = ocr_confidence
        self.vertical_text = vertical_text
        self.font_family = font_family
        self.font_size = font_size
        self.font_color = font_color
        self.background_color = background_color
        self.background_opacity = background_opacity
        self.caption_x = caption_x
        self.caption_y = caption_y
        self.caption_width = caption_width
        self.config_path = config_path

    @classmethod
    def load(cls, config_path: str | None = None) -> "Config":
        """Load configuration from YAML file."""
        if config_path is None:
            default_path = CONFIG_DIR / "config.yml"
            if default_path.exists():
                config_path = str(default_path)

        if config_path and os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            try:
                app_mode = AppMode(data.get("app_mode", "live_captions"))
            except ValueError:
                app_mode = AppMode.LIVE_CAPTIONS
            try:
                overlay_mode = OverlayMode(data.get("overlay_mode", "banner"))
            except ValueError:
                overlay_mode = OverlayMode.BANNER

            return cls(
                app_mode=app_mode,
                lc_source=str(data.get("lc_source", "en")),
                lc_target=str(data.get("lc_target", "ja")),
                ocr_direction=str(data.get("ocr_direction", "ja-en")),
                overlay_mode=overlay_mode,
                window_title=str(data.get("window_title", "")),
                ocr_confidence=float(data.get("ocr_confidence", 0.6)),
                vertical_text=bool(data.get("vertical_text", False)),
                font_family=data.get("font_family"),
                font_size=int(data.get("font_size", 18)),
                font_color=str(data.get("font_color", "#FFFFFF")),
                background_color=str(data.get("background_color", "#202124")),
                background_opacity=float(data.get("background_opacity", 0.92)),
                caption_x=data.get("caption_x"),
                caption_y=data.get("caption_y"),
                caption_width=data.get("caption_width"),
                config_path=str(Path(config_path).resolve()),
            )

        return cls()

    def save(self, config_path: str | None = None) -> None:
        """Save configuration to YAML file."""
        if config_path is None:
            config_path = self.config_path
        if config_path is None:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            config_path = str(CONFIG_DIR / "config.yml")

        data = {
            "app_mode": self.app_mode.value,
            "lc_source": str(self.lc_source),
            "lc_target": str(self.lc_target),
            "ocr_direction": str(self.ocr_direction),
            "overlay_mode": self.overlay_mode.value,
            "window_title": str(self.window_title),
            "ocr_confidence": float(self.ocr_confidence),
            "vertical_text": bool(self.vertical_text),
            "font_size": int(self.font_size),
            "font_color": str(self.font_color),
            "background_color": str(self.background_color),
            "background_opacity": float(self.background_opacity),
        }
        if self.font_family is not None:
            data["font_family"] = str(self.font_family)
        if self.caption_x is not None:
            data["caption_x"] = int(self.caption_x)
        if self.caption_y is not None:
            data["caption_y"] = int(self.caption_y)
        if self.caption_width is not None:
            data["caption_width"] = int(self.caption_width)

        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)

        self.config_path = config_path
        logger.info("config saved", path=config_path)
