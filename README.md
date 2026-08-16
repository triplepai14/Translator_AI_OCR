# Translator AI OCR

Offline AI screen translator for Windows with two modes:

- **Live Captions mode** — reads the Windows 11 Live Captions bar directly via UI Automation
  (no OCR, 100% accurate text) and translates English to **Japanese** or **Thai** offline.
- **Screen OCR mode** — captures any window (games, manga readers, browsers), OCRs the text
  (MeikiOCR for Japanese, RapidOCR for English) and translates offline
  (Sugoi V4 for JA→EN, NLLB-200 for EN→JA), shown as a caption bar or in-place overlay.

The UI is a slim always-on-top caption bar. Closing it hides the app to the **system tray**
(right-click the tray icon to quit).

## Install (Windows)

Download **TranslatorAIOCR-Setup.exe** from the
[Releases repo](https://github.com/triplepai14/Translator_AI_OCR-Releases) and run it.

Translation/OCR models are downloaded automatically on first use
(Sugoi ~1.1GB for JA→EN, NLLB ~2.4GB for EN→JA/TH) and cached in `~/.cache/huggingface`.

## Run from source

```powershell
uv tool install --python 3.12 --from <this repo> translator-ai-ocr
translator-ai-ocr
```

## Using Live Captions mode

1. Start the app (Live Captions mode is the default)
2. The app launches Windows Live Captions automatically (`Win+Ctrl+L` also works)
3. First time only: click **"Yes, continue"** on the Live Captions window to let Windows set it up
4. Play any English audio/video — translations appear in the caption bar

## Config

`~/.translator_ai_ocr/config.yml` — mode, languages, appearance, caption bar position.

## License

MIT
