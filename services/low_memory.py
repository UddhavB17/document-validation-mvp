"""Apply laptop-friendly defaults so the MVP fits in ~8GB RAM.

PP-StructureV3 + table models + broad Ollama workloads are the main crash
drivers on small MacBooks. When ``DMEF_LOW_MEMORY=true``, force the lighter OCR
path and disable optional LLM work by default. Explicit page-classifier
overrides remain allowed so a small local model can handle only Unknown and
low-OCR-confidence pages.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Only fill missing keys so an explicit .env override still wins.
_LOW_MEMORY_DEFAULTS = {
    "DMEF_CONFIG_PROFILE": "fast",
    "DMEF_PIPELINE_WORKERS": "1",
    "OCR_FORCE_FAST_PATH": "true",
    "PADDLE_STRUCTURE_USE_TABLE_RECOGNITION": "false",
    "PADDLE_STRUCTURE_USE_SEAL_RECOGNITION": "false",
    "PADDLE_STRUCTURE_USE_FORMULA_RECOGNITION": "false",
    "PADDLE_STRUCTURE_USE_CHART_RECOGNITION": "false",
    "PADDLE_STRUCTURE_USE_REGION_DETECTION": "false",
    "PADDLE_OCR_DUAL_LANG": "false",
    "PADDLE_OCR_DET_LIMIT_SIDE_LEN": "960",
    "DMEF_MAX_IMAGE_SIDE_PX": "1200",
    "DMEF_RENDER_SCALE": "0.85",
    # Keep OCR on every scanned page; digital pages still use free PDF text.
    "DMEF_FULL_SCAN_OCR": "true",
    "OCR_SOFT_TIMEOUT_SECONDS": "25",
    "OCR_HARD_TIMEOUT_SECONDS": "60",
    "OCR_FAST_PATH_MIN_CONFIDENCE": "0.70",
    "ENABLE_LLM_PAGE_CLASSIFIER": "false",
    "ENABLE_STRUCTURED_LLM_CLASSIFIER": "false",
    "ENABLE_LLM_SUMMARY": "false",
    "ENABLE_LLM_FIELD_VERIFIER": "false",
    "ENABLE_LLM_FIELD_ASSIGNMENT": "false",
    "LLM_PROVIDER": "none",
}


def low_memory_enabled() -> bool:
    return os.getenv("DMEF_LOW_MEMORY", "").strip().lower() in {"1", "true", "yes", "on"}


def ocr_force_fast_path() -> bool:
    if low_memory_enabled() and os.getenv("OCR_FORCE_FAST_PATH") is None:
        return True
    return os.getenv("OCR_FORCE_FAST_PATH", "").strip().lower() in {"1", "true", "yes", "on"}


# Always forced when low-memory is on — these are the crash drivers on 8GB laptops.
_LOW_MEMORY_FORCED = {
    "OCR_FORCE_FAST_PATH": "true",
    "PADDLE_STRUCTURE_USE_TABLE_RECOGNITION": "false",
    "PADDLE_OCR_DUAL_LANG": "false",
    "ENABLE_LLM_SUMMARY": "false",
    "ENABLE_LLM_FIELD_VERIFIER": "false",
    "ENABLE_LLM_FIELD_ASSIGNMENT": "false",
    "DMEF_PIPELINE_WORKERS": "1",
}


def apply_low_memory_defaults() -> None:
    """Populate lighter defaults after ``load_dotenv()`` when low-memory is on."""
    if not low_memory_enabled():
        return
    applied: list[str] = []
    for key, value in _LOW_MEMORY_DEFAULTS.items():
        if os.getenv(key) in (None, ""):
            os.environ[key] = value
            applied.append(key)
    forced: list[str] = []
    for key, value in _LOW_MEMORY_FORCED.items():
        if os.getenv(key) != value:
            os.environ[key] = value
            forced.append(key)
    logger.info(
        "DMEF_LOW_MEMORY enabled; defaults=%s forced=%s",
        applied or ["none"],
        forced or ["none"],
    )
