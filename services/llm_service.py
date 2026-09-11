"""LLM explanation service: TOON prompt input, JSON model output.

Prompts are encoded with ``toon.encode``; model responses are parsed with
``json.loads`` plus a schema check. ``generate_summaries`` returns the
bilingual operator summary persisted to ``applications.ops_summary_en/hi``.
"""

import json
import logging
import re

from toon import encode

from database.db import get_connection
from services.llm_client import call_llm_api, call_llm_messages, llm_provider
from services.llm_client import (
    extract_response_text as _extract_response_text,  # noqa: F401 - compatibility export
)
from services.ops_templates_en_hi import TEMPLATES

logger = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 6000
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def generate_explanation(
    anomalies: list[dict],
    ground_truth: dict,
    application_id: int | None = None,
) -> str | None:
    """Generate a short operations summary from anomalies in TOON format."""
    if not anomalies:
        return None

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    parsed = None
    try:
        prompt = _build_prompt(anomalies, ground_truth)
        raw_text = call_llm_api(prompt)
        if raw_text:
            parsed = parse_llm_summary(raw_text)
    except Exception as exc:
        logger.warning("LLM summary unavailable; using deterministic summary: %s", exc)

    if parsed is None:
        parsed = build_default_summary(anomalies, ground_truth)

    json_str = json.dumps(parsed, ensure_ascii=False)

    if application_id is not None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET llm_summary = ? WHERE id = ?",
                (json_str, application_id),
            )
        try:
            from services.audit_service import log_action

            log_action(application_id, "llm_summary_generated", {"summary_length": len(json_str)})
        except Exception:
            pass

    return json_str


