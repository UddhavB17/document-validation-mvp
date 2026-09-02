"""Google Cloud Vision OCR provider for scanned loan-document pages.

Supports two credential paths:
- ADC/service account via GOOGLE_APPLICATION_CREDENTIALS using google-cloud-vision.
- REST API key via GOOGLE_VISION_API_KEY for quick API-key experiments.
"""

from __future__ import annotations

import base64
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from services.config import get_int, get_setting


def google_vision_configured() -> bool:
    return bool(
        str(get_setting("google.vision.api_key", "") or "").strip()
        or os.getenv("GOOGLE_VISION_API_KEY")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    )


def run_google_vision_ocr_on_page(page_image: str | Path) -> dict[str, Any]:
    """Run Google Vision document OCR and return the legacy OCR dict shape."""
    path = Path(page_image)
    if not path.exists():
        return _error_result(path, f"Image file not found: {path}")

    auth_mode = _auth_mode()
    attempts = get_int("GOOGLE_VISION_MAX_ATTEMPTS", 3, minimum=1, maximum=5)
    for attempt in range(1, attempts + 1):
        try:
            if auth_mode == "api_key":
                payload = _call_rest_api_key(path)
            else:
                payload = _call_client_library(path)
            return _result_from_payload(path, payload, auth_mode=auth_mode)
        except Exception as exc:  # noqa: BLE001
            if attempt >= attempts or not _is_retryable_error(exc):
                return _error_result(
                    path, f"Google Vision OCR failed after {attempt} attempt(s): {exc}"
                )
            time.sleep(min(0.5 * (2 ** (attempt - 1)), 2.0))

    return _error_result(path, "Google Vision OCR failed without a response")


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    message = str(exc).casefold()
    return any(
        marker in message
        for marker in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "connection reset",
            "deadline exceeded",
            "dns",
            "hostname lookup",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "unavailable",
        )
    )


def _auth_mode() -> str:
    requested = (
        str(get_setting("google.vision.auth", os.getenv("GOOGLE_VISION_AUTH") or "auto") or "auto")
        .strip()
        .lower()
    )
    if requested in {"api_key", "apikey", "key"}:
        return "api_key"
    if requested in {"adc", "service_account", "client"}:
        return "adc"
    if _api_key():
        return "api_key"
    return "adc"


def _api_key() -> str:
    # Settings DB wins; the environment variable remains a fallback for
    # deployments configured outside the settings table.
    return str(
        get_setting("google.vision.api_key", "") or os.getenv("GOOGLE_VISION_API_KEY") or ""
    ).strip()


def _feature_type() -> str:
    raw = str(
        get_setting(
            "google.vision.feature", os.getenv("GOOGLE_VISION_FEATURE") or "DOCUMENT_TEXT_DETECTION"
        )
        or ""
    )
    normalized = raw.strip().upper()
    if normalized not in {"DOCUMENT_TEXT_DETECTION", "TEXT_DETECTION"}:
        return "DOCUMENT_TEXT_DETECTION"
    return normalized


def _timeout_seconds() -> int:
    return get_int("GOOGLE_VISION_TIMEOUT_SECONDS", 60, minimum=1, maximum=300)


def _call_rest_api_key(path: Path) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise RuntimeError("GOOGLE_VISION_API_KEY is not configured")
    endpoint = str(
        get_setting(
            "google.vision.rest_url",
            os.getenv("GOOGLE_VISION_REST_URL")
            or "https://vision.googleapis.com/v1/images:annotate",
        )
        or "https://vision.googleapis.com/v1/images:annotate"
    ).rstrip("?")
    content = base64.b64encode(path.read_bytes()).decode("ascii")
    request_payload: dict[str, Any] = {
        "image": {"content": content},
        "features": [{"type": _feature_type()}],
    }
    if hints := _language_hints():
        request_payload["imageContext"] = {"languageHints": hints}
    response = requests.post(
        f"{endpoint}?key={key}",
        json={"requests": [request_payload]},
        timeout=_timeout_seconds(),
    )
    response.raise_for_status()
    body = response.json()
    responses = body.get("responses") if isinstance(body, dict) else None
    if not responses:
        raise RuntimeError("Google Vision response did not include OCR results")
    first = responses[0] or {}
    error = first.get("error") if isinstance(first, dict) else None
    if isinstance(error, dict) and error.get("message"):
        raise RuntimeError(str(error.get("message")))
    return first


