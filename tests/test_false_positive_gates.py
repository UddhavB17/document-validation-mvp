"""False-positive gates: checks fire only on eligible pages.

Owned by ``ws-f-accuracy-ops-api``. A synthetic application carries:
(a) a confident PAN card page with PAN X,
(b) a photo page whose OCR text contains a different PAN-shaped string,
(c) an unrelated page (brochure) carrying a different name,
(d) a low-confidence page with a different PAN.
No TRUSTED_*, *_MISMATCH or *_NOT_FOUND anomaly may originate from
(b), (c) or (d); the PAN from (a) is compared.
"""

from __future__ import annotations

from services.consistency_checks import page_eligible_for, run_consistency_checks

TRUSTED_PAN = "ABCDE1234F"
OTHER_PAN = "ZZZZZ9999Z"
TRUSTED_NAME = "Suthar Anupkumar"


def _page(number: int, **overrides):
    page = {
        "page_number": number,
        "page_type": "scanned",
        "ocr_confidence": 0.95,
        "classification_confidence": 0.9,
        "detection_method": "detected",
        "person_id": "primary",
        "ocr_text": "",
        "extracted_fields": {},
    }
    page.update(overrides)
    return page


def _application(pan_on_confident_page: str = TRUSTED_PAN) -> list[dict]:
    return [
        _page(
            1,
            document_type="PAN Card",
            ocr_text=f"Income Tax Department {pan_on_confident_page} {TRUSTED_NAME}",
            extracted_fields={
                "pan_number": pan_on_confident_page,
                "applicant_name": TRUSTED_NAME,
            },
        ),
        _page(
            2,
            document_type="PAN Card",
            triage={"category": "photo"},
            ocr_confidence=0.2,
            classification_confidence=0.9,
            ocr_text=f"blurry photo {OTHER_PAN}",
            extracted_fields={"pan_number": OTHER_PAN},
        ),
        _page(
            3,
            document_type="Offer Letter",
            ocr_text="Join our loan festival brochure Someone Else Entirely",
            extracted_fields={"applicant_name": "Someone Else Entirely"},
        ),
        _page(
            4,
            document_type="PAN Card",
            ocr_confidence=0.3,
            classification_confidence=0.9,
            ocr_text=f"faint {OTHER_PAN}",
            extracted_fields={"pan_number": OTHER_PAN},
        ),
    ]


def _trusted() -> dict:
    return {
        "people": {
            "primary": {
                "applicant_name": TRUSTED_NAME,
                "pan_number": TRUSTED_PAN,
            }
        }
    }


def _flagged(anomalies: list[dict]) -> list[dict]:
    return [
        item
        for item in anomalies
        if str(item.get("rule_id", "")).startswith("TRUSTED_")
        or str(item.get("rule_id", "")).endswith(("_MISMATCH", "_NOT_FOUND"))
    ]


def test_no_findings_originate_from_ineligible_pages() -> None:
    anomalies = run_consistency_checks(_application(), _trusted())
    pages = {item.get("page_number") for item in _flagged(anomalies)}
    assert 2 not in pages
    assert 3 not in pages
    assert 4 not in pages


def test_confident_pan_page_is_compared() -> None:
    anomalies = run_consistency_checks(_application(pan_on_confident_page=OTHER_PAN), _trusted())
    assert any(
        item.get("rule_id") == "TRUSTED_PAN_NUMBER_MISMATCH" and item.get("page_number") == 1
        for item in anomalies
    )


def test_page_eligibility_gate_unit() -> None:
    confident_pan = _page(1, document_type="PAN Card")
    assert page_eligible_for("pan_number", confident_pan) is True
    assert (
        page_eligible_for(
            "pan_number",
            _page(2, document_type="PAN Card", triage={"category": "photo"}),
        )
        is False
    )
    assert (
        page_eligible_for(
            "applicant_name", _page(3, document_type="Offer Letter")
        )
        is False
    )
    assert (
        page_eligible_for(
            "pan_number", _page(4, document_type="PAN Card", ocr_confidence=0.3)
        )
        is False
    )
    # Identity types never inherit; bank statements may.
    assert (
        page_eligible_for(
            "applicant_name",
            _page(
                5,
                document_type="Aadhaar",
                detection_method="inherited",
                classification_confidence=0.9,
            ),
        )
        is False
    )
    assert (
        page_eligible_for(
            "applicant_name",
            _page(
                6,
                document_type="Bank Statement",
                detection_method="run_forward_smoothed",
                classification_confidence=0.2,
            ),
        )
        is True
    )
