import json

import pytest

from services.ops_llm_review import _dismissible, _validate_batch, generate_page_review


def test_review_covers_every_page_and_finding_then_translates(monkeypatch):
    calls, saved = [], []
    pages = [
        {"page_number": n, "document_type": "Unknown", "ocr_text": f"Page {n} evidence"}
        for n in range(1, 26)
    ]
    findings = [
        {"rule_id": "UNCLASSIFIED_PAGE", "page_number": 25, "reason": "unknown", "severity": "LOW"}
    ]

    def fake(_app, purpose, instruction, data, tokens):
        calls.append((purpose, data))
        if purpose == "ops_page_review":
            return {
                "pages": [
                    {
                        "page": p["page"],
                        "assessment": "unknown",
                        "reason": "Check document type",
                        "quote_ref": 0,
                    }
                    for p in data["pages"]
                ]
            }
        if purpose == "ops_findings_review":
            return {
                "findings": [
                    {"ref": 1, "verdict": "unresolved", "reason": "Unknown type", "pages": [25]}
                ]
            }
        if purpose == "ops_summary_en":
            return {"en": "Reviewed 25 pages. Page 25 requires document identification."}
        assert data == {"en": "Reviewed 25 pages. Page 25 requires document identification."}
        return {"hi": "25 पृष्ठों की समीक्षा हुई। पृष्ठ 25 के दस्तावेज़ की पहचान आवश्यक है।"}

    class Store:
        def exists(self, key):
            return False

        def put(self, key, data, content_type):
            if key.endswith("ops-review.json"):
                saved.append(json.loads(data))

    monkeypatch.setattr("services.ops_llm_review._call", fake)
    monkeypatch.setattr("services.ops_llm_review.get_store", Store)
    result = generate_page_review(4, {"pages": pages, "findings": findings})
    assert [c[0] for c in calls] == [
        "ops_page_review",
        "ops_page_review",
        "ops_findings_review",
        "ops_summary_en",
        "ops_summary_hi",
    ]
    assert len(saved[0]["pages"]) == 25
    assert saved[0]["total_findings"] == 1
    assert result["en"].startswith("Reviewed 25")


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [{"page": 2, "assessment": "consistent", "reason": "ok"}],
        [{"page": 1, "assessment": "consistent", "reason": "ok", "quote": "invented"}],
    ],
)
def test_incomplete_or_fabricated_page_evidence_is_rejected(rows):
    with pytest.raises(ValueError):
        _validate_batch({"pages": rows}, [{"page": 1, "text": "actual evidence"}])


def test_dismissal_requires_confidence_equivalence_and_source_quote():
    finding = {
        "rule_id": "PAN_NUMBER_MISMATCH",
        "expected_value": "ABCDE1234F",
        "found_value": "ABCDE 1234 F",
        "page_number": 2,
    }
    pages = [{"page": 2, "text": "PAN ABCDE 1234 F"}]
    item = {
        "verdict": "possible_false_positive",
        "confidence": 0.99,
        "pages": [2],
        "quote": "ABCDE 1234 F",
    }
    assert _dismissible(item, finding, pages)
    assert not _dismissible({**item, "confidence": 0.9}, finding, pages)
    assert not _dismissible({**item, "confidence": float("nan")}, finding, pages)
    assert not _dismissible({**item, "quote": "fabricated"}, finding, pages)
    assert not _dismissible(item, {**finding, "expected_value": "ABCDE1234G"}, pages)
    assert not _dismissible(item, {**finding, "page_number": 3}, pages)


@pytest.mark.parametrize(
    "rule,value",
    [
        ("PAN_NUMBER_MISMATCH", "---"),
        ("PAN_NUMBER_MISMATCH", "123"),
        ("AADHAAR_NUMBER_MISMATCH", "123456789012"),
    ],
)
def test_malformed_ids_cannot_be_automatically_dismissed(rule, value):
    finding = {"rule_id": rule, "expected_value": value, "found_value": value, "page_number": 1}
    item = {"verdict": "possible_false_positive", "confidence": 1.0, "pages": [1], "quote": value}
    assert not _dismissible(item, finding, [{"page": 1, "text": value}])
