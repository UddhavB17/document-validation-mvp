"""Consistency-check submodule."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from services.bureau_scores import has_explicit_no_score_evidence
from services.consistency.matching import _anomaly, _number


def _bureau_checks(pages: list[dict], observations: list[dict]) -> list[dict]:
    anomalies: list[dict] = []
    bureau_pages = [
        page for page in pages if page.get("document_type") in {"CRIF Report", "CIBIL Report"}
    ]
    grouped: dict[tuple[Any, str, Any], list[dict]] = defaultdict(list)
    for page in bureau_pages:
        fields = page.get("extracted_fields") or {}
        key = (
            page.get("source_document_id")
            or fields.get("credit_report_id")
            or page.get("detected_page_number")
            or page.get("page_number"),
            str(page.get("document_type") or ""),
            page.get("person_id"),
        )
        grouped[key].append(page)

    for (_segment, document_type, person_id), group_pages in grouped.items():
        score_values: list[tuple[Any, dict]] = []
        for page in group_pages:
            fields = page.get("extracted_fields") or {}
            for field in ("credit_score", "cibil_score", "crif_score"):
                value = fields.get(field)
                if value not in (None, "", [], {}):
                    score_values.append((value, page))
        valid_scores = [
            value
            for value, _page in score_values
            if (score := _number(value)) is not None and (score == 0 or 300 <= score <= 900)
        ]
        explicit_no_score = any(
            has_explicit_no_score_evidence(str(page.get("ocr_text") or "")) for page in group_pages
        )
        if valid_scores or explicit_no_score:
            continue
        score_page = next((_page for _value, _page in score_values), None)
        if score_page is None:
            score_page = next((page for page in group_pages if _has_bureau_score_table(page)), None)
        if score_page is None:
            continue
        found = next((value for value, _page in score_values if value not in (None, "")), None)
        obs = {
            "document_type": document_type,
            "page_number": score_page.get("page_number"),
            "person_id": person_id or "unassigned",
        }
        anomalies.append(
            _anomaly(
                "BUREAU_SCORE_MISSING",
                "HIGH",
                "Bureau score of 0 (no score) or 300 to 900",
                found if found not in (None, "") else "Blank score table",
                obs,
                "Credit bureau report does not expose a valid score on its score page.",
            )
        )
    return anomalies


def _has_bureau_score_table(page: dict) -> bool:
    text = str(page.get("ocr_text") or "").lower()
    return bool(
        re.search(r"\b(?:crif|cibil|credit\s+information|credit\s+report)\b", text)
        and re.search(r"\bscore(?:\(s\))?\b", text)
        and ("score name" in text or "range" in text or "crif hm score" in text)
    )
