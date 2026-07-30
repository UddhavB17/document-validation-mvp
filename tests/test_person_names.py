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


@pytest.mark.parametrize("value", ["Peeru Lal", "Radha Bai", "राम लाल"])
def test_accepts_indian_and_devanagari_person_names(value: str) -> None:
    result = canonicalize_person_name(value)
    assert result.valid is True
    assert result.value == value


def test_devanagari_names_match_without_latin_transliteration() -> None:
    assert names_match("श्री राम लाल", "राम लाल")
