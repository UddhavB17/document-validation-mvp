"""Evidence-backed exception review with audited, conservative dismissal.

The cloud report preserves coverage and per-finding recommendations. English is
written first; Hindi is translated from that exact English result. No page text
or model output is logged or exposed through the small operations payload.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from toon import encode

from database.db import get_connection
from services.config import cached_settings
from services.llm_client import call_llm_messages, llm_model
from services.review_prompts import (
    REVIEW_PROMPT_FINGERPRINT,
    REVIEW_PROMPT_VERSION,
    REVIEW_STAGE_PROMPTS,
    REVIEW_SYSTEM_PROMPT,
)
from services.storage import get_store

MAX_SUMMARY_CHARS = 6000


def _json(text: str | None) -> dict:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    result = json.loads(cleaned)
    if not isinstance(result, dict):
        raise ValueError("Expected review object")
    return result


def _call(application_id: int, purpose: str, instruction: str, data: Any, tokens: int) -> dict:
    return _json(
        call_llm_messages(
            [
                {
                    "role": "system",
                    "content": REVIEW_SYSTEM_PROMPT,
                },
                {"role": "user", "content": instruction + "\nInput (TOON):\n" + encode(data)},
            ],
            application_id=application_id,
            purpose=purpose,
            response_format="json",
            max_tokens=tokens,
            timeout=120,
        )
    )


def _page_records(pages: list[dict]) -> list[dict]:
    records = [
        {
            "page": int(p["page_number"]),
            "document": p.get("document_type"),
            "read_status": p.get("ocr_status"),
            "text": p.get("ocr_text") or "",
            "fields": p.get("extracted_fields") or {},
        }
        for p in pages
    ]
    return records


def _trusted_context(ground_truth: dict) -> dict:
    keys = (
        "person_id",
        "role",
        "applicant_name",
        "pan_number",
        "aadhaar_last4",
        "date_of_birth",
        "address",
        "loan_amount",
        "sanction_amount",
        "tenure",
        "roi",
        "emi",
        "product_type",
        "case_type",
    )
    result = {k: ground_truth[k] for k in keys if k in ground_truth}
    people = ground_truth.get("people")
    if isinstance(people, dict):
        result["people"] = {
            role: {k: person[k] for k in keys if k in person}
            for role, person in people.items()
            if isinstance(person, dict)
        }
    return result


def _finding_records(findings: list[dict]) -> list[dict]:
    return [
        {
            "ref": i + 1,
            **{
                k: f.get(k)
                for k in (
                    "id",
                    "rule_id",
                    "severity",
                    "document_type",
                    "page_number",
                    "collapsed_page_numbers",
                    "expected_value",
                    "found_value",
                    "reason",
                    "evidence_json",
                )
            },
        }
        for i, f in enumerate(findings)
    ]


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _dismissible(item: dict, finding: dict, pages: list[dict]) -> bool:
    """Confidence alone is insufficient: independently verify benign equivalence."""
    confidence = item.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.98 <= confidence <= 1
    ):
        return False
    if item.get("verdict") != "possible_false_positive":
        return False
    rule = str(finding.get("rule_id") or "")
    if "MISMATCH" not in rule or not any(k in rule for k in ("NAME", "PAN", "AADHAAR")):
        return False
    expected, found = finding.get("expected_value"), finding.get("found_value")
    if (
        not isinstance(expected, str)
        or not isinstance(found, str)
        or not expected.strip()
        or not found.strip()
    ):
        return False
    normalize = _normalize
    if "PAN" in rule or "AADHAAR" in rule:

        def normalize(value):
            return re.sub(r"[\s-]", "", value).casefold()

    if normalize(expected) != normalize(found):
        return False
    normalized = normalize(found)
    if "PAN" in rule and not re.fullmatch(r"[a-z]{5}\d{4}[a-z]", normalized):
        return False
    if "AADHAAR" in rule and not re.fullmatch(r"[2-9]\d{11}", normalized):
        return False
    quote = item.get("quote")
    if not isinstance(quote, str) or not quote.strip() or normalize(found) not in normalize(quote):
        return False
    original_pages = set(finding.get("collapsed_page_numbers") or [])
    if finding.get("page_number"):
        original_pages.add(finding["page_number"])
    return any(
        p["page"] in item["pages"]
        and p["page"] in original_pages
        and _normalize(quote) in _normalize(p["text"])
        for p in pages
    )


def _finding_context(finding: dict, pages: list[dict]) -> dict:
    """Retrieve bounded source excerpts, including potentially mislabelled documents.

    Retrieval is deterministic; it is not an LLM review of otherwise clear pages.
    Missing-document checks search source text as well as saved document labels.
    Any omitted context remains explicit so absence cannot be inferred from it.
    """
    direct = set(finding.get("collapsed_page_numbers") or [])
    if finding.get("page_number"):
        direct.add(finding["page_number"])
    terms = set(re.findall(r"[a-z0-9]+", str(finding.get("document_type") or "").casefold()))
    terms -= {"document", "documents", "report", "form", "letter", "and", "or"}
    candidates = []
    for page in pages:
        text = page["text"].casefold()
        matches = [term for term in terms if re.search(r"\b" + re.escape(term) + r"\b", text)]
        same_type = bool(finding.get("document_type")) and (
            str(page["document"]).casefold() == str(finding["document_type"]).casefold()
        )
        if page["page"] in direct or same_type or matches:
            candidates.append((page["page"] in direct, len(matches), same_type, page))
    candidates.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]["page"]))
    evidence = []
    for _, _, _, page in candidates[:12]:
        text = page["text"]
        # Keep the header and exact windows around finding values / document terms.
        starts = {0}
        needles = [finding.get("found_value"), finding.get("expected_value"), *sorted(terms)]
        for needle in needles:
            if not isinstance(needle, str) or not needle.strip():
                continue
            match = re.search(re.escape(needle.strip()), text, re.IGNORECASE)
            if match:
                starts.add(max(0, match.start() - 150))
        excerpts = [text[start : start + 800] for start in sorted(starts)[:4]]
        evidence.append(
            {
                "page": page["page"],
                "document": page["document"],
                "read_status": page["read_status"],
                "excerpts": excerpts,
                "complete_text": len(text) <= 800,
            }
        )
    return {
        "finding": finding,
        "evidence": evidence,
        "candidate_page_count": len(candidates),
        "omitted_candidate_pages": [row[3]["page"] for row in candidates[12:]],
        "scope": "Selected source excerpts, not an exhaustive document search or page review",
    }


def _validate_findings(result: dict, contexts: list[dict], pages: list[dict]) -> list[dict]:
    findings = [entry["finding"] for entry in contexts]
    assessments = result.get("findings")
    if not isinstance(assessments, list) or len(assessments) != len(findings):
        raise ValueError("Incomplete finding review")
    if any(not isinstance(r, dict) or type(r.get("ref")) is not int for r in assessments):
        raise ValueError("Invalid finding reference")
    if {r["ref"] for r in assessments} != {f["ref"] for f in findings}:
        raise ValueError("Finding review references do not match input")
    for item in assessments:
        if item.get("verdict") not in {"supported", "possible_false_positive", "unresolved"}:
            raise ValueError("Invalid finding recommendation")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError("Missing finding rationale")
        confidence = item.get("confidence")
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            raise ValueError("Invalid finding confidence")
        context = next(c for c in contexts if c["finding"]["ref"] == item["ref"])
        known_pages = {p["page"] for p in context["evidence"]}
        if (
            not isinstance(item.get("pages"), list)
            or any(type(n) is not int for n in item["pages"])
            or not set(item["pages"]).issubset(known_pages)
        ):
            raise ValueError("Invalid finding evidence pages")
        if item["verdict"] == "possible_false_positive":
            quote = item.get("quote")
            verified = (
                isinstance(quote, str)
                and bool(quote.strip())
                and any(
                    p["page"] in item["pages"]
                    and any(_normalize(quote) in _normalize(excerpt) for excerpt in p["excerpts"])
                    for p in context["evidence"]
                )
            )
            if not verified:
                raise ValueError("Unsupported false-positive evidence")
        item["dismissed"] = _dismissible(item, context["finding"], pages)
    return assessments


@cached_settings()
def generate_exception_review(application_id: int, context: dict) -> dict[str, str]:
    pages = _page_records(context["pages"])
    findings = _finding_records(context.get("findings") or [])
    finding_contexts = [_finding_context(f, pages) for f in findings]
    trusted_context = _trusted_context(context.get("ground_truth") or {})
    model = llm_model()
    digest = hashlib.sha256(
        json.dumps(
            {
                "prompt_fingerprint": REVIEW_PROMPT_FINGERPRINT,
                "model": model,
                "pages": pages,
                "findings": findings,
                "trusted_context": trusted_context,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    store = get_store()
    assessments = []
    for index in range(0, len(finding_contexts), 4):
        batch = finding_contexts[index : index + 4]
        key = (
            f"applications/{application_id}/reports/ops-review/{digest}/findings-{index // 4}.json"
        )
        if store.exists(key):
            assessments.extend(_validate_findings(json.loads(store.get(key)), batch, pages))
            continue
        # Retry only the invalid batch; successful batches remain durable.
        for attempt in range(2):
            try:
                result = _call(
                    application_id,
                    "ops_findings_review",
                    REVIEW_STAGE_PROMPTS["ops_findings_review"],
                    {"finding_contexts": batch, "trusted_context": trusted_context},
                    4000,
                )
                validated = _validate_findings(result, batch, pages)
                break
            except ValueError:
                if attempt == 1:
                    raise
        store.put(
            key,
            json.dumps({"findings": validated}, ensure_ascii=False).encode(),
            "application/json",
        )
        assessments.extend(validated)

    counts = {
        v: sum(r["verdict"] == v for r in assessments)
        for v in ("supported", "possible_false_positive", "unresolved")
    }
    report = {
        "prompt_version": REVIEW_PROMPT_VERSION,
        "prompt_fingerprint": REVIEW_PROMPT_FINGERPRINT,
        "model": model,
        "review_scope": "exceptions_only",
        "pages": [],
        "evidence_pages": sorted({p["page"] for c in finding_contexts for p in c["evidence"]}),
        "evidence_limits": [
            {
                "ref": c["finding"]["ref"],
                "candidate_page_count": c["candidate_page_count"],
                "omitted_candidate_pages": c["omitted_candidate_pages"],
            }
            for c in finding_contexts
        ],
        "coverage_note": "All supplied exceptions reviewed using selected source excerpts; "
        "no second whole-file AI page review was performed.",
        "findings": assessments,
        "counts": counts,
        "dismissed_count": sum(bool(r["dismissed"]) for r in assessments),
        "total_pages": len(pages),
        "total_findings": len(findings),
    }
    english = _call(
        application_id,
        "ops_summary_en",
        REVIEW_STAGE_PROMPTS["ops_summary_en"],
        {
            "review": report,
            "original_findings": findings,
            "case_context": {
                k: (context.get("ground_truth") or {}).get(k)
                for k in (
                    "loan_amount",
                    "sanction_amount",
                    "tenure",
                    "roi",
                    "emi",
                    "product_type",
                    "case_type",
                )
            },
        },
        2200,
    ).get("en")
    if not isinstance(english, str) or not english.strip() or len(english) > 4500:
        raise ValueError("Invalid English summary")
    hindi = _call(
        application_id,
        "ops_summary_hi",
        REVIEW_STAGE_PROMPTS["ops_summary_hi"],
        {"en": english},
        3800,
    ).get("hi")
    if not isinstance(hindi, str) or not re.search(r"[\u0900-\u097f]", hindi) or len(hindi) > 5500:
        raise ValueError("Invalid Hindi translation")
    if set(re.findall(r"\d+", english)) != set(re.findall(r"\d+", hindi)):
        raise ValueError("Translation changed numeric references")
    report.update(
        {
            "summary": {"en": english.strip(), "hi": hindi.strip()},
            "generated_at": datetime.now(UTC).isoformat(),
            "input_digest": hashlib.sha256(
                json.dumps(
                    {"pages": pages, "findings": findings},
                    sort_keys=True,
                    default=str,
                ).encode()
            ).hexdigest(),
        }
    )
    # Durable audit first; do not publish a summary whose audit could not be saved.
    store.put(
        f"applications/{application_id}/reports/ops-review.json",
        json.dumps(report, ensure_ascii=False).encode(),
        "application/json",
    )
    dismissed_refs = {r["ref"] for r in assessments if r["dismissed"]}
    if dismissed_refs:
        # Keep original rows and evidence. Update only matching findings on this application.
        with get_connection() as connection:
            for f in findings:
                if f["ref"] not in dismissed_refs:
                    continue
                connection.execute(
                    "UPDATE validation_results SET status = 'dismissed_by_llm' "
                    "WHERE application_id = ? AND rule_id = ? AND page_number = ? "
                    "AND expected_value = ? AND found_value = ? AND status = 'open'",
                    (
                        application_id,
                        f["rule_id"],
                        f["page_number"],
                        f["expected_value"],
                        f["found_value"],
                    ),
                )
        for i, finding in enumerate(context.get("findings") or []):
            if i + 1 in dismissed_refs:
                finding["status"] = "dismissed_by_llm"
    return report["summary"]
