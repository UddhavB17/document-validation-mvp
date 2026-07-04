"""LLM explanation service using local/open-source HTTP APIs."""

import json

from database.db import get_connection
from services.llm_client import call_llm_api, extract_response_text as _extract_response_text


def generate_explanation(
    anomalies: list[dict],
    ground_truth: dict,
    application_id: int | None = None,
) -> str | None:
    """Generate a short operations summary from anomalies.

    Defaults to a local Ollama-style API. In production, set LLM_API_URL or
    OPEN_SOURCE_LLM_API_URL to an open-source model endpoint.
    """
    if not anomalies:
        return None

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    try:
        text = call_llm_api(_build_prompt(anomalies, ground_truth))
    except Exception:
        return None

    if text and application_id is not None:
        with get_connection() as connection:
            connection.execute(
                "UPDATE applications SET llm_summary = ? WHERE id = ?",
                (text, application_id),
            )
        try:
            from services.audit_service import log_action

            log_action(application_id, "llm_summary_generated", {"summary_length": len(text)})
        except Exception:
            pass

    return text


def summarize_exceptions(exceptions: list[dict]) -> str | None:
    if not exceptions:
        return None

    high = sum(1 for item in exceptions if str(item.get("severity", "")).upper() == "HIGH")
    medium = sum(1 for item in exceptions if str(item.get("severity", "")).upper() == "MEDIUM")
    low = sum(1 for item in exceptions if str(item.get("severity", "")).upper() == "LOW")

    parts = [f"{len(exceptions)} exception(s) require review:"]
    if high:
        parts.append(f"{high} high-severity")
    if medium:
        parts.append(f"{medium} medium-severity")
    if low:
        parts.append(f"{low} low-severity")
    return "\n".join(parts)


def _build_prompt(anomalies: list[dict], ground_truth: dict) -> str:
    loan_id = ground_truth.get("loan_id", "")
    applicant_name = ground_truth.get("applicant_name", "")
    return (
        "You are an assistant for an NBFC operations team reviewing loan files in India. "
        "Explain anomalies in simple English. Always state the page number. "
        "Never invent information not in the data provided.\n\n"
        f"Loan file {loan_id} for {applicant_name}.\n"
        "Ground truth from application form:\n"
        f"{json.dumps(ground_truth, indent=2)}\n"
        "Anomalies detected:\n"
        f"{json.dumps(anomalies, indent=2)}\n"
        "Write:\n"
        "1. One sentence overall summary\n"
        "2. Per anomaly: what is wrong, page number, action needed\n"
        "3. Final: APPROVE / SEND BACK TO BRANCH / MANUAL REVIEW\n"
        "Keep response under 200 words."
    )


