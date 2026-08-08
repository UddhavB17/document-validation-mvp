"""Structured OCR engine for scanned loan-document pages.

Uses PP-StructureV3 with a configurable script/language model for Indian loan files.
Models are initialised lazily and reused across pages. In addition to the
backwards-compatible flattened OCR text, each result includes reading-order
layout blocks and the JSON-safe PP-StructureV3 response.

Public API
----------
run_ocr_on_page(image_path)
    Measure blur (advisory), run OCR, and return merged observed text.
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any, TypedDict

from services.config import get_bool, get_float, get_int
from services.offline_ocr_languages import normalize_paddle_language, recognition_model_for_language

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
    primary = normalize_paddle_language(os.getenv("PADDLE_OCR_LANG"))
    return [primary]


def _create_paddle_structure(lang: str) -> Any:
    """Create a PP-StructureV3 instance with CPU-safe OCR defaults."""
    from paddleocr import PPStructureV3

    det_limit = get_int("PADDLE_OCR_DET_LIMIT_SIDE_LEN", 1280, minimum=640, maximum=2400)
    det_model = os.getenv("PADDLE_OCR_DET_MODEL", "PP-OCRv5_mobile_det").strip() or "PP-OCRv5_mobile_det"
    rec_model = recognition_model_for_language(lang)

    base_kwargs = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "lang": lang,
        "text_detection_model_name": det_model,
        "text_det_limit_side_len": det_limit,
        "use_table_recognition": get_bool("PADDLE_STRUCTURE_USE_TABLE_RECOGNITION", True),
        "use_seal_recognition": get_bool("PADDLE_STRUCTURE_USE_SEAL_RECOGNITION", False),
        "use_formula_recognition": get_bool("PADDLE_STRUCTURE_USE_FORMULA_RECOGNITION", False),
        "use_chart_recognition": get_bool("PADDLE_STRUCTURE_USE_CHART_RECOGNITION", False),
        "use_region_detection": get_bool("PADDLE_STRUCTURE_USE_REGION_DETECTION", False),
    }
    if rec_model:
        base_kwargs["text_recognition_model_name"] = rec_model
    try:
        return PPStructureV3(**base_kwargs, enable_mkldnn=False)
    except TypeError:
        return PPStructureV3(**base_kwargs)


def _load_structure_models() -> dict[str, Any | None]:
    models: dict[str, Any | None] = {}
    for lang in _configured_ocr_langs():
        try:
            models[lang] = _create_paddle_structure(lang)
            logger.info("Loaded PP-StructureV3 model for lang=%s", lang)
        except Exception as exc:  # noqa: BLE001
            logger.warning("PP-StructureV3 could not load lang=%s (%s)", lang, exc)
            models[lang] = None
    return models


structure_models: dict[str, Any | None] | None = None
structure_model: Any | None = None


def get_structure_models() -> dict[str, Any | None]:
    """Load PP-StructureV3 models on first use instead of at import time."""
    global structure_models, structure_model
    if structure_models is None:
        structure_models = _load_structure_models()
        structure_model = structure_models.get("hi") or structure_models.get("en") or next(
            (model for model in structure_models.values() if model is not None),
            None,
        )
    return structure_models


class _OcrResult(TypedDict, total=False):
    is_readable: bool
    is_blurry: bool
    ocr_text: str
    confidence: float
    blur_score: float
    ocr_languages: list[str]
    char_count: int
    word_count: int
    line_count: int
    image_width: int
    image_height: int
    text_density: float
    ocr_pipeline: str
    header_text: str
    layout_blocks: list[dict[str, Any]]
    tables: list[dict[str, Any]]
    seals: list[dict[str, Any]]
    formulas: list[dict[str, Any]]
    structure_json: list[dict[str, Any]]
    error: str


def run_ocr_on_page(image_path: str | Path) -> _OcrResult:
    """Run OCR on a scanned page image.

    Blur is measured for quality warnings but never blocks OCR.
    When dual-language mode is enabled, Hindi and English structure models run
    until a sufficiently confident result is found. Their outputs are merged
    for downstream classification.
    """
    from services.image_limits import prepare_image_path_for_ocr
    from services.preprocessing import check_readability

    image_path = prepare_image_path_for_ocr(image_path)
    image_width, image_height = _image_dimensions(image_path)
    readability = check_readability(image_path)
    is_blurry = not readability["is_readable"]
    blur_score = readability["blur_score"]

    active_models = [(lang, model) for lang, model in get_structure_models().items() if model is not None]
    if not active_models:
        return {
            "is_readable": False,
            "is_blurry": is_blurry,
            "ocr_text": "",
            "confidence": 0.0,
            "blur_score": blur_score,
            "ocr_languages": [],
            "char_count": 0,
            "word_count": 0,
            "line_count": 0,
            "image_width": image_width,
            "image_height": image_height,
            "text_density": 0.0,
            **_empty_structure_metadata(),
            "error": (
                "PP-StructureV3 models are not loaded. "
                "Install paddlepaddle and paddleocr to enable OCR."
            ),
        }

    merged_texts: list[str] = []
    merged_scores: list[float] = []
    languages_used: list[str] = []
    errors: list[str] = []
    structure_results: list[dict[str, Any]] = []
    early_exit_confidence = _early_exit_confidence()
    early_exit_min_chars = _early_exit_min_chars()

    for lang, model in active_models:
        try:
            started_at = time.monotonic()
            result = _run_paddle_structure_with_timeout(model, image_path)
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
            structure_results.append(_normalize_structure_result(result))
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
    text_stats = _ocr_text_stats(ocr_text, image_width, image_height)
    structure_metadata = _merge_structure_metadata(structure_results)

    if not ocr_text and errors:
        return {
            "is_readable": False,
            "is_blurry": is_blurry,
            "ocr_text": "",
            "confidence": 0.0,
            "blur_score": blur_score,
            "ocr_languages": languages_used,
            **text_stats,
            **structure_metadata,
            "error": "; ".join(errors),
        }

    return {
        "is_readable": bool(ocr_text.strip()),
        "is_blurry": is_blurry,
        "ocr_text": ocr_text,
        "confidence": confidence,
        "blur_score": blur_score,
        "ocr_languages": languages_used,
        **text_stats,
        **structure_metadata,
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


def _run_paddle_structure(model: Any, image_path: str | Path) -> list[Any]:
    """Run PP-StructureV3 and materialize its result generator."""
    inference_kwargs = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "use_table_recognition": get_bool("PADDLE_STRUCTURE_USE_TABLE_RECOGNITION", True),
        "use_seal_recognition": get_bool("PADDLE_STRUCTURE_USE_SEAL_RECOGNITION", False),
        "use_formula_recognition": get_bool("PADDLE_STRUCTURE_USE_FORMULA_RECOGNITION", False),
        "use_chart_recognition": get_bool("PADDLE_STRUCTURE_USE_CHART_RECOGNITION", False),
        "use_region_detection": get_bool("PADDLE_STRUCTURE_USE_REGION_DETECTION", False),
    }
    try:
        return list(model.predict(str(image_path), **inference_kwargs))
    except TypeError:
        return list(model.predict(str(image_path)))


def _run_paddle_structure_with_timeout(model: Any, image_path: str | Path) -> Any:
    hard_timeout = _hard_timeout_seconds()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dmef-structure-page")
    future = executor.submit(_run_paddle_structure, model, image_path)
    try:
        return future.result(timeout=hard_timeout)
    except TimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"PP-StructureV3 exceeded hard timeout of {hard_timeout}s") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _image_dimensions(image_path: str | Path) -> tuple[int, int]:
    try:
        import cv2

        image = cv2.imread(str(image_path))
        if image is None:
            return 0, 0
        height, width = image.shape[:2]
        return int(width), int(height)
    except Exception:  # noqa: BLE001
        return 0, 0


def _ocr_text_stats(text: str, image_width: int, image_height: int) -> dict[str, Any]:
    char_count = len((text or "").strip())
    word_count = len(re.findall(r"\w+", text or ""))
    line_count = len([line for line in (text or "").splitlines() if line.strip()])
    megapixels = (image_width * image_height) / 1_000_000 if image_width and image_height else 1.0
    return {
        "char_count": char_count,
        "word_count": word_count,
        "line_count": line_count,
        "image_width": image_width,
        "image_height": image_height,
        "text_density": round(char_count / max(megapixels, 0.1), 2),
    }


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
    result = _result_mapping(result)
    if not result:
        return [], []

    overall_ocr = result.get("overall_ocr_res")
    if isinstance(overall_ocr, dict):
        result = overall_ocr

    rec_texts = result.get("rec_texts") or []
    rec_scores = result.get("rec_scores") or []

    lines = [str(text) for text in rec_texts if text]
    scores = [float(score) for score in rec_scores if score is not None]
    return lines, scores


def _result_mapping(result: Any) -> dict[str, Any]:
    """Return the unwrapped mapping from a Paddle result object."""
    if not isinstance(result, dict) and hasattr(result, "json"):
        try:
            result = result.json
            if callable(result):
                result = result()
        except Exception:  # noqa: BLE001
            return {}
    if not isinstance(result, dict):
        return {}
    if "res" in result and isinstance(result["res"], dict):
        return result["res"]
    return result


def _empty_structure_metadata() -> dict[str, Any]:
    return {
        "ocr_pipeline": "PP-StructureV3",
        "header_text": "",
        "layout_blocks": [],
        "tables": [],
        "seals": [],
        "formulas": [],
        "structure_json": [],
    }


def _normalize_structure_result(result: Any) -> dict[str, Any]:
    """Normalize PP-StructureV3 output without retaining image tensors."""
    pages = result if isinstance(result, list) else [result]
    metadata = _empty_structure_metadata()
    header_candidates: list[str] = []

    for page_result in pages:
        page = _result_mapping(page_result)
        if not page:
            continue
        safe_page = _compact_native_page(page)
        if isinstance(safe_page, dict):
            metadata["structure_json"].append(safe_page)

        raw_blocks = page.get("parsing_res_list") or []
        for position, raw_block in enumerate(raw_blocks):
            if not isinstance(raw_block, dict):
                continue
            block_type = str(raw_block.get("block_label") or "text")
            text = str(raw_block.get("block_content") or "").strip()
            raw_bbox = raw_block.get("block_bbox")
            raw_order = raw_block.get("index")
            block = {
                "type": block_type,
                "text": text,
                "bbox": _json_safe(raw_bbox if raw_bbox is not None else []),
                "order": int(raw_order if raw_order is not None else position),
                "sub_label": str(raw_block.get("sub_label") or ""),
                "paragraph_start": bool(raw_block.get("seg_start_flag", False)),
                "paragraph_end": bool(raw_block.get("seg_end_flag", False)),
            }
            metadata["layout_blocks"].append(block)
            label = f"{block_type} {block['sub_label']}".lower()
            if text and any(token in label for token in ("title", "header")):
                header_candidates.append(text)

        metadata["tables"].extend(_safe_mapping_list(page.get("table_res_list")))
        metadata["seals"].extend(_safe_mapping_list(page.get("seal_res_list")))
        metadata["formulas"].extend(_safe_mapping_list(page.get("formula_res_list")))

    metadata["layout_blocks"].sort(key=lambda block: int(block.get("order", 0)))
    if not header_candidates:
        header_candidates = [
            str(block.get("text") or "")
            for block in metadata["layout_blocks"][:8]
            if block.get("text") and block.get("type") != "table"
        ]
    metadata["header_text"] = "\n".join(_deduplicate_strings(header_candidates))
    return metadata


def _merge_structure_metadata(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return _empty_structure_metadata()

    merged = _empty_structure_metadata()
    header_texts: list[str] = []
    for result in results:
        header_texts.extend(str(result.get("header_text") or "").splitlines())
        merged["layout_blocks"].extend(result.get("layout_blocks") or [])
        merged["tables"].extend(result.get("tables") or [])
        merged["seals"].extend(result.get("seals") or [])
        merged["formulas"].extend(result.get("formulas") or [])
        merged["structure_json"].extend(result.get("structure_json") or [])

    merged["header_text"] = "\n".join(_deduplicate_strings(header_texts))
    merged["layout_blocks"] = _deduplicate_mappings(merged["layout_blocks"], ("type", "text", "bbox"))
    merged["tables"] = _deduplicate_mappings(merged["tables"])
    merged["seals"] = _deduplicate_mappings(merged["seals"])
    merged["formulas"] = _deduplicate_mappings(merged["formulas"])
    return merged


def _safe_mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    safe_items: list[dict[str, Any]] = []
    for item in value:
        safe_item = _json_safe(item)
        if isinstance(safe_item, dict):
            safe_items.append(safe_item)
    return safe_items


_NATIVE_PAGE_KEYS = (
    "input_path",
    "page_index",
    "page_count",
    "width",
    "height",
    "overall_ocr_res",
    "parsing_res_list",
    "table_res_list",
    "seal_res_list",
    "formula_res_list",
)

_BINARY_RESULT_KEYS = {
    "image",
    "img",
    "input_image",
    "input_img",
    "output_image",
    "output_img",
    "visualization",
    "visualization_image",
    "vis_img",
    "heatmap",
    "feature_map",
    "mask",
}


def _compact_native_page(page: dict[str, Any]) -> dict[str, Any]:
    """Keep useful native OCR fields while excluding large model artifacts.

    PP-StructureV3 includes full image arrays under ``doc_preprocessor_res``
    and related result objects. Converting those arrays to JSON can add tens of
    megabytes per page and keeps that memory alive for the entire document.
    Normalized layout/table fields are persisted separately, so the compact
    native representation only needs the small, review-relevant fields below.
    """
    return {
        key: _json_safe(page[key])
        for key in _NATIVE_PAGE_KEYS
        if key in page
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in value.items()
            if not _is_binary_result_key(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except Exception:  # noqa: BLE001
            pass
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_binary_result_key(key: str) -> bool:
    normalized = key.strip().lower()
    return (
        normalized in _BINARY_RESULT_KEYS
        or normalized.endswith("_image")
        or normalized.endswith("_img")
    )


def _deduplicate_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduplicated: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduplicated.append(normalized)
    return deduplicated


def _deduplicate_mappings(
    values: list[dict[str, Any]],
    fields: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduplicated: list[dict[str, Any]] = []
    for value in values:
        identity_value: Any = value if fields is None else [value.get(field) for field in fields]
        identity = repr(identity_value)
        if identity not in seen:
            seen.add(identity)
            deduplicated.append(value)
    return deduplicated


def _mean_score(scores: list[float]) -> float:
    return sum(scores) / len(scores) if scores else 0.0


def _early_exit_confidence() -> float:
    return get_float("PADDLE_OCR_EARLY_EXIT_CONFIDENCE", 0.92, minimum=0.0, maximum=1.0)


def _early_exit_min_chars() -> int:
    return get_int("PADDLE_OCR_EARLY_EXIT_MIN_CHARS", 24, minimum=1)


def _soft_timeout_seconds() -> int:
    return get_int("OCR_SOFT_TIMEOUT_SECONDS", 30, minimum=1)


def _hard_timeout_seconds() -> int:
    return get_int("OCR_HARD_TIMEOUT_SECONDS", 100, minimum=1)