def parse_llm_summary(text: str) -> dict | None:
    if not text:
        return None
    cleaned = text.strip()

    # Strip code blocks if LLM wrapped them
    fence_match = re.search(r"```(?:toon)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        from toon import decode

        parsed = decode(cleaned)
        if isinstance(parsed, dict) and "overall_summary" in parsed:
            # Normalize list formatting
            if "page_summaries" in parsed and isinstance(parsed["page_summaries"], list):
                for page_sum in parsed["page_summaries"]:
                    if "summary_points" in page_sum:
                        points = page_sum["summary_points"]
                        if isinstance(points, str):
                            page_sum["summary_points"] = [points]
                        elif not isinstance(points, list):
                            page_sum["summary_points"] = [str(points)]
            return parsed
    except Exception as exc:
        logger.debug("Could not decode LLM summary as TOON: %s", exc)
    return None


def build_default_summary(anomalies: list[dict], ground_truth: dict) -> dict:
    page_summaries = []
    for anomaly in anomalies:
        page_num = anomaly.get("page_number")
        doc_type = anomaly.get("document_type") or "Unknown Document"
        reason = anomaly.get("reason") or f"Validation check {anomaly.get('rule_id')} failed."
        expected = anomaly.get("expected_value")
        found = anomaly.get("found_value")

        summary_points = []
        if doc_type:
            summary_points.append(f"Document type classified as {doc_type}.")
        if expected is not None:
            summary_points.append(f"Expected value was: {expected}.")
        if found is not None:
            summary_points.append(f"Found value was: {found}.")

        page_summaries.append(
            {
                "page_number": page_num,
                "document_type": doc_type,
                "rule_id": anomaly.get("rule_id"),
                "summary_points": summary_points,
                "problem_description": reason,
            }
        )

    high = sum(1 for item in anomalies if str(item.get("severity", "")).upper() == "HIGH")
    medium = sum(1 for item in anomalies if str(item.get("severity", "")).upper() == "MEDIUM")
    low = sum(1 for item in anomalies if str(item.get("severity", "")).upper() == "LOW")

    parts = [f"{len(anomalies)} exception(s) require review:"]
    if high:
        parts.append(f"{high} high-severity")
    if medium:
        parts.append(f"{medium} medium-severity")
    if low:
        parts.append(f"{low} low-severity")
    overall_msg = " ".join(parts)

    rec = "APPROVE"
    if high > 0:
        rec = "MANUAL REVIEW"
    elif medium > 0:
        rec = "SEND BACK TO BRANCH"

    return {
        "overall_summary": overall_msg,
        "final_recommendation": rec,
        "page_summaries": page_summaries,
    }


def summarize_exceptions(exceptions: list[dict]) -> str | None:
    if not exceptions:
        return None
    default_summary = build_default_summary(exceptions, {})
    return json.dumps(default_summary, ensure_ascii=False)


def generate_summaries(application_id: int, context: dict) -> dict[str, str]:
    """Return ``{"en": ..., "hi": ...}`` operator summaries for one application.

    The model receives TOON prompt input and must answer in JSON. Any
    validation failure (or provider ``none``) falls back to the deterministic
    count-based wording. The result is persisted to
    ``applications.ops_summary_en/hi``; the ``reviewer_summaries`` write in
    :func:`generate_explanation` is left untouched.
    """
    if isinstance(context, dict) and context.get("pages"):
        from services.ops_llm_review import generate_exception_review

        try:
            result = generate_exception_review(application_id, context)
            _persist_ops_summaries(application_id, result)
            return result
        except Exception as exc:
            # Existing valid summaries survive failed refreshes. No fake success.
            logger.warning("AI exception review unavailable (%s)", type(exc).__name__)
            result = {
                "en": "AI exception review unavailable. Review the saved findings and their evidence manually.",
                "hi": "एआई अपवाद समीक्षा उपलब्ध नहीं है। सहेजी गई समस्याओं और उनके प्रमाण की मानव जाँच करें।",
            }
            _persist_ops_summaries(application_id, result)
            return result
    findings = _extract_findings(context)
    ground_truth = context.get("ground_truth") if isinstance(context, dict) else {}
    fallback = build_bilingual_fallback(findings)

    result = fallback
    try:
        if llm_provider() != "none":
            prompt = _build_bilingual_prompt(findings, ground_truth or {})
            raw_text = call_llm_messages(
                [
                    {
                        "role": "system",
                        "content": (
                            "You write short loan-file summaries for non-technical "
                            "operations staff in India. Use plain words only."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                purpose="summary_en",
                application_id=application_id,
                max_tokens=400,
                timeout=60,
                response_format="json",
            )
            parsed = parse_bilingual_summary(raw_text or "")
            if parsed is not None:
                result = parsed
            else:
                logger.warning("Bilingual LLM summary invalid; using fallback")
    except Exception as exc:  # noqa: BLE001 - fallback covers every failure
        logger.warning("Bilingual LLM summary unavailable; using fallback: %s", exc)

    _persist_ops_summaries(application_id, result)
    return result


def parse_bilingual_summary(text: str) -> dict[str, str] | None:
    """Parse and validate the ``{"en": ..., "hi": ...}`` model response."""
    if not text or not text.strip():
        return None
    cleaned = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    try:
        parsed = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.debug("Bilingual summary is not valid JSON: %s", exc)
        return None
    if not isinstance(parsed, dict):
        return None
    en = parsed.get("en")
    hi = parsed.get("hi")
    if not isinstance(en, str) or not isinstance(hi, str):
        return None
    en, hi = en.strip(), hi.strip()
    if not en or not hi:
        return None
    if len(en) > MAX_SUMMARY_CHARS or len(hi) > MAX_SUMMARY_CHARS:
        logger.debug("Bilingual summary exceeds %d characters", MAX_SUMMARY_CHARS)
        return None
    if not _DEVANAGARI_RE.search(hi):
        logger.debug("Hindi summary contains no Devanagari script")
        return None
    return {"en": en, "hi": hi}


def build_bilingual_fallback(findings: list[dict]) -> dict[str, str]:
    """Deterministic count-based summary in English and Hindi."""
    items = findings or []
    total = len(items)
    high = sum(1 for item in items if str(item.get("severity", "")).upper() == "HIGH")
    medium = sum(1 for item in items if str(item.get("severity", "")).upper() == "MEDIUM")
    low = sum(1 for item in items if str(item.get("severity", "")).upper() == "LOW")

    if total == 0:
        en = (
            "This loan file looks complete with no issues found. "
            "You may proceed with the next step of approval."
        )
        hi = (
            "यह ऋण फ़ाइल पूरी लग रही है और इसमें कोई समस्या नहीं मिली। "
            "आप अनुमोदन के अगले चरण के साथ आगे बढ़ सकते हैं।"
        )
        return {"en": en, "hi": hi}

    parts = []
    if high:
        parts.append(f"{high} high priority")
    if medium:
        parts.append(f"{medium} medium priority")
    if low:
        parts.append(f"{low} low priority")
    breakdown = ", ".join(parts)

    en = (
        f"Review of this loan file found {total} issue(s) needing attention: {breakdown}. "
        "Please check the highlighted pages with your branch team before approval."
    )
    hi = (
        f"इस ऋण फ़ाइल की समीक्षा में {total} समस्या(एँ) पाई गईं जिन पर ध्यान देना आवश्यक है: {breakdown}। "
        "कृपया अनुमोदन से पहले अपनी शाखा टीम के साथ चिह्नित पृष्ठों की जाँच करें।"
    )
    return {"en": en[:MAX_SUMMARY_CHARS], "hi": hi[:MAX_SUMMARY_CHARS]}


def _extract_findings(context: dict | list | None) -> list[dict]:
    if isinstance(context, list):
        return [item for item in context if isinstance(item, dict)]
    if not isinstance(context, dict):
        return []
    for key in ("findings", "anomalies", "exceptions", "top_findings"):
        value = context.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _build_bilingual_prompt(findings: list[dict], ground_truth: dict) -> str:
    titles = {code: template["title"]["en"] for code, template in TEMPLATES.items()}
    known_codes = ", ".join(f"{code}: {title}" for code, title in titles.items())
    compact = [
        {
            "code": item.get("code") or item.get("rule_id"),
            "severity": item.get("severity"),
            "pages": item.get("pages") or item.get("page_number"),
        }
        for item in findings
    ]
    return (
        "Summarize this loan-file review for non-technical operations staff.\n"
        "Write 2-3 sentences in English and 2-3 sentences in Hindi. "
        "Use plain words only: no rule IDs, no codes, no technical terms.\n"
        'Answer in JSON only, exactly: {"en": "...", "hi": "..."}\n'
        "Keep each summary under 600 characters. "
        "The Hindi text must be written in Devanagari script.\n\n"
        f"Known issue titles (for your understanding only, do not repeat codes):\n{known_codes}\n\n"
        "Review findings (TOON):\n"
        f"{encode(compact)}\n"
        "Application details (TOON):\n"
        f"{encode(ground_truth or {})}\n"
    )


def _persist_ops_summaries(application_id: int, result: dict[str, str]) -> None:
    try:
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET ops_summary_en = ?, ops_summary_hi = ? WHERE id = ?",
                (result["en"], result["hi"], application_id),
            )
    except Exception as exc:  # noqa: BLE001 - summary persistence is best effort
        logger.warning("Could not persist ops summaries for %s: %s", application_id, exc)


def _build_prompt(anomalies: list[dict], ground_truth: dict) -> str:
    loan_id = ground_truth.get("loan_id", "")
    applicant_name = ground_truth.get("applicant_name", "")
    return (
        "You are an assistant for an NBFC operations team reviewing loan files in India.\n"
        "Explain anomalies in simple English. Never invent information not in the data provided.\n"
        "You must analyze the ground truth and anomalies, and output a structured configuration in TOON (Token-Oriented Object Notation) format.\n"
        "Do not write any markdown quotes, formatting, or extra text. Output ONLY the raw TOON string.\n\n"
        "Use the following structure for the TOON output:\n"
        "overall_summary: A concise summary of the loan file review results.\n"
        "final_recommendation: APPROVE / SEND BACK TO BRANCH / MANUAL REVIEW\n\n"
        "page_summaries[1]{page_number,document_type,rule_id,summary_points,problem_description}:\n"
        '  3,Bank Statement,TRUSTED_NAME_MISMATCH,["Statement is for State Bank of India account","Covers April to June 2026"],Applicant name does not match the application.\n\n'
        f"Loan file {loan_id} for {applicant_name}.\n"
        "Ground truth from application form (TOON):\n"
        f"{encode(ground_truth)}\n"
        "Anomalies detected (TOON):\n"
        f"{encode(anomalies)}\n"
    )
