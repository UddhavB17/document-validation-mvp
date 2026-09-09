"""Page classification, smoothing, and filename inference."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from services.classification_review_log import log_classification_review_event
from services.document_classifier import HIGH_CONFIDENCE
from services.person_names import has_independent_identity_anchor
from services.pipeline._shared import (
    _EMAIL_ADDRESS_RE,
    _EMAIL_INFERRED_EVIDENCE_TYPES,
    _FILENAME_IDENTITY_TYPE_ANCHORS,
    _INTRINSIC_IDENTITY_TYPES,
    _MID_CONFIDENCE_BOUNDARY,
    _MULTI_PAGE_RUN_FILL_TYPES,
    _NO_PAGE_INHERITANCE_TYPES,
    _NO_SANDWICH_SMOOTHING_TYPES,
    _ONE_PAGE_INHERITANCE_TYPES,
    DOCUMENT_TYPE_ALIASES,
)
from services.pipeline.page_details import _extract_fields_with_layout
from services.progress_tracker import record_page_completed
from services.validation_gates import attach_field_provenance

try:  # pragma: no cover - exercised when rapidfuzz is available
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover - fallback keeps the pipeline dependency-light
    fuzz = None


def _deterministic_routing_document_type(
    *,
    document_type: str,
    detection_method: str,
    classification_metadata: dict[str, Any],
) -> str:
    """Prevent an optional LLM classification from selecting an OCR route."""
    if detection_method in {"inherited", "filename_inference", "filename_override"}:
        return document_type
    if classification_metadata.get("source") != "llm":
        return document_type
    rule_type = _normalize_document_type(classification_metadata.get("rule_document_type"))
    rule_confidence = float(classification_metadata.get("rule_confidence") or 0.0)
    return rule_type if rule_type != "Unknown" and rule_confidence >= HIGH_CONFIDENCE else "Unknown"


def _apply_smoothed_document_type(
    page: dict[str, Any],
    document_type: str,
    *,
    confidence: float,
    method: str,
    application_id: int | None,
    total_pages: int,
) -> None:
    page["document_type"] = document_type
    page["classification_confidence"] = confidence
    page["detection_method"] = method

    text = page.get("ocr_text", "")
    from services.field_assignment_refiner import refine_field_assignments

    extracted_fields = _extract_fields_with_layout(
        document_type,
        text,
        page.get("structured_content") or page.get("ocr_structure"),
    )
    extracted_fields = refine_field_assignments(
        document_type=document_type,
        ocr_text=text,
        extracted_fields=extracted_fields,
    )

    orig_cls = page.get("extracted_fields", {}).get("_classification", {})
    if isinstance(orig_cls, dict):
        orig_cls["assigned_type"] = document_type
        orig_cls["detection_method"] = method
    else:
        orig_cls = {
            "assigned_type": document_type,
            "detection_method": method,
            "raw_document_type": "Unknown",
            "raw_confidence": 0.0,
            "detected_page_number": page.get("page_number"),
            "triage": {},
        }
    extracted_fields["_classification"] = orig_cls
    page["extracted_fields"] = extracted_fields

    if application_id is not None:
        record_page_completed(
            application_id,
            page_number=int(page.get("page_number") or 0),
            total_pages=total_pages,
            page_type=page.get("page_type"),
            document_type=document_type,
            elapsed_seconds=0.0,
            extracted_fields=extracted_fields,
            status="completed",
            error=None,
        )


def _looks_like_loan_agreement_continuation(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = (
        "borrower",
        "lender",
        "repayment",
        "facility",
        "event of default",
        "उधारकर्ता",
        "उ ारक",
        "अनुच्छेद",
        "अनुJेद",
        "ऋणदा",
        "ऋण अनुबंध",
        "ઉધારકર્તા",
        "લોનદાતા",
        "લોન કરાર",
        "ફેસિલિટી એગ્રીમમેન્ટ",
        "કલમ",
        "sanction letter",
        "joint liability",
        "herein",
        "hereof",
        "article ",
    )
    hits = sum(1 for marker in markers if marker in lowered)
    if hits >= 2:
        return True
    # Dense legal/agreement body pages often only keep a couple of English fragments.
    if hits >= 1 and len(str(text or "")) >= 600:
        return True
    return False


def _looks_like_multi_page_continuation(document_type: str, text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered.strip():
        return False
    if document_type in {"Loan Agreement", "Facility Agreement"}:
        return _looks_like_loan_agreement_continuation(text)
    if document_type == "Application Form":
        return any(
            marker in lowered
            for marker in (
                "applicant",
                "co-applicant",
                "kyc",
                "mobile",
                "address",
                "आवेदक",
                "सह-आवेदक",
                "पिनकोड",
                "pincode",
                "declaration",
                "અરજદાર",
                "સહ અરજદાર",
                "સરનામું",
                "ઘોષણા",
            )
        )
    if document_type == "Bank Statement":
        ledger_markers = (
            "debit",
            "credit",
            "balance",
            "neft",
            "upi",
            "withdrawal",
            "deposit",
            "opening balance",
            "closing balance",
            "transaction",
            "brought forward",
            "end balance",
            "instrument no",
            "amount received",
            "loan allocation amount",
            "receipt no",
            "txn date",
            "value date",
            "installment amount due",
            "instalment amount due",
        )
        return sum(1 for marker in ledger_markers if marker in lowered) >= 2
    if document_type in {"CIBIL Report", "CRIF Report"}:
        return any(
            marker in lowered
            for marker in (
                "account",
                "enquiry",
                "payment history",
                "overdue",
                "score",
                "credit",
                "member",
                "control number",
                "high mark",
                "cibil",
                "crif",
            )
        )
    if document_type == "Passbook":
        return any(
            marker in lowered
            for marker in ("passbook", "pass book", "balance", "deposit", "withdrawal", "पासबुक")
        )
    if document_type == "Guarantee Deed":
        return any(
            marker in lowered
            for marker in (
                "deed of guarantee",
                "guarantee deed",
                "this guarantee",
                "guarantor",
                "guaranteors",
                "guarantee",
                "જામીનદાર",
                "ગેરંટી",
            )
        )
    return False


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

        if curr_page.get("document_type") == "Unknown" and not _is_email_correspondence(
            str(curr_page.get("ocr_text") or "")
        ):
            prev_type = prev_page.get("document_type")
            next_type = next_page.get("document_type")
            if (
                prev_type != "Unknown"
                and prev_type == next_type
                and prev_type not in _NO_SANDWICH_SMOOTHING_TYPES
                and _same_source_context(prev_page, curr_page, next_page)
            ):
                _apply_smoothed_document_type(
                    curr_page,
                    prev_type,
                    confidence=round(
                        (
                            float(prev_page.get("classification_confidence") or 0.70)
                            + float(next_page.get("classification_confidence") or 0.70)
                        )
                        / 2.0,
                        3,
                    ),
                    method="sandwich_smoothed",
                    application_id=application_id,
                    total_pages=total_pages,
                )
                fields = (
                    curr_page.get("extracted_fields")
                    if isinstance(curr_page.get("extracted_fields"), dict)
                    else {}
                )
                _mark_unanchored_inherited_identity(
                    fields,
                    detection_method="sandwich_smoothed",
                    raw_document_type="Unknown",
                )
                curr_page["extracted_fields"] = fields
                attach_field_provenance(curr_page)

    # Fill short Unknown runs (1-2 pages) between the same multi-page document type.
    for i in range(1, len(sorted_pages) - 2):
        left = sorted_pages[i - 1]
        mid_a = sorted_pages[i]
        mid_b = sorted_pages[i + 1]
        right = sorted_pages[i + 2]
        left_type = str(left.get("document_type") or "Unknown")
        right_type = str(right.get("document_type") or "Unknown")
        if (
            left_type == right_type
            and left_type in _MULTI_PAGE_RUN_FILL_TYPES
            and mid_a.get("document_type") == "Unknown"
            and mid_b.get("document_type") == "Unknown"
            and not _is_email_correspondence(str(mid_a.get("ocr_text") or ""))
            and not _is_email_correspondence(str(mid_b.get("ocr_text") or ""))
            and _same_source_context(left, mid_a, mid_b, right)
        ):
            for mid in (mid_a, mid_b):
                _apply_smoothed_document_type(
                    mid,
                    left_type,
                    confidence=0.70,
                    method="sandwich_run_smoothed",
                    application_id=application_id,
                    total_pages=total_pages,
                )

    # Forward-fill Unknown runs inside multi-page document blocks.
    agreement_types = {"Loan Agreement", "Facility Agreement"}
    for i, curr_page in enumerate(sorted_pages):
        curr_type = str(curr_page.get("document_type") or "Unknown")
        text = str(curr_page.get("ocr_text") or "")
        if i == 0:
            continue
        if _is_email_correspondence(text):
            continue
        prev_type = str(sorted_pages[i - 1].get("document_type") or "Unknown")
        next_type = (
            str(sorted_pages[i + 1].get("document_type") or "Unknown")
            if i + 1 < len(sorted_pages)
            else "Unknown"
        )

        # Reclaim agreement-body pages that a short keyword (KFS / insurance clause)
        # stole from the surrounding Facility/Loan Agreement run.
        if (
            curr_type
            in {
                "KFS",
                "Insurance Form",
                "Insurance Consent Letter",
                "Charges Deduction Document",
                "Guarantee Deed",
                "Income Tax Return",
                "Unknown",
            }
            and _looks_like_loan_agreement_continuation(text)
            and (prev_type in agreement_types or next_type in agreement_types)
        ):
            target = (
                prev_type
                if prev_type in agreement_types
                and _same_source_context(sorted_pages[i - 1], curr_page)
                else next_type
                if next_type in agreement_types
                and i + 1 < len(sorted_pages)
                and _same_source_context(curr_page, sorted_pages[i + 1])
                else "Unknown"
            )
            if target in agreement_types:
                _apply_smoothed_document_type(
                    curr_page,
                    target,
                    confidence=0.74,
                    method="agreement_context_smoothed",
                    application_id=application_id,
                    total_pages=total_pages,
                )
                continue

        if curr_type != "Unknown":
            continue
        if prev_type not in _MULTI_PAGE_RUN_FILL_TYPES:
            continue
        if not _same_source_context(sorted_pages[i - 1], curr_page):
            continue
        if not _looks_like_multi_page_continuation(prev_type, text):
            continue
        _apply_smoothed_document_type(
            curr_page,
            prev_type,
            confidence=0.72,
            method="run_forward_smoothed",
            application_id=application_id,
            total_pages=total_pages,
        )
        fields = (
            curr_page.get("extracted_fields")
            if isinstance(curr_page.get("extracted_fields"), dict)
            else {}
        )
        _mark_unanchored_inherited_identity(
            fields,
            detection_method="run_forward_smoothed",
            raw_document_type="Unknown",
        )
        cls_meta = fields.get("_classification") if isinstance(fields, dict) else None
        if isinstance(cls_meta, dict):
            cls_meta["assigned_type"] = prev_type
            cls_meta["detection_method"] = "run_forward_smoothed"
        fields["_classification"] = cls_meta or {
            "assigned_type": prev_type,
            "detection_method": "run_forward_smoothed",
            "raw_document_type": "Unknown",
            "raw_confidence": 0.0,
            "detected_page_number": curr_page.get("page_number"),
            "triage": {},
        }
        curr_page["extracted_fields"] = fields
        attach_field_provenance(curr_page)

    return sorted_pages


def _same_source_context(*pages: dict[str, Any]) -> bool:
    """Do not smooth classifications across ZIP-member boundaries."""
    identifiers = [
        str(page.get("source_document_id") or page.get("source_filename") or "").strip()
        for page in pages
    ]
    if not any(identifiers):
        # A plain merged PDF has no source-member metadata.
        return True
    return all(identifiers) and len(set(identifiers)) == 1


def _source_document_for_page(
    source_documents: list[dict[str, Any]],
    page_number: int,
) -> dict[str, Any] | None:
    for source in source_documents:
        start = source.get("internal_page_start")
        end = source.get("internal_page_end")
        if start is None or end is None:
            continue
        if int(start) <= page_number <= int(end):
            return source
    return None


def _mark_unanchored_inherited_identity(
    fields: dict[str, Any],
    *,
    detection_method: str | None,
    raw_document_type: str | None,
) -> None:
    raw_type = _normalize_document_type(raw_document_type)
    if (
        detection_method not in {"inherited", "sandwich_smoothed", "run_forward_smoothed"}
        or raw_type != "Unknown"
    ):
        return
    if has_independent_identity_anchor(fields):
        return
    if any(
        fields.get(field) not in (None, "", [], {})
        for field in ("applicant_name", "borrower_name", "account_holder_name", "customer_name")
    ):
        fields["_identity_extraction_reliable"] = False
        fields["_identity_extraction_unreliable_reason"] = (
            "inherited_unknown_without_identity_anchor"
        )


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
    agreement_types = {"Loan Agreement", "Facility Agreement"}

    # A combined loan PDF can start the KFS near the bottom of a page after
    # application/agreement boilerplate.  That embedded, explicit title is a
    # real boundary even though it is not one of the first header lines.
    if _looks_like_kfs_start(text):
        return {
            "document_type": "KFS",
            "confidence": max(raw_confidence if raw_type == "KFS" else 0.0, 0.98),
            "detection_method": "detected",
            "detected_page_number": page_number,
            "raw_document_type": raw_type,
            "raw_confidence": raw_confidence,
        }

    # KFS fee tables, qualitative disclosures, APR illustrations, and the
    # amortisation schedule often classify as insurance/agreement pages when
    # viewed independently.  Keep them in the open KFS until a genuine next
    # document heading appears.
    if (
        current_type == "KFS"
        and _looks_like_kfs_continuation(text)
        and not _looks_like_fresh_page_without_match(text)
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="kfs-run-context",
        )

    # Once an agreement title opens a run, references inside its clauses to a
    # KFS, sanction letter, PDC, MOA/AOA, or another agreement synonym are not
    # new documents. A real title at the top/embedded boundary still wins.
    if current_type in agreement_types and (
        (
            raw_type in agreement_types
            and (
                raw_type == current_type or not _looks_like_explicit_agreement_start(text, raw_type)
            )
        )
        or (
            _looks_like_loan_agreement_continuation(text)
            and not _looks_like_fresh_page_without_match(text)
        )
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="agreement-run-context",
        )

    # Guarantee deeds repeatedly refer to the underlying loan agreement and
    # lender.  Those references are continuation clauses, not a new loan
    # agreement, unless a genuine new-document heading is present.
    if (
        current_type == "Guarantee Deed"
        and raw_type in {"Unknown", "Guarantee Deed", "Loan Agreement", "Facility Agreement"}
        and _looks_like_multi_page_continuation(current_type, text)
        and not _looks_like_fresh_page_without_match(text)
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="guarantee-deed-run-context",
        )

    # Multi-page application forms contain loan/facility declarations and can
    # otherwise be reclassified as agreements halfway through the form.  Keep
    # co-applicant, security, banking and declaration pages in the open form.
    if (
        current_type == "Application Form"
        and raw_type
        in {
            "Unknown",
            "Application Form",
            "Loan Agreement",
            "Facility Agreement",
            "Property Document",
            "Aadhaar",
        }
        and _looks_like_multi_page_continuation(current_type, text)
        and not _looks_like_fresh_page_without_match(text)
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="application-form-run-context",
        )

    # A statement transaction can mention NACH, ACH, cheque, insurance, or
    # dozens of other payment modes. Those narration tokens are not standalone
    # documents. Preserve the open ledger until an actual mandate/form title
    # starts a new document.
    if (
        current_type == "Bank Statement"
        and raw_type in {"Unknown", "Bank Statement", "NACH Form", "Cheque"}
        and _looks_like_multi_page_continuation(current_type, text)
        and not _looks_like_explicit_nach_start(text)
        and not _looks_like_fresh_page_without_match(text)
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="statement-ledger-continuation",
        )

    # Sanction conditions often mention the agreement, property/security, and
    # stamp duty. Those are clause references until a real next-document title
    # appears (for example FACILITY AGREEMENT or SALE DEED).
    if (
        current_type == "Sanction Letter"
        and _looks_like_sanction_letter_continuation(text)
        and not _looks_like_fresh_page_without_match(text)
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="sanction-conditions-context",
        )

    # Credit-report appendices commonly lose the bureau name and look like a
    # bank statement because they contain account/payment-history tables.
    if (
        current_type in {"CIBIL Report", "CRIF Report"}
        and _looks_like_multi_page_continuation(current_type, text)
        and not _looks_like_explicit_bureau_report_start(text)
        and not _looks_like_fresh_page_without_match(text)
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="bureau-appendix-context",
        )

    # A disbursement request can continue with payment instructions mentioning
    # a statement of account. Keep the short continuation in the open letter.
    if (
        current_type == "Disbursement Request"
        and current_detected_page is not None
        and page_number - current_detected_page <= 2
        and not _looks_like_fresh_page_without_match(text)
    ):
        return _inherited_sequence_result(
            current_type=current_type,
            current_confidence=current_confidence,
            current_detected_page=current_detected_page,
            raw_type=raw_type,
            raw_confidence=raw_confidence,
            reason="disbursement-request-continuation",
        )

    if raw_type != "Unknown" and raw_confidence >= HIGH_CONFIDENCE:
        return {
            "document_type": raw_type,
            "confidence": raw_confidence,
            "detection_method": "detected",
            "detected_page_number": page_number,
            "raw_document_type": raw_type,
            "raw_confidence": raw_confidence,
        }

    # Mid-confidence hits that disagree with the open run start a new document
    # boundary instead of inheriting the previous type (or staying Unknown).
    if (
        raw_type != "Unknown"
        and raw_confidence >= _MID_CONFIDENCE_BOUNDARY
        and raw_type != current_type
    ):
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
        inheritance_reason = _identity_inheritance_block_reason(
            current_type=current_type,
            page_number=page_number,
            current_detected_page=current_detected_page,
        )
        if inheritance_reason:
            return {
                "document_type": "Unknown",
                "confidence": 0.0,
                "detection_method": "unknown",
                "detected_page_number": None,
                "raw_document_type": raw_type,
                "raw_confidence": raw_confidence,
                "abstain_reason": inheritance_reason,
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


def _inherited_sequence_result(
    *,
    current_type: str,
    current_confidence: float,
    current_detected_page: int | None,
    raw_type: str,
    raw_confidence: float,
    reason: str,
) -> dict[str, Any]:
    inherited_confidence = max(0.55, min(0.85, current_confidence * 0.85))
    return {
        "document_type": current_type,
        "confidence": round(inherited_confidence, 3),
        "detection_method": "inherited",
        "detected_page_number": current_detected_page,
        "raw_document_type": raw_type,
        "raw_confidence": raw_confidence,
        "inheritance_warning": reason,
    }


def _identity_inheritance_block_reason(
    *,
    current_type: str,
    page_number: int,
    current_detected_page: int | None,
) -> str | None:
    if current_type in _NO_PAGE_INHERITANCE_TYPES:
        return "single-page-identity-document-does-not-inherit"
    if current_type in _ONE_PAGE_INHERITANCE_TYPES:
        if current_detected_page is None or page_number - current_detected_page > 1:
            return "identity-document-inheritance-limit-reached"
    return None


def _looks_like_sanction_letter_continuation(text: str) -> bool:
    normalized = _normalize_fresh_document_text(text)
    if not normalized:
        return False
    markers = (
        "sanction",
        "sanctioned",
        "terms and conditions",
        "disbursement",
        "credit verification",
        "interest rate",
        "loan tenure",
        "loan amount",
        "મંજૂરી",
        "મંજૂર",
        "વિતરણ",
        "વ્યાજ દર",
        "લોનની મુદત",
        "શરતો",
    )
    hits = sum(1 for marker in markers if marker in normalized)
    return hits >= 2 or (hits >= 1 and len(normalized) >= 400)


def _looks_like_explicit_agreement_start(text: str, document_type: str) -> bool:
    """Recognize a real agreement title without treating body words as a boundary."""
    phrases = {
        "Loan Agreement": ("loan agreement", "loan contract", "ऋण समझौता", "ऋण अनुबंध", "લોન કરાર"),
        "Facility Agreement": ("facility agreement", "ફેસિલિટી એગ્રીમમેન્ટ"),
    }.get(document_type, ())
    header_lines = [
        _normalize_fresh_document_text(line)
        for line in str(text or "").splitlines()[:6]
        if _normalize_fresh_document_text(line)
    ]
    return any(
        line == phrase
        or (line.startswith(f"{phrase} ") and len(line.split()) <= len(phrase.split()) + 5)
        for line in header_lines
        for phrase in phrases
    )


def _looks_like_explicit_nach_start(text: str) -> bool:
    """Require mandate-form structure, not a NACH transaction narration."""
    header = _normalize_fresh_document_text("\n".join(str(text or "").splitlines()[:20]))
    if not header:
        return False
    has_title = bool(
        re.search(
            r"\b(?:nach|ecs|national automated clearing house)\s+(?:debit\s+)?mandate\b|"
            r"\b(?:debit|auto debit)\s+mandate\b",
            header,
        )
    )
    form_signals = sum(
        1
        for marker in (
            "umrn",
            "sponsor bank",
            "utility code",
            "authorize to debit",
            "authorise to debit",
            "frequency",
            "maximum amount",
        )
        if marker in header
    )
    return has_title or form_signals >= 2


def _looks_like_explicit_bureau_report_start(text: str) -> bool:
    """Distinguish a new bureau report cover from its account appendices."""
    header = _normalize_fresh_document_text("\n".join(str(text or "").splitlines()[:20]))
    if not header:
        return False
    has_report_title = any(
        title in header
        for title in (
            "cibil report",
            "crif report",
            "credit information report",
            "consumer credit report",
        )
    )
    has_new_subject = any(
        marker in header
        for marker in (
            "consumer name",
            "applicant name",
            "subject name",
            "report id",
            "control number",
            "member reference number",
        )
    )
    return has_report_title and has_new_subject


def _looks_like_kfs_start(text: str) -> bool:
    normalized = _normalize_fresh_document_text(text)
    if not re.search(r"\bkey facts? statement(?: kfs)?\b", normalized):
        return False
    return any(
        marker in normalized
        for marker in (
            "part 1 interest rate fees charges",
            "sanctioned loan amount",
            "loan proposal ac no",
            "annual percentage rate",
        )
    )


def _looks_like_kfs_continuation(text: str) -> bool:
    normalized = _normalize_fresh_document_text(text)
    if not normalized:
        return False
    if any(
        marker in normalized
        for marker in (
            "part 2 other qualitative information",
            "illustration for computation of apr",
            "repayment schedule under equated periodic instalment",
        )
    ):
        return True
    if "key facts statement" in normalized and any(
        marker in normalized for marker in ("repayment schedule", "irr", "kfs")
    ):
        return True
    marker_families = (
        ("type of loan", "loan terms", "frequency of epis", "installments details"),
        ("annual percentage rate", "contingent charges", "net disbursed amount"),
        ("foreclosure charges", "prepayment charges", "long tenor fee", "rate reduction fee"),
        ("statement of a c charges", "duplicate repayment schedule", "cheque ecs bounce charges"),
        ("opening balance", "closing balance", "principal", "interest"),
        ("total interest amount", "total amount to be paid", "sanctioned loan amount"),
    )
    family_hits = sum(
        1 for family in marker_families if sum(1 for marker in family if marker in normalized) >= 2
    )
    return family_hits >= 1


def _looks_like_fresh_page_without_match(text: str) -> bool:
    raw_text = text or ""
    # Some digitally generated PDFs expose the entire page as one enormous
    # line.  Treating that whole line as a heading makes a continuation page
    # look "fresh" merely because words such as letter/report occur later in
    # boilerplate.  Document-boundary evidence belongs near the top of a page.
    raw_header_lines = raw_text.splitlines()[:6]
    normalized_text = _normalize_fresh_document_text(raw_text)
    if not normalized_text:
        return False

    # Strong title-like phrases only — bare generics like "form"/"statement"
    # appear on continuation pages and must not break inheritance.
    strong_title_phrases = (
        "key fact statement",
        "key facts statement",
        "sanction letter",
        "loan sanction",
        "facility agreement",
        "loan agreement",
        "customer application form",
        "loan application form",
        "credit approval memo",
        "credit appraisal memo",
        "bank statement",
        "account statement",
        "cibil report",
        "crif report",
        "credit information report",
        "consent letter",
        "end-use letter",
        "end use letter",
        "request for disbursal",
        "request for disbursement",
        "disbursement request",
        "drawdown request",
        "deed of guarantee",
        "acceptance letter",
        "certificate of stamp duty",
        "sale deed",
        "title deed",
        "registered deed",
        "વેચાણ દસ્તાવેજ",
        "માલિકી હક દસ્તાવેજ",
        "નોંધાયેલ દસ્તાવેજ",
        "permanent account number",
        "income tax department",
        "driving licence",
        "driving license",
        "election commission",
        "unique identification authority",
    )
    normalized_header_lines = [
        _normalize_fresh_document_text(line)
        for line in raw_header_lines
        if _normalize_fresh_document_text(line)
    ]
    if any(
        line == phrase
        or (line.startswith(f"{phrase} ") and len(line.split()) <= len(phrase.split()) + 5)
        for line in normalized_header_lines
        for phrase in strong_title_phrases
    ):
        return True

    # These phrases are document forms only when they look like a short title
    # near the top. Searching the entire page made contractual obligations such
    # as "submit an affidavit" appear to be new documents.
    title_like_terms = (
        "affidavit",
        "notary",
        "notarised",
        "notarized",
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
    extended_header_lines = [
        _normalize_fresh_document_text(line)
        for line in raw_text.splitlines()[:16]
        if _normalize_fresh_document_text(line)
    ]
    if any(
        line == normalized_term
        or (
            line.startswith(f"{normalized_term} ")
            and len(line.split()) <= len(normalized_term.split()) + 8
        )
        for line in extended_header_lines
        for term in title_like_terms
        if (normalized_term := _normalize_fresh_document_text(term))
    ):
        return True

    fuzzy_terms = ("शपथ", "हलफनामा", "पट्टा", "प्रपत्र", "नोटरी", "स्टाम्प", "न्यायिक", "घोषणा")
    header_text = " ".join(extended_header_lines)
    return any(
        _fuzzy_contains(header_text, _normalize_fresh_document_text(term)) for term in fuzzy_terms
    )


def _normalize_fresh_document_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
    cleaned = "".join(
        character
        if character.isalnum()
        or character == "-"
        or unicodedata.category(character).startswith("M")
        else " "
        for character in normalized
    )
    return re.sub(r"\s+", " ", cleaned).strip()


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

    # Keyword inference must only see the file name and its immediate parent
    # folder.  Matching the whole path lets a shared archive root (for example
    # "26000_Quality_Checker_Documents/") stamp one bogus type onto every
    # member of the ZIP ("Checker" once classified 175 pages as "Cheque").
    parts = [part for part in lower.split("/") if part]
    scope = " / ".join(parts[-2:]) if parts else ""

    image_suffix = suffix in {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
    if image_suffix and ("ration" in scope or "rashan" in scope):
        return "Ration Card Photo"
    if image_suffix and (
        any(term in scope for term in ("kyc", "aadhaar", "aadhar", "voter"))
        or re.search(r"\bpan\b", scope)
    ):
        return "KYC Card Photo"
    if image_suffix and any(folder in lower for folder in ("/collateral/", "/valuation/")):
        return "Property Image"

    # Direct keyword matches against the file name / immediate parent folder.
    # Short tokens use word boundaries so "company" is not PAN and
    # "checker"/"checklist" is not a Cheque.
    if re.search(r"\bpan\b", scope):
        return "PAN Card"
    if "aadhar" in scope or "aadhaar" in scope or "uidai" in scope:
        return "Aadhaar"
    if "passport" in scope:
        return "Passport"
    if (
        "driving" in scope
        or re.search(r"\bdl\b", scope)
        or "licence" in scope
        or "license" in scope
    ):
        return "Driving License"
    if "voter" in scope or re.search(r"\bepic\b", scope):
        return "Voter ID"
    if re.search(r"\bcheques?\b|\bchq\b|cancelled\s+check\b", scope):
        return "Cheque"
    if "spdc" in scope or re.search(r"(?:^|[/_\-\s])pdc(?:[/_\-\s.]|$)", scope):
        return "PDC"
    if "property paper" in scope or "proprty paper" in scope:
        return "Property Document"
    if "house photo" in scope:
        return "House Photo"
    if "working place" in scope or "workplace" in scope:
        return "Workplace Photo"
    if "technical report" in scope:
        return "Technical Report"
    if "ration card" in scope:
        return "Ration Card"
    if "cersai" in scope:
        return "CERSAI Report"
    if "insurance consent" in scope:
        return "Insurance Consent Letter"
    if "property insurance" in scope:
        return "Property Insurance Form"
    if "life insurance" in scope:
        return "Life Insurance Form"
    if "insurance" in scope:
        return "Insurance Form"
    if "banking" in scope:
        return "Bank Statement"
    if "statement" in scope or "bank_stmt" in scope or "bank stmt" in scope or "bankstmt" in scope:
        return "Bank Statement"
    if (
        "utility" in scope
        or "bill" in scope
        or "electricity" in scope
        or "water" in scope
        or "gas_bill" in scope
    ):
        return "Utility Bill"
    if "sanction" in scope or "loan_sanction" in scope:
        return "Sanction Letter"
    if "deed of guarantee" in scope or "guarantee deed" in scope:
        return "Guarantee Deed"
    if "agreement" in scope or "contract" in scope or "loan_agreement" in scope:
        return "Loan Agreement"
    if "salary" in scope or "pay slip" in scope or "payslip" in scope or "salary_slip" in scope:
        return "Salary Slip"
    if re.search(r"\bkfs\b", scope) or "key fact" in scope:
        return "KFS (Key Fact Statement)"
    if re.search(r"(?:^|[/_\-\s])cam(?:[/_\-\s.(]|$)", scope):
        return "CAM"

    # Unknown prose in a file or folder name is not a document type. Only the
    # generic markers above are safe evidence; everything else must degrade to
    # Unknown and sequence smoothing.
    return None


def _source_filename_override_allowed(source_type: str, detected_type: str) -> bool:
    """Do not let a generic KYC-photo folder erase a card's intrinsic type."""
    return not (source_type == "KYC Card Photo" and detected_type in _INTRINSIC_IDENTITY_TYPES)


