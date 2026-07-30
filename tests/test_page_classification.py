from __future__ import annotations

from services import page_classification


def _force_llm(monkeypatch, document_type: str) -> page_classification.LlmClassifierBudget:
    monkeypatch.setattr(
        page_classification,
        "classify_page",
        lambda _text: {"document_type": "None", "confidence": 0.0},
    )
    monkeypatch.setattr(page_classification, "needs_llm_classification", lambda *_args: True)
    monkeypatch.setattr(
        page_classification,
        "classify_page_with_llm",
        lambda _text: {"document_type": document_type, "confidence": 0.95, "reason": "LLM guess"},
    )
    return page_classification.LlmClassifierBudget(1)


def test_llm_cannot_call_application_kyc_table_an_aadhaar(monkeypatch) -> None:
    budget = _force_llm(monkeypatch, "Aadhaar")
    result, metadata = page_classification.classify_page_text(
        "GUARANTOR KYC DETAILS\nAPPLICANT NAME\nAADHAAR\nNot Provided",
        llm_budget=budget,
    )

    assert result["document_type"] == "None"
    assert metadata["llm_skipped"] == "required_evidence_missing"


def test_llm_aadhaar_is_accepted_with_authority_evidence(monkeypatch) -> None:
    budget = _force_llm(monkeypatch, "Aadhaar")
    result, metadata = page_classification.classify_page_text(
        "Unique Identification Authority of India\nName\nRamesh Kumar",
        llm_budget=budget,
    )

    assert result["document_type"] == "Aadhaar"
    assert metadata["source"] == "llm"


def test_llm_cannot_invent_kyc_osv_from_kyc_details(monkeypatch) -> None:
    budget = _force_llm(monkeypatch, "KYC OSV Mark")
    result, metadata = page_classification.classify_page_text(
        "APPLICANT KYC DETAILS\nAADHAAR\nPAN\nVOTER ID",
        llm_budget=budget,
    )

    assert result["document_type"] == "None"
    assert metadata["llm_skipped"] == "required_evidence_missing"
