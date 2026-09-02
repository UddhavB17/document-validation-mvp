"""Tests for decomposed backend domain packages and compatibility facades."""

from __future__ import annotations

import importlib

import pytest
from services.checklist_engine import (
    bank_statement_required_month_labels,
    build_anomaly,
    condition_applies,
)
from services.consistency_checks import (
    EXACT_FIELDS,
    _matches,
    _names_equivalent,
    run_consistency_checks,
)
from services.field_extractor import extract_fields
from services.person_ownership import resolve_person_owner


@pytest.mark.parametrize(
    "module_path",
    [
        "services.extraction._shared",
        "services.extraction.loan_terms",
        "services.extraction.identity",
        "services.extraction.banking",
        "services.checklist.bank_period",
        "services.checklist.anomaly_builder",
        "services.consistency.matching",
        "services.consistency.runner",
        "services.ownership.resolution",
        "services.ownership._helpers",
    ],
)
def test_internal_domain_modules_import(module_path: str) -> None:
    importlib.import_module(module_path)


def test_field_extractor_facade_matches_dispatcher() -> None:
    text = "Sanctioned Loan Amount: Rs. 5,00,000\nTenure: 60 months"
    assert extract_fields("Sanction Letter", text)["loan_amount"] == "500000"


def test_consistency_matches_honorific_tolerance() -> None:
    assert _names_equivalent("Mr. Peeru Lal", "PEERU LAL")


def test_consistency_exact_pan_match() -> None:
    assert _matches("pan_number", "TSTAA0001T", "tstaa0001t")


def test_assign_page_owners_best_effort_in_consistency_runner(monkeypatch) -> None:
    """Ownership assignment failures must not suppress consistency checks."""
    calls: list[str] = []

    def _boom(_pages, _trusted):
        calls.append("assign")
        raise ValueError("simulated ownership failure")

    monkeypatch.setattr(
        "services.person_ownership.assign_page_owners",
        _boom,
    )
    pages = [
        {
            "page_number": 1,
            "document_type": "PAN Card",
            "extracted_fields": {"pan_number": "TSTAA0001T", "applicant_name": "Peeru Lal"},
            "ocr_text": "PAN TSTAA0001T",
        }
    ]
    trusted = {"people": {"primary": {"pan_number": "TSTAA0001T", "applicant_name": "Peeru Lal"}}}
    anomalies = run_consistency_checks(pages, trusted)
    assert calls == ["assign"]
    assert isinstance(anomalies, list)


def test_resolve_person_owner_returns_dict_shape() -> None:
    page = {
        "document_type": "Bank Statement",
        "ocr_text": "Account Holder Name\nPEERU LAL",
        "extracted_fields": {"account_holder_name": "Peeru Lal"},
    }
    people = {"primary": {"applicant_name": "Peeru Lal", "pan_number": "TSTAA0001T"}}
    owner = resolve_person_owner(page, people, "Bank Statement")
    assert "person_id" in owner
    assert "confidence" in owner


def test_checklist_build_anomaly_has_timestamp() -> None:
    anomaly = build_anomaly("TEST", 1, "HIGH", "expected", "found", "reason")
    assert anomaly["rule_id"] == "TEST"
    assert "timestamp" in anomaly


def test_exact_fields_constant_exposed_from_facade() -> None:
    assert "pan_number" in EXACT_FIELDS


def test_bank_statement_month_labels_helper() -> None:
    labels = bank_statement_required_month_labels(
        {"application_date": "2025-01-15"},
        6.0,
    )
    assert isinstance(labels, list)
    assert labels


def test_condition_applies_unknown_when_field_missing() -> None:
    item = {"condition_field": "loan_amount", "condition_operator": ">=", "condition_value": 100000}
    assert condition_applies(item, {}) is None