def _is_email_correspondence(text: str) -> bool:
    """Recognize Outlook/Gmail exports and forwarded-message header blocks."""
    raw = str(text or "")
    header_hits = sum(
        bool(re.search(rf"(?im)^\s*{label}\b\s*:?\s*\S", raw))
        for label in ("from", "sent", "date", "to", "cc", "subject")
    )
    branded_export = bool(re.search(r"(?im)^\s*(?:outlook|gmail)\s*$", raw))
    return bool(
        (branded_export and header_hits >= 3)
        or header_hits >= 4
        or (header_hits >= 2 and len(_EMAIL_ADDRESS_RE.findall(raw)) >= 2)
    )


def _filename_type_contradicted_by_text(document_type: str, text: str) -> bool:
    """True when a filename-derived identity type conflicts with page content."""
    raw = str(text or "")
    if document_type in _EMAIL_INFERRED_EVIDENCE_TYPES and _is_email_correspondence(raw):
        # An approval email about insurance/PDC/cheques is correspondence, not
        # the underlying document named in its ZIP member filename.
        return True
    anchors = _FILENAME_IDENTITY_TYPE_ANCHORS.get(str(document_type or ""))
    if not anchors:
        return False
    if len(_EMAIL_ADDRESS_RE.findall(raw)) >= 2:
        # Email correspondence about a document is not the document itself.
        return True
    if len(raw.strip()) < 300:
        # Short/noisy OCR (card photos) cannot contradict the filename.
        return False
    lowered = raw.casefold()
    return not any(anchor in lowered for anchor in anchors)


def _image_evidence_type_from_text(text: str) -> str | None:
    normalized = _normalize_fresh_document_text(text)
    if not normalized:
        return None
    if "gps map camera" in normalized:
        return "Property Image"
    if any(term in normalized for term in ("ration card", "राशन कार्ड", "परिवार राशन")):
        return "Ration Card Photo"
    if any(
        term in normalized
        for term in ("unique identification authority", "uidai", "aadhaar", "pan card", "voter")
    ):
        return "KYC Card Photo"
    if any(
        term in normalized for term in ("patta", "पट्टा", "lease deed", "allotment order", "khasra")
    ):
        return "Property Document"
    return None


def _content_category_for_image_type(document_type: str) -> str:
    return {
        "Ration Card Photo": "ration_card_photo",
        "KYC Card Photo": "kyc_card_photo",
        "House Photo": "house_photo",
        "Workplace Photo": "workplace_photo",
        "Property Document": "property_document_photo",
    }.get(document_type, "property_image")