def _call_client_library(path: Path) -> dict[str, Any]:
    try:
        from google.cloud import vision
    except ImportError as exc:  # pragma: no cover - exercised in deployment without dependency
        raise RuntimeError("Install google-cloud-vision to use GOOGLE_VISION_AUTH=adc") from exc

    client_options = None
    endpoint = str(
        os.getenv("GOOGLE_VISION_API_ENDPOINT")
        or get_setting("google.vision.api_endpoint", "")
        or ""
    ).strip()
    if endpoint:
        client_options = {"api_endpoint": endpoint}
    client = (
        vision.ImageAnnotatorClient(client_options=client_options)
        if client_options
        else vision.ImageAnnotatorClient()
    )
    image = vision.Image(content=path.read_bytes())
    hints = _language_hints()
    request_kwargs: dict[str, Any] = {
        "image": image,
        "timeout": _timeout_seconds(),
    }
    if hints:
        request_kwargs["image_context"] = vision.ImageContext(language_hints=hints)
    if _feature_type() == "TEXT_DETECTION":
        response = client.text_detection(**request_kwargs)
    else:
        response = client.document_text_detection(**request_kwargs)
    if getattr(response, "error", None) and response.error.message:
        raise RuntimeError(response.error.message)
    if hasattr(response, "_pb"):
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(response._pb, preserving_proto_field_name=False)
    return response


def _result_from_payload(path: Path, payload: Any, *, auth_mode: str) -> dict[str, Any]:
    mapping = payload if isinstance(payload, dict) else {}
    full_text = _full_text(mapping)
    annotations = mapping.get("textAnnotations") or mapping.get("text_annotations") or []
    boxes = _text_annotation_boxes(annotations)
    confidence = _average_confidence(mapping)
    width, height = _image_dimensions(path)
    char_count = len(full_text.strip())
    megapixels = (width * height) / 1_000_000 if width and height else 1.0
    detected_languages = _detected_languages(mapping)
    return {
        "ocr_text": full_text,
        "confidence": confidence if confidence > 0 else (0.9 if full_text.strip() else 0.0),
        "is_readable": bool(full_text.strip()),
        "ocr_languages": detected_languages or ["google_vision"],
        "ocr_language_hints": _language_hints(),
        "ocr_pipeline": "Google Vision API",
        "ocr_provider": "google_vision",
        "google_vision_auth": auth_mode,
        "bounding_boxes": boxes,
        "char_count": char_count,
        "word_count": len(re.findall(r"\w+", full_text)),
        "line_count": len([line for line in full_text.splitlines() if line.strip()]),
        "image_width": width,
        "image_height": height,
        "text_density": round(char_count / max(megapixels, 0.1), 2),
        "header_text": _first_line(full_text),
        "layout_blocks": _layout_blocks(mapping),
        "tables": [],
        "seals": [],
        "formulas": [],
        "structure_json": [mapping] if mapping else [],
    }


def _full_text(mapping: dict[str, Any]) -> str:
    full = mapping.get("fullTextAnnotation") or mapping.get("full_text_annotation") or {}
    if isinstance(full, dict) and full.get("text"):
        return str(full.get("text") or "")
    annotations = mapping.get("textAnnotations") or mapping.get("text_annotations") or []
    if annotations and isinstance(annotations[0], dict):
        return str(annotations[0].get("description") or "")
    return ""


def _language_hints() -> list[str]:
    """Return optional BCP-47 hints; empty means API auto-detection.

    DOCUMENT_TEXT_DETECTION can auto-detect multiple languages. Deployments may
    still provide a small case-specific list (for example ``en,gu``) when scans
    are noisy. A global all-India list is intentionally not forced.
    """
    raw = str(
        get_setting(
            "google.vision.language_hints",
            os.getenv("GOOGLE_VISION_LANGUAGE_HINTS") or "",
        )
        or ""
    )
    return list(dict.fromkeys(part.strip() for part in raw.split(",") if part.strip()))[:10]


