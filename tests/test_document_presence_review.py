"""Presence uncertainty stays reviewable without accepting incomplete evidence."""

import json

import pytest

import database.db as db
from services.checklist_engine import _run_presence_checks
from services.checklist_output import build_checklist_verification_response
from services.checklist_status import build_checklist_status
from services.exception_aggregator import save_aggregation
from services.ops_presentation import build_ops_payload
from services.pipeline.persistence import _save_ground_truth, _save_pages


def _page(number=173, kind="Insurance Form", confidence=0.64, owner=None, **extras):
    return {
        "page_number": number,
        "document_type": kind,
        "page_type": "scanned",
        "ocr_confidence": confidence,
        "classification_confidence": 0.99,
        "ocr_status": "success",
        "is_readable": True,
        "person_id": owner,
        "extracted_fields": {},
        **extras,
    }


def _item(**extras):
    return {
        "s_no": 22,
        "document_type": "Insurance Form",
        "check_type": "presence",
        "description": "Insurance form",
        "ai_checkable": True,
        "severity_if_missing": "MEDIUM",
        **extras,
    }


@pytest.mark.parametrize(
    "check_type", ["presence", "presence_any", "presence_all", "presence_min_count", "requirements"]
)
def test_uncertain_evidence_preserved_across_presence_rule_shapes(check_type):
    item = _item(check_type=check_type)
    if check_type in {"presence_any", "presence_all"}:
        item["document_type"] = ["Insurance Form"]
    if check_type == "requirements":
        item["requirements"] = [{"document_type": "Insurance Form"}]
    pages = [_page(), _page(174)]
    findings = _run_presence_checks(pages, [item], {})
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "REVIEW_REQUIRED_S22"
    assert findings[0]["evidence_json"]["candidate_pages"] == [173, 174]
    assert findings[0]["collapsed_page_numbers"] == [173, 174]
    rows = build_checklist_status([item], pages, findings)
    assert rows[0]["status"] == "manual_review"
    assert rows[0]["pages"] == "173, 174"


def test_actual_absence_and_known_unrelated_unreadable_page_remain_missing():
    for pages in ([], [_page(kind="Loan Agreement", is_readable=False, ocr_status="failed")]):
        assert _run_presence_checks(pages, [_item()], {})[0]["rule_id"] == "MISSING_DOC_S22"


def test_scan_without_confidence_requires_review():
    findings = _run_presence_checks([_page(confidence=None)], [_item()], {})
    assert findings[0]["rule_id"] == "REVIEW_REQUIRED_S22"
    assert findings[0]["evidence_json"]["candidate_pages"] == [173]


@pytest.mark.parametrize("kind,status", [("Unknown", "failed"), ("OCR Skipped", "not_applicable")])
def test_unreadable_unidentified_pages_do_not_prove_absence(kind, status):
    findings = _run_presence_checks(
        [_page(kind=kind, ocr_status=status, is_readable=False)], [_item()], {}
    )
    assert findings[0]["rule_id"] == "REVIEW_REQUIRED_S22"
    assert findings[0]["evidence_json"]["coverage_pages"] == [173]


def test_scoped_evidence_does_not_accept_another_borrower():
    item = _item(scope="each_borrower")
    people = {
        "people": {
            "primary": {"applicant_name": "Ravi"},
            "coapplicant_1": {"applicant_name": "Rita"},
        }
    }
    primary = _page(confidence=0.99, owner="primary")
    findings = _run_presence_checks([primary], [item], people)
    assert [f["rule_id"] for f in findings] == ["MISSING_DOC_S22_coapplicant_1"]
    findings = _run_presence_checks([primary, _page(174, confidence=0.99)], [item], people)
    assert [f["rule_id"] for f in findings] == ["REVIEW_REQUIRED_S22_coapplicant_1"]
    assert findings[0]["evidence_json"]["candidate_pages"] == [174]


def test_duplicate_cheque_pages_do_not_satisfy_minimum():
    pages = [
        _page(n, kind="PDC", confidence=0.99, extracted_fields={"cheque_numbers": ["000001"]})
        for n in (1, 2)
    ]
    item = _item(document_type="PDC", check_type="presence_min_count", min_count=2)
    findings = _run_presence_checks(pages, [item], {})
    assert findings[0]["rule_id"] == "MISSING_DOC_S22"
    assert findings[0]["found_value"] == "1 cheque(s)"


def test_alternative_accepted_document_satisfies_presence_without_false_warning():
    item = _item(check_type="presence_any", document_type=["Insurance Form", "Sanction Letter"])
    pages = [_page(), _page(174, kind="Sanction Letter", confidence=0.99)]
    assert _run_presence_checks(pages, [item], {}) == []


def test_presence_review_survives_database_and_ops_output(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATABASE_PATH", tmp_path / "presence.db")
    db.init_db()
    with db.get_connection() as connection:
        app_id = connection.execute(
            "INSERT INTO applications (loan_id, product_type) VALUES (?, ?) RETURNING id",
            ("PRESENCE-SYNTHETIC", "LAP"),
        ).fetchone()["id"]
    pages = [_page(), _page(174)]
    items = [_item()]
    findings = _run_presence_checks(pages, items, {})
    _save_pages(app_id, pages)
    _save_ground_truth(
        app_id, {"case_type": "Normal Case", "people": {"primary": {"applicant_name": "Example"}}}
    )
    save_aggregation(app_id, findings, "MEDIUM")
    monkeypatch.setattr("services.checklist_output.get_all_checklist_items", lambda *_: items)
    monkeypatch.setattr("services.checklist_service.get_all_checklist_items", lambda *_: items)
    result = build_checklist_verification_response(
        loan_file_id="test", pages=pages, anomalies=findings
    )
    assert result.items[0].status == "manual_review"
    assert result.summary.required_and_missing == 0
    payload = build_ops_payload(app_id)
    assert payload["checklist"] == {
        "total": 1,
        "found": 0,
        "missing": 0,
        "not_checked": 1,
        "rows": [
            {
                "s_no": 22,
                "description": "Insurance Form",
                "status": "NOT_CHECKED",
                "pages": [173, 174],
            }
        ],
    }
    assert payload["top_findings"][0]["code"] == "REVIEW_REQUIRED"
    assert payload["top_findings"][0]["pages"] == [173, 174]
    assert "raw_json" not in json.dumps(payload)
