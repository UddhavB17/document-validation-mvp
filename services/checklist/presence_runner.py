"""Checklist engine submodule."""

from __future__ import annotations

import os

from services.checklist.anomalies import check_presence_any, check_presence_min_count
from services.checklist.anomaly_builder import build_anomaly
from services.checklist.conditions import (
    _applicability_unknown_anomaly,
    _scoped_people,
    _system_flag_anomaly,
    condition_applies,
)
from services.checklist.page_helpers import (
    _document_evidence_count,
    _document_types,
    _find_pages,
    _matching_pages,
    _missing_presence_anomaly,
    _pages_for_person,
)


def _accuracy_checks_enabled() -> bool:
    return os.getenv("ENABLE_ACCURACY_CHECKS", "true").lower() in {"1", "true", "yes", "on"}


def _run_presence_checks(
    pages: list[dict],
    items: list[dict],
    system_data: dict,
) -> list[dict]:
    anomalies: list[dict] = []

    for item in items:
        # Some manual checklist controls live in the source system or a CSO
        # workflow rather than in the uploaded PDF.  Keep them visible in the
        # 44-item checklist, but do not treat absent PDF evidence as proof that
        # the control failed.
        if item.get("automated_presence_check", True) is False:
            continue

        check_type = item["check_type"]
        s_no = item.get("s_no")
        description = item.get("description", "")
        severity = item.get("severity_if_missing", "MEDIUM")
        document_type = item.get("document_type")

        applies = condition_applies(item.get("applies_when"), system_data)
        if applies is None:
            document_label = " / ".join(
                str(value) for value in _document_types(document_type) if value
            )
            anomalies.append(_applicability_unknown_anomaly(item, document_type=document_label))
            continue
        if applies is False:
            continue

        if check_type == "system_flag":
            anomaly = _system_flag_anomaly(item, system_data)
            if anomaly is not None:
                anomalies.append(anomaly)
            continue

        scoped_people = _scoped_people(item.get("scope"), system_data)
        if scoped_people:
            types = document_type if isinstance(document_type, list) else [document_type]
            for person_id in scoped_people:
                person_pages = _pages_for_person(pages, person_id)
                if item.get("check_type") == "presence_all":
                    missing_types = [
                        doc_type for doc_type in types if not _find_pages(person_pages, doc_type)
                    ]
                    for missing_type in missing_types:
                        anomalies.append(
                            _missing_presence_anomaly(
                                item, document_type=missing_type, person_id=person_id
                            )
                        )
                elif item.get("check_type") == "presence_min_count":
                    minimum = int(item.get("min_count") or 1)
                    found_count = sum(
                        _document_evidence_count(_find_pages(person_pages, doc_type), doc_type)[0]
                        for doc_type in types
                    )
                    if found_count < minimum:
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"MISSING_DOC_S{s_no}_{person_id}",
                                s_no=s_no,
                                severity=severity,
                                expected_value=f"At least {minimum} document(s) for {person_id}",
                                found_value=f"{found_count} found",
                                reason=description,
                                document_type=", ".join(types),
                                person_id=person_id,
                            )
                        )
                elif item.get("check_type") == "consistency_only":
                    continue
                elif not check_presence_any(person_pages, types)["passed"]:
                    anomalies.append(
                        _missing_presence_anomaly(
                            item, document_type=", ".join(types), person_id=person_id
                        )
                    )
            continue

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

        elif check_type == "consistency_only":
            if not _matching_pages(pages, document_type):
                anomalies.append(
                    _missing_presence_anomaly(
                        item,
                        document_type=" / ".join(_document_types(document_type)),
                    )
                )
            continue

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

        elif check_type == "presence_all":
            for required_type in document_type:
                if not _find_pages(pages, required_type):
                    anomalies.append(_missing_presence_anomaly(item, document_type=required_type))

        elif check_type == "requirements":
            applicability_unknown_reported = False
            for requirement in item.get("requirements") or []:
                requirement_applies = condition_applies(
                    requirement.get("applies_when"), system_data
                )
                if requirement_applies is None:
                    if not applicability_unknown_reported:
                        anomalies.append(
                            _applicability_unknown_anomaly(
                                item, document_type=str(requirement.get("document_type") or "")
                            )
                        )
                        applicability_unknown_reported = True
                    continue
                if requirement_applies is False:
                    continue
                required_type = str(requirement.get("document_type") or "")
                requirement_item = {**item, **requirement}
                requirement_scope = requirement.get("scope") or item.get("scope")
                required_people = _scoped_people(requirement_scope, system_data)
                requirement_check_type = str(requirement.get("check_type") or "presence")
                minimum = int(requirement.get("min_count") or 1)
                if required_people:
                    for person_id in required_people:
                        person_pages = _pages_for_person(pages, person_id)
                        found_count = _document_evidence_count(
                            _find_pages(person_pages, required_type), required_type
                        )[0]
                        if found_count < minimum:
                            anomalies.append(
                                build_anomaly(
                                    rule_id=f"MISSING_DOC_S{s_no}_{person_id}",
                                    s_no=s_no,
                                    severity=requirement_item.get("severity_if_missing", severity),
                                    expected_value=(
                                        f"At least {minimum} {required_type} document(s) for {person_id}"
                                        if requirement_check_type == "presence_min_count"
                                        or minimum > 1
                                        else f"Document present for {person_id}"
                                    ),
                                    found_value=f"{found_count} found",
                                    reason=description,
                                    document_type=required_type,
                                    person_id=person_id,
                                )
                            )
                else:
                    found_count = _document_evidence_count(
                        _find_pages(pages, required_type), required_type
                    )[0]
                    if found_count < minimum:
                        anomalies.append(
                            build_anomaly(
                                rule_id=f"MISSING_DOC_S{s_no}",
                                s_no=s_no,
                                severity=requirement_item.get("severity_if_missing", severity),
                                expected_value=(
                                    f"At least {minimum} {required_type} document(s)"
                                    if requirement_check_type == "presence_min_count" or minimum > 1
                                    else "Document present"
                                ),
                                found_value=f"{found_count} found",
                                reason=description,
                                document_type=required_type,
                            )
                        )

    return anomalies
