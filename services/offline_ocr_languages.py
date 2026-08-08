"""Model selection for the optional, test-only PaddleOCR path."""

from __future__ import annotations

import os


# Language abbreviations are PaddleOCR's public ``lang`` values.  Some differ
# from standard BCP-47 codes (for example, Magahi is ``mah`` in PaddleOCR).
DEVANAGARI_LANGUAGES = frozenset({
    "hi", "mr", "ne", "bh", "mai", "ang", "bho", "mah", "sck", "new", "gom", "sa", "bgc",
})
ARABIC_SCRIPT_LANGUAGES = frozenset({"ar", "fa", "ug", "ur", "ps", "ku", "sd", "bal"})

LANGUAGE_ALIASES = {
    "haryanvi": "bgc",
    "hariyanvi": "bgc",
    "bihari": "bh",
    "bhojpuri": "bho",
    "maithili": "mai",
    "magahi": "mah",
    "hindi": "hi",
    "marathi": "mr",
    "nepali": "ne",
    "sanskrit": "sa",
    "konkani": "gom",
    "urdu": "ur",
    "tamil": "ta",
    "telugu": "te",
    "english": "en",
}


def normalize_paddle_language(value: str | None) -> str:
    language = str(value or "hi").strip().lower().replace("-", "_")
    return LANGUAGE_ALIASES.get(language, language)


def recognition_model_for_language(language: str | None) -> str | None:
    """Return a PP-OCRv5 recognizer name, or None for Paddle auto-selection."""
    if explicit := os.getenv("PADDLE_OCR_REC_MODEL", "").strip():
        return explicit

    code = normalize_paddle_language(language)
    if code in DEVANAGARI_LANGUAGES:
        return (
            os.getenv("PADDLE_OCR_REC_MODEL_DEVANAGARI")
            or os.getenv("PADDLE_OCR_REC_MODEL_HI")
            or "devanagari_PP-OCRv5_mobile_rec"
        ).strip()
    if code in ARABIC_SCRIPT_LANGUAGES:
        return (os.getenv("PADDLE_OCR_REC_MODEL_ARABIC") or "arabic_PP-OCRv5_mobile_rec").strip()
    if code == "ta":
        return (os.getenv("PADDLE_OCR_REC_MODEL_TAMIL") or "ta_PP-OCRv5_mobile_rec").strip()
    if code == "te":
        return (os.getenv("PADDLE_OCR_REC_MODEL_TELUGU") or "te_PP-OCRv5_mobile_rec").strip()
    if code == "en":
        return (os.getenv("PADDLE_OCR_REC_MODEL_EN") or "en_PP-OCRv5_mobile_rec").strip()
    return None
