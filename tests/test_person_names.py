import pytest

from services.person_names import canonicalize_person_name, names_match


@pytest.mark.parametrize(
    "value",
    [
        "Semali Bakhata",
        "C/O",
        "S/O",
        "F/O",
        "Applicant Name",
        "Unknown",
        "Not Provided",
        "Name: 12345",
        "पति का नाम",
        "सं/ठन का",
        "फोन नंबर",
        "a credit facility",
        "No declaration about name",
        "INDIVIDUAL",
        "Pachpahad",
    ],
)
def test_rejects_obvious_non_person_name_candidates(value: str) -> None:
    assert canonicalize_person_name(value).valid is False


@pytest.mark.parametrize("value", ["Veeru Lal", "Sudha Bai", "राम लाल"])
def test_accepts_indian_and_devanagari_person_names(value: str) -> None:
    result = canonicalize_person_name(value)
    assert result.valid is True
    assert result.value == value


def test_devanagari_names_match_without_latin_transliteration() -> None:
    assert names_match("श्री राम लाल", "राम लाल")


@pytest.mark.parametrize(
    "value",
    [
        "खाताधारक का नाम",  # account holder's name (Hindi label)
        "संगठन का नाम",  # organisation name (Hindi label)
        "અરજદારનું નામ",  # applicant's name (Gujarati label)
        "ખાતાધારકનું નામ",  # account holder's name (Gujarati label)
        "Landline",
        "Business Constitution",
        "Transaction Details",
    ],
)
def test_rejects_form_labels_and_non_name_vocabulary(value: str) -> None:
    assert canonicalize_person_name(value).valid is False


def test_rejects_candidate_containing_indic_label_token() -> None:
    # OCR often glues the label to the value; any candidate carrying a literal
    # label word ("नाम"/"पता") is form furniture, not a person.
    assert canonicalize_person_name("नाम रमेश").valid is False
