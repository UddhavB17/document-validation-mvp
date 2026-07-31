from __future__ import annotations
import pytest
from pydantic import BaseModel
from typing import Optional

from services.generic_kv_extractor import (
    extract_kv_deterministic,
    extract_kv_from_table,
    build_document_schema,
    merge_extraction_results,
    summarize_extraction_sources,
)

def test_no_pattern_same_block_passing_deterministically() -> None:
    # A same-block match with no value_pattern uses CONFIDENCE_NO_PATTERN_SAME_BLOCK = 0.90.
    # Combined with fuzzy label match (100%), overall confidence is min(1.0, 0.9) = 0.90 >= 0.85 (accepted deterministically).
    layout_blocks = [
        {"type": "text", "text": "Applicant Name: John Doe", "bbox": [10, 10, 200, 30]}
    ]
    field_config = {
        "type": "Aadhaar",
        "fields": [
            {
                "name": "applicant_name",
                "field_type": "form",
                "label_aliases": ["Applicant Name", "Name"],
                "value_pattern": None
            }
        ]
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["applicant_name"]["value"] == "John Doe"
    assert res["applicant_name"]["confidence"] == 0.90
    assert res["applicant_name"]["extraction_source"] == "deterministic"


def test_no_pattern_spatial_routes_to_fallback() -> None:
    # Spatial fallback uses CONFIDENCE_NO_PATTERN_SPATIAL = 0.65.
    # min(1.0, 0.65) = 0.65 < 0.85, so it must route to LLM/unmatched.
    layout_blocks = [
        {"type": "text", "text": "Applicant Name", "bbox": [10, 10, 100, 30]},
        {"type": "text", "text": "John Doe", "bbox": [110, 10, 250, 30]}
    ]
    field_config = {
        "type": "Aadhaar",
        "fields": [
            {
                "name": "applicant_name",
                "field_type": "form",
                "label_aliases": ["Applicant Name", "Name"],
                "value_pattern": None
            }
        ]
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["applicant_name"]["extraction_source"] == "unmatched"
    assert res["applicant_name"]["reason"] == "low_confidence"


def test_corrupted_value_pattern_fails_deterministic() -> None:
    # Value matches label, but the value shape is corrupted. Should map to unmatched with mismatch reason.
    layout_blocks = [
        {"type": "text", "text": "PAN: ABC123XYZ", "bbox": [10, 10, 200, 30]} # ABC123XYZ fails 5-letter 4-digit 1-letter shape
    ]
    field_config = {
        "type": "PAN Card",
        "fields": [
            {
                "name": "pan_number",
                "field_type": "form",
                "label_aliases": ["PAN", "PAN Number"],
                "value_pattern": "\\b[A-Z]{5}[0-9]{4}[A-Z]\\b"
            }
        ]
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["pan_number"]["value"] is None
    assert res["pan_number"]["extraction_source"] == "unmatched"
    assert res["pan_number"]["reason"] == "value_pattern_mismatch"


def test_table_region_extraction_intersection() -> None:
    # Table blocks contain parsed HTML
    table_blocks = [
        {
            "pred_html": "<table>"
                         "<tr><td>Header Row</td><td>Amount</td></tr>"
                         "<tr><td>Requested Loan Amount</td><td>275000.00</td></tr>"
                         "</table>"
        }
    ]
    field_config = {
        "fields": [
            {
                "name": "requested_amount",
                "field_type": "table",
                "label_aliases": ["Requested Loan Amount", "Loan Amount"],
                "header_aliases": ["Amount", "Requested"],
                "value_pattern": "\\b\\d+\\.\\d{2}\\b"
            }
        ]
    }
    res = extract_kv_from_table(table_blocks, field_config)
    assert res["requested_amount"]["value"] == "275000.00"
    assert res["requested_amount"]["extraction_source"] == "deterministic"


def test_table_region_extraction_row_only() -> None:
    table_blocks = [
        {
            "pred_html": "<table>"
                         "<tr><td>Requested IRR</td><td>26.00</td></tr>"
                         "</table>"
        }
    ]
    field_config = {
        "fields": [
            {
                "name": "roi",
                "field_type": "table",
                "label_aliases": ["Requested IRR"],
                "value_pattern": "\\b\\d+\\.\\d{2}\\b"
            }
        ]
    }
    res = extract_kv_from_table(table_blocks, field_config)
    assert res["roi"]["value"] == "26.00"
    assert res["roi"]["extraction_source"] == "deterministic"


def test_llm_fallback_carrying_self_reported_confidence() -> None:
    # 1. Build schema
    field_config = {
        "type": "PAN Card",
        "fields": [
            {"name": "applicant_name", "description": "Name", "label_aliases": ["Name"]}
        ]
    }
    schema = build_document_schema(field_config)
    
    # 2. Mock LLM output
    llm_output = schema(
        applicant_name="John Doe",
        applicant_name_confidence=0.88,
        applicant_name_note="Clear matching text found."
    )
    
    deterministic_res = {
        "applicant_name": {"value": None, "confidence": 0.0, "extraction_source": "unmatched"}
    }
    
    merged = merge_extraction_results(deterministic_res, llm_output)
    assert merged["applicant_name"]["value"] == "John Doe"
    assert merged["applicant_name"]["confidence"] == 0.88
    assert merged["applicant_name"]["extraction_source"] == "llm_fallback"
    assert merged["applicant_name"]["note"] == "Clear matching text found."


def test_not_found_versus_unmatched() -> None:
    field_config = {
        "type": "PAN Card",
        "fields": [
            {"name": "dob", "description": "Date of Birth", "label_aliases": ["DOB"]}
        ]
    }
    schema = build_document_schema(field_config)
    
    # Mock LLM returns null because DOB is genuinely absent
    llm_output = schema(
        dob=None,
        dob_confidence=0.0,
        dob_note="Field DOB is missing from the document."
    )
    
    deterministic_res = {
        "dob": {"value": None, "confidence": 0.0, "extraction_source": "unmatched"}
    }
    
    merged = merge_extraction_results(deterministic_res, llm_output)
    assert merged["dob"]["value"] is None
    # Terminal state should be 'not_found' when LLM fails to find it, reserving 'unmatched' for deterministic stage.
    assert merged["dob"]["extraction_source"] == "not_found"


def test_summarize_extraction_sources_math() -> None:
    results = [
        {
            "document_type": "PAN Card",
            "fields": {
                "pan_number": {"extraction_source": "deterministic"},
                "applicant_name": {"extraction_source": "llm_fallback"},
                "dob": {"extraction_source": "not_found"}
            }
        },
        {
            "document_type": "PAN Card",
            "fields": {
                "pan_number": {"extraction_source": "deterministic"},
                "applicant_name": {"extraction_source": "deterministic"},
                "dob": {"extraction_source": "unmatched"}
            }
        }
    ]
    summary = summarize_extraction_sources(results)
    pan_stats = summary["PAN Card"]
    assert pan_stats["deterministic"] == 50.0   # 3 / 6
    assert pan_stats["llm_fallback"] == 16.67   # 1 / 6
    assert pan_stats["not_found"] == 16.67      # 1 / 6
    assert pan_stats["unmatched"] == 16.67      # 1 / 6


def test_aadhaar_clean_and_fuzzy_extraction() -> None:
    # Aadhaar form field same block matching
    layout_blocks = [
        {"type": "text", "text": "Aadhar No: 1234 5678 9012", "bbox": [10, 10, 200, 30]},
        {"type": "text", "text": "Nam e", "bbox": [10, 40, 100, 60]},
        {"type": "text", "text": "Uddhav B", "bbox": [110, 40, 250, 60]}
    ]
    field_config = {
        "type": "Aadhaar",
        "fields": [
            {
                "name": "aadhaar_number",
                "field_type": "form",
                "label_aliases": ["Aadhaar Number", "Aadhar No"],
                "value_pattern": "\\b\\d{4}\\s?\\d{4}\\s?\\d{4}\\b"
            },
            {
                "name": "applicant_name",
                "field_type": "form",
                "label_aliases": ["Name", "Resident Name"],
                "value_pattern": None
            }
        ]
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["aadhaar_number"]["value"] == "1234 5678 9012"
    assert res["aadhaar_number"]["extraction_source"] == "deterministic"
    # applicant_name has spatial fallback without pattern, so it should be unmatched due to CONFIDENCE_NO_PATTERN_SPATIAL (0.65)
    assert res["applicant_name"]["extraction_source"] == "unmatched"
    assert res["applicant_name"]["reason"] == "low_confidence"


def test_split_value_merging() -> None:
    # Bbox format: [x0, y0, x1, y1] -> height is y1 - y0.
    # Label: "Aadhar No: ", initial block has "2271" with height 20.
    # Gap from 2271 to 5385: x-distance is 15px (which is < 20 * 2.0 = 40px).
    # Center alignment diff is 0 (which is < 20 * 0.3 = 6px).
    layout_blocks = [
        {"type": "text", "text": "Aadhar No:", "bbox": [10, 10, 100, 30]},
        {"type": "text", "text": "2271", "bbox": [110, 10, 150, 30]},
        {"type": "text", "text": "5385", "bbox": [165, 10, 205, 30]},  # gap is 15px
        {"type": "text", "text": "1187", "bbox": [220, 10, 260, 30]},  # gap is 15px
    ]
    field_config = {
        "fields": [
            {
                "name": "aadhaar_number",
                "field_type": "form",
                "label_aliases": ["Aadhar No"],
                "value_pattern": "\\b\\d{4}\\s?\\d{4}\\s?\\d{4}\\b"
            }
        ]
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["aadhaar_number"]["value"] == "2271 5385 1187"
    assert res["aadhaar_number"]["extraction_source"] == "deterministic"
    assert res["aadhaar_number"].get("value_merged") is True


def test_merge_thresholds_scale_with_resolution() -> None:
    # Scale 1: 1x resolution (DPI 1)
    # Block height is 20. Gap is 30. (30 < 20 * 2.0 = 40, so it merges).
    layout_blocks_1x = [
        {"type": "text", "text": "Aadhar No:", "bbox": [10, 10, 100, 30]},
        {"type": "text", "text": "2271", "bbox": [110, 10, 150, 30]},
        {"type": "text", "text": "5385", "bbox": [180, 10, 220, 30]},  # gap is 30px
        {"type": "text", "text": "1187", "bbox": [250, 10, 290, 30]},  # gap is 30px
    ]
    
    # Scale 2: 2x resolution (DPI 2)
    # Block coordinates and dimensions are doubled.
    # Block height is 40. Gap is 60. (60 < 40 * 2.0 = 80, so it merges).
    # If we used a fixed pixel limit of, say, 50px, this would fail to merge!
    # But height-based limit scales to 80px, so it succeeds.
    layout_blocks_2x = [
        {"type": "text", "text": "Aadhar No:", "bbox": [20, 20, 200, 60]},
        {"type": "text", "text": "2271", "bbox": [220, 20, 300, 60]},
        {"type": "text", "text": "5385", "bbox": [360, 20, 440, 60]},  # gap is 60px
        {"type": "text", "text": "1187", "bbox": [500, 20, 580, 60]},  # gap is 60px
    ]
    
    field_config = {
        "fields": [
            {
                "name": "aadhaar_number",
                "field_type": "form",
                "label_aliases": ["Aadhar No"],
                "value_pattern": "\\b\\d{4}\\s?\\d{4}\\s?\\d{4}\\b"
            }
        ]
    }
    
    # Assert 1x scale merges successfully
    res_1x = extract_kv_deterministic(layout_blocks_1x, field_config)
    assert res_1x["aadhaar_number"]["value"] == "2271 5385 1187"
    assert res_1x["aadhaar_number"].get("value_merged") is True
    
    # Assert 2x scale merges successfully
    res_2x = extract_kv_deterministic(layout_blocks_2x, field_config)
    assert res_2x["aadhaar_number"]["value"] == "2271 5385 1187"
    assert res_2x["aadhaar_number"].get("value_merged") is True


def test_negative_no_merge_needed() -> None:
    # If initial value matches the pattern on its own, do not merge adjacent blocks.
    layout_blocks = [
        {"type": "text", "text": "Aadhar No: 1234 5678 9012", "bbox": [10, 10, 300, 30]},
        {"type": "text", "text": "9999", "bbox": [310, 10, 350, 30]},  # adjacent block that should be ignored
    ]
    field_config = {
        "fields": [
            {
                "name": "aadhaar_number",
                "field_type": "form",
                "label_aliases": ["Aadhar No"],
                "value_pattern": "\\b\\d{4}\\s?\\d{4}\\s?\\d{4}\\b"
            }
        ]
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["aadhaar_number"]["value"] == "1234 5678 9012"
    # value_merged should be absent or False
    assert not res["aadhaar_number"].get("value_merged")


def test_table_region_extraction_style1_fallback_to_style2() -> None:
    # A table where row 0 is a title row (merged, doesn't match column headers),
    # but row 1 contains both label and value in inline style.
    table_blocks = [
        {
            "pred_html": "<table>"
                         "<tr><td colspan='2'>APPLICATION DETAILS</td></tr>"
                         "<tr><td>Requested Loan Amount</td><td>275000.00</td></tr>"
                         "</table>"
        }
    ]
    field_config = {
        "fields": [
            {
                "name": "requested_amount",
                "field_type": "table",
                "label_aliases": ["Requested Loan Amount"],
                "header_aliases": ["Amount", "Requested"],
                "value_pattern": "\\b\\d+\\.\\d{2}\\b"
            }
        ]
    }
    res = extract_kv_from_table(table_blocks, field_config)
    # Merged title cell in row 0 prevents column headers from matching, 
    # but it should fall back to Style 2 and successfully match.
    assert res["requested_amount"]["value"] == "275000.00"
    assert res["requested_amount"]["extraction_source"] == "deterministic"


# ── id_number field_hint sanity check tests ───────────────────────────────────

from services.generic_kv_extractor import _passes_id_sanity_check


def test_id_sanity_check_passes_for_plausible_dl_number() -> None:
    # A realistic Driving License number should pass: correct length, mostly alphanumeric.
    assert _passes_id_sanity_check("MH1234567890123") is True   # 15 chars, all alnum
    assert _passes_id_sanity_check("KA0320170123456") is True   # Karnataka format
    assert _passes_id_sanity_check("DL0420110123456") is True   # Delhi format


def test_id_sanity_check_fails_for_too_short() -> None:
    # Values shorter than 5 characters are nonsensical ID numbers.
    assert _passes_id_sanity_check("AB1") is False
    assert _passes_id_sanity_check("") is False


def test_id_sanity_check_fails_for_too_long() -> None:
    # Values longer than 20 characters are unlikely to be a single ID field.
    assert _passes_id_sanity_check("A" * 21) is False


def test_id_sanity_check_fails_for_garbage_ocr() -> None:
    # More than 30% non-alphanumeric characters — typical OCR garbage or a label.
    assert _passes_id_sanity_check("::--??..@@") is False        # all punctuation
    assert _passes_id_sanity_check("DL No.: --??") is False      # label bled into value


def test_id_sanity_check_integration_garbled_value_routes_to_fallback() -> None:
    """End-to-end: garbled OCR value on a field_hint='id_number' field must
    produce extraction_source='unmatched', reason='sanity_check_failed'."""
    layout_blocks = [
        # Label block and garbled value block adjacent to each other
        {"type": "text", "text": "DL No", "bbox": [10, 10, 80, 30]},
        {"type": "text", "text": "::---???", "bbox": [85, 10, 200, 30]},
    ]
    field_config = {
        "type": "Driving License",
        "fields": [
            {
                "name": "dl_number",
                "field_type": "form",
                "label_aliases": ["DL No", "Licence No"],
                "field_hint": "id_number",
            }
        ],
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["dl_number"]["extraction_source"] == "unmatched"
    assert res["dl_number"]["reason"] == "sanity_check_failed"
    assert res["dl_number"]["value"] is None


def test_id_sanity_check_integration_plausible_value_passes() -> None:
    """End-to-end: a plausible DL number on a field_hint='id_number' field
    must succeed deterministically at the usual 0.90 confidence."""
    layout_blocks = [
        {"type": "text", "text": "DL No: MH0120230001234", "bbox": [10, 10, 260, 30]},
    ]
    field_config = {
        "type": "Driving License",
        "fields": [
            {
                "name": "dl_number",
                "field_type": "form",
                "label_aliases": ["DL No"],
                "field_hint": "id_number",
            }
        ],
    }
    res = extract_kv_deterministic(layout_blocks, field_config)
    assert res["dl_number"]["extraction_source"] == "deterministic"
    assert res["dl_number"]["value"] == "MH0120230001234"
