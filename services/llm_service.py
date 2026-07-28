"""LLM explanation service using local/open-source HTTP APIs with TOON format."""

import json
import re

from database.db import get_connection
from services.llm_client import call_llm_api, extract_response_text as _extract_response_text


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
        print(f"Error calling LLM or decoding TOON: {exc}")

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
        print(f"TOON decode error: {exc}")
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

        page_summaries.append({
            "page_number": page_num,
            "document_type": doc_type,
            "summary_points": summary_points,
            "problem_description": reason
        })

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
        "page_summaries": page_summaries
    }


def summarize_exceptions(exceptions: list[dict]) -> str | None:
    if not exceptions:
        return None
    default_summary = build_default_summary(exceptions, {})
    return json.dumps(default_summary, ensure_ascii=False)


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
        "page_summaries[1]{page_number,document_type,summary_points,problem_description}:\n"
        "  3,Bank Statement,[\"Statement is for State Bank of India account\",\"Covers April to June 2026\"],Applicant name does not match the application.\n\n"
        f"Loan file {loan_id} for {applicant_name}.\n"
        "Ground truth from application form:\n"
        f"{json.dumps(ground_truth, indent=2)}\n"
        "Anomalies detected:\n"
        f"{json.dumps(anomalies, indent=2)}\n"
    )


