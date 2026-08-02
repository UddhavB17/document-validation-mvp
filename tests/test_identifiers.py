"""Aadhaar plausibility: 12 digits is necessary but not sufficient."""

import pytest

from services.identifiers import plausible_aadhaar_digits


def test_accepts_plain_twelve_digit_aadhaar() -> None:
    assert plausible_aadhaar_digits("234512341234") == "234512341234"


def test_accepts_spaced_and_hyphenated_aadhaar() -> None:
    assert plausible_aadhaar_digits("2345 1234 1234") == "234512341234"
    assert plausible_aadhaar_digits("2345-1234-1234") == "234512341234"


@pytest.mark.parametrize(
    "value",
    [
        "919374200200",  # mobile number with 91 country code
        "917359401463",
        "9374200200",  # bare 10-digit mobile
        "12345",
        "",
        None,
    ],
)
def test_rejects_phone_numbers_and_wrong_lengths(value) -> None:
    assert plausible_aadhaar_digits(value) is None


def test_91_prefix_requires_mobile_shape_to_reject() -> None:
    # 12-digit values starting 91 but not followed by a valid mobile first
    # digit (6-9) are still plausible Aadhaar numbers.
    assert plausible_aadhaar_digits("915374200200") == "915374200200"
