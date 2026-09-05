"""Operations payload builder for ``GET /ops/applications/{id}``.

Owned by ``ws-f-accuracy-ops-api`` per contracts §5. Everything a
non-technical user sees comes from this endpoint: finding codes only (never
rule IDs), EN/HI strings from :mod:`services.ops_templates_en_hi`, at most
five top findings, no OCR text or JSON dumps.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from typing import Any

from database.db import get_connection
from services.ops_templates_en_hi import (
    CODE_ORDER,
    SEVERITY_ORDER,
    document_label,
    render,
)

LOGGER = logging.getLogger(__name__)

TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled", "stale"})
FAILED_JOB_STATUSES = frozenset({"failed"})

# Rule-ID families per contracts §11, in code priority order. First match wins;
# anything unmapped is admin-only and excluded from the operations payload.
CODE_PATTERNS: list[tuple[str, list[str]]] = [
    (
        "NAME_MISMATCH",
        [
            "APPLICANT_NAME_MISMATCH",
            "TRUSTED_*NAME*MISMATCH",
            "CROSS_DOCUMENT_APPLICANT_NAME_MISMATCH",
            "NAME_MISMATCH",
            "APPLICATION_NAME_MISMATCH",
            "BORDERLINE_NAME_MATCH",
        ],
    ),
    (
        "ID_MISMATCH",
        [
            "PAN_NUMBER_MISMATCH",
            "AADHAAR_NUMBER_MISMATCH",
            "TRUSTED_PAN_*",
            "TRUSTED_AADHAAR_*",
            "DATE_OF_BIRTH_MISMATCH",
            "INVALID_PAN_FORMAT",
            "DL_NUMBER_MISMATCH",
            "VOTER_ID_NUMBER_MISMATCH",
            "TRUSTED_DL_*",
            "TRUSTED_VOTER_*",
        ],
    ),
    (
        "ADDRESS_MISMATCH",
        [
            "TRUSTED_*ADDRESS*MISMATCH",
            "CROSS_DOCUMENT_ADDRESS_MISMATCH",
            "AADHAAR_ADDRESS_MISMATCH",
            "ADDRESS_MISMATCH",
        ],
    ),
    ("MISSING_DOCUMENT", ["MISSING_DOC*", "DOCUMENT_MISSING"]),
    ("BANK_STATEMENT_OLD", ["PERIOD_*", "DATE_CHECK_S*"]),
    ("PAGE_UNREADABLE", ["UNREADABLE_PAGE", "DOCUMENT_NOT_READABLE"]),
    (
        "OCR_FAILED",
        ["LOW_OCR_CONFIDENCE*", "LOW_CONFIDENCE_PAGE", "OCR_BUDGET_PARTIAL_SCAN"],
    ),
    (
        "DATA_MISSING",
        ["*_NOT_FOUND", "*_EXTRACTION_UNRELIABLE", "FIELD_VALUE_MISSING_S*"],
    ),
    ("PROCESSING_ERROR", ["PAGE_PROCESSING_ERROR"]),
]

SUMMARY_PHRASES: dict[str, dict[str, str]] = {
    "NAME_MISMATCH": {"en": "name mismatch", "hi": "नाम मेल नहीं खाता"},
    "ID_MISMATCH": {"en": "PAN mismatch", "hi": "पैन मेल नहीं खाता"},
    "ADDRESS_MISMATCH": {"en": "address mismatch", "hi": "पता मेल नहीं खाता"},
    "MISSING_DOCUMENT": {"en": "missing document", "hi": "दस्तावेज़ नहीं मिला"},
    "BANK_STATEMENT_OLD": {
        "en": "bank statement older than 3 months",
        "hi": "बैंक स्टेटमेंट 3 महीने से पुराना",
    },
    "PAGE_UNREADABLE": {"en": "blurry page", "hi": "धुंधला पृष्ठ"},
    "OCR_FAILED": {"en": "page could not be read", "hi": "पृष्ठ पढ़ा नहीं जा सका"},
    "DATA_MISSING": {"en": "information missing", "hi": "जानकारी नहीं मिली"},
    "PROCESSING_ERROR": {"en": "processing error", "hi": "प्रसंस्करण त्रुटि"},
}


def rule_to_code(rule_id: str | None) -> str | None:
    """Map an internal rule ID to an operations finding code (or None)."""
    rule = str(rule_id or "").strip()
    if not rule:
        return None
    for code, patterns in CODE_PATTERNS:
        if any(fnmatch.fnmatchcase(rule, pattern) for pattern in patterns):
            return code
    return None


def _severity_key(severity: Any) -> int:
    return SEVERITY_ORDER.get(str(severity or "LOW").upper(), 3)


def _pages_phrase(pages: list[int], lang: str) -> str:
    joined = ", ".join(str(page) for page in pages)
    if lang == "hi":
        return f"पृष्ठ {joined}"
    return f"page {joined}" if len(pages) == 1 else f"pages {joined}"


def _months_from_found(found: Any) -> str:
    match = re.search(r"([\d]+(?:\.[\d]+)?)\s*months?\s*old", str(found or ""))
    if match:
        try:
            return str(int(float(match.group(1))))
        except (TypeError, ValueError):
            return match.group(1)
    return ""


def _anomaly_pages(anomaly: dict) -> list[int]:
    pages: list[int] = []
    collapsed = anomaly.get("collapsed_page_numbers")
    if isinstance(collapsed, list):
        pages.extend(int(p) for p in collapsed if p is not None)
    for key in ("page_number", "page"):
        value = anomaly.get(key)
        if value is not None:
            try:
                pages.append(int(value))
            except (TypeError, ValueError):
                continue
    return sorted(set(pages))


def _evidence_shape(evidence: Any) -> dict | None:
    if not isinstance(evidence, dict):
        return None
    page = evidence.get("page")
    bbox = evidence.get("bbox")
    try:
        page_num = int(page) if page is not None else None
    except (TypeError, ValueError):
        page_num = None
    if (
        page_num is None
        or not isinstance(bbox, (list, tuple))
        or len(bbox) != 4
    ):
        return None
    try:
        bbox_floats = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return None
    return {
        "page": page_num,
        "bbox": bbox_floats,
        "text": str(evidence.get("text") or ""),
    }


def _finding_from_group(code: str, items: list[dict]) -> dict:
    ordered = sorted(items, key=lambda item: (_severity_key(item.get("severity")),))
    primary = ordered[0]
    pages = sorted({page for item in items for page in _anomaly_pages(item)})
    severity = str(primary.get("severity") or "LOW").upper()
    expected = primary.get("expected_value")
    found = primary.get("found_value")
    document_type = primary.get("document_type")
    evidence = None
    for item in ordered:
        evidence = _evidence_shape(item.get("evidence_json") or item.get("evidence"))
        if evidence is not None:
            break
    if evidence is None and pages:
        evidence = {"page": pages[0], "bbox": None, "text": ""}
    # Evidence bbox may be null; contract allows null.
    if evidence is not None and evidence.get("bbox") is None:
        evidence = {"page": evidence["page"], "bbox": None, "text": evidence.get("text", "")}
    values = {
        "expected": "" if expected is None else str(expected),
        "found": "" if found is None else str(found),
        "document": document_label(document_type, "en"),
        "pages": _pages_phrase(pages, "en") if pages else "the file",
        "months": _months_from_found(found),
    }
    values_hi = {
        **values,
        "document": document_label(document_type, "hi"),
        "pages": _pages_phrase(pages, "hi") if pages else "फ़ाइल",
    }
    return {
        "code": code,
        "severity": severity,
        "title": {"en": render(code, "title", "en"), "hi": render(code, "title", "hi")},
        "detail": {
            "en": render(code, "detail", "en", **values),
            "hi": render(code, "detail", "hi", **values_hi),
        },
        "pages": pages,
        "evidence": evidence,
        "_sort_pages": pages[:1],
    }


def _summary_part(code: str, pages: list[int], lang: str) -> str:
    phrase = SUMMARY_PHRASES[code][lang]
    if not pages:
        return phrase
    return f"{phrase} ({_pages_phrase(pages, lang)})"


def _summaries(findings: list[dict]) -> dict[str, str]:
    count = len(findings)
    if not count:
        return {
            "en": "No issues found. The file looks good.",
            "hi": "कोई समस्या नहीं मिली। फ़ाइल ठीक है।",
        }
    noun_en = "issue" if count == 1 else "issues"
    parts_en = ", ".join(
        _summary_part(f["code"], f["pages"], "en") for f in findings
    )
    parts_hi = ", ".join(
        _summary_part(f["code"], f["pages"], "hi") for f in findings
    )
    return {
        "en": f"{count} {noun_en} need your attention: {parts_en}.",
        "hi": f"{count} समस्याओं पर ध्यान दें: {parts_hi}।",
    }


# ---------------------------------------------------------------------------
# Database loading
# ---------------------------------------------------------------------------


def _load_application(application_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        return dict(row) if row is not None else None


def _load_anomalies(application_id: int) -> list[dict]:
    with get_connection() as connection:
        try:
            rows = connection.execute(
                "SELECT * FROM validation_results WHERE application_id = ? ORDER BY id",
                (application_id,),
            ).fetchall()
        except Exception:
            return []
    anomalies: list[dict] = []
    for row in rows:
        item = dict(row)
        evidence = item.get("evidence_json")
        if isinstance(evidence, str) and evidence:
            try:
                item["evidence_json"] = json.loads(evidence)
            except (TypeError, ValueError):
                item["evidence_json"] = None
        anomalies.append(item)
    return anomalies


def _load_job(application_id: int) -> dict | None:
    with get_connection() as connection:
        try:
            row = connection.execute(
                "SELECT * FROM pipeline_jobs WHERE application_id = ? "
                "ORDER BY id DESC LIMIT 1",
                (application_id,),
            ).fetchone()
        except Exception:
            return None
        return dict(row) if row is not None else None


def _load_progress(application_id: int) -> dict | None:
    with get_connection() as connection:
        try:
            row = connection.execute(
                "SELECT * FROM pipeline_progress WHERE application_id = ?",
                (application_id,),
            ).fetchone()
        except Exception:
            return None
        return dict(row) if row is not None else None


def _load_pages(application_id: int) -> list[dict]:
    with get_connection() as connection:
        try:
            rows = connection.execute(
                "SELECT * FROM pages WHERE application_id = ? ORDER BY page_number",
                (application_id,),
            ).fetchall()
        except Exception:
            return []
    pages: list[dict] = []
    for row in rows:
        page = dict(row)
        extracted = page.get("extracted_fields")
        if isinstance(extracted, str) and extracted:
            try:
                page["extracted_fields"] = json.loads(extracted)
            except (TypeError, ValueError):
                page["extracted_fields"] = {}
        pages.append(page)
    return pages


def _stored_findings(application: dict) -> dict | None:
    raw = application.get("ops_findings_json")
    if not raw:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------

_CHECKLIST_STATUS_MAP = {
    "verified": "FOUND",
    "missing": "MISSING",
    "needs_review": "NOT_CHECKED",
    "unknown": "NOT_CHECKED",
    "not_applicable": "NOT_CHECKED",
}


def _checklist_section(
    application: dict, pages: list[dict], anomalies: list[dict]
) -> dict:
    try:
        from services.checklist_output import build_checklist_verification_response

        response = build_checklist_verification_response(
            loan_file_id=str(application.get("loan_id") or application.get("id") or ""),
            pages=pages,
            anomalies=anomalies,
            product_type=str(application.get("product_type") or "LAP"),
        )
    except Exception as exc:
        LOGGER.warning("checklist build failed for ops payload: %s", exc)
        return {"total": 0, "found": 0, "missing": 0, "not_checked": 0, "rows": []}
    pages_by_sno: dict[int, set[int]] = {}
    for anomaly in anomalies:
        try:
            sno = int(anomaly.get("s_no")) if anomaly.get("s_no") is not None else None
        except (TypeError, ValueError):
            sno = None
        if sno is None:
            continue
        for page_num in _anomaly_pages(anomaly):
            pages_by_sno.setdefault(sno, set()).add(page_num)
    rows = []
    counts = {"FOUND": 0, "MISSING": 0, "NOT_CHECKED": 0}
    for item in response.items:
        status = _CHECKLIST_STATUS_MAP.get(str(item.status), "NOT_CHECKED")
        counts[status] += 1
        rows.append(
            {
                "s_no": item.item_number,
                "description": item.document_name,
                "status": status,
                "pages": sorted(pages_by_sno.get(item.item_number, set())),
            }
        )
    return {
        "total": len(rows),
        "found": counts["FOUND"],
        "missing": counts["MISSING"],
        "not_checked": counts["NOT_CHECKED"],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_findings(anomalies: list[dict]) -> list[dict]:
    """Map anomalies to deduped, severity-ordered finding dicts (all codes)."""
    groups: dict[str, list[dict]] = {}
    for anomaly in anomalies:
        if not isinstance(anomaly, dict):
            continue
        code = rule_to_code(anomaly.get("rule_id"))
        if code is None:
            continue
        groups.setdefault(code, []).append(anomaly)
    findings = [_finding_from_group(code, items) for code, items in groups.items()]
    findings.sort(
        key=lambda f: (
            _severity_key(f["severity"]),
            CODE_ORDER.index(f["code"]) if f["code"] in CODE_ORDER else len(CODE_ORDER),
        )
    )
    for finding in findings:
        finding.pop("_sort_pages", None)
    return findings


def build_ops_payload(application_id: int) -> dict:
    """Build the operator-facing payload for one application (§5)."""
    application = _load_application(application_id)
    if application is None:
        raise KeyError(f"application {application_id} not found")
    anomalies = _load_anomalies(application_id)
    job = _load_job(application_id) or {}
    progress = _load_progress(application_id) or {}

    stored = _stored_findings(application)
    if stored and isinstance(stored.get("top_findings"), list):
        findings = stored["top_findings"]
        overflow = stored.get("pages_to_verify", [])
        summary = stored.get("summary")
    else:
        all_findings = compute_findings(anomalies)
        findings = all_findings[:5]
        overflow = _overflow_pages(all_findings[5:], anomalies)
        summary = None

    if not summary or not summary.get("en") or not summary.get("hi"):
        stored_summary = None
        if application.get("ops_summary_en") and application.get("ops_summary_hi"):
            stored_summary = {
                "en": str(application["ops_summary_en"]),
                "hi": str(application["ops_summary_hi"]),
            }
        summary = stored_summary or _summaries(findings)

    job_status = str(job.get("status") or "").strip().casefold()
    failure_reason = job.get("failure_reason") or job.get("error")
    if job_status in FAILED_JOB_STATUSES:
        status = "failed"
    elif job_status and job_status not in TERMINAL_JOB_STATUSES:
        status = "processing"
    elif findings:
        status = "needs_review"
    else:
        status = "clean"

    try:
        percentage = float(progress.get("percentage", 0) or 0)
    except (TypeError, ValueError):
        percentage = 0.0
    try:
        attempt = int(job.get("attempt", 1) or 1)
    except (TypeError, ValueError):
        attempt = 1

    pages = _load_pages(application_id)
    return {
        "application_id": int(application_id),
        "loan_id": application.get("loan_id"),
        "applicant_name": application.get("applicant_name"),
        "status": status,
        "processing": {
            "stage": progress.get("stage") or job.get("job_type"),
            "percentage": percentage,
            "attempt": attempt,
            "failure_reason": failure_reason,
        },
        "summary": summary,
        "top_findings": findings,
        "pages_to_verify": overflow,
        "checklist": _checklist_section(application, pages, anomalies),
    }


def _overflow_pages(all_overflow: list[dict], anomalies: list[dict]) -> list[dict]:
    """Group findings beyond the top 5 by page for manual verification."""
    by_page: dict[int, dict] = {}
    for finding in all_overflow:
        for page_num in finding.get("pages", []):
            slot = by_page.setdefault(int(page_num), {"codes": [], "finding": finding})
            slot["codes"].append(finding["code"])
    doc_by_page: dict[int, Any] = {}
    for anomaly in anomalies:
        for page_num in _anomaly_pages(anomaly):
            doc_by_page.setdefault(int(page_num), anomaly.get("document_type"))
    result = []
    for page_num in sorted(by_page):
        document_type = doc_by_page.get(page_num)
        problems_en = ", ".join(
            SUMMARY_PHRASES[code]["en"] for code in dict.fromkeys(by_page[page_num]["codes"])
        )
        problems_hi = ", ".join(
            SUMMARY_PHRASES[code]["hi"] for code in dict.fromkeys(by_page[page_num]["codes"])
        )
        result.append(
            {
                "page": int(page_num),
                "document": {
                    "en": document_label(document_type, "en"),
                    "hi": document_label(document_type, "hi"),
                },
                "problem": {"en": problems_en, "hi": problems_hi},
            }
        )
    return result


def store_ops_payload(application_id: int) -> dict | None:
    """Compute findings (minus checklist) and persist to ops_findings_json.

    Intended one-line call from ``services/pipeline/finalization.py`` at
    pipeline finalisation (that file is owned by another stream, so the call
    itself is listed under NEEDS-COORDINATION and NOT made here).
    """
    try:
        anomalies = _load_anomalies(application_id)
        findings = compute_findings(anomalies)[:5]
        overflow = _overflow_pages(compute_findings(anomalies)[5:], anomalies)
        stored = {
            "top_findings": findings,
            "pages_to_verify": overflow,
            "summary": _summaries(findings),
        }
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET ops_findings_json = ? WHERE id = ?",
                (json.dumps(stored, ensure_ascii=False), application_id),
            )
        return stored
    except Exception as exc:
        LOGGER.warning("storing ops payload failed for %s: %s", application_id, exc)
        return None
