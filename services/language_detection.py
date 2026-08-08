"""Script-first language evidence for multilingual Indian loan documents.

OCR observes characters, not the spoken language that produced them.  That
distinction matters for Devanagari in particular: Hindi, Haryanvi, Bhojpuri,
Maithili, Magahi, Marathi, Nepali, and several other languages can all use the
same script.  This module therefore reports scripts as facts and languages only
as candidates unless another source explicitly identifies the language.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
import re
import unicodedata


_SCRIPT_RANGES: tuple[tuple[str, int, int], ...] = (
    ("latin", 0x0041, 0x024F),
    ("arabic", 0x0600, 0x06FF),
    ("arabic", 0x0750, 0x077F),
    ("devanagari", 0x0900, 0x097F),
    ("bengali", 0x0980, 0x09FF),
    ("gurmukhi", 0x0A00, 0x0A7F),
    ("gujarati", 0x0A80, 0x0AFF),
    ("odia", 0x0B00, 0x0B7F),
    ("tamil", 0x0B80, 0x0BFF),
    ("telugu", 0x0C00, 0x0C7F),
    ("kannada", 0x0C80, 0x0CFF),
    ("malayalam", 0x0D00, 0x0D7F),
    ("ol_chiki", 0x1C50, 0x1C7F),
    ("devanagari", 0xA8E0, 0xA8FF),
    ("meetei_mayek", 0xABC0, 0xABFF),
    ("tirhuta", 0x11480, 0x114DF),
)

# These are intentionally candidates, not detections.  The list focuses on
# languages likely to appear in Indian lending documents and can be extended
# without changing the script detector or validation rules.
_SCRIPT_LANGUAGE_CANDIDATES: dict[str, tuple[tuple[str, str], ...]] = {
    "devanagari": (
        ("hi", "Hindi"),
        ("bgc", "Haryanvi"),
        ("bho", "Bhojpuri"),
        ("mai", "Maithili"),
        ("mag", "Magahi"),
        ("bh", "Bihari language group"),
        ("anp", "Angika"),
        ("mr", "Marathi"),
        ("ne", "Nepali"),
        ("sa", "Sanskrit"),
        ("kok", "Konkani"),
    ),
    "bengali": (("bn", "Bengali"), ("as", "Assamese")),
    "gurmukhi": (("pa", "Punjabi"),),
    "gujarati": (("gu", "Gujarati"),),
    "odia": (("or", "Odia"),),
    "tamil": (("ta", "Tamil"),),
    "telugu": (("te", "Telugu"),),
    "kannada": (("kn", "Kannada"), ("kok", "Konkani")),
    "malayalam": (("ml", "Malayalam"),),
    "arabic": (("ur", "Urdu"), ("ks", "Kashmiri"), ("sd", "Sindhi")),
    "ol_chiki": (("sat", "Santali"),),
    "meetei_mayek": (("mni", "Manipuri (Meitei)"),),
    "tirhuta": (("mai", "Maithili"),),
}

_LANGUAGE_ALIASES: dict[str, str] = {
    "english": "en",
    "angrezi": "en",
    "अंग्रेजी": "en",
    "अंग्रेज़ी": "en",
    "hindi": "hi",
    "हिंदी": "hi",
    "हिन्दी": "hi",
    "haryanvi": "bgc",
    "hariyanvi": "bgc",
    "हरियाणवी": "bgc",
    "bhojpuri": "bho",
    "भोजपुरी": "bho",
    "maithili": "mai",
    "मैथिली": "mai",
    "magahi": "mag",
    "मगही": "mag",
    "bihari": "bh",
    "बिहारी": "bh",
    "angika": "anp",
    "अंगिका": "anp",
    "marathi": "mr",
    "मराठी": "mr",
    "nepali": "ne",
    "नेपाली": "ne",
    "sanskrit": "sa",
    "संस्कृत": "sa",
    "punjabi": "pa",
    "panjabi": "pa",
    "ਪੰਜਾਬੀ": "pa",
    "gujarati": "gu",
    "ગુજરાતી": "gu",
    "bengali": "bn",
    "bangla": "bn",
    "বাংলা": "bn",
    "assamese": "as",
    "odia": "or",
    "oriya": "or",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",
    "urdu": "ur",
    "اردو": "ur",
    "kashmiri": "ks",
    "sindhi": "sd",
    "santali": "sat",
    "manipuri": "mni",
    "meitei": "mni",
    "konkani": "kok",
}

_KNOWN_LANGUAGE_CODES = {
    code for candidates in _SCRIPT_LANGUAGE_CANDIDATES.values() for code, _name in candidates
} | {"en"}


def analyze_text_languages(text: Any, *, minimum_characters: int = 3) -> dict[str, Any]:
    """Return script observations and possible languages for the observed text.

    ``language_candidates`` must not be interpreted as detected languages.  A
    provider response, a printed language declaration, template metadata, or a
    separate language-identification model is required to resolve them.
    """
    counts: Counter[str] = Counter()
    for character in unicodedata.normalize("NFKC", str(text or "")):
        if not _is_text_character(character):
            continue
        script = _script_for_character(character)
        if script:
            counts[script] += 1

    scripts = [
        script
        for script, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if count >= minimum_characters
    ]
    candidates = [
        {"code": code, "name": name, "script": script}
        for script in scripts
        for code, name in _SCRIPT_LANGUAGE_CANDIDATES.get(script, ())
    ]

    return {
        "scripts": scripts,
        "script_counts": {script: counts[script] for script in scripts},
        "language_candidates": candidates,
        "language_evidence": "script_only" if scripts else "no_text",
        "multiscript": len(scripts) >= 2,
    }


def normalize_language_code(value: Any) -> str | None:
    """Normalize a declared/provider language name or code when recognized."""
    text = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    if not text:
        return None
    compact = re.sub(r"[\s_.]+", " ", text).strip()
    if compact in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[compact]
    code = re.split(r"[-_]", compact, maxsplit=1)[0]
    # PaddleOCR calls Magahi ``mah``; use its standard language code internally.
    if code == "mah":
        return "mag"
    return code if code in _KNOWN_LANGUAGE_CODES else None


def is_regional_language_other_than_hindi(value: Any) -> bool:
    """Return true only for a recognized language other than Hindi/English."""
    code = normalize_language_code(value)
    return bool(code and code not in {"en", "hi"})


def _script_for_character(character: str) -> str | None:
    codepoint = ord(character)
    for name, start, end in _SCRIPT_RANGES:
        if start <= codepoint <= end:
            return name
    return None


def _is_text_character(character: str) -> bool:
    category = unicodedata.category(character)
    return category.startswith("L") or category.startswith("M")
