"""Page classification smoothing and sequential assignment."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from services.classification_review_log import log_classification_review_event
from services.document_classifier import HIGH_CONFIDENCE
from services.pipeline._shared import DOCUMENT_TYPE_ALIASES
from services.progress_tracker import record_page_completed

try:  # pragma: no cover
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None


def _smooth_page_classifications(
    pages: list[dict[str, Any]],
    application_id: int | None,
    total_pages: int,
) -> list[dict[str, Any]]:
    if len(pages) < 3:
        return pages

    sorted_pages = sorted(pages, key=lambda item: int(item.get("page_number") or 0))
    for i in range(1, len(sorted_pages) - 1):
        prev_page = sorted_pages[i - 1]
        curr_page = sorted_pages[i]
        next_page = sorted_pages[i + 1]

        if curr_page.get("document_type") == "Unknown":
            prev_type = prev_page.get("document_type")
            next_type = next_page.get("document_type")
            if prev_type != "Unknown" and prev_type == next_type:
                curr_page["document_type"] = prev_type
                curr_page["classification_confidence"] = round(
                    (prev_page.get("classification_confidence", 0.70) + next_page.get("classification_confidence", 0.70)) / 2.0,
                    3,
                )
                curr_page["detection_method"] = "sandwich_smoothed"

                text = curr_page.get("ocr_text", "")
                from services.field_extractor import extract_fields
                from services.field_assignment_refiner import refine_field_assignments

                extracted_fields = extract_fields(prev_type, text)
                extracted_fields = refine_field_assignments(
                    document_type=prev_type,
                    ocr_text=text,
                    extracted_fields=extracted_fields,
                )

                orig_cls = curr_page.get("extracted_fields", {}).get("_classification", {})
                if isinstance(orig_cls, dict):
                    orig_cls["assigned_type"] = prev_type
                    orig_cls["detection_method"] = "sandwich_smoothed"
                else:
                    orig_cls = {
                        "assigned_type": prev_type,
                        "detection_method": "sandwich_smoothed",
                        "raw_document_type": "Unknown",
                        "raw_confidence": 0.0,
                        "detected_page_number": curr_page.get("page_number"),
                        "triage": {},
                    }
                extracted_fields["_classification"] = orig_cls
                curr_page["extracted_fields"] = extracted_fields

                if application_id is not None:
                    record_page_completed(
                        application_id,
                        page_number=int(curr_page.get("page_number") or 0),
                        total_pages=total_pages,
                        page_type=curr_page.get("page_type"),
                        document_type=prev_type,
                        elapsed_seconds=0.0,
                        extracted_fields=extracted_fields,
                        status="completed",
                        error=None,
                    )
    return sorted_pages


def _assign_sequential_document_type(
    *,
    page_number: int,
    text: str,
    classification: dict[str, Any],
    current_type: str,
    current_confidence: float,
    current_detected_page: int | None,
) -> dict[str, Any]:
    raw_type = _normalize_document_type(classification.get("document_type"))
    raw_confidence = float(classification.get("confidence") or 0.0)
    if raw_type != "Unknown" and raw_confidence >= HIGH_CONFIDENCE:
        return {
            "document_type": raw_type,
            "confidence": raw_confidence,
            "detection_method": "detected",
            "detected_page_number": page_number,
            "raw_document_type": raw_type,
            "raw_confidence": raw_confidence,
        }

    if current_type != "Unknown":
        if _looks_like_fresh_page_without_match(text):
            return {
                "document_type": "Unknown",
                "confidence": 0.0,
                "detection_method": "unknown",
                "detected_page_number": None,
                "raw_document_type": raw_type,
                "raw_confidence": raw_confidence,
                "abstain_reason": "fresh-page-like-no-match",
            }
        inherited_confidence = max(0.55, min(0.85, current_confidence * 0.85))
        return {
            "document_type": current_type,
            "confidence": round(inherited_confidence, 3),
            "detection_method": "inherited",
            "detected_page_number": current_detected_page,
            "raw_document_type": raw_type,
            "raw_confidence": raw_confidence,
            "inheritance_warning": None,
        }

    return {
        "document_type": "Unknown",
        "confidence": 0.0,
        "detection_method": "unknown",
        "detected_page_number": None,
        "raw_document_type": raw_type,
        "raw_confidence": raw_confidence,
    }


def _looks_like_fresh_page_without_match(text: str) -> bool:
    raw_text = text or ""
    # Some digitally generated PDFs expose the entire page as one enormous
    # line.  Treating that whole line as a heading makes a continuation page
    # look "fresh" merely because words such as letter/report occur later in
    # boilerplate.  Document-boundary evidence belongs near the top of a page.
    header = " ".join(raw_text.splitlines()[:6])[:360]
    normalized_header = _normalize_fresh_document_text(header)
    normalized_text = _normalize_fresh_document_text(raw_text)
    if not normalized_text:
        return False

    generic_header_terms = (
        "certificate",
        "letter",
        "agreement",
        "deed",
        "report",
        "statement",
        "form",
        "application",
        "undertaking",
        "declaration",
    )
    if any(term in normalized_header for term in generic_header_terms):
        return True

    strong_terms = (
        "affidavit",
        "notary",
        "notarised",
        "notarized",
        "attested",
        "stamp paper",
        "non judicial",
        "non-judicial",
        "adhesive stamp",
        "gps map camera",
        "patta",
        "शपथ",
        "शपथ पत्र",
        "हलफनामा",
        "पट्टा",
        "प्रपत्र",
        "नोटरी",
        "स्टाम्प",
        "न्यायिक",
        "घोषणा",
        "अभियान",
    )
    if any(_normalize_fresh_document_text(term) in normalized_text for term in strong_terms):
        return True

    fuzzy_terms = ("शपथ", "हलफनामा", "पट्टा", "प्रपत्र", "नोटरी", "स्टाम्प", "न्यायिक", "घोषणा")
    return any(_fuzzy_contains(normalized_text, _normalize_fresh_document_text(term)) for term in fuzzy_terms)


def _normalize_fresh_document_text(value: str) -> str:
    normalized = str(value or "").lower()
    normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
    normalized = re.sub(r"[^0-9a-z\u0900-\u097f-]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _fuzzy_contains(text: str, term: str, *, threshold: float = 0.85) -> bool:
    if not text or not term:
        return False
    if term in text:
        return True
    if fuzz is not None:
        return (float(fuzz.partial_ratio(term, text)) / 100.0) >= threshold

    term_length = len(term)
    if len(text) <= term_length:
        return SequenceMatcher(None, term, text).ratio() >= threshold
    best_ratio = 0.0
    for start in range(0, len(text) - term_length + 1):
        window = text[start : start + term_length]
        best_ratio = max(best_ratio, SequenceMatcher(None, term, window).ratio())
        if best_ratio >= threshold:
            return True
    return False


def _normalize_document_type(document_type: str | None) -> str:
    if not document_type:
        return "Unknown"
    return DOCUMENT_TYPE_ALIASES.get(document_type, document_type)


def _infer_document_type_from_filename(filename: str) -> str | None:
    if not filename:
        return None
    lower = filename.lower().replace("\\", "/")
    suffix = Path(lower).suffix

    if suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff"} and any(
        folder in lower for folder in ("/collateral/", "/valuation/")
    ):
        return "Property Image"

    # Check for direct keyword matches in the whole path
    if "pan" in lower:
        return "PAN Card"
    if "aadhar" in lower or "aadhaar" in lower or "uidai" in lower:
        return "Aadhaar Card"
    if "passport" in lower:
        return "Passport"
    if "driving" in lower or "dl " in lower or "licence" in lower or "license" in lower:
        return "Driving License"
    if "voter" in lower or "epic" in lower:
        return "Voter ID"
    if "cheque" in lower or "check" in lower:
        return "Cheque"
    if "spdc" in lower or re.search(r"(?:^|[/_\-\s])pdc(?:[/_\-\s.]|$)", lower):
        return "PDC"
    if "property paper" in lower or "proprty paper" in lower:
        return "Property Document"
    if "house photo" in lower:
        return "House Photo"
    if "working place" in lower or "workplace" in lower:
        return "Workplace Photo"
    if "technical report" in lower:
        return "Technical Report"
    if "ration card" in lower:
        return "Ration Card"
    if "cersai" in lower:
        return "CERSAI Report"
    if "insurance consent" in lower:
        return "Insurance Consent Letter"
    if "property insurance" in lower:
        return "Property Insurance Form"
    if "life insurance" in lower:
        return "Life Insurance Form"
    if "insurance" in lower:
        return "Insurance Form"
    if "banking" in lower:
        return "Bank Statement"
    if "statement" in lower or "bank_stmt" in lower or "bank stmt" in lower or "bankstmt" in lower:
        return "Bank Statement"
    if "utility" in lower or "bill" in lower or "electricity" in lower or "water" in lower or "gas_bill" in lower:
        return "Utility Bill"
    if "sanction" in lower or "loan_sanction" in lower:
        return "Sanction Letter"
    if "agreement" in lower or "contract" in lower or "loan_agreement" in lower:
        return "Loan Agreement"
    if "salary" in lower or "pay slip" in lower or "payslip" in lower or "salary_slip" in lower:
        return "Salary Slip"
    if "kfs" in lower or "key fact" in lower:
        return "KFS (Key Fact Statement)"
    if re.search(r"(?:^|[/_\-\s])cam(?:[/_\-\s.(]|$)", lower):
        return "CAM"

    # If it's a generic file name like page_1.png, image.jpg, scan.pdf, etc.,
    # we can try to use the parent folder name if it exists.
    parts = [p for p in lower.split("/") if p]
    if len(parts) > 1:
        parent = parts[-2]
        # Ignore generic parent folders
        if parent not in {
            "sources", "source", "uploads", "documents", "files", "temp", "tmp", "pages",
            "task", "task 1", "task_1", "report", "bank", "kyc", "income",
            "creditbureau", "creditbureau 1", "creditbureau 2", "creditbureau 3",
        }:
            cleaned = parent.replace("_", " ").replace("-", " ")
            return " ".join(word.capitalize() for word in cleaned.split())

    # Fallback to the file base name if it is not generic
    base_name = Path(parts[-1]).stem
    generic_patterns = {
        "image", "img", "scan", "page", "document", "doc", "file", "photo", "pic",
        "output", "export", "pdf", "unnamed", "untitled", "unknown"
    }
    cleaned_base = base_name.replace("_", " ").replace("-", " ").strip()
    if re.search(r"\b(?:combine|combined|merged|bundle|packet)\b", cleaned_base, re.IGNORECASE):
        return None
    if re.fullmatch(r"credit\s*score(?:\s*\(\d+\))?", cleaned_base, re.IGNORECASE):
        return None
    words = cleaned_base.split()

    is_generic = True
    for word in words:
        word_clean = "".join(c for c in word.lower() if c.isalpha())
        if word_clean and word_clean not in generic_patterns:
            is_generic = False
            break

    if not is_generic and cleaned_base:
        return " ".join(word.capitalize() for word in words)

    return None


def _log_classification_review_if_needed(
    *,
    application_id: int | None,
    page_number: int,
    document_type: str,
    confidence: float,
    metadata: dict[str, Any],
) -> None:
    anchor_type = metadata.get("anchor_document_type")
    llm_type = metadata.get("llm_document_type")
    anchor_matches = metadata.get("anchor_matches") or {}
    if anchor_type and llm_type and anchor_type != llm_type:
        log_classification_review_event(
            application_id=application_id,
            page_number=page_number,
            predicted_type=document_type,
            confidence=confidence,
            reason="anchor_llm_disagreement",
            anchor_match_results=anchor_matches,
            llm_document_type=str(llm_type),
        )
        return

    if confidence < 0.65:
        log_classification_review_event(
            application_id=application_id,
            page_number=page_number,
            predicted_type=document_type,
            confidence=confidence,
            reason="classification_confidence_below_threshold",
            anchor_match_results=anchor_matches,
            llm_document_type=str(llm_type) if llm_type else None,
        )
