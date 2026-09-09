"""Gemini model bake-off: run the pipeline per model over eval fixtures.

Usage:
    python scripts/eval_gemini_models.py \\
        --models gemini-2.5-flash,gemini-2.5-pro \\
        --fixtures tests/fixtures/eval \\
        --out outputs/gemini_eval_<timestamp>.csv

For each model x fixture the script runs the pipeline in-process with
``LLM_PROVIDER=gemini`` and ``GEMINI_MODEL=<model>``, then scores the run
against ``gold.json`` (contracts section 11 finding codes plus expected
extracted values). Fixture PDFs are generated deterministically from the
``pages`` text in ``gold.json`` so no binaries live in the repo.

How to add a case: append an entry to ``tests/fixtures/eval/gold.json``
(see its ``_how_to_add_a_case`` key) and re-run this script.

Without Gemini credentials the script prints the evaluation plan
(models x fixtures matrix) and exits 0 (skipif-friendly for CI).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import tempfile
import time
from pathlib import Path

# Env must be fixed before any database/service import reads it.
os.environ.setdefault("LLM_PROVIDER", "gemini")

# Rule-id families -> contracts section 11 finding codes. This is an
# approximation for scoring; ws-f-accuracy-ops-api owns the canonical mapping.
_RULE_FAMILY_TO_CODE = (
    (("APPLICANT_NAME_MISMATCH", "TRUSTED_", "NAME_MISMATCH", "APPLICATION_NAME_MISMATCH",
      "CROSS_DOCUMENT_APPLICANT_NAME"), "NAME_MISMATCH"),
    (("PAN_NUMBER_MISMATCH", "AADHAAR_NUMBER_MISMATCH", "TRUSTED_PAN", "TRUSTED_AADHAAR",
      "DATE_OF_BIRTH_MISMATCH", "INVALID_PAN_FORMAT"), "ID_MISMATCH"),
    (("ADDRESS_MISMATCH", "AADHAAR_ADDRESS_MISMATCH", "CROSS_DOCUMENT_ADDRESS"), "ADDRESS_MISMATCH"),
    (("MISSING_DOC_S",), "MISSING_DOCUMENT"),
    (("PERIOD_", "DATE_CHECK_S"), "BANK_STATEMENT_OLD"),
    (("UNREADABLE_PAGE", "DOCUMENT_NOT_READABLE"), "PAGE_UNREADABLE"),
    (("LOW_OCR_CONFIDENCE", "LOW_CONFIDENCE_PAGE", "OCR_BUDGET_PARTIAL_SCAN"), "OCR_FAILED"),
    (("NOT_FOUND", "EXTRACTION_UNRELIABLE", "FIELD_VALUE_MISSING_S"), "DATA_MISSING"),
    (("PAGE_PROCESSING_ERROR",), "PROCESSING_ERROR"),
)


def rule_to_code(rule_id: str) -> str | None:
    needle = str(rule_id or "").upper()
    for family, code in _RULE_FAMILY_TO_CODE:
        if any(token in needle for token in family):
            return code
    return None


def has_credentials() -> bool:
    if os.getenv("GEMINI_API_KEY", "").strip():
        return True
    return bool(os.getenv("GOOGLE_CLOUD_PROJECT", "").strip())


def load_gold(fixtures_dir: Path) -> list[dict]:
    with open(fixtures_dir / "gold.json", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("cases", []))


def ensure_fixture_pdf(case: dict, fixtures_dir: Path) -> Path:
    """Render the case's text pages into a digital PDF (deterministic)."""
    import fitz

    pdf_path = fixtures_dir / case["file"]
    if pdf_path.exists():
        return pdf_path
    document = fitz.open()
    for page_text in case.get("pages", ["empty page"]):
        page = document.new_page()
        page.insert_text((72, 72), str(page_text), fontsize=11)
    document.save(pdf_path)
    document.close()
    return pdf_path


