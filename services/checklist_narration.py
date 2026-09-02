"""LLM narration for deterministic checklist results."""

from __future__ import annotations

import json
from database.models import ChecklistItem
from services.llm_client import call_llm_messages


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
                extracted_fields_json=json.dumps(
                    item.extracted_fields, indent=2, ensure_ascii=False
                ),
            ),
        },
    ]


def narrate_checklist_item(item: ChecklistItem, *, timeout: int = 60) -> str | None:
    """Generate narration through the configured LLM without changing status."""
    if item.status == "verified":
        return None

    try:
        text = call_llm_messages(
            build_narration_messages(item),
            max_tokens=140,
            timeout=timeout,
        )
    except Exception:
        return None

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
