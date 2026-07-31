"""Validation harness for generic_kv_extractor using cached OCR text from dmef.db.

Instead of re-running PaddleOCR (which stalls on model init in CPU-only
Windows environments), this script reads the already-stored ocr_text from
each page row and converts it into synthetic bounding boxes — one per line —
so the deterministic extractor can run instantly without any model loading.

This gives us a real-data extraction result (same OCR text the pipeline saw)
without the ~10 minute model warm-up cost.
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.document_classifier import load_document_type_registry
from services.generic_kv_extractor import (
    extract_kv_deterministic,
    extract_kv_from_table,
)

DATABASE_PATH = PROJECT_ROOT / "data" / "dmef.db"
REPORT_PATH = PROJECT_ROOT / "data" / "reports" / "kv_validation_output.txt"


def text_to_fake_blocks(text: str) -> list[dict]:
    """Convert flat OCR text to synthetic per-line bounding boxes for the extractor."""
    blocks = []
    y = 10
    for line in text.splitlines():
        line = line.strip()
        if line:
            blocks.append({
                "type": "text",
                "text": line,
                "bbox": [10, y, 800, y + 20],
            })
            y += 25
    return blocks


def main() -> None:
    lines = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    emit("=" * 70)
    emit("DMEF KV EXTRACTION VALIDATION HARNESS  (cached OCR text mode)")
    emit("=" * 70)

    # Load registry
    registry = load_document_type_registry()
    configs = {c["type"]: c for c in registry.get("document_types", []) if c.get("fields")}
    emit(f"Loaded {len(configs)} document types with field configurations.")

    # Pull pages from DB that have stored OCR text
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT application_id, page_number, document_type, ocr_text, structured_content "
        "FROM pages WHERE ocr_text IS NOT NULL AND ocr_text != ''"
    ).fetchall()
    conn.close()

    emit(f"Found {len(rows)} pages with stored OCR text in dmef.db.\n")

    # Group by document_type
    by_type: dict[str, list] = defaultdict(list)
    for row in rows:
        dtype = row["document_type"]
        if dtype in configs:
            by_type[dtype].append(row)

    configured_types_found = sorted(by_type.keys())
    emit(f"Document types with config AND stored OCR text ({len(configured_types_found)}): "
         f"{', '.join(configured_types_found)}\n")

    # field_stats: { doc_type: { field_name: {total, det, llm, unmatched, vpm, sanity} } }
    field_stats: dict[str, dict] = {}

    for dtype in configured_types_found:
        doc_config = configs[dtype]
        pages = by_type[dtype][:5]   # cap at 5 per type

        has_table_fields = any(f.get("field_type") == "table" for f in doc_config.get("fields", []))
        emit(f"Processing {dtype}  ({len(pages)} pages sampled)...")

        field_stats.setdefault(dtype, {})

        for row in pages:
            ocr_text: str = row["ocr_text"] or ""
            
            raw_sc = row["structured_content"]
            sc_dict = json.loads(raw_sc) if raw_sc and raw_sc != "null" else {}
            
            if isinstance(sc_dict, dict) and sc_dict.get("layout_regions"):
                layout_blocks = sc_dict["layout_regions"]
            else:
                layout_blocks = text_to_fake_blocks(ocr_text)

            # Form extraction
            form_res = extract_kv_deterministic(layout_blocks, doc_config)

            # Table extraction (uses structured_content if present)
            table_res: dict = {}
            if has_table_fields:
                table_blocks = sc_dict.get("tables", []) if isinstance(sc_dict, dict) else (sc_dict if isinstance(sc_dict, list) else [])
                if isinstance(table_blocks, list) and table_blocks:
                    table_res = extract_kv_from_table(table_blocks, doc_config)

            det_res = {**form_res, **table_res}

            for field, meta in det_res.items():
                if not isinstance(meta, dict):
                    continue  # skip any non-meta values
                f_stats = field_stats[dtype].setdefault(field, {
                    "total": 0, "deterministic": 0, "llm_fallback": 0,
                    "unmatched": 0, "value_pattern_mismatch": 0, "sanity_check_failed": 0
                })
                f_stats["total"] += 1
                src = meta.get("extraction_source", "unmatched")
                if src in f_stats:
                    f_stats[src] += 1
                else:
                    f_stats["unmatched"] += 1
                reason = meta.get("reason", "")
                if reason == "value_pattern_mismatch":
                    f_stats["value_pattern_mismatch"] += 1
                elif reason == "sanity_check_failed":
                    f_stats["sanity_check_failed"] += 1

    # Report
    emit("")
    emit("=" * 70)
    emit("PER-FIELD BREAKDOWN")
    emit("=" * 70)

    global_det = global_llm = global_unmatched = global_total = 0

    for dtype, fields in field_stats.items():
        doc_total = sum(f["total"] for f in fields.values())
        doc_det = sum(f["deterministic"] for f in fields.values())
        doc_unmatched = sum(f["unmatched"] for f in fields.values())
        doc_fail_pct = (doc_unmatched / doc_total * 100) if doc_total else 0

        global_total += doc_total
        global_det += doc_det
        global_unmatched += doc_unmatched
        global_llm += sum(f.get("llm_fallback", 0) for f in fields.values())

        flag = "  [FLAG: >50% UNMATCHED]" if doc_fail_pct > 50 else ""
        n_sampled = min(5, len(by_type.get(dtype, [])))
        emit(f"\n{dtype}{flag}  (pages sampled: {n_sampled})")

        for fname, stats in sorted(fields.items()):
            t = stats["total"]
            fail_pct = (stats["unmatched"] / t * 100) if t else 0
            f_flag = "  [FLAG: >50% UNMATCHED]" if fail_pct > 50 else ""

            regex_flag = ""
            if stats["unmatched"] > 0 and (stats["value_pattern_mismatch"] / stats["unmatched"]) > 0.5:
                regex_flag = "  [FLAG: CONSISTENT REGEX MISMATCH]"

            sanity_flag = ""
            if stats.get("sanity_check_failed", 0) > 0:
                sanity_flag = f"  [sanity_check_failed={stats['sanity_check_failed']}]"

            emit(
                f"  {fname:<28} Det:{stats['deterministic']:<3} LLM:{stats.get('llm_fallback', 0):<3} "
                f"Unmatched:{stats['unmatched']:<3} (fail {fail_pct:.0f}%)"
                f"{f_flag}{regex_flag}{sanity_flag}"
            )

    emit("")
    emit("=" * 70)
    emit("AGGREGATE TOTALS")
    emit("=" * 70)
    emit(f"Total field evaluations : {global_total}")
    if global_total:
        emit(f"Deterministic           : {global_det}  ({global_det/global_total*100:.1f}%)")
        emit(f"LLM Fallback            : {global_llm}  ({global_llm/global_total*100:.1f}%)")
        emit(f"Unmatched               : {global_unmatched}  ({global_unmatched/global_total*100:.1f}%)")

    # Write report file
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    emit(f"\nReport written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