def _detected_languages(mapping: dict[str, Any]) -> list[str]:
    full = mapping.get("fullTextAnnotation") or mapping.get("full_text_annotation") or {}
    found: list[tuple[str, float]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            detected = value.get("detectedLanguages") or value.get("detected_languages")
            if isinstance(detected, list):
                for item in detected:
                    if not isinstance(item, dict):
                        continue
                    code = str(item.get("languageCode") or item.get("language_code") or "").strip()
                    try:
                        confidence = float(item.get("confidence") or 0.0)
                    except (TypeError, ValueError):
                        confidence = 0.0
                    if code:
                        found.append((code, confidence))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(full)
    best: dict[str, float] = {}
    for code, confidence in found:
        best[code] = max(confidence, best.get(code, 0.0))
    return [
        code for code, _confidence in sorted(best.items(), key=lambda item: (-item[1], item[0]))
    ]


def _text_annotation_boxes(annotations: Any) -> list[dict[str, Any]]:
    boxes: list[dict[str, Any]] = []
    if not isinstance(annotations, list):
        return boxes
    for annotation in annotations[1:] if len(annotations) > 1 else annotations:
        if not isinstance(annotation, dict):
            continue
        description = str(annotation.get("description") or "").strip()
        if not description:
            continue
        poly = annotation.get("boundingPoly") or annotation.get("bounding_poly") or {}
        vertices = poly.get("vertices") if isinstance(poly, dict) else []
        boxes.append(
            {
                "text": description,
                "confidence": annotation.get("confidence"),
                "bbox": [
                    {"x": int(vertex.get("x") or 0), "y": int(vertex.get("y") or 0)}
                    for vertex in vertices or []
                    if isinstance(vertex, dict)
                ],
            }
        )
    return boxes


def _layout_blocks(mapping: dict[str, Any]) -> list[dict[str, Any]]:
    full = mapping.get("fullTextAnnotation") or mapping.get("full_text_annotation") or {}
    pages = full.get("pages") if isinstance(full, dict) else []
    blocks: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages or []):
        if not isinstance(page, dict):
            continue
        for block in page.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            text = _block_text(block)
            blocks.append(
                {
                    "type": str(block.get("blockType") or block.get("block_type") or "TEXT"),
                    "text": text,
                    "page_index": page_index,
                    "confidence": block.get("confidence"),
                    "bounding_box": block.get("boundingBox") or block.get("bounding_box") or {},
                }
            )
    return blocks


def _block_text(block: dict[str, Any]) -> str:
    words: list[str] = []
    for paragraph in block.get("paragraphs") or []:
        if not isinstance(paragraph, dict):
            continue
        for word in paragraph.get("words") or []:
            symbols = word.get("symbols") if isinstance(word, dict) else []
            token = "".join(
                str(symbol.get("text") or "")
                for symbol in symbols or []
                if isinstance(symbol, dict)
            )
            if token:
                words.append(token)
    return " ".join(words)


def _average_confidence(mapping: dict[str, Any]) -> float:
    values: list[float] = []
    full = mapping.get("fullTextAnnotation") or mapping.get("full_text_annotation") or {}
    pages = full.get("pages") if isinstance(full, dict) else []
    for page in pages or []:
        _collect_confidence(page, values)
    if values:
        return round(sum(values) / len(values), 4)
    return 0.0


def _collect_confidence(value: Any, values: list[float]) -> None:
    if isinstance(value, dict):
        confidence = value.get("confidence")
        if confidence is not None:
            try:
                values.append(float(confidence))
            except (TypeError, ValueError):
                pass
        for key, item in value.items():
            # Language-detection confidence describes the language guess, not
            # OCR recognition quality, and must not dilute the page score.
            if key in {"detectedLanguages", "detected_languages"}:
                continue
            _collect_confidence(item, values)
    elif isinstance(value, list):
        for item in value:
            _collect_confidence(item, values)


def _first_line(text: str) -> str:
    for line in str(text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _image_dimensions(page_image: str | Path) -> tuple[int, int]:
    try:
        import cv2

        image = cv2.imread(str(page_image))
        if image is None:
            return 0, 0
        height, width = image.shape[:2]
        return int(width), int(height)
    except Exception:  # noqa: BLE001
        return 0, 0


def _error_result(path: Path, message: str) -> dict[str, Any]:
    width, height = _image_dimensions(path)
    return {
        "ocr_text": "",
        "confidence": 0.0,
        "is_readable": False,
        "ocr_languages": ["google_vision"],
        "ocr_pipeline": "Google Vision API",
        "ocr_provider": "google_vision",
        "bounding_boxes": [],
        "char_count": 0,
        "word_count": 0,
        "line_count": 0,
        "image_width": width,
        "image_height": height,
        "text_density": 0.0,
        "header_text": "",
        "layout_blocks": [],
        "tables": [],
        "seals": [],
        "formulas": [],
        "structure_json": [],
        "error": message,
    }
