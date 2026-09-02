"""Checklist engine submodule."""

from __future__ import annotations

import re

from services.checklist._fuzzy import fuzz
from services.checklist.anomaly_builder import build_anomaly
from services.checklist.page_helpers import _find_pages_any_confidence
from services.config import effective_config
from services.processing_policy import is_ocr_skipped_page


def _run_quality_checks(pages: list[dict], ground_truth: dict) -> list[dict]:
    anomalies: list[dict] = []
    primary_id = str(ground_truth.get("person_id") or "primary")
    pan_pages = [
        page
        for page in _find_pages_any_confidence(pages, "PAN")
        if str(page.get("person_id") or page.get("applicant_role") or "") == primary_id
    ]
    ocr_threshold = float(effective_config().min_scanned_ocr_confidence)
    image_heavy_types = {
        "property image",
        "gps",
        "photo",
        "screenshot",
        "ocr skipped",
        "house photo",
        "workplace photo",
        "kyc card photo",
        "ration card photo",
    }

    for page in pages:
        if is_ocr_skipped_page(page):
            continue

        page_number = page.get("page_number")
        document_type = page.get("document_type")
        doc_type_key = str(document_type or "").strip().lower()
        if doc_type_key in image_heavy_types:
            continue

        if page.get("is_readable") is False:
            anomalies.append(
                build_anomaly(
                    "UNREADABLE_PAGE",
                    None,
                    "MEDIUM",
                    "Clear scan",
                    "Blurry or unreadable",
                    "Page scan quality too low for OCR",
                    page_number,
                    document_type,
                )
            )

        confidence = page.get("ocr_confidence", page.get("confidence"))
        if (
            page.get("page_type") == "scanned"
            and confidence is not None
            and confidence < ocr_threshold
        ):
            anomalies.append(
                build_anomaly(
                    "LOW_OCR_CONFIDENCE",
                    None,
                    "LOW",
                    f"Confidence above {ocr_threshold:.0%}",
                    f"{confidence:.0%} confidence",
                    "OCR confidence below acceptable threshold",
                    page_number,
                    document_type,
                )
            )

        if document_type in (None, "Unknown"):
            ocr_text = str(page.get("ocr_text") or "").strip()
            # Blank / nearly blank trailing pages are not actionable unclassified docs.
            if len(re.sub(r"\s+", "", ocr_text)) < 40:
                continue
            anomalies.append(
                build_anomaly(
                    "UNCLASSIFIED_PAGE",
                    None,
                    "LOW",
                    "Known document type",
                    "Unknown",
                    "Page could not be classified",
                    page_number,
                    document_type,
                )
            )

    if pan_pages:
        pan_fields = pan_pages[0].get("extracted_fields", {})
        pan_number = pan_fields.get("pan_number")
        if pan_number and not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]{1}", str(pan_number).upper()):
            anomalies.append(
                build_anomaly(
                    "INVALID_PAN_FORMAT",
                    None,
                    "HIGH",
                    "Valid PAN format",
                    pan_number,
                    "PAN number format is invalid",
                    pan_pages[0].get("page_number"),
                    "PAN",
                )
            )

        ground_pan = ground_truth.get("pan_number")
        if ground_pan and pan_number and str(ground_pan).upper() != str(pan_number).upper():
            anomalies.append(
                build_anomaly(
                    "PAN_NUMBER_MISMATCH",
                    None,
                    "HIGH",
                    ground_pan,
                    pan_number,
                    "PAN number differs from digital application form",
                    pan_pages[0].get("page_number"),
                    "PAN",
                )
            )

        ground_name = ground_truth.get("applicant_name")
        pan_name = pan_fields.get("applicant_name")
        if ground_name and pan_name:
            try:
                from services.person_ownership import name_matches_trusted_person

                primary_record = (
                    (ground_truth.get("people") or {}).get(primary_id)
                    or (ground_truth.get("reference_data") or {}).get(primary_id)
                    or ground_truth
                )
                if name_matches_trusted_person(pan_name, primary_record):
                    pan_name = None
            except Exception:
                pass
        if ground_name and pan_name:
            score = fuzz.ratio(str(ground_name).strip().lower(), str(pan_name).strip().lower())
            if 75 <= score < 90:
                anomalies.append(
                    build_anomaly(
                        "BORDERLINE_NAME_MATCH",
                        None,
                        "MEDIUM",
                        ground_name,
                        pan_name,
                        f"Name match score {score}%, review needed",
                        pan_pages[0].get("page_number"),
                        "PAN",
                    )
                )
            elif score < 75:
                anomalies.append(
                    build_anomaly(
                        "NAME_MISMATCH",
                        None,
                        "HIGH",
                        ground_name,
                        pan_name,
                        f"Name match score {score}%, likely mismatch",
                        pan_pages[0].get("page_number"),
                        "PAN",
                    )
                )

    return anomalies
