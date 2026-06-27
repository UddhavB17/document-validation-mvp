"""Tests for services/checklist_engine.py."""

import pytest

from services.checklist_engine import ISSUE_MISSING, ISSUE_MISMATCH, evaluate_checklist


# ── Helper fixtures ───────────────────────────

BASE_CHECKLIST = {
    "required_documents": ["PAN", "Aadhaar", "Bank Statement"],
    "field_rules": {
        "loan_amount": {"type": "number", "min": 100_000, "max": 10_000_000},
    },
}


# ── Document presence checks ──────────────────

def test_no_exceptions_when_all_docs_present() -> None:
    scanned = {"PAN": {}, "Aadhaar": {}, "Bank Statement": {}}
    digital = {"loan_amount": "500000"}
    result = evaluate_checklist(BASE_CHECKLIST, digital, scanned)
    assert result == []


def test_flags_single_missing_document() -> None:
    scanned = {"PAN": {}, "Aadhaar": {}}   # Bank Statement missing
    digital = {"loan_amount": "500000"}
    result = evaluate_checklist(BASE_CHECKLIST, digital, scanned)
    issues = [e["document"] for e in result]
    assert "Bank Statement" in issues
    assert all(e["issue"] == ISSUE_MISSING for e in result)


def test_flags_all_missing_documents() -> None:
    result = evaluate_checklist(BASE_CHECKLIST, {}, {})
    missing_docs = {e["document"] for e in result if e["issue"] == ISSUE_MISSING}
    assert "PAN" in missing_docs
    assert "Aadhaar" in missing_docs
    assert "Bank Statement" in missing_docs


# ── Field-level rule checks ───────────────────

def test_flags_missing_required_field() -> None:
    scanned = {"PAN": {}, "Aadhaar": {}, "Bank Statement": {}}
    digital = {}   # loan_amount absent
    result = evaluate_checklist(BASE_CHECKLIST, digital, scanned)
    issues = [e["issue"] for e in result]
    assert ISSUE_MISSING in issues


def test_flags_non_numeric_field() -> None:
    scanned = {"PAN": {}, "Aadhaar": {}, "Bank Statement": {}}
    digital = {"loan_amount": "not-a-number"}
    result = evaluate_checklist(BASE_CHECKLIST, digital, scanned)
    issues = [e["issue"] for e in result]
    assert ISSUE_MISMATCH in issues


def test_flags_field_below_minimum() -> None:
    scanned = {"PAN": {}, "Aadhaar": {}, "Bank Statement": {}}
    digital = {"loan_amount": "50000"}   # below min 100,000
    result = evaluate_checklist(BASE_CHECKLIST, digital, scanned)
    issues = [e["issue"] for e in result]
    assert ISSUE_MISMATCH in issues


def test_flags_field_above_maximum() -> None:
    scanned = {"PAN": {}, "Aadhaar": {}, "Bank Statement": {}}
    digital = {"loan_amount": "99999999"}  # above max 10,000,000
    result = evaluate_checklist(BASE_CHECKLIST, digital, scanned)
    issues = [e["issue"] for e in result]
    assert ISSUE_MISMATCH in issues


def test_valid_field_within_range() -> None:
    scanned = {"PAN": {}, "Aadhaar": {}, "Bank Statement": {}}
    digital = {"loan_amount": "2000000"}
    result = evaluate_checklist(BASE_CHECKLIST, digital, scanned)
    assert result == []
