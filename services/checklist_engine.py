"""Checklist matching logic."""

import os
from datetime import datetime
import re

from services import checklist_service

try:
    from rapidfuzz import fuzz
except Exception:
    from difflib import SequenceMatcher

    class fuzz:
        @staticmethod
        def ratio(left: str, right: str) -> int:
            return int(SequenceMatcher(None, left, right).ratio() * 100)


def _parse_date(value: object) -> datetime:
    try:
        from dateutil import parser

        return parser.parse(str(value))
    except Exception:
        return datetime.fromisoformat(str(value))


def build_anomaly(
    rule_id: str,
    s_no: int | None,
    severity: str,
    expected_value: object,
    found_value: object,
    reason: str,
    page_number: int | None = None,
    document_type: str | None = None,
) -> dict:
    return {
        "rule_id": rule_id,
        "s_no": s_no,
        "severity": severity,
        "document_type": document_type,
        "expected_value": expected_value,
        "found_value": found_value,
        "page_number": page_number,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }


def check_presence_any(pages: list[dict], document_types: list[str]) -> dict:
    found_types = {page.get("document_type") for page in pages if page.get("document_type")}
    found = any(document_type in found_types for document_type in document_types)

    if not found:
        return {
            "passed": False,
            "found_value": "None of required types found",
            "expected_value": f"Any one of: {', '.join(document_types)}",
        }

    matched = [document_type for document_type in document_types if document_type in found_types]
    return {"passed": True, "found_value": matched[0]}


def check_field_match(extracted_fields: dict, system_data: dict, field_names: list[str]) -> list[dict]:
    anomalies = []

    for field in field_names:
        system_val = system_data.get(field)
        extracted_val = extracted_fields.get(field)
        if system_val in (None, "") or extracted_val in (None, ""):
            continue

        if field in ["loan_amount", "emi", "tenure"]:
            try:
                sys_num = float(str(system_val).replace(",", ""))
                ext_num = float(str(extracted_val).replace(",", ""))
                tolerance = sys_num * 0.01
                if abs(sys_num - ext_num) > tolerance:
                    anomalies.append({"field": field, "expected": system_val, "found": extracted_val})
            except Exception:
                continue
        elif field == "pan_number":
            if str(system_val).upper() != str(extracted_val).upper():
                anomalies.append({"field": field, "expected": system_val, "found": extracted_val})
        else:
            score = fuzz.ratio(str(system_val).lower(), str(extracted_val).lower())
            if score < 85:
                anomalies.append(
                    {
                        "field": field,
                        "expected": system_val,
                        "found": extracted_val,
                        "match_score": score,
                    }
                )

    return anomalies


def check_date_range(extracted_fields: dict, min_months: int) -> dict:
    date_val = extracted_fields.get("statement_period_end")
    if not date_val:
        return {"passed": False, "reason": "Statement date not found"}

    try:
        parsed = _parse_date(date_val)
        months_old = (datetime.now() - parsed).days / 30
        if months_old > min_months:
            return {
                "passed": False,
                "found_value": f"{int(months_old)} months old",
                "expected_value": f"Within {min_months} months",
            }
        return {"passed": True}
    except Exception:
        return {"passed": False, "reason": "Could not parse statement date"}


def check_presence_min_count(pages: list[dict], document_type: str, min_count: int) -> dict:
    found_pages = _find_pages(pages, document_type)
    if len(found_pages) >= min_count:
        return {
            "passed": True,
            "found_value": f"{len(found_pages)} page(s)",
            "expected_value": f"At least {min_count}",
        }
    return {
        "passed": False,
        "found_value": f"{len(found_pages)} page(s)",
        "expected_value": f"At least {min_count} page(s) of {document_type}",
    }


def _accuracy_checks_enabled() -> bool:
    return os.getenv("ENABLE_ACCURACY_CHECKS", "true").lower() in {"1", "true", "yes", "on"}


