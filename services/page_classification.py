"""Rule-based page classification with optional local LLM fallback."""

from __future__ import annotations

from typing import Any

from services.bureau_anchors import classify_credit_bureau_by_anchors
from services.document_classifier import classify_page
from services.llm_page_classifier import (
    classify_page_with_llm,
    is_llm_page_classifier_enabled,
    llm_classifier_max_pages_per_file,
    needs_llm_classification,
)


class LlmClassifierBudget:
    """Tracks how many LLM classification calls remain for one file."""

    def __init__(self, remaining: int) -> None:
        self.remaining = remaining

    def consume(self) -> bool:
        if self.remaining <= 0:
            return False
        self.remaining -= 1
        return True


def create_llm_classifier_budget() -> LlmClassifierBudget | None:
    if not is_llm_page_classifier_enabled():
        return None
    return LlmClassifierBudget(llm_classifier_max_pages_per_file())


def classify_page_text(
    text: str,
    *,
    ocr_confidence: float | None = None,
    layout_metadata: dict[str, Any] | None = None,
    llm_budget: LlmClassifierBudget | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Classify page text using rules, optionally falling back to a local LLM."""
    anchor_result = classify_credit_bureau_by_anchors(text, layout_metadata)
    if anchor_result.get("document_type"):
        return (
            {
                "document_type": anchor_result["document_type"],
                "confidence": anchor_result.get("confidence", 0.0),
            },
            {
                "source": "anchors",
                "anchor_document_type": anchor_result.get("document_type"),
                "anchor_confidence": anchor_result.get("confidence", 0.0),
                "anchor_matches": anchor_result.get("matches", {}),
            },
        )

    rule_result = classify_page(text)
    metadata: dict[str, Any] = {
        "source": "rules",
        "rule_document_type": rule_result.get("document_type"),
        "rule_confidence": rule_result.get("confidence", 0.0),
        "anchor_document_type": anchor_result.get("document_type"),
        "anchor_confidence": anchor_result.get("confidence", 0.0),
        "anchor_matches": anchor_result.get("matches", {}),
    }

    if llm_budget is None or not needs_llm_classification(rule_result, ocr_confidence):
        return rule_result, metadata

    if not llm_budget.consume():
        metadata["llm_skipped"] = "budget_exhausted"
        return rule_result, metadata

    enriched_text = _layout_enriched_text(text, layout_metadata)
    llm_result = classify_page_with_llm(enriched_text)
    if not llm_result:
        metadata["llm_skipped"] = "call_failed"
        return rule_result, metadata

    llm_document_type = str(llm_result.get("document_type") or "None")
    rule_document_type = str(rule_result.get("document_type") or "None")
    rule_confidence = float(rule_result.get("confidence") or 0.0)

    if llm_document_type == "None":
        metadata.update(
            {
                "source": "llm",
                "llm_document_type": "None",
                "llm_confidence": llm_result.get("confidence", 0.0),
                "llm_reason": llm_result.get("reason"),
                "rejected_document_type": llm_result.get("rejected_document_type"),
            }
        )
        return rule_result, metadata

    # Keep a confident rule hit when the LLM invents a conflicting label.
    if (
        rule_document_type not in {"", "None"}
        and rule_confidence >= 0.70
        and llm_document_type != rule_document_type
    ):
        metadata.update(
            {
                "source": "rules",
                "llm_document_type": llm_document_type,
                "llm_confidence": llm_result.get("confidence", 0.0),
                "llm_reason": llm_result.get("reason"),
                "llm_skipped": "rule_preferred",
            }
        )
        return rule_result, metadata

    metadata.update(
        {
            "source": "llm",
            "llm_document_type": llm_document_type,
            "llm_confidence": llm_result.get("confidence", 0.0),
            "llm_reason": llm_result.get("reason"),
        }
    )
    return {
        "document_type": llm_document_type,
        "confidence": llm_result.get("confidence", 0.0),
    }, metadata


def _layout_enriched_text(text: str, layout_metadata: dict[str, Any] | None) -> str:
    """Add compact PP-StructureV3 labels to the LLM classification input."""
    if not layout_metadata:
        return text
    blocks = layout_metadata.get("layout_blocks")
    if not isinstance(blocks, list):
        return text

    structured_lines: list[str] = []
    for block in blocks[:40]:
        if not isinstance(block, dict):
            continue
        content = str(block.get("text") or "").strip()
        if not content:
            continue
        block_type = str(block.get("type") or "text").upper()
        structured_lines.append(f"[{block_type}] {content}")

    if not structured_lines:
        return text
    return "STRUCTURED PAGE CONTENT:\n" + "\n".join(structured_lines) + "\n\nFULL OCR TEXT:\n" + text
