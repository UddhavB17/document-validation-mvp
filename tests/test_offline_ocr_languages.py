from services.offline_ocr_languages import (
    normalize_paddle_language,
    recognition_model_for_language,
)


def test_haryanvi_and_bihari_languages_share_devanagari_recognizer(monkeypatch) -> None:
    for variable in (
        "PADDLE_OCR_REC_MODEL",
        "PADDLE_OCR_REC_MODEL_DEVANAGARI",
        "PADDLE_OCR_REC_MODEL_HI",
    ):
        monkeypatch.delenv(variable, raising=False)

    for language in ("bgc", "bho", "mai", "mah", "bh", "Haryanvi", "Bhojpuri"):
        assert recognition_model_for_language(language) == "devanagari_PP-OCRv5_mobile_rec"


def test_other_supported_scripts_select_their_own_recognizers(monkeypatch) -> None:
    for variable in (
        "PADDLE_OCR_REC_MODEL",
        "PADDLE_OCR_REC_MODEL_ARABIC",
        "PADDLE_OCR_REC_MODEL_TAMIL",
        "PADDLE_OCR_REC_MODEL_TELUGU",
        "PADDLE_OCR_REC_MODEL_EN",
    ):
        monkeypatch.delenv(variable, raising=False)

    assert recognition_model_for_language("ur") == "arabic_PP-OCRv5_mobile_rec"
    assert recognition_model_for_language("ta") == "ta_PP-OCRv5_mobile_rec"
    assert recognition_model_for_language("te") == "te_PP-OCRv5_mobile_rec"
    assert recognition_model_for_language("en") == "en_PP-OCRv5_mobile_rec"
    assert normalize_paddle_language("Magahi") == "mah"


def test_unknown_paddle_language_uses_provider_auto_selection(monkeypatch) -> None:
    monkeypatch.delenv("PADDLE_OCR_REC_MODEL", raising=False)

    assert recognition_model_for_language("gu") is None