def _run_presence_checks(
    pages: list[dict],
    items: list[dict],
) -> list[dict]:
    anomalies: list[dict] = []

    for item in items:
        check_type = item["check_type"]
        s_no = item.get("s_no")
        description = item.get("description", "")
        severity = item.get("severity_if_missing", "MEDIUM")
        document_type = item.get("document_type")

        if check_type == "presence":
            found = bool(_find_pages(pages, document_type))
            if not found:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"MISSING_DOC_S{s_no}",
                        s_no=s_no,
                        severity=severity,
                        expected_value="Document present",
                        found_value="Not found in file",
                        reason=description,
                        document_type=document_type,
                    )
                )

        elif check_type == "presence_any":
            result = check_presence_any(pages, document_type)
            if not result["passed"]:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"MISSING_DOC_S{s_no}",
                        s_no=s_no,
                        severity=severity,
                        expected_value=result["expected_value"],
                        found_value=result["found_value"],
                        reason=description,
                        document_type=", ".join(document_type),
                    )
                )

        elif check_type == "presence_min_count":
            min_count = int(item.get("min_count") or 1)
            result = check_presence_min_count(pages, document_type, min_count)
            if not result["passed"]:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"MISSING_DOC_S{s_no}",
                        s_no=s_no,
                        severity=severity,
                        expected_value=result["expected_value"],
                        found_value=result["found_value"],
                        reason=description,
                        document_type=document_type,
                    )
                )

    return anomalies


def _find_pages(pages: list[dict], document_type: str) -> list[dict]:
    return [page for page in pages if page.get("document_type") == document_type]


def _run_accuracy_checks(
    pages: list[dict],
    ground_truth: dict,
    system_data: dict,
    items: list[dict],
) -> list[dict]:
    anomalies: list[dict] = []

    for item in items:
        check_type = item["check_type"]
        s_no = item.get("s_no")
        description = item.get("description", "")
        document_type = item.get("document_type")

        if check_type == "presence_and_match":
            doc_pages = _find_pages(pages, document_type)
            if doc_pages:
                mismatches = check_field_match(
                    doc_pages[0].get("extracted_fields", {}),
                    system_data,
                    [item["match_field"]],
                )
                for mismatch in mismatches:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"FIELD_MISMATCH_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_mismatch", "HIGH"),
                            expected_value=str(mismatch["expected"]),
                            found_value=str(mismatch["found"]),
                            reason=f"{document_type} field mismatch: {mismatch['field']}",
                            page_number=doc_pages[0].get("page_number"),
                            document_type=document_type,
                        )
                    )

        elif check_type == "field_match":
            doc_pages = _find_pages(pages, document_type)
            if doc_pages:
                mismatches = check_field_match(
                    doc_pages[0].get("extracted_fields", {}),
                    system_data,
                    item.get("match_fields", []),
                )
                for mismatch in mismatches:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"FIELD_MISMATCH_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_mismatch", "HIGH"),
                            expected_value=str(mismatch["expected"]),
                            found_value=str(mismatch["found"]),
                            reason=f"{document_type} field mismatch: {mismatch['field']}",
                            page_number=doc_pages[0].get("page_number"),
                            document_type=document_type,
                        )
                    )

        elif check_type == "date_range":
            doc_pages = _find_pages(pages, document_type)
            if doc_pages:
                result = check_date_range(doc_pages[0].get("extracted_fields", {}), item["min_months"])
                if not result["passed"]:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"DATE_CHECK_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_fail", "MEDIUM"),
                            expected_value=result.get("expected_value", ""),
                            found_value=result.get("found_value", ""),
                            reason=result.get("reason", description),
                            page_number=doc_pages[0].get("page_number"),
                            document_type=document_type,
                        )
                    )

    return anomalies



