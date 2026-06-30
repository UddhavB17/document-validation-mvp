"""Tests for services/ocr_engine.py and services/preprocessing.py.

Strategy
--------
- preprocessing tests use real OpenCV images (synthesised via numpy).
- OCR tests mock ``services.ocr_engine.ocr_model`` so the suite runs even
  when PaddleOCR / PaddlePaddle are not installed in this environment.
- The ``test_ocr_model_loaded_once`` test verifies the module-level singleton
  pattern by asserting the same object identity is returned on repeated access.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Image creation helpers (no PDF or OCR dependency)
# ---------------------------------------------------------------------------


def _make_sharp_png(path: Path, size: int = 200) -> None:
    """Save a high-contrast checkerboard PNG – high Laplacian variance."""
    cv2 = pytest.importorskip("cv2")
    img = np.zeros((size, size), dtype=np.uint8)
    # Checkerboard: alternating 10×10 black/white squares → many sharp edges
    square = 10
    for r in range(0, size, square):
        for c in range(0, size, square):
            if (r // square + c // square) % 2 == 0:
                img[r : r + square, c : c + square] = 255
    cv2.imwrite(str(path), img)


def _make_blurry_png(path: Path, size: int = 200) -> None:
    """Save a heavily blurred uniform-grey PNG – near-zero Laplacian variance."""
    cv2 = pytest.importorskip("cv2")
    img = np.full((size, size), 128, dtype=np.uint8)
    blurred = cv2.GaussianBlur(img, (51, 51), 0)
    cv2.imwrite(str(path), blurred)


# ---------------------------------------------------------------------------
# Tests: preprocessing.check_readability
# ---------------------------------------------------------------------------


class TestCheckReadability:

    def test_sharp_image_is_readable(self, tmp_path: Path) -> None:
        """A high-contrast checkerboard must be classified as readable."""
        pytest.importorskip("cv2")
        from services.preprocessing import check_readability

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        result = check_readability(img_path)

        assert result["is_readable"] is True
        assert result["blur_score"] >= 100.0

    def test_blurry_image_flagged(self, tmp_path: Path) -> None:
        """A flat/blurry image must be flagged as unreadable."""
        pytest.importorskip("cv2")
        from services.preprocessing import check_readability

        img_path = tmp_path / "blurry.png"
        _make_blurry_png(img_path)

        result = check_readability(img_path)

        assert result["is_readable"] is False
        assert result["blur_score"] < 100.0

    def test_missing_image_returns_unreadable(self, tmp_path: Path) -> None:
        """A path that does not exist must return is_readable=False, score=0.0."""
        pytest.importorskip("cv2")
        from services.preprocessing import check_readability

        result = check_readability(tmp_path / "nonexistent.png")

        assert result["is_readable"] is False
        assert result["blur_score"] == 0.0


# ---------------------------------------------------------------------------
# Tests: preprocessing.preprocess_image
# ---------------------------------------------------------------------------


class TestPreprocessImage:

    def test_returns_numpy_array(self, tmp_path: Path) -> None:
        """preprocess_image must return a numpy ndarray."""
        pytest.importorskip("cv2")
        from services.preprocessing import preprocess_image

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        result = preprocess_image(img_path)

        assert isinstance(result, np.ndarray)
        assert result.ndim == 2  # grayscale: height × width

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        """preprocess_image must raise FileNotFoundError for a missing path."""
        pytest.importorskip("cv2")
        from services.preprocessing import preprocess_image

        with pytest.raises(FileNotFoundError):
            preprocess_image(tmp_path / "missing.png")


# ---------------------------------------------------------------------------
# Tests: ocr_engine.run_ocr_on_page
# ---------------------------------------------------------------------------


class TestRunOcrOnPage:

    # ── test_blurry_image_flagged ────────────────────────────────────────────

    def test_blurry_image_flagged(self, tmp_path: Path) -> None:
        """A blurry image must return is_readable=False without calling OCR."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "blurry.png"
        _make_blurry_png(img_path)

        # Even if OCR model is None or mocked, blurry check happens first.
        with patch.object(ocr_engine, "ocr_model", MagicMock()):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is False
        assert result["ocr_text"] == ""
        assert result["confidence"] == 0.0

    # ── test_clear_image_returns_text ────────────────────────────────────────

    def test_clear_image_returns_text(self, tmp_path: Path) -> None:
        """A sharp image processed by a mocked OCR model must return text."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        # Mock PaddleOCR result: list-of-results → [[line, ...]]
        # Each line is [bounding_box, [text, confidence]]
        fake_ocr_output = [
            [
                [None, ["Applicant Name: Ramesh Kumar", 0.98]],
                [None, ["PAN: ABCDE1234F", 0.95]],
                [None, ["Loan Amount: 5,00,000", 0.92]],
            ]
        ]
        mock_model = MagicMock()
        mock_model.predict.return_value = fake_ocr_output
        mock_model.ocr.return_value = fake_ocr_output

        with patch.object(ocr_engine, "ocr_model", mock_model):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is True
        assert "Ramesh Kumar" in result["ocr_text"]
        assert "ABCDE1234F" in result["ocr_text"]
        assert 0.0 < result["confidence"] <= 1.0

    def test_clear_image_returns_text_from_paddleocr_v3_result(self, tmp_path: Path) -> None:
        """PaddleOCR 3.x dict results must return text and confidence."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        v3_result = [
            {
                "rec_texts": ["Applicant Name: Ramesh Kumar", "PAN: ABCDE1234F"],
                "rec_scores": [0.98, 0.95],
            }
        ]
        mock_model = MagicMock()
        mock_model.predict.return_value = v3_result
        mock_model.ocr.return_value = v3_result

        with patch.object(ocr_engine, "ocr_model", mock_model):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is True
        assert "Ramesh Kumar" in result["ocr_text"]
        assert "ABCDE1234F" in result["ocr_text"]
        assert result["confidence"] == pytest.approx(0.965)

    def test_clear_image_returns_text_from_wrapped_paddleocr_v3_result(self, tmp_path: Path) -> None:
        """PaddleOCR 3.x result JSON may wrap fields under a res key."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        mock_result = MagicMock()
        mock_result.json = {
            "res": {
                "rec_texts": ["Applicant Name: Ramesh Kumar", "PAN: ABCDE1234F"],
                "rec_scores": [0.98, 0.95],
            }
        }
        wrapped_result = [mock_result]
        mock_model = MagicMock()
        mock_model.predict.return_value = wrapped_result
        mock_model.ocr.return_value = wrapped_result

        with patch.object(ocr_engine, "ocr_model", mock_model):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is True
        assert "Ramesh Kumar" in result["ocr_text"]
        assert "ABCDE1234F" in result["ocr_text"]
        assert result["confidence"] == pytest.approx(0.965)

    def test_ocr_exception_returns_error_dict(self, tmp_path: Path) -> None:
        """If the OCR call raises, the result must include an 'error' key."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("model crash")
        mock_model.ocr.side_effect = RuntimeError("model crash")

        with patch.object(ocr_engine, "ocr_model", mock_model):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is False
        assert result["ocr_text"] == ""
        assert "error" in result
        assert "model crash" in result["error"]

    def test_no_model_returns_error_dict(self, tmp_path: Path) -> None:
        """When ocr_model is None, result must contain an 'error' key."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        with patch.object(ocr_engine, "ocr_model", None):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is False
        assert "error" in result

    # ── test_ocr_model_loaded_once ───────────────────────────────────────────

    def test_ocr_model_loaded_once(self) -> None:
        """The module-level ocr_model must be the same object on every import."""
        import importlib

        import services.ocr_engine as engine_a

        # Re-importing from the same process must return the cached module.
        engine_b = importlib.import_module("services.ocr_engine")

        # Both references must point to the exact same module object.
        assert engine_a is engine_b

        # And therefore the same singleton model object.
        assert engine_a.ocr_model is engine_b.ocr_model
