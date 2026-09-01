"""Public compatibility facade for the pipeline package.

Application code and tests should import from ``services.pipeline``. Internal
modules import dependencies from their owning modules directly.
"""

from services.field_extractor import extract_fields
from services.llm_service import generate_explanation, summarize_exceptions
from services.ocr_engine import run_ocr_on_page
from services.page_classification import classify_page_text
from services.pipeline._shared import DOCUMENT_TYPE_ALIASES
from services.pipeline.classification import _assign_sequential_document_type, _infer_document_type_from_filename
from services.pipeline.input_preparation import _build_unsupported_page_records
from services.pipeline.orchestrator import run_pipeline
from services.pipeline.page_processing import _build_page_records
from services.pipeline.partner import run_partner_json_pipeline
from services.pipeline.persistence import _save_ground_truth, _save_pages
from services.structured_llm_classifier import classify_with_structured_llm

# Re-exported to preserve the historical public namespace for application code
# and external callers. Tests patch dependencies in their implementation
# modules so runtime dependency resolution remains explicit.
__all__ = [
    "DOCUMENT_TYPE_ALIASES",
    "_assign_sequential_document_type",
    "_build_page_records",
    "_build_unsupported_page_records",
    "_infer_document_type_from_filename",
    "_save_ground_truth",
    "_save_pages",
    "classify_page_text",
    "classify_with_structured_llm",
    "extract_fields",
    "generate_explanation",
    "run_ocr_on_page",
    "run_partner_json_pipeline",
    "run_pipeline",
    "summarize_exceptions",
]