def run_checks(
    pages: list[dict],
    ground_truth: dict,
    system_data: dict | None,
    product_type: str,
) -> list[dict]:
    system_data = system_data or ground_truth or {}
    presence_items = checklist_service.get_ai_checkable_items(product_type)
    relevance_anomaly = _non_loan_relevance_anomaly(pages, presence_items)
    if relevance_anomaly is not None:
        return [relevance_anomaly]
    anomalies = _run_presence_checks(pages, presence_items)

    if _accuracy_checks_enabled():
        accuracy_items = checklist_service.get_accuracy_check_items(product_type)
        anomalies.extend(_run_accuracy_checks(pages, ground_truth, system_data, accuracy_items))

    anomalies.extend(_run_quality_checks(pages, ground_truth))
    return anomalies


def _non_loan_relevance_anomaly(
    pages: list[dict],
    presence_items: list[dict],
) -> dict | None:
    """Return one anomaly when uploaded file appears unrelated to loan processing.

    We only short-circuit when:
    - there are pages, and
    - no required checklist document type is detected anywhere, and
    - almost all pages are unclassified/unknown.
    """
    if not pages:
        return None

    expected_types: set[str] = set()
    for item in presence_items:
        document_type = item.get("document_type")
        if isinstance(document_type, str) and document_type:
            expected_types.add(document_type)
        elif isinstance(document_type, list):
            expected_types.update(str(value) for value in document_type if value)

    if not expected_types:
        return None

    doc_types = [str(page.get("document_type") or "").strip() for page in pages]
    matched_expected = sum(1 for item in doc_types if item in expected_types)
    unknown_count = sum(1 for item in doc_types if item in {"", "Unknown", "None"})
    unknown_ratio = unknown_count / max(1, len(doc_types))

    # Keep valid loan files unaffected: only block obvious non-loan uploads.
    if matched_expected > 0 or unknown_ratio < 0.8:
        return None

    return build_anomaly(
        rule_id="UNSUPPORTED_DOCUMENT_TYPE",
        s_no=None,
        severity="HIGH",
        expected_value="Loan-file documents matching checklist",
        found_value=f"No expected document classes detected across {len(pages)} pages",
        reason="Uploaded PDF appears unrelated to the loan checklist workflow.",
        page_number=1,
        document_type="Unsupported",
    )


def _run_quality_checks(pages: list[dict], ground_truth: dict) -> list[dict]:
    anomalies: list[dict] = []
    pan_pages = _find_pages(pages, "PAN")

    for page in pages:
        page_number = page.get("page_number")
        document_type = page.get("document_type")
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
        if page.get("page_type") == "scanned" and confidence is not None and confidence < 0.70:
            anomalies.append(
                build_anomaly(
                    "LOW_OCR_CONFIDENCE",
                    None,
                    "LOW",
                    "Confidence above 70%",
                    f"{confidence:.0%} confidence",
                    "OCR confidence below acceptable threshold",
                    page_number,
                    document_type,
                )
            )

        if document_type in (None, "Unknown"):
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
            score = fuzz.ratio(str(ground_name), str(pan_name))
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

    for bank_page in _find_pages(pages, "Bank Statement"):
        result = check_date_range(bank_page.get("extracted_fields", {}), 6)
        if not result["passed"] and result.get("found_value"):
            anomalies.append(
                build_anomaly(
                    "STATEMENT_TOO_OLD",
                    None,
                    "MEDIUM",
                    result.get("expected_value", "Recent statement"),
                    result.get("found_value", ""),
                    "Bank statement is older than allowed recency window",
                    bank_page.get("page_number"),
                    "Bank Statement",
                )
            )

    return anomalies


def evaluate_checklist(checklist: dict, extracted_documents: dict) -> list[dict]:
    required_docs = checklist.get("required_documents", [])
    found_docs = set(extracted_documents.keys())
    return [
        {"document": doc_name, "issue": "missing"}
        for doc_name in required_docs
        if doc_name not in found_docs
    ]
