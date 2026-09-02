"""Field extractor for DMEF — compatibility facade.

Extracts structured fields from OCR-extracted text for each document type.
Implementation lives in ``services.extraction`` by document family.

Public API
----------
extract_fields(document_type: str, text: str) -> dict
    Dispatches to the correct per-type extractor and returns a flat dict
    of field_name → value.

Cross-match contract (Sanction Letter & Loan Agreement)
-------------------------------------------------------
These fields are consumed by checklist_engine for Graviton cross-matching.
Field names and types MUST NOT change without updating the engine:

    loan_amount  → str   (digits only, no commas, no currency symbols)
    tenure       → int   (always normalised to number of months)
    emi          → str   (digits only, no commas, no currency symbols)
    roi          → float (percentage as a float, e.g. 8.5 for 8.5%)
"""

from services.extraction.dispatcher import extract_fields

__all__ = ["extract_fields"]
