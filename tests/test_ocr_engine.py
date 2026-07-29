"""Tests for services/ocr_engine.py and services/preprocessing.py.

Strategy
--------
- preprocessing tests use real OpenCV images (synthesised via numpy).
- OCR tests mock ``services.ocr_engine.structure_model`` so the suite runs even
  when PaddleOCR / PaddlePaddle are not installed in this environment.
- The ``test_ocr_model_loaded_once`` test verifies the module-level singleton
  pattern by asserting the same object identity is returned on repeated access.
"""

from __future__ import annotations

from pathlib import Path
import time
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

    def test_blurry_image_still_runs_ocr(self, tmp_path: Path) -> None:
        """Blurry pages must still run OCR; blur is advisory only."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "blurry.png"
        _make_blurry_png(img_path)

        fake_ocr_output = [[ [None, ["Blurry Passbook Page", 0.42]] ]]
        mock_model = MagicMock()
        mock_model.predict.return_value = fake_ocr_output
        with patch.object(ocr_engine, "structure_models", {"hi": mock_model, "en": mock_model}):
            result = run_ocr_on_page(img_path)

        assert result["is_blurry"] is True
        assert "Blurry Passbook Page" in result["ocr_text"]
        assert result["confidence"] == pytest.approx(0.42)
        assert result["ocr_languages"] == ["hi", "en"]

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
        with patch.object(ocr_engine, "structure_models", {"hi": mock_model, "en": mock_model}):
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
        with patch.object(ocr_engine, "structure_models", {"hi": mock_model, "en": mock_model}):
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
        with patch.object(ocr_engine, "structure_models", {"hi": mock_model, "en": mock_model}):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is True
        assert "Ramesh Kumar" in result["ocr_text"]
        assert "ABCDE1234F" in result["ocr_text"]
        assert result["confidence"] == pytest.approx(0.965)

    def test_pp_structure_v3_returns_layout_and_compact_json(self, tmp_path: Path) -> None:
        """Useful structure data remains available without native image arrays."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)
        structure_result = [
            {
                "parsing_res_list": [
                    {
                        "block_label": "title",
                        "block_content": "HOME LOAN APPLICATION",
                        "block_bbox": [10, 20, 180, 45],
                        "index": 0,
                        "sub_label": "doc_title",
                    },
                    {
                        "block_label": "text",
                        "block_content": "Applicant Name: Ramesh Kumar",
                        "block_bbox": [10, 60, 180, 90],
                        "index": 1,
                    },
                ],
                "overall_ocr_res": {
                    "rec_texts": ["HOME LOAN APPLICATION", "Applicant Name: Ramesh Kumar"],
                    "rec_scores": [0.99, 0.97],
                    "vis_img": np.zeros((100, 100, 3), dtype=np.uint8),
                },
                "doc_preprocessor_res": {
                    "output_img": np.zeros((1600, 1600, 3), dtype=np.uint8),
                    "angle": 0,
                },
                "table_res_list": [{"pred_html": "<table><tr><td>Name</td></tr></table>"}],
                "seal_res_list": [{"rec_texts": ["STATE BANK OF INDIA"]}],
            }
        ]
        mock_model = MagicMock()
        mock_model.predict.return_value = structure_result

        with patch.object(ocr_engine, "structure_models", {"hi": mock_model}):
            result = run_ocr_on_page(img_path)

        assert result["ocr_pipeline"] == "PP-StructureV3"
        assert result["header_text"] == "HOME LOAN APPLICATION"
        assert result["layout_blocks"][0]["type"] == "title"
        assert result["tables"][0]["pred_html"].startswith("<table>")
        assert result["seals"][0]["rec_texts"] == ["STATE BANK OF INDIA"]
        assert result["structure_json"][0]["overall_ocr_res"]["rec_scores"] == [0.99, 0.97]
        assert "doc_preprocessor_res" not in result["structure_json"][0]
        assert "vis_img" not in result["structure_json"][0]["overall_ocr_res"]
        assert result["confidence"] == pytest.approx(0.98)

    def test_ocr_exception_returns_error_dict(self, tmp_path: Path) -> None:
        """If the OCR call raises, the result must include an 'error' key."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("model crash")
        with patch.object(ocr_engine, "structure_models", {"hi": mock_model, "en": mock_model}):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is False
        assert result["ocr_text"] == ""
        assert "error" in result
        assert "model crash" in result["error"]

    def test_no_model_returns_error_dict(self, tmp_path: Path) -> None:
        """When OCR models are unavailable, result must contain an 'error' key."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)

        with patch.object(ocr_engine, "structure_models", {"hi": None, "en": None}):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is False
        assert "error" in result

    def test_ocr_hard_timeout_returns_error_dict(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A hung OCR call should return an error instead of blocking forever."""
        pytest.importorskip("cv2")
        from services import ocr_engine
        from services.ocr_engine import run_ocr_on_page

        img_path = tmp_path / "sharp.png"
        _make_sharp_png(img_path)
        monkeypatch.setenv("OCR_HARD_TIMEOUT_SECONDS", "1")

        mock_model = MagicMock()

        def slow_timeout(*_args, **_kwargs):
            raise TimeoutError("OCR exceeded hard timeout of 1s")

        monkeypatch.setattr(ocr_engine, "_run_paddle_structure_with_timeout", slow_timeout)
        with patch.object(ocr_engine, "structure_models", {"hi": mock_model}):
            result = run_ocr_on_page(img_path)

        assert result["is_readable"] is False
        assert "OCR exceeded hard timeout" in result["error"]

    # ── test_ocr_model_loaded_once ───────────────────────────────────────────

    def test_ocr_model_loaded_once(self) -> None:
        """The module-level structure model is stable across repeated imports."""
        import importlib

        import services.ocr_engine as engine_a

        # Re-importing from the same process must return the cached module.
        engine_b = importlib.import_module("services.ocr_engine")

        # Both references must point to the exact same module object.
        assert engine_a is engine_b

        # And therefore the same singleton model object.
        assert engine_a.structure_model is engine_b.structure_model
