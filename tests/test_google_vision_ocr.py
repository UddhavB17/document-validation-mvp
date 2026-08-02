from __future__ import annotations

import json

import pytest

from services import google_vision_ocr


@pytest.fixture(autouse=True)
def _isolate_from_settings_db(monkeypatch) -> None:
    # The provider prefers the settings DB over environment variables; tests
    # must not depend on whatever the developer's live settings table holds.
    monkeypatch.setattr(google_vision_ocr, "get_setting", lambda _key, default=None: default)


def test_google_vision_rest_api_key_parses_document_text(monkeypatch, tmp_path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"fake-image")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_VISION_AUTH", "api_key")

    captured: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "responses": [{
                    "fullTextAnnotation": {
                        "text": "Applicant Name\nRamesh Kumar",
                        "pages": [{
                            "blocks": [{
                                "blockType": "TEXT",
                                "confidence": 0.8,
                                "paragraphs": [{
                                    "words": [{
                                        "confidence": 0.9,
                                        "symbols": [{"text": "R"}, {"text": "K"}],
                                    }]
                                }],
                            }]
                        }],
                    },
                    "textAnnotations": [
                        {"description": "Applicant Name\nRamesh Kumar"},
                        {
                            "description": "Ramesh",
                            "boundingPoly": {"vertices": [{"x": 1, "y": 2}, {"x": 3, "y": 4}]},
                        },
                    ],
                }]
            }

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(google_vision_ocr.requests, "post", fake_post)

    result = google_vision_ocr.run_google_vision_ocr_on_page(image)

    assert "key=test-key" in captured["url"]
    assert captured["json"]["requests"][0]["features"][0]["type"] == "DOCUMENT_TEXT_DETECTION"
    assert result["ocr_text"] == "Applicant Name\nRamesh Kumar"
    assert result["ocr_pipeline"] == "Google Vision API"
    assert result["ocr_provider"] == "google_vision"
    assert result["is_readable"] is True
    assert result["confidence"] == pytest.approx(0.85)
    assert result["bounding_boxes"][0]["text"] == "Ramesh"
    assert result["layout_blocks"][0]["text"] == "RK"


def test_google_vision_returns_clear_error_when_image_missing(tmp_path) -> None:
    result = google_vision_ocr.run_google_vision_ocr_on_page(tmp_path / "missing.png")

    assert result["is_readable"] is False
    assert result["ocr_provider"] == "google_vision"
    assert "Image file not found" in result["error"]


def test_google_vision_retries_transient_service_failures(monkeypatch, tmp_path) -> None:
    image = tmp_path / "page.png"
    image.write_bytes(b"fake-image")
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_VISION_AUTH", "api_key")
    monkeypatch.setenv("GOOGLE_VISION_MAX_ATTEMPTS", "3")
    monkeypatch.setattr(google_vision_ocr.time, "sleep", lambda _seconds: None)
    calls: list[int] = []

    def transient_then_success(_path):
        calls.append(1)
        if len(calls) < 3:
            raise google_vision_ocr.requests.ConnectionError("503 hostname lookup error")
        return {"fullTextAnnotation": {"text": "Recovered OCR text", "pages": []}}

    monkeypatch.setattr(google_vision_ocr, "_call_rest_api_key", transient_then_success)

    result = google_vision_ocr.run_google_vision_ocr_on_page(image)

    assert len(calls) == 3
    assert result["ocr_text"] == "Recovered OCR text"
    assert result.get("error") is None
