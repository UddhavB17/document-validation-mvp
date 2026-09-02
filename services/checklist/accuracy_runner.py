"""Checklist engine submodule."""

from __future__ import annotations

from datetime import datetime

from services.checklist._dates import _parse_date
from services.checklist.anomalies import check_date_range, check_field_match
from services.checklist.anomaly_builder import build_anomaly
from services.checklist.bank_period import _bank_period_anomaly
from services.checklist.conditions import _people, condition_applies
from services.checklist.page_helpers import (
    _distinct_document_key,
    _document_types,
    _field_from_pages,
    _has_explicit_status_field,
    _is_positive_status,
    _matching_pages,
    _numeric,
    _page_status,
    _status_looks_like_full_page_fallback,
)


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

        applies = condition_applies(item.get("applies_when"), system_data)
        if applies is not True:
            continue

        if check_type == "presence_and_match":
            doc_pages = _matching_pages(pages, document_type)
            if doc_pages:
                emitted_fields: set[str] = set()
                people = _people(system_data)
                multi_person = len(people) > 1
                for page in doc_pages:
                    person_id = str(page.get("person_id") or page.get("applicant_role") or "")
                    if person_id in {"", "unassigned", "unknown"}:
                        # Ownership unresolved — do not compare against primary dump.
                        continue
                    if multi_person and person_id not in people:
                        continue
                    expected_data = people[person_id] if person_id in people else system_data
                    mismatches = check_field_match(
                        page.get("extracted_fields", {}), expected_data, [item["match_field"]]
                    )
                    for mismatch in mismatches:
                        field_key = f"{person_id}:{mismatch['field']}"
                        if field_key in emitted_fields:
                            continue
                        emitted_fields.add(field_key)
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"FIELD_MISMATCH_S{s_no}",
                                s_no=s_no,
                                severity=item.get("severity_if_mismatch", "HIGH"),
                                expected_value=str(mismatch["expected"]),
                                found_value=str(mismatch["found"]),
                                reason=f"{document_type} field mismatch: {mismatch['field']}",
                                page_number=page.get("page_number"),
                                document_type=" / ".join(_document_types(document_type)),
                                person_id=person_id or None,
                            )
                        )

        elif check_type == "field_match":
            doc_pages = _matching_pages(pages, document_type)
            if doc_pages:
                emitted_fields: set[str] = set()
                for page in doc_pages:
                    mismatches = check_field_match(
                        page.get("extracted_fields", {}), system_data, item.get("match_fields", [])
                    )
                    for mismatch in mismatches:
                        field_name = str(mismatch["field"])
                        if field_name in emitted_fields:
                            continue
                        emitted_fields.add(field_name)
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"FIELD_MISMATCH_S{s_no}",
                                s_no=s_no,
                                severity=item.get("severity_if_mismatch", "HIGH"),
                                expected_value=str(mismatch["expected"]),
                                found_value=str(mismatch["found"]),
                                reason=f"Loan document field mismatch: {mismatch['field']}",
                                page_number=page.get("page_number"),
                                document_type=str(page.get("document_type") or document_type),
                            )
                        )

        elif check_type == "date_range":
            doc_pages = _matching_pages(pages, document_type)
            if doc_pages:
                result = check_date_range(
                    doc_pages[0].get("extracted_fields", {}), item["min_months"]
                )
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

        elif check_type == "period_minimum_months":
            doc_pages = _matching_pages(pages, document_type)
            if doc_pages:
                anomaly = _bank_period_anomaly(
                    pages=doc_pages,
                    item=item,
                    system_data=system_data,
                )
                if anomaly is not None:
                    anomalies.append(anomaly)

        elif check_type == "document_age_max_months":
            doc_pages = _matching_pages(pages, document_type)
            maximum = float(item.get("max_months") or 0)
            for page in doc_pages:
                fields = page.get("extracted_fields") or {}
                date_value = next(
                    (
                        fields.get(field_name)
                        for field_name in item.get("document_fields", [])
                        if fields.get(field_name) not in (None, "")
                    ),
                    None,
                )
                if date_value in (None, ""):
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"FIELD_VALUE_MISSING_S{s_no}",
                            s_no=s_no,
                            severity="LOW",
                            expected_value="Utility-bill date available",
                            found_value="Date not extracted",
                            reason=description,
                            page_number=page.get("page_number"),
                            document_type=str(page.get("document_type")),
                        )
                    )
                    continue
                try:
                    age_months = (datetime.now() - _parse_date(date_value)).days / 30
                except Exception:
                    age_months = maximum + 1
                if age_months > maximum:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"DATE_CHECK_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_fail", "HIGH"),
                            expected_value=f"Not older than {maximum:g} months",
                            found_value=f"{max(0, age_months):.1f} months old",
                            reason=description,
                            page_number=page.get("page_number"),
                            document_type=str(page.get("document_type")),
                        )
                    )

        elif check_type == "date_not_after":
            doc_pages = _matching_pages(pages, document_type)
            found_value, found_page = _field_from_pages(doc_pages, *item.get("document_fields", []))
            expected_value = system_data.get(item.get("system_field"))
            if found_value not in (None, "") and expected_value not in (None, ""):
                try:
                    passed = _parse_date(found_value).date() <= _parse_date(expected_value).date()
                except Exception:
                    passed = False
                if not passed:
                    anomalies.append(
                        build_anomaly(
                            rule_id=f"DATE_CHECK_S{s_no}",
                            s_no=s_no,
                            severity=item.get("severity_if_fail", "HIGH"),
                            expected_value=f"On or before {expected_value}",
                            found_value=found_value,
                            reason=description,
                            page_number=(found_page or {}).get("page_number"),
                            document_type=" / ".join(_document_types(document_type)),
                        )
                    )

        elif check_type == "field_less_than":
            doc_pages = _matching_pages(pages, document_type)
            found_value, found_page = _field_from_pages(doc_pages, *item.get("document_fields", []))
            expected_value = system_data.get(item.get("system_field"))
            found_number, expected_number = _numeric(found_value), _numeric(expected_value)
            if (
                found_number is not None
                and expected_number is not None
                and found_number >= expected_number
            ):
                anomalies.append(
                    build_anomaly(
                        rule_id=f"FIELD_RELATION_S{s_no}",
                        s_no=s_no,
                        severity=item.get("severity_if_fail", "MEDIUM"),
                        expected_value=f"Less than {expected_value}",
                        found_value=found_value,
                        reason=description,
                        page_number=(found_page or {}).get("page_number"),
                        document_type=" / ".join(_document_types(document_type)),
                    )
                )

        elif check_type == "required_status":
            doc_pages = _matching_pages(pages, document_type)
            accepted = item.get("accepted_statuses") or [
                "clear",
                "cleared",
                "positive",
                "approved",
                "registered",
            ]
            rejected = item.get("rejected_statuses") or [
                "not clear",
                "not cleared",
                "negative",
                "rejected",
                "pending",
            ]
            status_fields = item.get("status_fields") or ["status"]

            # Partition pages: those that pass vs those that fail the status check.
            passing_pages = [
                page
                for page in doc_pages
                if _is_positive_status(page, accepted, rejected, status_fields)
            ]
            # If ANY page in the document group has a passing status, treat the
            # whole document as cleared — no anomaly needed.
            if passing_pages:
                pass  # at least one page confirms clearance
            else:
                failing_pages = [page for page in doc_pages if page not in passing_pages]
                if failing_pages:
                    first = failing_pages[0]
                    # Check if the failing page relied on full OCR text (no dedicated
                    # status field found) AND has low OCR confidence.
                    first_has_status_field = _has_explicit_status_field(first, status_fields)
                    first_ocr_conf = float(first.get("ocr_confidence") or 1.0)
                    low_conf_fallback = not first_has_status_field and first_ocr_conf < 0.60
                    # Valuation/report cover pages rarely embed "cleared/approved" wording.
                    # Do not HIGH-fail just because whole-page OCR lacks those tokens.
                    unverifiable_fallback = (
                        not first_has_status_field
                        and all(
                            _status_looks_like_full_page_fallback(page, status_fields)
                            for page in failing_pages
                        )
                        and not any(
                            term.lower() in _page_status(page, status_fields)
                            for page in failing_pages
                            for term in rejected
                        )
                    )

                    page_preview = ", ".join(
                        str(page.get("page_number"))
                        for page in failing_pages[:6]
                        if page.get("page_number") is not None
                    )
                    if len(failing_pages) > 6:
                        page_preview += f", … (+{len(failing_pages) - 6} more)"

                    if low_conf_fallback or unverifiable_fallback:
                        # Cannot verify status reliably — emit a softer warning instead
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"STATUS_UNVERIFIABLE_S{s_no}",
                                s_no=s_no,
                                severity="LOW",
                                expected_value=" / ".join(accepted),
                                found_value=(
                                    (
                                        f"OCR confidence {first_ocr_conf:.0%} — status field not extractable"
                                        if low_conf_fallback
                                        else "No explicit clearance status field on valuation/report pages"
                                    )
                                    + (
                                        f" across {len(failing_pages)} page(s): {page_preview}"
                                        if len(failing_pages) > 1
                                        else ""
                                    )
                                ),
                                reason=f"{description} (status not explicitly extractable; manual review)",
                                page_number=first.get("page_number"),
                                document_type=str(first.get("document_type") or document_type),
                            )
                        )
                    else:
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"STATUS_CHECK_S{s_no}",
                                s_no=s_no,
                                severity=item.get("severity_if_fail", "HIGH"),
                                expected_value=" / ".join(accepted),
                                found_value=(
                                    f"{_page_status(first, status_fields)[:120] or 'Status not found'}"
                                    + (
                                        f" across {len(failing_pages)} page(s): {page_preview}"
                                        if len(failing_pages) > 1
                                        else ""
                                    )
                                ),
                                reason=description,
                                page_number=first.get("page_number"),
                                document_type=str(first.get("document_type") or document_type),
                            )
                        )

        elif check_type == "distinct_positive_count":
            doc_pages = _matching_pages(pages, document_type)
            positive_pages = [
                page
                for page in doc_pages
                if _is_positive_status(
                    page,
                    item.get("accepted_statuses") or ["positive", "clear", "cleared", "approved"],
                    item.get("rejected_statuses")
                    or ["negative", "rejected", "not clear", "not cleared"],
                    item.get("status_fields") or ["status", "report_status"],
                )
            ]
            distinct_count = len({_distinct_document_key(page) for page in positive_pages})
            minimum = int(item.get("min_count") or 1)
            if distinct_count < minimum:
                anomalies.append(
                    build_anomaly(
                        rule_id=f"COUNT_STATUS_CHECK_S{s_no}",
                        s_no=s_no,
                        severity=item.get("severity_if_fail", "HIGH"),
                        expected_value=f"At least {minimum} distinct positive report(s)",
                        found_value=f"{distinct_count} distinct positive report(s)",
                        reason=description,
                        document_type=" / ".join(_document_types(document_type)),
                    )
                )

    return anomalies
