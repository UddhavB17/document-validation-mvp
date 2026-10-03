"""Evidence-backed exception review with audited, conservative dismissal.

The cloud report preserves coverage and per-finding recommendations. English is
written first; Hindi is translated from that exact English result. No page text
or model output is logged or exposed through the small operations payload.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
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


class ReviewValidationError(ValueError):
    """A safe, stable validation category for the review audit.

    The exception deliberately carries no model response or source text.  The
    report and audit log can therefore explain why a stage did not complete
    without making sensitive provider output durable.
    """

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _safe_category(exc: BaseException, default: str) -> str:
    category = getattr(exc, "category", None)
    return category if isinstance(category, str) and category else default


def _error_entry(
    stage: str,
    category: str,
    contexts: list[dict] | None = None,
) -> dict:
    """Build bounded audit detail, mapping finding refs without source text."""
    entry = {"stage": stage, "category": category}
    if contexts:
        refs = []
        for context in contexts:
            finding = context.get("finding") or {}
            refs.append(
                {
                    "ref": finding.get("ref"),
                    "rule_id": finding.get("rule_id"),
                    "page_number": finding.get("page_number"),
                }
            )
        entry["finding_refs"] = refs
    return entry


def _json(text: str | None) -> dict:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
    try:
        result = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ReviewValidationError("invalid_json") from exc
    if not isinstance(result, dict):
        raise ReviewValidationError("invalid_object")
    return result


def _call(application_id: int, purpose: str, instruction: str, data: Any, tokens: int) -> dict:
    try:
        raw = call_llm_messages(
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
    except Exception as exc:  # noqa: BLE001 - caller records a safe category
        raise ReviewValidationError("provider_error") from exc
    if raw is None:
        raise ReviewValidationError("provider_unavailable")
    return _json(raw)


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
        raise ReviewValidationError("incomplete_findings")
    if any(not isinstance(r, dict) or type(r.get("ref")) is not int for r in assessments):
        raise ReviewValidationError("invalid_finding_reference")
    if {r["ref"] for r in assessments} != {f["ref"] for f in findings}:
        raise ReviewValidationError("finding_reference_mismatch")
    for item in assessments:
        if item.get("verdict") not in {"supported", "possible_false_positive", "unresolved"}:
            raise ReviewValidationError("invalid_verdict")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise ReviewValidationError("missing_finding_reason")
        confidence = item.get("confidence")
        if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
            raise ReviewValidationError("invalid_confidence")
        context = next(c for c in contexts if c["finding"]["ref"] == item["ref"])
        known_pages = {p["page"] for p in context["evidence"]}
        if (
            not isinstance(item.get("pages"), list)
            or any(type(n) is not int for n in item["pages"])
            or not set(item["pages"]).issubset(known_pages)
        ):
            raise ReviewValidationError("invalid_evidence_pages")
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
                raise ReviewValidationError("unsupported_false_positive_evidence")
        item["dismissed"] = _dismissible(item, context["finding"], pages)
    return assessments


def _validate_english_summary(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4500:
        raise ReviewValidationError("invalid_summary_en")
    return value.strip()


def _validate_hindi_summary(value: Any, english: str) -> str:
    if not isinstance(value, str) or not re.search(r"[\u0900-\u097f]", value):
        raise ReviewValidationError("invalid_translation_hi")
    if len(value) > 5500:
        raise ReviewValidationError("translation_too_long")
    if Counter(re.findall(r"\d+", english)) != Counter(re.findall(r"\d+", value)):
        raise ReviewValidationError("translation_numeric_mismatch")
    return value.strip()


def _status_for_review(
    total_batches: int,
    failed_batches: int,
    reviewed_findings: int,
    total_findings: int,
    stage_errors: list[dict],
) -> str:
    if failed_batches and reviewed_findings == 0 and total_findings:
        return "failed"
    if failed_batches or stage_errors:
        return "partial"
    if total_batches == 0 or reviewed_findings == total_findings:
        return "completed"
    return "partial"


def _coverage_note(status: str, reviewed: int, total: int) -> str:
    if status == "completed":
        return (
            f"Completed bounded exception review for {reviewed} of {total} supplied finding(s) "
            "using selected source excerpts; no second whole-file AI page review was performed."
        )
    if status == "failed":
        return (
            f"Exception review failed before any of the {total} supplied finding(s) were assessed; "
            "selected source excerpts and manual review are still required. This was not a full-page review."
        )
    return (
        f"Partial bounded exception review assessed {reviewed} of {total} supplied finding(s) "
        "using selected source excerpts; remaining findings require manual review. "
        "This was not a full-page review."
    )


def _fallback_summaries(report: dict) -> dict[str, str]:
    """A matched, bounded bilingual fallback based only on audited counts."""
    total = int(report.get("total_findings") or 0)
    reviewed = len(report.get("findings") or [])
    counts = report.get("counts") or {}
    supported = int(counts.get("supported") or 0)
    possible = int(counts.get("possible_false_positive") or 0)
    unresolved = int(counts.get("unresolved") or 0)
    return {
        "en": (
            f"AI assessed {reviewed} of {total} supplied exceptions using selected source excerpts. "
            "This was not a review of every page. "
            f"Assessments: {supported} supported, {possible} possible false positives, "
            f"{unresolved} unresolved. {total - reviewed} exceptions were not assessed. "
            "Possible false positives remain recommendations unless independently verified "
            "and recorded as dismissed. Complete the remaining document and human checks "
            "before making a decision."
        ),
        "hi": (
            f"चयनित स्रोत अंशों के आधार पर एआई ने {total} में से {reviewed} अपवादों की जाँच की। "
            "यह हर पृष्ठ की समीक्षा नहीं थी। "
            f"परिणाम: {supported} समर्थित, {possible} संभावित गलत अपवाद, "
            f"{unresolved} अनिर्णीत। {total - reviewed} अपवादों की जाँच नहीं हुई। "
            "संभावित गलत अपवाद सुझाव हैं, जब तक स्वतंत्र जाँच के बाद उन्हें खारिज दर्ज न किया जाए। "
            "निर्णय लेने से पहले शेष दस्तावेज़ और मानव जाँच पूरी करें।"
        ),
    }


def _finding_map(findings: list[dict]) -> list[dict]:
    return [
        {
            "ref": f.get("ref"),
            "rule_id": f.get("rule_id"),
            "page_number": f.get("page_number"),
        }
        for f in findings
    ]


@cached_settings()
def generate_exception_review(application_id: int, context: dict) -> dict[str, str]:
    pages = _page_records(context["pages"])
    findings = _finding_records(context.get("findings") or [])
    finding_contexts = [_finding_context(f, pages) for f in findings]
    trusted_context = _trusted_context(context.get("ground_truth") or {})
    stage_errors: list[dict] = []
    try:
        model = str(llm_model() or "unknown")
    except Exception:
        model = "unknown"
        stage_errors.append(_error_entry("model_resolution", "provider_config"))
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
    assessments: list[dict] = []
    batch_statuses: list[dict] = []
    failed_batches = 0
    batch_size = 4
    for index in range(0, len(finding_contexts), batch_size):
        batch = finding_contexts[index : index + batch_size]
        batch_number = index // batch_size
        refs = [c["finding"]["ref"] for c in batch]
        key = f"applications/{application_id}/reports/ops-review/{digest}/findings-{batch_number}.json"
        validated: list[dict] | None = None
        attempts = 0
        checkpoint_category: str | None = None
        try:
            if store.exists(key):
                try:
                    validated = _validate_findings(json.loads(store.get(key)), batch, pages)
                except Exception as exc:  # noqa: BLE001 - retry a corrupt checkpoint
                    checkpoint_category = _safe_category(exc, "invalid_checkpoint")
                    validated = None
        except Exception:
            checkpoint_category = "checkpoint_read_failed"

        if validated is None:
            # Retry only this failed batch. Earlier valid checkpoints remain intact.
            last_error: BaseException | None = None
            for attempt in range(1, 3):
                attempts = attempt
                try:
                    instruction = REVIEW_STAGE_PROMPTS["ops_findings_review"]
                    if last_error is not None:
                        instruction += (
                            "\nThe previous attempt failed validation: "
                            + _safe_category(last_error, "invalid_response")
                            + ". Return every supplied ref exactly once. Use unresolved when "
                            "evidence is insufficient; do not invent a supporting quote."
                        )
                    result = _call(
                        application_id,
                        "ops_findings_review",
                        instruction,
                        {"finding_contexts": batch, "trusted_context": trusted_context},
                        4000,
                    )
                    validated = _validate_findings(result, batch, pages)
                    try:
                        store.put(
                            key,
                            json.dumps({"findings": validated}, ensure_ascii=False).encode(),
                            "application/json",
                        )
                    except Exception as exc:  # noqa: BLE001 - do not claim an uncheckpointed batch
                        checkpoint_category = "checkpoint_write_failed"
                        validated = None
                        last_error = exc
                    else:
                        last_error = None
                    if validated is not None:
                        break
                except Exception as exc:  # noqa: BLE001 - classify and retry this batch only
                    last_error = exc
                    validated = None
                if validated is None and attempt == 2:
                    category = _safe_category(
                        last_error, checkpoint_category or "finding_review_failed"
                    )
                    stage_errors.append(_error_entry("ops_findings_review", category, batch))
        if validated is None:
            failed_batches += 1
            batch_statuses.append(
                {
                    "batch": batch_number,
                    "refs": refs,
                    "status": "failed",
                    "attempts": attempts,
                }
            )
            continue
        assessments.extend(validated)
        batch_statuses.append(
            {
                "batch": batch_number,
                "refs": refs,
                "status": "completed",
                "attempts": attempts,
                "checkpoint": key,
            }
        )

    assessments.sort(key=lambda item: item["ref"])
    reviewed_refs = {item["ref"] for item in assessments}
    unreviewed_refs = [f["ref"] for f in findings if f["ref"] not in reviewed_refs]

    dismissal_row_ids: dict[int, int] = {}
    for item in assessments:
        original = next(f for f in findings if f["ref"] == item["ref"])
        if not item["dismissed"]:
            continue
        try:
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
        except Exception:
            item["dismissed"] = False
            stage_errors.append(
                _error_entry(
                    "dismissal_persistence", "dismissal_lookup_failed", [{"finding": original}]
                )
            )

    counts = {
        value: sum(r["verdict"] == value for r in assessments)
        for value in ("supported", "possible_false_positive", "unresolved")
    }
    provisional_status = _status_for_review(
        len(batch_statuses), failed_batches, len(assessments), len(findings), stage_errors
    )
    report = {
        "prompt_version": REVIEW_PROMPT_VERSION,
        "prompt_fingerprint": REVIEW_PROMPT_FINGERPRINT,
        "model": model,
        "review_status": provisional_status,
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
        "finding_map": _finding_map(findings),
        "finding_batches": batch_statuses,
        "coverage_note": _coverage_note(provisional_status, len(assessments), len(findings)),
        "findings": assessments,
        "counts": counts,
        "dismissed_count": sum(bool(r["dismissed"]) for r in assessments),
        "total_pages": len(pages),
        "total_findings": len(findings),
        "reviewed_finding_refs": sorted(reviewed_refs),
        "unreviewed_finding_refs": unreviewed_refs,
        "stage_errors": stage_errors,
    }
    summary_status = {"en": "model", "hi": "model"}
    try:
        english = _validate_english_summary(
            _call(
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
        )
    except Exception as exc:  # noqa: BLE001 - retain finding review with fallback
        stage_errors.append(_error_entry("ops_summary_en", _safe_category(exc, "summary_failed")))
        summary_status["en"] = "fallback"
        english = _fallback_summaries(report)["en"]

    try:
        hindi = _validate_hindi_summary(
            _call(
                application_id,
                "ops_summary_hi",
                REVIEW_STAGE_PROMPTS["ops_summary_hi"],
                {"en": english},
                3800,
            ).get("hi"),
            english,
        )
    except Exception as exc:  # noqa: BLE001 - retain English and finding review
        stage_errors.append(
            _error_entry("ops_summary_hi", _safe_category(exc, "translation_failed"))
        )
        summary_status["hi"] = "fallback"
        # A generic Hindi fallback cannot be presented as a translation of a
        # different model-written English summary. Fall back to a matched pair.
        summary_status["en"] = "fallback"
        fallback = _fallback_summaries(report)
        english, hindi = fallback["en"], fallback["hi"]

    final_status = _status_for_review(
        len(batch_statuses), failed_batches, len(assessments), len(findings), stage_errors
    )
    if failed_batches:
        # Deterministic coverage remains authoritative on incomplete reviews,
        # even if the model summary incorrectly implies everything was checked.
        fallback = _fallback_summaries(report)
        english, hindi = fallback["en"], fallback["hi"]
        summary_status = {"en": "fallback", "hi": "fallback"}
    english += (
        f"\n\nAI review {final_status}; model {model}. "
        f"Assessed {len(assessments)} of {len(findings)} exceptions."
    )
    hindi += (
        f"\n\nएआई समीक्षा: { {'completed': 'पूरी', 'partial': 'आंशिक', 'failed': 'विफल'}[final_status] }; "
        f"मॉडल {model}। {len(findings)} में से {len(assessments)} अपवादों की जाँच हुई।"
    )
    report.update(
        {
            "review_status": final_status,
            "coverage_note": _coverage_note(final_status, len(assessments), len(findings)),
            "stage_errors": stage_errors,
            "summary_status": summary_status,
            "summary": {"en": english, "hi": hindi},
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
    # Durable audit first; do not publish a dismissal whose review report could
    # not be saved. The report always includes valid batches and safe categories.
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
    try:
        from services.audit_service import log_action

        log_action(
            application_id,
            "llm_exception_review_finished",
            {
                "review_status": final_status,
                "model": model,
                "reviewed_finding_refs": sorted(reviewed_refs),
                "unreviewed_finding_refs": unreviewed_refs,
                "stage_errors": stage_errors,
            },
        )
    except Exception:
        # The object-store report is the source of truth for this review; an
        # auxiliary audit row must not turn a completed run into a failure.
        pass
    return report["summary"]
