"""Keep uncertain document evidence separate from verified presence and absence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.page_quality import is_confident_document_match, is_document_type_candidate


@dataclass
class PresenceAssessment:
    accepted_pages: list[dict] = field(default_factory=list)
    candidate_pages: list[dict] = field(default_factory=list)
    coverage_pages: list[dict] = field(default_factory=list)

    @property
    def review_pages(self) -> list[int]:
        return sorted(
            {
                int(p["page_number"])
                for p in self.candidate_pages + self.coverage_pages
                if p.get("page_number") is not None
            }
        )


def assess_document_presence(
    pages: list[dict], document_types: list[str], *, person_id: str | None = None
) -> PresenceAssessment:
    """Collect candidates without allowing uncertain evidence to satisfy a rule."""
    result = PresenceAssessment()
    for page in pages:
        fields = page.get("extracted_fields") or {}
        ownership = fields.get("_ownership") or {}
        owner = str(
            page.get("person_id") or page.get("applicant_role") or ownership.get("person_id") or ""
        ).casefold()
        unknown_owner = owner in {"", "unknown", "unassigned", "unresolved", "none"}
        if person_id and not unknown_owner and owner != person_id.casefold():
            continue
        candidates = [t for t in document_types if is_document_type_candidate(page, t)]
        if candidates:
            if any(is_confident_document_match(page, t) for t in candidates) and not (
                person_id and unknown_owner
            ):
                result.accepted_pages.append(page)
            else:
                result.candidate_pages.append(page)
        elif str(page.get("document_type") or "").casefold() in {
            "",
            "none",
            "unknown",
            "ocr skipped",
        } and (
            page.get("is_readable") is False
            or str(page.get("ocr_status") or "").casefold() in {"failed", "no_text_extracted"}
            or str(page.get("document_type") or "").casefold() == "ocr skipped"
        ):
            # An unreadable unidentified page might contain the required
            # document. A known unrelated document cannot establish this doubt.
            result.coverage_pages.append(page)
    return result


def review_presence_findings(
    pages: list[dict], anomalies: list[dict], items: list[dict]
) -> list[dict]:
    """Retain original count/applicability rules; qualify unsupported absences.

    This runs after the existing rules, so one multi-page document or duplicate
    cheque never satisfies a minimum merely because it has several pages.
    """
    definitions = {int(item.get("s_no") or 0): item for item in items}
    result = []
    for original in anomalies:
        rule = str(original.get("rule_id") or "")
        item = definitions.get(int(original.get("s_no") or 0), {})
        if not rule.startswith("MISSING_DOC") or item.get("check_type") == "system_flag":
            result.append(original)
            continue
        requested = original.get("document_type") or item.get("document_type") or ""
        types = (
            requested
            if isinstance(requested, list)
            else [
                part.strip()
                for part in str(requested).replace(" / ", ",").split(",")
                if part.strip()
            ]
        )
        assessment = assess_document_presence(pages, types, person_id=original.get("person_id"))
        if not assessment.candidate_pages and not assessment.coverage_pages:
            result.append(original)
            continue
        candidate_numbers = sorted(
            {
                int(p["page_number"])
                for p in assessment.candidate_pages
                if p.get("page_number") is not None
            }
        )
        coverage_numbers = sorted(
            {
                int(p["page_number"])
                for p in assessment.coverage_pages
                if p.get("page_number") is not None
            }
        )
        if candidate_numbers:
            detail = "Possible document found; verify its type, readability and borrower before accepting it."
            state = "candidate_review"
        else:
            detail = "Document presence could not be determined because some unidentified pages were not read successfully."
            state = "insufficient_scan_coverage"
        evidence: dict[str, Any] = {
            "presence_state": state,
            "candidate_pages": candidate_numbers,
            "coverage_pages": coverage_numbers,
            "pages": assessment.review_pages,
        }
        result.append(
            {
                **original,
                "rule_id": rule.replace("MISSING_DOC", "REVIEW_REQUIRED", 1),
                "status": "open",
                "reason": detail,
                "found_value": detail,
                "page_number": (assessment.review_pages or [None])[0],
                "collapsed_page_numbers": assessment.review_pages,
                "evidence_json": evidence,
            }
        )
    return result
