"""Local Ollama narration for deterministic checklist results."""

from __future__ import annotations

import json
import os

import requests

from database.models import ChecklistItem
from services.llm_client import extract_response_text


CHECKLIST_NARRATION_SYSTEM_PROMPT = (
    "You are a document verification narration assistant for an Indian NBFC. "
    "The deterministic classifier and rules engine already decided the checklist status. "
    "Your only job is to explain why that exact status was assigned in plain English. "
    "Never override, re-derive, contradict, or invent a status. "
    "Use only the provided deterministic status, confidence detail, extracted fields, "
    "and flagged reason. Write 1-2 factual sentences. Do not hedge with phrases like "
    "'appears to', 'might be', or 'possibly'. If fields are missing, state that they "
    "were not extracted. The status word in your answer must be exactly the status "
    "provided by the caller."
)

CHECKLIST_NARRATION_USER_PROMPT_TEMPLATE = (
    "Document type: {document_type}\n"
    "Deterministic status: {status}\n"
    "Confidence detail: {confidence_detail}\n"
    "Flagged reason: {flagged_reason}\n"
    "Extracted fields JSON:\n"
    "{extracted_fields_json}\n\n"
    "Write 1-2 sentences explaining why the deterministic status '{status}' was assigned. "
    "Do not use any other status word."
)


def build_narration_messages(item: ChecklistItem) -> list[dict[str, str]]:
    """Return Ollama chat API messages for one non-verified checklist item."""
    return [
        {"role": "system", "content": CHECKLIST_NARRATION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": CHECKLIST_NARRATION_USER_PROMPT_TEMPLATE.format(
                document_type=item.document_name,
                status=item.status,
                confidence_detail=item.confidence_detail,
                flagged_reason=item.flagged_reason or "none",
                extracted_fields_json=json.dumps(item.extracted_fields, indent=2, ensure_ascii=False),
            ),
        },
    ]


def narrate_checklist_item(item: ChecklistItem, *, timeout: int = 60) -> str | None:
    """Generate narration through local Ollama without changing deterministic status."""
    if item.status == "verified":
        return None

    url = _ollama_chat_url()
    model = _narration_model()
    try:
        response = requests.post(
            url,
            json={"model": model, "messages": build_narration_messages(item), "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    text = extract_response_text(response.json())
    return _guard_narration(text, item.status)


def _guard_narration(text: str | None, status: str) -> str | None:
    if not text:
        return None
    cleaned = " ".join(str(text).split())
    forbidden_statuses = {"verified", "needs_review", "missing", "unknown"} - {status}
    lowered = cleaned.lower()
    if any(forbidden in lowered for forbidden in forbidden_statuses):
        return None
    return cleaned


def _ollama_chat_url() -> str:
    configured = (
        os.getenv("CHECKLIST_NARRATION_OLLAMA_URL")
        or os.getenv("LOCAL_LLM_API_URL")
        or os.getenv("LLM_API_URL")
        or "http://localhost:11434/api/generate"
    )
    configured = configured.rstrip("/")
    if configured.endswith("/api/generate"):
        return configured[: -len("/api/generate")] + "/api/chat"
    if configured.endswith("/api/chat"):
        return configured
    return configured + "/api/chat"


def _narration_model() -> str:
    return (
        os.getenv("CHECKLIST_NARRATION_MODEL")
        or os.getenv("LOCAL_LLM_MODEL")
        or os.getenv("LLM_MODEL")
        or "qwen3:14b"
    )