def run_case(model: str, case: dict, fixtures_dir: Path, work_root: Path) -> dict:
    """Run the pipeline in-process for one model x fixture and score it."""
    os.environ["LLM_PROVIDER"] = "gemini"
    os.environ["GEMINI_MODEL"] = model

    from database.db import get_connection, init_db
    from services.pipeline.orchestrator import run_pipeline

    init_db()
    pdf_path = ensure_fixture_pdf(case, fixtures_dir)
    started = time.monotonic()
    notes: list[str] = []
    application_id: int | None = None
    try:
        with get_connection() as connection:
            row = connection.execute(
                "INSERT INTO applications (loan_id, applicant_name, status) "
                "VALUES (?, ?, ?) RETURNING id",
                (case.get("loan_id", case["file"]), case.get("applicant_name", ""), "uploaded"),
            ).fetchone()
            application_id = int(row["id"])
        run_pipeline(pdf_path, application_id, output_dir=work_root / "processed",
                     generate_llm_summary=True)
    except Exception as exc:  # noqa: BLE001 - record the failure in the CSV row
        notes.append(f"pipeline error: {exc}")
    seconds = time.monotonic() - started

    expected_codes = set(case.get("expected_codes", []))
    found_codes: set[str] = set()
    extracted: dict[str, str] = {}
    tokens_in = tokens_out = calls = 0
    usd = 0.0
    try:
        with get_connection() as connection:
            for row in connection.execute(
                "SELECT rule_id FROM validation_results WHERE application_id = ?",
                (application_id,),
            ).fetchall():
                code = rule_to_code(row["rule_id"])
                if code:
                    found_codes.add(code)
            ground = connection.execute(
                "SELECT applicant_name, pan_number, address FROM ground_truth "
                "WHERE application_id = ? ORDER BY id DESC LIMIT 1",
                (application_id,),
            ).fetchone()
            if ground:
                extracted = {key: str(ground[key] or "") for key in ground.keys()}
            stats = connection.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(tokens_in), 0) AS t_in, "
                "COALESCE(SUM(tokens_out), 0) AS t_out, "
                "COALESCE(SUM(est_cost_usd), 0) AS usd "
                "FROM llm_calls WHERE application_id = ?",
                (application_id,),
            ).fetchone()
            calls, tokens_in, tokens_out, usd = (
                int(stats["calls"]), int(stats["t_in"]), int(stats["t_out"]), float(stats["usd"]),
            )
    except Exception as exc:  # noqa: BLE001 - scoring must not crash the bake-off
        notes.append(f"scoring error: {exc}")

    if expected_codes:
        accuracy = round(len(expected_codes & found_codes) / len(expected_codes), 3)
    else:
        accuracy = 1.0 if not found_codes else 0.0
    false_positives = sorted(found_codes - expected_codes)

    expected_values = case.get("expected_values", {})
    mismatches = [
        key for key, want in expected_values.items()
        if want and want.strip().lower() not in extracted.get(key, "").strip().lower()
    ]
    if mismatches:
        notes.append(f"value mismatch: {','.join(mismatches)}")

    return {
        "model": model,
        "file": case["file"],
        "accuracy": accuracy,
        "false_positives": len(false_positives),
        "seconds": round(seconds, 1),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "usd": round(usd, 6),
        "calls": calls,
        "notes": "; ".join(notes + (["codes=" + ",".join(sorted(found_codes))] if found_codes else [])),
    }


def print_plan(models: list[str], cases: list[dict], reason: str) -> None:
    print(f"Skipping live bake-off ({reason}). Evaluation plan:")
    for model in models:
        for case in cases:
            print(f"  - model={model} file={case['file']} "
                  f"expected_codes={','.join(case.get('expected_codes', [])) or '(clean)'}")
    print("Set GEMINI_API_KEY (or GOOGLE_CLOUD_PROJECT for ADC) to run the live bake-off.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="comma-separated Gemini model ids")
    parser.add_argument("--fixtures", required=True, help="dir containing gold.json")
    parser.add_argument("--out", required=True, help="output CSV path")
    args = parser.parse_args()

    models = [item.strip() for item in args.models.split(",") if item.strip()]
    fixtures_dir = Path(args.fixtures)
    cases = load_gold(fixtures_dir)

    if os.getenv("LLM_PROVIDER", "gemini") == "none" or not has_credentials():
        reason = "LLM_PROVIDER=none" if os.getenv("LLM_PROVIDER") == "none" else "no Gemini credentials"
        print_plan(models, cases, reason)
        return 0

    tmp_root = Path(tempfile.mkdtemp(prefix="gemini-eval-"))
    os.environ["DATABASE_PATH"] = str(tmp_root / "eval.db")
    os.environ["DMEF_JOB_WORK_DIR"] = str(tmp_root / "jobs")

    rows = [run_case(model, case, fixtures_dir, tmp_root) for model in models for case in cases]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["model", "file", "accuracy", "false_positives", "seconds",
               "tokens_in", "tokens_out", "usd", "calls", "notes"]
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")

    print("\nPer-model summary:")
    print(f"{'model':<24}{'cases':>7}{'avg_acc':>9}{'fp_total':>10}{'seconds':>9}{'tokens':>9}{'usd':>10}{'calls':>7}")
    for model in models:
        subset = [row for row in rows if row["model"] == model]
        avg_acc = sum(row["accuracy"] for row in subset) / len(subset) if subset else 0.0
        print(f"{model:<24}{len(subset):>7}{avg_acc:>9.3f}"
              f"{sum(r['false_positives'] for r in subset):>10}"
              f"{sum(r['seconds'] for r in subset):>9.1f}"
              f"{sum(r['tokens_in'] + r['tokens_out'] for r in subset):>9}"
              f"{sum(r['usd'] for r in subset):>10.6f}"
              f"{sum(r['calls'] for r in subset):>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
