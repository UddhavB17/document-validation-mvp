"""Public compatibility facade for the pipeline package.

Application code and tests should import from ``services.pipeline``. Internal
modules import dependencies from their owning modules directly.
"""

from services.field_extractor import extract_fields
from services.llm_service import generate_explanation, summarize_exceptions

# Re-exported as part of the historical facade. Tests patch the implementation
# module (``services.pipeline.page_processing.get_ocr_router``) directly.
from services.ocr_router import get_ocr_router
from services.page_classification import classify_page_text
from services.pipeline._shared import DOCUMENT_TYPE_ALIASES
from services.pipeline.classification import (
    _assign_sequential_document_type,
    _deterministic_routing_document_type,
    _filename_type_contradicted_by_text,
    _image_evidence_type_from_text,
    _infer_document_type_from_filename,
    _smooth_page_classifications,
    _source_filename_override_allowed,
)
from services.pipeline.input_preparation import _build_unsupported_page_records
from services.pipeline.orchestrator import run_pipeline
from services.pipeline.page_details import _ensure_page_has_json_details
from services.pipeline.page_processing import (
    _build_page_records,
    _build_page_reuse_map,
    _clone_reused_page,
    _refresh_page_from_cached_ocr,
    run_ocr_on_page,
)
from services.pipeline.partner import run_partner_json_pipeline
from services.pipeline.persistence import _save_ground_truth, _save_pages
from services.structured_llm_classifier import classify_with_structured_llm

__all__ = [
    "DOCUMENT_TYPE_ALIASES",
    "_assign_sequential_document_type",
    "_build_page_records",
    "_build_page_reuse_map",
    "_build_unsupported_page_records",
    "_clone_reused_page",
    "_deterministic_routing_document_type",
    "_ensure_page_has_json_details",
    "_filename_type_contradicted_by_text",
    "_image_evidence_type_from_text",
    "_infer_document_type_from_filename",
    "_refresh_page_from_cached_ocr",
    "_save_ground_truth",
    "_save_pages",
    "_smooth_page_classifications",
    "_source_filename_override_allowed",
    "classify_page_text",
    "classify_with_structured_llm",
    "extract_fields",
    "generate_explanation",
    "get_ocr_router",
    "run_ocr_on_page",
    "run_partner_json_pipeline",
    "run_pipeline",
    "summarize_exceptions",
]
