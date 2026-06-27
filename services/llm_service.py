"""LLM explanation service."""

import json
import os

import requests

from database.db import get_connection


def generate_explanation(
    anomalies: list[dict],
    ground_truth: dict,
    application_id: int | None = None,
) -> str | None:
    if not anomalies:
        return None

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass

    try:
        text = _call_llm_api(_build_prompt(anomalies, ground_truth))
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


def _call_llm_api(prompt: str) -> str | None:
    api_url = (
        os.getenv("LLM_API_URL")
        or os.getenv("LOCAL_LLM_API_URL")
        or os.getenv("OPEN_SOURCE_LLM_API_URL")
        or "http://localhost:11434/api/generate"
    )
    model = os.getenv("LOCAL_LLM_MODEL") or os.getenv("LLM_MODEL") or "llama3.1"

    if "11434" in api_url or api_url.endswith("/api/generate"):
        payload = {"model": model, "prompt": prompt, "stream": False}
    else:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 450,
        }

    response = requests.post(api_url, json=payload, timeout=90)
    response.raise_for_status()
    return _extract_response_text(response.json())


def _extract_response_text(payload: dict) -> str | None:
    if payload.get("response"):
        return payload["response"]
    if payload.get("text"):
        return payload["text"]
    if payload.get("output"):
        return payload["output"]

    choices = payload.get("choices") or []
    if choices:
        first_choice = choices[0]
        message = first_choice.get("message") or {}
        return message.get("content") or first_choice.get("text")

    return None


def summarize_exceptions(exceptions: list[dict]) -> str | None:
    if not exceptions:
        return None
    return f"{len(exceptions)} exception(s) require review."
