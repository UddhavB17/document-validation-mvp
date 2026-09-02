"""Deterministic, registry-driven routing between plain and structured OCR."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from services.config import get_float, get_int, get_setting
from services.document_classifier import document_type_config
from services.low_memory import ocr_force_fast_path
from services.ocr_engine import run_ocr_on_page
from services.offline_ocr_languages import normalize_paddle_language, recognition_model_for_language

logger = logging.getLogger(__name__)

OCRRoute = Literal["fast", "structured", "google_vision"]
OCRProcessor = Callable[[str | Path], Any]


class OCRResult(BaseModel):
    """Unified result returned by either OCR route."""

    model_config = ConfigDict(extra="allow")

    text: str = ""
    structured_content: dict[str, Any] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    route_used: OCRRoute
    escalated: bool = False
    bounding_boxes: list[dict[str, Any]] = Field(default_factory=list)
    routing_rationale: str = ""
    requested_route: OCRRoute | None = None
    original_confidence: float | None = None
    processing_time_ms: int = Field(default=0, ge=0)
    char_count: int = Field(default=0, ge=0)
    word_count: int = Field(default=0, ge=0)
    line_count: int = Field(default=0, ge=0)
    image_width: int = Field(default=0, ge=0)
    image_height: int = Field(default=0, ge=0)
    text_density: float = Field(default=0.0, ge=0.0)
    error: str | None = None

    def to_legacy_dict(self) -> dict[str, Any]:
        """Expose the existing OCR dictionary contract during migration."""
        structure = self.structured_content or {}
        return {
            "ocr_text": self.text,
            "confidence": self.confidence,
            "is_readable": bool(self.text.strip()),
            "ocr_route": self.route_used,
            "ocr_escalated": self.escalated,
            "ocr_routing_rationale": self.routing_rationale,
            "ocr_original_confidence": self.original_confidence,
            "ocr_processing_time_ms": self.processing_time_ms,
            "bounding_boxes": self.bounding_boxes,
            "structured_content": self.structured_content,
            "char_count": self.char_count,
            "word_count": self.word_count,
            "line_count": self.line_count,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "text_density": self.text_density,
            "error": self.error,
            "ocr_pipeline": (
                "Google Vision API"
                if self.route_used == "google_vision"
                else "PP-StructureV3"
                if self.route_used == "structured"
                else "PaddleOCR"
            ),
            "header_text": structure.get("header_text", ""),
            "layout_blocks": structure.get("layout_regions", []),
            "tables": structure.get("tables", []),
            "seals": structure.get("seals", []),
            "formulas": structure.get("formulas", []),
            "structure_json": structure.get("native", []),
        }


class OCRRoutingDecision(BaseModel):
    route: OCRRoute
    rationale: str


class OCRRouter:
    """Route a classified page through plain OCR or PP-StructureV3."""

    def __init__(
        self,
        *,
        fast_processor: OCRProcessor | None = None,
        structured_processor: OCRProcessor | None = None,
        google_vision_processor: OCRProcessor | None = None,
        confidence_threshold: float | None = None,
        event_recorder: Callable[..., None] | None = None,
    ) -> None:
        self._fast_processor = fast_processor or run_fast_ocr_on_page
        self._structured_processor = structured_processor or run_ocr_on_page
        self._google_vision_processor = google_vision_processor or _run_google_vision_ocr_on_page
        self._confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else get_float("OCR_FAST_PATH_MIN_CONFIDENCE", 0.85, minimum=0.0, maximum=1.0)
        )
        self._event_recorder = event_recorder or _record_ocr_route_event

    def decide_route(
        self,
        doc_type: str | dict[str, Any],
        *,
        inherited_route: OCRRoute | None = None,
    ) -> OCRRoutingDecision:
        """Return a deterministic config-based route and its rationale."""
        provider = ocr_provider()
        if provider == "google_vision":
            return OCRRoutingDecision(
                route="google_vision",
                rationale="OCR_PROVIDER=google_vision: all OCR is offloaded to Google Vision API",
            )
        if ocr_force_fast_path():
            return OCRRoutingDecision(
                route="fast",
                rationale="OCR_FORCE_FAST_PATH/DMEF_LOW_MEMORY: skip PP-StructureV3",
            )
        if inherited_route is not None:
            return OCRRoutingDecision(
                route=inherited_route,
                rationale=f"inherited {inherited_route} route from parent document",
            )

        metadata = doc_type if isinstance(doc_type, dict) else {}
        document_type = str(
            metadata.get("document_type")
            or metadata.get("type")
            or (doc_type if isinstance(doc_type, str) else "None")
        )
        configured = document_type_config(document_type)
        has_tabular_data = bool(metadata.get("has_tabular_data", configured.has_tabular_data))
        multi_column = bool(metadata.get("multi_column", configured.multi_column))
        configured_route = metadata.get("ocr_route", configured.ocr_route)
        if configured_route not in {"fast", "structured"}:
            configured_route = "structured"
        if has_tabular_data:
            return OCRRoutingDecision(
                route="structured",
                rationale=f"{document_type} is configured with has_tabular_data=true",
            )
        if multi_column:
            return OCRRoutingDecision(
                route="structured",
                rationale=f"{document_type} is configured with multi_column=true",
            )
        return OCRRoutingDecision(
            route=configured_route,
            rationale=f"{document_type} registry ocr_route={configured_route}",
        )

    def process_page(
        self,
        page_image: str | Path,
        doc_type: str | dict[str, Any],
        page_num: int,
        *,
        doc_id: str | int | None = None,
        inherited_route: OCRRoute | None = None,
        preliminary_fast_result: OCRResult | dict[str, Any] | None = None,
    ) -> OCRResult:
        """Process one page without exposing the selected OCR engine to callers."""
        started_at = time.perf_counter()
        decision = self.decide_route(doc_type, inherited_route=inherited_route)
        document_type = _document_type_name(doc_type)

        if decision.route == "google_vision":
            if _result_route(preliminary_fast_result) == "google_vision":
                result = _coerce_google_vision_result(preliminary_fast_result)
            else:
                result = _coerce_google_vision_result(self._google_vision_processor(page_image))
            result.requested_route = "google_vision"
            result.routing_rationale = (
                f"{decision.rationale}; reused classification OCR result"
                if _result_route(preliminary_fast_result) == "google_vision"
                else decision.rationale
            )
        elif decision.route == "structured":
            result = _coerce_structured_result(self._structured_processor(page_image))
            result.requested_route = "structured"
            result.routing_rationale = decision.rationale
        else:
            fast_result = (
                _coerce_fast_result(preliminary_fast_result)
                if preliminary_fast_result is not None
                else _coerce_fast_result(self._fast_processor(page_image))
            )
            fast_result.requested_route = "fast"
            fast_result.routing_rationale = decision.rationale
            if not ocr_force_fast_path() and fast_result.confidence < self._confidence_threshold:
                result = _coerce_structured_result(self._structured_processor(page_image))
                result.escalated = True
                result.requested_route = "fast"
                result.original_confidence = fast_result.confidence
                result.routing_rationale = (
                    f"{decision.rationale}; escalated because fast confidence "
                    f"{fast_result.confidence:.3f} < {self._confidence_threshold:.3f}"
                )
                self._record_event(
                    event_type="escalation",
                    doc_id=doc_id,
                    document_type=document_type,
                    page_num=page_num,
                    requested_route="fast",
                    route_used="structured",
                    reason="low_fast_path_confidence",
                    original_confidence=fast_result.confidence,
                    duration_ms=int((time.perf_counter() - started_at) * 1000),
                )
            else:
                result = fast_result
                if ocr_force_fast_path() and fast_result.confidence < self._confidence_threshold:
                    result.routing_rationale = (
                        f"{decision.rationale}; kept fast path despite confidence "
                        f"{fast_result.confidence:.3f} (structured escalation disabled)"
                    )

        routed_duration_ms = int((time.perf_counter() - started_at) * 1000)
        result.processing_time_ms = max(result.processing_time_ms, routed_duration_ms)
        self._record_event(
            event_type="processing",
            doc_id=doc_id,
            document_type=document_type,
            page_num=page_num,
            requested_route=decision.route,
            route_used=result.route_used,
            reason=result.routing_rationale,
            original_confidence=result.original_confidence,
            duration_ms=result.processing_time_ms,
        )
        return result

    def process_fast_for_classification(self, page_image: str | Path) -> OCRResult:
        """Produce classification text through the explicitly configured provider."""
        started_at = time.perf_counter()
        if ocr_provider() == "google_vision":
            result = _coerce_google_vision_result(self._google_vision_processor(page_image))
            result.requested_route = "google_vision"
            result.routing_rationale = "OCR_PROVIDER=google_vision: classification OCR offloaded"
            result.processing_time_ms = int((time.perf_counter() - started_at) * 1000)
            return result
        result = _coerce_fast_result(self._fast_processor(page_image))
        result.processing_time_ms = int((time.perf_counter() - started_at) * 1000)
        return result

    def _record_event(self, **event: Any) -> None:
        try:
            self._event_recorder(**event)
        except Exception:  # noqa: BLE001
            logger.exception("Could not persist OCR routing telemetry")


_fast_model: Any | None = None
_fast_model_lock = Lock()
_default_router: OCRRouter | None = None


def get_ocr_router() -> OCRRouter:
    global _default_router
    if _default_router is None:
        _default_router = OCRRouter()
    return _default_router


def ocr_provider() -> str:
    """Return Google Vision normally, or local only in explicit test mode."""
    # Local OCR is deliberately unavailable through ordinary production
    # settings.  It must be opted into explicitly for a developer smoke test.
    local_test_mode = os.getenv("DMEF_LOCAL_OCR_TEST_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if local_test_mode:
        raw = str(os.getenv("OCR_PROVIDER") or "local").strip().lower()
    else:
        raw = str(get_setting("ocr.provider", "google_vision") or "google_vision").strip().lower()
    normalized = raw.replace("-", "_")
    if normalized in {"google", "google_cloud", "google_vision", "vision"}:
        return "google_vision"
    if normalized == "auto":
        if local_test_mode and not _google_vision_configured():
            return "local"
        return "google_vision"
    return "local" if local_test_mode else "google_vision"


def _google_vision_configured() -> bool:
    try:
        from services.google_vision_ocr import google_vision_configured

        return google_vision_configured()
    except Exception:  # noqa: BLE001
        return False


def _run_google_vision_ocr_on_page(page_image: str | Path) -> dict[str, Any]:
    from services.google_vision_ocr import run_google_vision_ocr_on_page

    return run_google_vision_ocr_on_page(page_image)


def _get_fast_model() -> Any:
    global _fast_model
    if _fast_model is not None:
        return _fast_model
    with _fast_model_lock:
        if _fast_model is None:
            from paddleocr import PaddleOCR

            lang = normalize_paddle_language(os.getenv("PADDLE_OCR_LANG"))
            recognition_model = recognition_model_for_language(lang)
            kwargs = {
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
                "lang": lang,
                "text_detection_model_name": os.getenv(
                    "PADDLE_OCR_DET_MODEL", "PP-OCRv5_mobile_det"
                ),
                "text_det_limit_side_len": get_int(
                    "PADDLE_OCR_DET_LIMIT_SIDE_LEN", 1280, minimum=640, maximum=2400
                ),
            }
            if recognition_model:
                kwargs["text_recognition_model_name"] = recognition_model
            try:
                _fast_model = PaddleOCR(**kwargs, enable_mkldnn=False)
            except TypeError:
                _fast_model = PaddleOCR(**kwargs)
    return _fast_model


def run_fast_ocr_on_page(page_image: str | Path) -> OCRResult:
    """Run PaddleOCR text detection/recognition without layout or table models."""
    model = _get_fast_model()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dmef-fast-ocr")
    future = executor.submit(_predict_fast, model, page_image)
    try:
        raw_result = list(
            future.result(timeout=get_int("OCR_HARD_TIMEOUT_SECONDS", 180, minimum=1))
        )
    except TimeoutError as exc:
        future.cancel()
        raise TimeoutError("Fast OCR exceeded its hard timeout") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    texts: list[str] = []
    scores: list[float] = []
    boxes: list[dict[str, Any]] = []
    for item in raw_result:
        mapping = _result_mapping(item)
        item_texts = list(mapping.get("rec_texts") or [])
        item_scores = list(mapping.get("rec_scores") or [])
        item_boxes = mapping.get("rec_boxes")
        if item_boxes is None:
            item_boxes = mapping.get("rec_polys")
        if item_boxes is None:
            item_boxes = []
        item_boxes = _json_safe(item_boxes)
        texts.extend(str(text) for text in item_texts if text)
        scores.extend(float(score) for score in item_scores if score is not None)
        for index, text in enumerate(item_texts):
            boxes.append(
                {
                    "text": str(text),
                    "confidence": float(item_scores[index]) if index < len(item_scores) else None,
                    "bbox": item_boxes[index] if index < len(item_boxes) else [],
                }
            )
    confidence = sum(scores) / len(scores) if scores else 0.0
    text = "\n".join(texts)
    width, height = _image_dimensions(page_image)
    char_count = len(text.strip())
    megapixels = (width * height) / 1_000_000 if width and height else 1.0
    return OCRResult(
        text=text,
        confidence=confidence,
        route_used="fast",
        bounding_boxes=boxes,
        char_count=char_count,
        word_count=len(re.findall(r"\w+", text)),
        line_count=len([line for line in text.splitlines() if line.strip()]),
        image_width=width,
        image_height=height,
        text_density=round(char_count / max(megapixels, 0.1), 2),
    )


def _predict_fast(model: Any, page_image: str | Path) -> list[Any]:
    kwargs = {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
    }
    try:
        return list(model.predict(str(page_image), **kwargs))
    except TypeError:
        return list(model.predict(str(page_image)))


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


def _coerce_fast_result(value: OCRResult | dict[str, Any]) -> OCRResult:
    if isinstance(value, OCRResult):
        value.route_used = "fast"
        value.structured_content = None
        return value
    return OCRResult(
        text=str(value.get("text") or value.get("ocr_text") or ""),
        confidence=float(value.get("confidence") or 0.0),
        route_used="fast",
        bounding_boxes=list(value.get("bounding_boxes") or []),
        char_count=int(
            value.get("char_count")
            or len(str(value.get("text") or value.get("ocr_text") or "").strip())
        ),
        word_count=int(value.get("word_count") or 0),
        line_count=int(value.get("line_count") or 0),
        image_width=int(value.get("image_width") or 0),
        image_height=int(value.get("image_height") or 0),
        text_density=float(value.get("text_density") or 0.0),
        error=str(value.get("error")) if value.get("error") else None,
    )


def _coerce_google_vision_result(value: OCRResult | dict[str, Any]) -> OCRResult:
    if isinstance(value, OCRResult):
        value.route_used = "google_vision"
        return value
    structured_content = {
        "header_text": value.get("header_text") or "",
        "layout_regions": list(value.get("layout_blocks") or []),
        "tables": list(value.get("tables") or []),
        "seals": list(value.get("seals") or []),
        "formulas": list(value.get("formulas") or []),
        "native": list(value.get("structure_json") or []),
    }
    return OCRResult(
        text=str(value.get("text") or value.get("ocr_text") or ""),
        structured_content=structured_content,
        confidence=float(value.get("confidence") or 0.0),
        route_used="google_vision",
        bounding_boxes=list(value.get("bounding_boxes") or []),
        char_count=int(
            value.get("char_count")
            or len(str(value.get("text") or value.get("ocr_text") or "").strip())
        ),
        word_count=int(value.get("word_count") or 0),
        line_count=int(value.get("line_count") or 0),
        image_width=int(value.get("image_width") or 0),
        image_height=int(value.get("image_height") or 0),
        text_density=float(value.get("text_density") or 0.0),
        error=str(value.get("error")) if value.get("error") else None,
    )


def _coerce_structured_result(value: OCRResult | dict[str, Any]) -> OCRResult:
    if isinstance(value, OCRResult):
        value.route_used = "structured"
        return value
    structured_content = {
        "header_text": value.get("header_text") or "",
        "layout_regions": list(value.get("layout_blocks") or []),
        "tables": list(value.get("tables") or []),
        "seals": list(value.get("seals") or []),
        "formulas": list(value.get("formulas") or []),
        "native": list(value.get("structure_json") or []),
    }
    return OCRResult(
        text=str(value.get("text") or value.get("ocr_text") or ""),
        structured_content=structured_content,
        confidence=float(value.get("confidence") or 0.0),
        route_used="structured",
        bounding_boxes=list(value.get("bounding_boxes") or []),
        char_count=int(
            value.get("char_count")
            or len(str(value.get("text") or value.get("ocr_text") or "").strip())
        ),
        word_count=int(value.get("word_count") or 0),
        line_count=int(value.get("line_count") or 0),
        image_width=int(value.get("image_width") or 0),
        image_height=int(value.get("image_height") or 0),
        text_density=float(value.get("text_density") or 0.0),
        error=str(value.get("error")) if value.get("error") else None,
    )


def _document_type_name(doc_type: str | dict[str, Any]) -> str:
    if isinstance(doc_type, dict):
        return str(doc_type.get("document_type") or doc_type.get("type") or "None")
    return str(doc_type or "None")


def _result_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) and hasattr(value, "json"):
        value = value.json
        if callable(value):
            value = value()
    if not isinstance(value, dict):
        return {}
    wrapped = value.get("res")
    return wrapped if isinstance(wrapped, dict) else value


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _result_route(value: OCRResult | dict[str, Any] | None) -> str | None:
    if isinstance(value, OCRResult):
        return value.route_used
    if not isinstance(value, dict):
        return None
    return (
        str(
            value.get("route_used") or value.get("ocr_route") or value.get("ocr_provider") or ""
        ).strip()
        or None
    )


def _record_ocr_route_event(**event: Any) -> None:
    """Persist route timing/escalation data without any external call."""
    if event.get("doc_id") is None:
        return
    from database.db import get_connection

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO ocr_route_events (
                document_id, document_type, page_number, event_type,
                requested_route, route_used, reason, original_confidence,
                duration_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(event.get("doc_id")),
                event.get("document_type"),
                event.get("page_num"),
                event.get("event_type"),
                event.get("requested_route"),
                event.get("route_used"),
                event.get("reason"),
                event.get("original_confidence"),
                event.get("duration_ms"),
            ),
        )


def get_ocr_route_metrics(document_id: str | int) -> list[dict[str, Any]]:
    """Aggregate processing counts and time by route for one document/job."""
    from database.db import get_connection

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT route_used,
                   COUNT(*) AS page_count,
                   SUM(duration_ms) AS total_duration_ms,
                   AVG(duration_ms) AS average_duration_ms,
                   SUM(CASE WHEN requested_route = 'fast' AND route_used = 'structured'
                            THEN 1 ELSE 0 END) AS escalation_count
            FROM ocr_route_events
            WHERE document_id = ? AND event_type = 'processing'
            GROUP BY route_used
            ORDER BY route_used
            """,
            (str(document_id),),
        ).fetchall()
    return [dict(row) for row in rows]
