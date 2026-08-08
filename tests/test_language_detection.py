from services.language_detection import (
    analyze_text_languages,
    is_regional_language_other_than_hindi,
    normalize_language_code,
)


def test_mixed_english_gujarati_page_reports_both_scripts() -> None:
    result = analyze_text_languages("Loan Application અરજદારનું નામ અને સરનામું")

    assert result["scripts"] == ["gujarati", "latin"]
    assert result["language_candidates"] == [
        {"code": "gu", "name": "Gujarati", "script": "gujarati"}
    ]
    assert result["language_evidence"] == "script_only"
    assert result["multiscript"] is True


def test_devanagari_does_not_collapse_multiple_languages_to_hindi() -> None:
    result = analyze_text_languages("ऋण आवेदन पत्र आवेदक का नाम")

    assert result["scripts"] == ["devanagari"]
    candidates = {item["code"] for item in result["language_candidates"]}
    assert {"hi", "bgc", "bho", "mai", "mag", "bh"}.issubset(candidates)
    assert "language_hints" not in result
    assert result["multiscript"] is False


def test_language_names_and_provider_codes_are_normalized_separately() -> None:
    assert normalize_language_code("Haryanvi") == "bgc"
    assert normalize_language_code("भोजपुरी") == "bho"
    assert normalize_language_code("mah") == "mag"
    assert is_regional_language_other_than_hindi("Maithili") is True
    assert is_regional_language_other_than_hindi("हिंदी") is False
    assert is_regional_language_other_than_hindi("unknown OCR guess") is False
