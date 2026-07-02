"""OCR engine for scanned loan-document pages.

Uses PaddleOCR with Hindi + English coverage for Indian loan files.
Models are initialised once at import time and reused across pages.

Public API
----------
run_ocr_on_page(image_path)
    Measure blur (advisory), run OCR, and return merged Hindi/English text.
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any, TypedDict

from services.config import get_float, get_int

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
PADDLE_CACHE_DIR = Path(os.getenv("PADDLE_PDX_CACHE_HOME", _PROJECT_ROOT / "data/paddlex_cache"))


def _configure_paddle_runtime() -> None:
    """Apply Paddle flags before the native runtime is imported."""
    os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(PADDLE_CACHE_DIR))
    os.environ.setdefault("FLAGS_use_mkldnn", "0")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


_configure_paddle_runtime()


def _dual_lang_enabled() -> bool:
    return os.getenv("PADDLE_OCR_DUAL_LANG", "false").lower() in {"1", "true", "yes", "on"}


def _configured_ocr_langs() -> list[str]:
    if _dual_lang_enabled():
        return ["hi", "en"]
    primary = (os.getenv("PADDLE_OCR_LANG") or "hi").strip().lower()
    return [primary]


def _create_paddle_ocr(lang: str) -> Any:
    """Create a PaddleOCR instance with CPU-safe defaults."""
    from paddleocr import PaddleOCR as _PaddleOCR

    base_kwargs = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "lang": lang,
    }
    try:
        return _PaddleOCR(**base_kwargs, enable_mkldnn=False)
    except TypeError:
        return _PaddleOCR(**base_kwargs)


def _load_ocr_models() -> dict[str, Any | None]:
    models: dict[str, Any | None] = {}
    for lang in _configured_ocr_langs():
        try:
            models[lang] = _create_paddle_ocr(lang)
            logger.info("Loaded PaddleOCR model for lang=%s", lang)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PaddleOCR could not load lang=%s (%s)", lang, exc)
            models[lang] = None
    return models


ocr_models: dict[str, Any | None] | None = None
ocr_model: Any | None = None


def get_ocr_models() -> dict[str, Any | None]:
    """Load PaddleOCR models on first use instead of at module import time."""
    global ocr_models, ocr_model
    if ocr_models is None:
        ocr_models = _load_ocr_models()
        ocr_model = ocr_models.get("hi") or ocr_models.get("en") or next(
            (model for model in ocr_models.values() if model is not None),
            None,
        )
    return ocr_models


class _OcrResult(TypedDict, total=False):
    is_readable: bool
    is_blurry: bool
    ocr_text: str
    confidence: float
    blur_score: float
    ocr_languages: list[str]
    error: str


def run_ocr_on_page(image_path: str | Path) -> _OcrResult:
    """Run OCR on a scanned page image.

    Blur is measured for quality warnings but never blocks OCR.
    When dual-language mode is enabled, Hindi and English models both run
    and their outputs are merged for downstream classification.
    """
    from services.preprocessing import check_readability

    readability = check_readability(image_path)
    is_blurry = not readability["is_readable"]
    blur_score = readability["blur_score"]

    active_models = [(lang, model) for lang, model in get_ocr_models().items() if model is not None]
    if not active_models:
        return {
            "is_readable": False,
            "is_blurry": is_blurry,
            "ocr_text": "",
            "confidence": 0.0,
            "blur_score": blur_score,
            "ocr_languages": [],
            "error": (
                "PaddleOCR models are not loaded. "
                "Install paddlepaddle and paddleocr to enable OCR."
            ),
        }

    merged_texts: list[str] = []
    merged_scores: list[float] = []
    languages_used: list[str] = []
    errors: list[str] = []
    early_exit_confidence = _early_exit_confidence()
    early_exit_min_chars = _early_exit_min_chars()

    for lang, model in active_models:
        try:
            started_at = time.monotonic()
            result = _run_paddle_ocr_with_timeout(model, image_path)
            elapsed = time.monotonic() - started_at
            soft_timeout = _soft_timeout_seconds()
            if elapsed > soft_timeout:
                logger.warning(
                    "OCR exceeded soft timeout for %s (%s): %.1fs > %ss",
                    image_path,
                    lang,
                    elapsed,
                    soft_timeout,
                )
            text, confidence = _extract_ocr_text_and_confidence(result)
            languages_used.append(lang)
            if text.strip():
                merged_texts.append(text.strip())
            if confidence > 0:
                merged_scores.append(confidence)
            if confidence >= early_exit_confidence and len(text.strip()) >= early_exit_min_chars:
                # High-confidence extraction from the primary language model is enough.
                break
        except Exception as exc:  # noqa: BLE001
            logger.exception("OCR failed for %s (%s)", image_path, lang)
            errors.append(f"{lang}: {exc}")

    ocr_text = _merge_ocr_texts(merged_texts)
    confidence = max(merged_scores) if merged_scores else 0.0

    if not ocr_text and errors:
        return {
            "is_readable": False,
            "is_blurry": is_blurry,
            "ocr_text": "",
            "confidence": 0.0,
            "blur_score": blur_score,
            "ocr_languages": languages_used,
            "error": "; ".join(errors),
        }

    return {
        "is_readable": bool(ocr_text.strip()),
        "is_blurry": is_blurry,
        "ocr_text": ocr_text,
        "confidence": confidence,
        "blur_score": blur_score,
        "ocr_languages": languages_used,
    }


def _merge_ocr_texts(texts: list[str]) -> str:
    """Merge OCR outputs from multiple language models without duplicate lines."""
    seen: set[str] = set()
    merged: list[str] = []
    for chunk in texts:
        for part in re.split(r"\n+", chunk):
            normalized = part.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                merged.append(normalized)
    return "\n".join(merged)


def _run_paddle_ocr(model: Any, image_path: str | Path) -> Any:
    """Run PaddleOCR 3.x ``predict`` or fall back to legacy ``ocr``."""
    from services.preprocessing import preprocess_image

    path = str(image_path)
    inference_kwargs = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }

    if hasattr(model, "predict"):
        try:
            return model.predict(path, **inference_kwargs)
        except TypeError:
            return model.predict(path)

    preprocessed = _prepare_for_paddle(preprocess_image(image_path))
    try:
        return model.ocr(preprocessed, **inference_kwargs)
    except TypeError:
        return model.ocr(preprocessed)


def _run_paddle_ocr_with_timeout(model: Any, image_path: str | Path) -> Any:
    hard_timeout = _hard_timeout_seconds()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dmef-ocr-page")
    future = executor.submit(_run_paddle_ocr, model, image_path)
    try:
        return future.result(timeout=hard_timeout)
    except TimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"OCR exceeded hard timeout of {hard_timeout}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _prepare_for_paddle(image: Any) -> Any:
    import cv2

    if image.ndim == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    return image


def _extract_ocr_text_and_confidence(result: Any) -> tuple[str, float]:
    if not result:
        return "", 0.0

    if isinstance(result, list):
        legacy_text, legacy_scores = _extract_legacy_lines(result)
        if legacy_text or legacy_scores:
            return " ".join(legacy_text), _mean_score(legacy_scores)

        new_text: list[str] = []
        new_scores: list[float] = []
        for page_result in result:
            page_text, page_scores = _extract_mapping_result(page_result)
            new_text.extend(page_text)
            new_scores.extend(page_scores)
        return " ".join(new_text), _mean_score(new_scores)

    text, scores = _extract_mapping_result(result)
    return " ".join(text), _mean_score(scores)


def _extract_legacy_lines(result: list[Any]) -> tuple[list[str], list[float]]:
    page_lines = result[0] if result and isinstance(result[0], list) else result
    lines: list[str] = []
    scores: list[float] = []
    for line in page_lines:
        if not isinstance(line, (list, tuple)) or len(line) < 2:
            continue
        text_score = line[1]
        if not isinstance(text_score, (list, tuple)) or len(text_score) < 2:
            continue
        lines.append(str(text_score[0]))
        scores.append(float(text_score[1]))
    return lines, scores


def _extract_mapping_result(result: Any) -> tuple[list[str], list[float]]:
    if not isinstance(result, dict) and hasattr(result, "json"):
        try:
            result = result.json
        except Exception:  # noqa: BLE001
            pass

    if not isinstance(result, dict):
        return [], []

    if "res" in result and isinstance(result["res"], dict):
        result = result["res"]

    rec_texts = result.get("rec_texts") or []
    rec_scores = result.get("rec_scores") or []

    lines = [str(text) for text in rec_texts if text]
    scores = [float(score) for score in rec_scores if score is not None]
    return lines, scores


def _mean_score(scores: list[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0


def _early_exit_confidence() -> float:
    return get_float("PADDLE_OCR_EARLY_EXIT_CONFIDENCE", 0.92, minimum=0.0, maximum=1.0)


def _early_exit_min_chars() -> int:
    return get_int("PADDLE_OCR_EARLY_EXIT_MIN_CHARS", 24, minimum=1)


def _soft_timeout_seconds() -> int:
    return get_int("OCR_SOFT_TIMEOUT_SECONDS", 30, minimum=1)


def _hard_timeout_seconds() -> int:
    return get_int("OCR_HARD_TIMEOUT_SECONDS", 90, minimum=1)
