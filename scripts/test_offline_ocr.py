"""Run one page through the isolated local PaddleOCR smoke-test path."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OCR one image or PDF page locally; never calls the configured OCR API."
    )
    parser.add_argument("input", type=Path, help="Image or PDF to inspect")
    parser.add_argument(
        "--lang",
        default="hi",
        help="Paddle language/name, e.g. bgc, bho, mai, mah, bh, hi, ur, ta, te, en",
    )
    parser.add_argument("--page", type=int, default=1, help="One-based PDF page number")
    parser.add_argument("--dpi", type=int, default=200, help="PDF render DPI (default: 200)")
    return parser.parse_args()


def _render_pdf_page(source: Path, page_number: int, dpi: int, output_dir: Path) -> Path:
    import fitz

    document = fitz.open(source)
    try:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError(f"Page must be between 1 and {document.page_count}.")
        page = document.load_page(page_number - 1)
        scale = max(dpi, 72) / 72
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        output = output_dir / f"page-{page_number}.png"
        pixmap.save(output)
        return output
    finally:
        document.close()


def main() -> int:
    args = _arguments()
    source = args.input.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Input file does not exist: {source}")

    # These values isolate local OCR from the application's database-backed
    # production provider selection.
    os.environ["DMEF_LOCAL_OCR_TEST_MODE"] = "true"
    os.environ["OCR_PROVIDER"] = "local"
    os.environ["PADDLE_OCR_LANG"] = args.lang

    from services.offline_ocr_languages import normalize_paddle_language

    with tempfile.TemporaryDirectory(prefix="dmef-offline-ocr-") as directory:
        image = source
        if source.suffix.casefold() == ".pdf":
            image = _render_pdf_page(source, args.page, args.dpi, Path(directory))
        try:
            from services.ocr_router import run_fast_ocr_on_page

            result = run_fast_ocr_on_page(image)
        except ModuleNotFoundError as exc:
            if exc.name in {"paddle", "paddleocr", "paddlex"}:
                raise SystemExit(
                    "Local OCR dependencies are missing. Activate a Python 3.11 environment and run "
                    "`pip install -r requirements-ocr-local.txt`."
                ) from exc
            raise

    from services.language_detection import analyze_text_languages

    payload = {
        "input": str(source),
        "page": args.page if source.suffix.casefold() == ".pdf" else None,
        "ocr_provider": "local_test_only",
        "requested_paddle_language": normalize_paddle_language(args.lang),
        "confidence": result.confidence,
        "text": result.text,
        "script_profile": analyze_text_languages(result.text),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
