"""Translation engines for Live Captions mode.

"offline" uses the bundled CTranslate2 models (Sugoi V4 / NLLB-200).
The rest are online or self-hosted services, configured in Settings.
"""

from abc import ABC, abstractmethod

import requests

from . import log
from .translate import DEFAULT_CACHE_SIZE, MODEL_SPECS, TranslationCache, Translator, cache_size_bytes

logger = log.get_logger()

REQUEST_TIMEOUT = 10

# Language code fixes per service (default: use the code as-is)
GOOGLE_CODES = {"zh": "zh-CN"}
DEEPL_CODES = {"en": "EN", "ja": "JA", "zh": "ZH", "ko": "KO", "fr": "FR", "de": "DE", "es": "ES"}
LANG_NAMES = {
    "en": "English",
    "ja": "Japanese",
    "th": "Thai",
    "zh": "Chinese",
    "ko": "Korean",
    "vi": "Vietnamese",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
}


class TranslationEngine(ABC):
    """A translation engine translating from a fixed source to a target language."""

    #: True if load() may download/convert large models (show a longer status)
    requires_download = False

    def __init__(self, source: str, target: str):
        self._source = source
        self._target = target

    def load(self) -> None:
        """Prepare the engine (may raise)."""

    @abstractmethod
    def translate_text(self, text: str) -> str:
        """Translate text; raises on failure."""


class OfflineEngine(TranslationEngine):
    """Bundled CTranslate2 models (Sugoi V4 / NLLB-200), fully offline."""

    requires_download = True

    def __init__(self, source: str, target: str):
        super().__init__(source, target)
        self._direction = f"{source}-{target}"
        self._translator = Translator(direction=self._direction)

    def load(self) -> None:
        self._translator.load()

    def translate_text(self, text: str) -> str:
        return self._translator.translate(text)[0]

    def download_progress(self) -> tuple[int, int] | None:
        """Return (downloaded_bytes, approx_total_bytes) for the model."""
        spec = MODEL_SPECS[self._direction]
        total = spec.get("approx_size")
        if not total:
            return None
        return cache_size_bytes(spec["repo_id"]), total


class GoogleEngine(TranslationEngine):
    """Google Translate free web endpoint (no API key needed)."""

    def translate_text(self, text: str) -> str:
        params = {
            "client": "gtx",
            "sl": GOOGLE_CODES.get(self._source, self._source),
            "tl": GOOGLE_CODES.get(self._target, self._target),
            "dt": "t",
            "q": text,
        }
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single", params=params, timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        data = r.json()
        return "".join(seg[0] for seg in (data[0] or []) if seg and seg[0]).strip()


