"""Checklist engine submodule."""

from __future__ import annotations

from datetime import datetime

from services.checklist._dates import _parse_date
from services.checklist._fuzzy import fuzz
from services.checklist.page_helpers import _document_evidence_count, _find_pages
from services.page_quality import is_confident_document_match
from services.person_names import is_person_name_candidate


def check_presence_any(pages: list[dict], document_types: list[str]) -> dict:
    found_types = {
        document_type
        for document_type in document_types
        if any(is_confident_document_match(page, document_type) for page in pages)
    }
    found = any(document_type in found_types for document_type in document_types)

    if not found:
        return {
            "passed": False,
            "found_value": "None of required types found",
            "expected_value": f"Any one of: {', '.join(document_types)}",
        }

    matched = [document_type for document_type in document_types if document_type in found_types]
    return {"passed": True, "found_value": matched[0]}


def check_field_match(
    extracted_fields: dict, system_data: dict, field_names: list[str]
) -> list[dict]:
    anomalies = []

    for field in field_names:
        system_val = system_data.get(field)
        extracted_val = extracted_fields.get(field)
        if system_val in (None, "") or extracted_val in (None, ""):
            continue
        if field in {"applicant_name", "borrower_name", "account_holder_name", "name"} and (
            not is_person_name_candidate(system_val) or not is_person_name_candidate(extracted_val)
        ):
            continue

        if field in ["loan_amount", "emi", "tenure", "roi", "interest_rate"]:
            try:
                sys_num = float(str(system_val).replace(",", ""))
                ext_num = float(str(extracted_val).replace(",", ""))
                tolerance = sys_num * 0.01
                if abs(sys_num - ext_num) > tolerance:
                    anomalies.append(
                        {"field": field, "expected": system_val, "found": extracted_val}
                    )
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
    found_count, unit = _document_evidence_count(found_pages, document_type)
    if found_count >= min_count:
        return {
            "passed": True,
            "found_value": f"{found_count} {unit}",
            "expected_value": f"At least {min_count}",
        }
    return {
        "passed": False,
        "found_value": f"{found_count} {unit}",
        "expected_value": f"At least {min_count} {unit} of {document_type}",
    }
