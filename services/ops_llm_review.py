"""Evidence-backed review of every saved page with audited, conservative dismissal.

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
    for page in records:
        # Complete text in numbered spans: the model selects existing evidence
        # instead of retyping/paraphrasing a quote and pretending it is exact.
        page["spans"] = [
            {"ref": i // 500, "text": page["text"][i : i + 500]}
            for i in range(0, len(page["text"]), 500)
        ]
    return records


def _batches(pages: list[dict]):
    batch, size = [], 0
    for page in pages:
        length = len(
            json.dumps(
                {k: v for k, v in page.items() if k != "text"}, ensure_ascii=False, default=str
            )
        )
        if batch and (size + length > 60000 or len(batch) >= 24):
            yield batch
            batch, size = [], 0
        batch.append(page)
        size += length
    if batch:
        yield batch


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


def _validate_batch(result: dict, pages: list[dict]) -> list[dict]:
    expected = {p["page"]: p for p in pages}
    rows = result.get("pages")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("Incomplete page review")
    if {r.get("page") for r in rows if isinstance(r, dict)} != set(expected):
        raise ValueError("Review page references do not match input")
    for row in rows:
        if row.get("assessment") not in {"consistent", "needs_review", "unknown", "unreadable"}:
            raise ValueError("Invalid page assessment")
        if not isinstance(row.get("reason"), str) or not row["reason"].strip():
            raise ValueError("Missing page assessment reason")
        if "quote_ref" in row:
            ref = row["quote_ref"]
            spans = expected[row["page"]].get("spans") or []
            if ref is not None and (type(ref) is not int or not 0 <= ref < len(spans)):
                raise ValueError("Invalid evidence span reference")
            row["quote"] = spans[ref]["text"] if ref is not None else ""
        quote = row.get("quote") or ""
        if quote and _normalize(quote) not in _normalize(expected[row["page"]]["text"]):
            raise ValueError("Unsupported evidence quote")
        if not expected[row["page"]]["text"].strip():
            row["assessment"] = "unreadable"
    return rows


@cached_settings()
def generate_page_review(application_id: int, context: dict) -> dict[str, str]:
    pages = _page_records(context["pages"])
    findings = _finding_records(context.get("findings") or [])
    model = llm_model()
    digest = hashlib.sha256(
        json.dumps(
            {
                "prompt_fingerprint": REVIEW_PROMPT_FINGERPRINT,
                "model": model,
                "pages": pages,
                "findings": findings,
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    store = get_store()
    reviews = []
    for index, batch in enumerate(_batches(pages)):
        key = f"applications/{application_id}/reports/ops-review/{digest}/batch-{index}.json"
        if store.exists(key):
            reviews.extend(_validate_batch(json.loads(store.get(key)), batch))
            continue
        result = _call(
            application_id,
            "ops_page_review",
            REVIEW_STAGE_PROMPTS["ops_page_review"],
            {
                "pages": [{k: v for k, v in p.items() if k != "text"} for p in batch],
                "findings": findings,
            },
            8000,
        )
        validated = _validate_batch(result, batch)
        store.put(
            key, json.dumps({"pages": validated}, ensure_ascii=False).encode(), "application/json"
        )
        reviews.extend(validated)

    audit = _call(
        application_id,
        "ops_findings_review",
        REVIEW_STAGE_PROMPTS["ops_findings_review"],
        {"findings": findings, "page_reviews": reviews},
        8000,
    )
    assessments = audit.get("findings")
    if not isinstance(assessments, list) or len(assessments) != len(findings):
        raise ValueError("Incomplete finding review")
    if {r.get("ref") for r in assessments if isinstance(r, dict)} != {f["ref"] for f in findings}:
        raise ValueError("Finding review references do not match input")
    known_pages = {p["page"] for p in pages}
    dismissal_row_ids = {}
    for item in assessments:
        if item.get("verdict") not in {"supported", "possible_false_positive", "unresolved"}:
            raise ValueError("Invalid finding recommendation")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ValueError("Missing finding rationale")
        if not isinstance(item.get("pages"), list) or not set(item["pages"]).issubset(known_pages):
            raise ValueError("Invalid finding evidence pages")
        if item["verdict"] == "possible_false_positive" and not item["pages"]:
            item["verdict"] = "unresolved"
        original = next(f for f in findings if f["ref"] == item["ref"])
        item["dismissed"] = _dismissible(item, original, pages)
        if item["dismissed"]:
            with get_connection() as connection:
                matches = connection.execute(
                    "SELECT id FROM validation_results "
                    "WHERE application_id = ? AND rule_id = ? AND page_number = ? "
                    "AND expected_value = ? AND found_value = ? AND status = 'open'",
                    (
                        application_id,
                        original["rule_id"],
                        original["page_number"],
                        original["expected_value"],
                        original["found_value"],
                    ),
                ).fetchall()
            # Aggregate findings need not carry database IDs. When their values
            # match multiple rows, retain the recommendation rather than dismiss
            # an unresolved sibling that happens to share those values.
            item["dismissed"] = len(matches) == 1
            if item["dismissed"]:
                dismissal_row_ids[item["ref"]] = matches[0]["id"]

    counts = {
        v: sum(r["verdict"] == v for r in assessments)
        for v in ("supported", "possible_false_positive", "unresolved")
    }
    report = {
        "prompt_version": REVIEW_PROMPT_VERSION,
        "prompt_fingerprint": REVIEW_PROMPT_FINGERPRINT,
        "model": model,
        "pages": reviews,
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
        {"review": report, "original_findings": findings},
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
    if dismissal_row_ids:
        # Keep original rows and evidence. Update only matching findings on this application.
        with get_connection() as connection:
            for f in findings:
                if f["ref"] not in dismissal_row_ids:
                    continue
                connection.execute(
                    "UPDATE validation_results SET status = 'dismissed_by_llm' "
                    "WHERE id = ? AND application_id = ? AND rule_id = ? AND page_number = ? "
                    "AND expected_value = ? AND found_value = ? AND status = 'open'",
                    (
                        dismissal_row_ids[f["ref"]],
                        application_id,
                        f["rule_id"],
                        f["page_number"],
                        f["expected_value"],
                        f["found_value"],
                    ),
                )
        for i, finding in enumerate(context.get("findings") or []):
            if i + 1 in dismissal_row_ids:
                finding["status"] = "dismissed_by_llm"
    return report["summary"]