class DeepLEngine(TranslationEngine):
    """DeepL API (free or pro key)."""

    def __init__(self, source: str, target: str, api_key: str):
        super().__init__(source, target)
        self._key = (api_key or "").strip()

    def load(self) -> None:
        if not self._key:
            raise RuntimeError("DeepL API key is not set (Settings)")
        if self._target not in DEEPL_CODES:
            raise RuntimeError(f"DeepL does not support target language '{self._target}'")

    def translate_text(self, text: str) -> str:
        host = "api-free.deepl.com" if self._key.endswith(":fx") else "api.deepl.com"
        data = {"text": text, "target_lang": DEEPL_CODES[self._target]}
        if self._source in DEEPL_CODES:
            data["source_lang"] = DEEPL_CODES[self._source]
        r = requests.post(
            f"https://{host}/v2/translate",
            data=data,
            headers={"Authorization": f"DeepL-Auth-Key {self._key}"},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()["translations"][0]["text"].strip()


_LLM_SYSTEM_PROMPT = (
    "You are a professional real-time subtitle translator. "
    "Translate the user's text from {src} to {tgt}. "
    "Output ONLY the translation, nothing else."
)


class OpenAICompatEngine(TranslationEngine):
    """OpenAI-compatible chat API (OpenAI, OpenRouter, LM Studio, etc.)."""

    def __init__(self, source: str, target: str, base_url: str, api_key: str, model: str):
        super().__init__(source, target)
        self._base = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._key = (api_key or "").strip()
        self._model = (model or "gpt-4o-mini").strip()

    def load(self) -> None:
        if not self._key:
            raise RuntimeError("API key is not set (Settings)")

    def translate_text(self, text: str) -> str:
        system = _LLM_SYSTEM_PROMPT.format(
            src=LANG_NAMES.get(self._source, self._source), tgt=LANG_NAMES.get(self._target, self._target)
        )
        r = requests.post(
            f"{self._base}/chat/completions",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "temperature": 0.2,
            },
            headers={"Authorization": f"Bearer {self._key}"},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


class OllamaEngine(TranslationEngine):
    """Local LLM via Ollama."""

    def __init__(self, source: str, target: str, base_url: str, model: str):
        super().__init__(source, target)
        self._base = (base_url or "http://localhost:11434").rstrip("/")
        self._model = (model or "").strip()

    def load(self) -> None:
        if not self._model:
            raise RuntimeError("Ollama model name is not set (Settings)")
        # Verify the server is reachable
        requests.get(f"{self._base}/api/tags", timeout=5).raise_for_status()

    def translate_text(self, text: str) -> str:
        system = _LLM_SYSTEM_PROMPT.format(
            src=LANG_NAMES.get(self._source, self._source), tgt=LANG_NAMES.get(self._target, self._target)
        )
        r = requests.post(
            f"{self._base}/api/chat",
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                "stream": False,
            },
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


class LibreTranslateEngine(TranslationEngine):
    """Self-hosted or public LibreTranslate server."""

    def __init__(self, source: str, target: str, base_url: str, api_key: str):
        super().__init__(source, target)
        self._base = (base_url or "").rstrip("/")
        self._key = (api_key or "").strip()

    def load(self) -> None:
        if not self._base:
            raise RuntimeError("LibreTranslate server URL is not set (Settings)")

    def translate_text(self, text: str) -> str:
        payload = {"q": text, "source": self._source, "target": self._target, "format": "text"}
        if self._key:
            payload["api_key"] = self._key
        r = requests.post(f"{self._base}/translate", json=payload, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()["translatedText"].strip()


class CachedEngine:
    """Wraps an engine with the fuzzy translation cache."""

    def __init__(self, engine: TranslationEngine):
        self._engine = engine
        self._cache = TranslationCache(DEFAULT_CACHE_SIZE)

    @property
    def requires_download(self) -> bool:
        return self._engine.requires_download

    def download_progress(self) -> tuple[int, int] | None:
        fn = getattr(self._engine, "download_progress", None)
        return fn() if fn else None

    def load(self) -> None:
        self._engine.load()

    def translate(self, text: str) -> tuple[str, bool]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached, True
        result = self._engine.translate_text(text)
        if result:
            self._cache.put(text, result)
        return result, False


def create_engine(config) -> CachedEngine:
    """Build the Live Captions translation engine from config."""
    src, tgt = config.lc_source, config.lc_target
    kind = config.translation_engine
    if kind == "google":
        engine = GoogleEngine(src, tgt)
    elif kind == "deepl":
        engine = DeepLEngine(src, tgt, config.deepl_api_key)
    elif kind == "openai":
        engine = OpenAICompatEngine(src, tgt, config.openai_base_url, config.openai_api_key, config.openai_model)
    elif kind == "ollama":
        engine = OllamaEngine(src, tgt, config.ollama_base_url, config.ollama_model)
    elif kind == "libretranslate":
        engine = LibreTranslateEngine(src, tgt, config.libretranslate_url, config.libretranslate_api_key)
    else:
        engine = OfflineEngine(src, tgt)
    logger.info("translation engine created", engine=kind, source=src, target=tgt)
    return CachedEngine(engine)
