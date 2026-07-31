from __future__ import annotations
import re
import os
from typing import Any, Literal, Type, Optional
from pydantic import BaseModel, Field, create_model
from html.parser import HTMLParser

try:
    from rapidfuzz import fuzz
except ImportError:
    fuzz = None

# Core configuration thresholds and constants
MIN_ACCEPTABLE_CONFIDENCE = 0.85
CONFIDENCE_NO_PATTERN_SAME_BLOCK = 0.90
CONFIDENCE_NO_PATTERN_SPATIAL = 0.65
DEFAULT_LLM_CONFIDENCE = 0.90

# Scale-relative, resolution-invariant multipliers relative to block height
MERGE_HORIZONTAL_GAP_HEIGHT_MULTIPLIER = 2.0
MERGE_VERTICAL_ALIGNMENT_HEIGHT_MULTIPLIER = 0.3


class TableHTMLParser(HTMLParser):
    """Lite HTML table parser converting PP-StructureV3 output to 2D string grid."""
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("td", "th"):
            self.in_cell = True
            self.current_cell = []
        elif tag == "tr":
            self.current_row = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th"):
            self.in_cell = False
            self.current_row.append("".join(self.current_cell).strip())
        elif tag == "tr":
            self.rows.append(self.current_row)

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.current_cell.append(data)


def parse_html_table(html_str: str) -> list[list[str]]:
    parser = TableHTMLParser()
    parser.feed(html_str)
    return parser.rows


def get_median_block_height(all_blocks: list) -> float:
    """Calculate the median height of all valid blocks on the page as a fallback basis."""
    heights = []
    for b in all_blocks:
        bbox = b.get("bbox")
        if bbox and len(bbox) == 4:
            h = bbox[3] - bbox[1]
            if h > 0:
                heights.append(h)
    if not heights:
        return 20.0  # Safe default fallback height
    heights.sort()
    n = len(heights)
    if n % 2 == 1:
        return float(heights[n // 2])
    return (heights[n // 2 - 1] + heights[n // 2]) / 2.0


def get_right_merge_candidates(current_block: dict, all_blocks: list, all_labels_set: set) -> list[dict]:
    """Finds candidate blocks to the right of current_block on the same line using relative height thresholds."""
    cx0, cy0, cx1, cy1 = current_block["bbox"]
    current_height = cy1 - cy0
    if current_height <= 0:
        current_height = get_median_block_height(all_blocks)
        
    gap_threshold = current_height * MERGE_HORIZONTAL_GAP_HEIGHT_MULTIPLIER
    v_align_threshold = current_height * MERGE_VERTICAL_ALIGNMENT_HEIGHT_MULTIPLIER
    
    candidates = []
    for block in all_blocks:
        if block == current_block:
            continue
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        bx0, by0, bx1, by1 = bbox
        
        # Check if block is to the right
        if bx0 < cx1 - 10:
            continue
            
        # Check horizontal distance
        gap = bx0 - cx1
        if gap > gap_threshold:
            continue
            
        # Check vertical alignment (center difference relative to height)
        c_center = (cy0 + cy1) / 2.0
        b_center = (by0 + by1) / 2.0
        v_center_diff = abs(c_center - b_center)
        if v_center_diff > v_align_threshold:
            continue
            
        # Check if block text contains any label alias
        txt = block.get("text", "").strip()
        if not txt:
            continue
            
        is_label = False
        for lbl in all_labels_set:
            if fuzz:
                score = max(fuzz.token_sort_ratio(txt.lower(), lbl.lower()), fuzz.ratio(txt.lower(), lbl.lower()))
            else:
                score = 100 if txt.lower() == lbl.lower() else 0
            if score >= 80:
                is_label = True
                break
        if not is_label:
            candidates.append((bx0, block))
            
    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates]


def attempt_merge_value(initial_val: str, start_block: dict, all_blocks: list, pattern_re, all_labels_set: set) -> tuple[str | None, bool]:
    """Iteratively merges adjacent blocks to the right of start_block to see if they satisfy pattern_re."""
    if not pattern_re:
        return None, False
        
    current_val = initial_val
    current_block = start_block
    merged_any = False
    
    for _ in range(5):
        candidates = get_right_merge_candidates(current_block, all_blocks, all_labels_set)
        if not candidates:
            break
        # Take the closest candidate to the right
        next_block = candidates[0]
        next_text = next_block.get("text", "").strip()
        current_val = f"{current_val} {next_text}".strip()
        current_block = next_block
        merged_any = True
        
        # Test if it now matches
        match = pattern_re.search(current_val)
        if match:
            matched_text = match.group(1) if match.groups() else match.group(0)
            return matched_text, True
            
    return None, False


def find_adjacent_blocks(label_block: dict, all_blocks: list) -> list[dict]:
    """Spatially overlaps label_block box with nearby candidate value blocks."""
    if not label_block.get("bbox") or len(label_block["bbox"]) != 4:
        return []
    lx0, ly0, lx1, ly1 = label_block["bbox"]
    right_candidates = []
    below_candidates = []
    
    for block in all_blocks:
        if block == label_block:
            continue
        if not block.get("bbox") or len(block["bbox"]) != 4:
            continue
        cx0, cy0, cx1, cy1 = block["bbox"]
        
        v_overlap = min(ly1, cy1) - max(ly0, cy0)
        h_overlap = min(lx1, cx1) - max(lx0, cx0)
        
        # Check vertical overlap (same line / right block)
        if v_overlap > 0 and (v_overlap / max(1, ly1 - ly0) > 0.3 or v_overlap / max(1, cy1 - cy0) > 0.3):
            if cx0 >= lx1 - 15:
                dist = cx0 - lx1
                right_candidates.append((dist, block))
                
        # Check horizontal overlap (aligned below)
        if h_overlap > 0 and (h_overlap / max(1, lx1 - lx0) > 0.3 or h_overlap / max(1, cx1 - cx0) > 0.3):
            if cy0 >= ly1 - 15:
                dist = cy0 - ly1
                below_candidates.append((dist, block))
                
    right_candidates.sort(key=lambda x: x[0])
    below_candidates.sort(key=lambda x: x[0])
    
    adjacent = [item[1] for item in right_candidates if item[0] < 300]
    adjacent.extend([item[1] for item in below_candidates if item[0] < 150])
    return adjacent


def extract_from_single_block(block_text: str, alias: str) -> str | None:
    """Extracts inline values from a single block text based on delimiter/prefixes."""
    for sep in (":", "="):
        if sep in block_text:
            left, right = block_text.split(sep, 1)
            left_clean = left.strip()
            if fuzz:
                score = max(fuzz.token_sort_ratio(left_clean.lower(), alias.lower()), fuzz.ratio(left_clean.lower(), alias.lower()))
            else:
                score = 100 if left_clean.lower() == alias.lower() else 0
            if score >= 80:
                return right.strip()
                
    words_in_text = block_text.split()
    words_in_alias = alias.split()
    num_words = len(words_in_alias)
    if len(words_in_text) >= num_words:
        prefix_candidate = " ".join(words_in_text[:num_words])
        if fuzz:
            score = max(fuzz.token_sort_ratio(prefix_candidate.lower(), alias.lower()), fuzz.ratio(prefix_candidate.lower(), alias.lower()))
        else:
            score = 100 if prefix_candidate.lower() == alias.lower() else 0
        if score >= 80:
            rest = " ".join(words_in_text[num_words:]).strip()
            rest = re.sub(r"^[:\-\s=]+", "", rest)
            return rest
    return None


def _passes_id_sanity_check(value: str) -> bool:
    """Lightweight sanity check for id_number fields lacking a value_pattern.

    Guards against garbled OCR blocks (e.g. all-punctuation, absurdly short/long)
    being accepted as deterministic matches purely on label-proximity confidence.

    Rules:
      - Length must be 5–20 characters (inclusive).
      - At most 30% of characters may be non-alphanumeric (punctuation/whitespace).
    """
    value = value.strip()
    if not value:
        return False
    if not (5 <= len(value) <= 20):
        return False
    non_alnum = sum(1 for c in value if not c.isalnum())
    if non_alnum / len(value) > 0.30:
        return False
    return True


def extract_kv_deterministic(layout_blocks: list[dict], field_config: dict) -> dict[str, dict]:

    """Performs deterministic spatial extraction on form-style fields."""
    all_labels = {
        alias.lower()
        for f in field_config.get("fields", [])
        for alias in (f.get("label_aliases") or [])
    }
    results = {}
    for field in field_config.get("fields", []):
        if field.get("field_type", "form") != "form":
            continue
            
        name = field["name"]
        label_aliases = field.get("label_aliases") or []
        value_pattern = field.get("value_pattern")
        pattern_re = re.compile(value_pattern) if value_pattern else None
        field_hint = field.get("field_hint")
        
        matched_val = None
        best_overall_conf = 0.0
        extraction_reason = "not_found"
        is_merged = False
        
        for block in layout_blocks:
            block_text = block.get("text", "").strip()
            if not block_text:
                continue
                
            for alias in label_aliases:
                # Scenario 1: Delimiter/prefix inline match
                val_cand = extract_from_single_block(block_text, alias)
                if val_cand is not None and val_cand.strip() != "":
                    val_cand_clean = val_cand.strip()
                    has_delim = any(sep in block_text for sep in (":", "="))
                    if not has_delim and len(val_cand_clean) <= 2:
                        # Probably label noise (e.g. "Nam e"), ignore inline match
                        pass
                    else:
                        if value_pattern:
                            match = pattern_re.search(val_cand_clean)
                            if match:
                                matched_val = match.group(1) if match.groups() else match.group(0)
                                best_overall_conf = 1.0
                                extraction_reason = "pattern_match"
                                break
                            else:
                                # Attempt merging adjacent blocks!
                                merged_text, success = attempt_merge_value(val_cand_clean, block, layout_blocks, pattern_re, all_labels)
                                if success:
                                    matched_val = merged_text
                                    best_overall_conf = 1.0
                                    extraction_reason = "pattern_match"
                                    is_merged = True
                                    break
                                else:
                                    matched_val = None
                                    best_overall_conf = 0.0
                                    extraction_reason = "value_pattern_mismatch"
                                    break
                        else:
                            matched_val = val_cand_clean
                            best_overall_conf = CONFIDENCE_NO_PATTERN_SAME_BLOCK
                            extraction_reason = "no_pattern_same_block"
                            break
                        
                # Scenario 2: Spatial adjacent block search
                if fuzz:
                    label_score = max(fuzz.token_sort_ratio(block_text.lower(), alias.lower()), fuzz.ratio(block_text.lower(), alias.lower()))
                else:
                    label_score = 100 if block_text.lower() == alias.lower() else 0
                    
                if label_score >= 80:
                    label_conf = label_score / 100.0
                    adj_blocks = find_adjacent_blocks(block, layout_blocks)
                    found_adj = False
                    for adj in adj_blocks:
                        adj_text = adj.get("text", "").strip()
                        if not adj_text:
                            continue
                        if value_pattern:
                            match = pattern_re.search(adj_text)
                            if match:
                                matched_val = match.group(1) if match.groups() else match.group(0)
                                best_overall_conf = min(label_conf, 1.0)
                                extraction_reason = "pattern_match"
                                found_adj = True
                                break
                            else:
                                # Attempt merging adjacent blocks starting from adj!
                                merged_text, success = attempt_merge_value(adj_text, adj, layout_blocks, pattern_re, all_labels)
                                if success:
                                    matched_val = merged_text
                                    best_overall_conf = min(label_conf, 1.0)
                                    extraction_reason = "pattern_match"
                                    is_merged = True
                                    found_adj = True
                                    break
                                else:
                                    matched_val = None
                                    best_overall_conf = 0.0
                                    extraction_reason = "value_pattern_mismatch"
                                    break
                        else:
                            # No value_pattern — accept adjacent text directly.
                            # For id_number fields, first run the lightweight sanity check.
                            if field_hint == "id_number" and not _passes_id_sanity_check(adj_text):
                                matched_val = None
                                best_overall_conf = 0.0
                                extraction_reason = "sanity_check_failed"
                            else:
                                matched_val = adj_text
                                best_overall_conf = min(label_conf, CONFIDENCE_NO_PATTERN_SPATIAL)
                                extraction_reason = "no_pattern_spatial"
                                found_adj = True
                            break
                    if found_adj:
                        break
                    
                    if value_pattern:
                        matched_val = None
                        best_overall_conf = 0.0
                        extraction_reason = "value_pattern_mismatch"
                        
            if extraction_reason in ("pattern_match", "no_pattern_same_block", "no_pattern_spatial") and best_overall_conf >= MIN_ACCEPTABLE_CONFIDENCE:
                break
                
        if extraction_reason == "value_pattern_mismatch":
            results[name] = {
                "value": None,
                "confidence": 0.0,
                "extraction_source": "unmatched",
                "reason": "value_pattern_mismatch"
            }
        elif extraction_reason == "sanity_check_failed":
            results[name] = {
                "value": None,
                "confidence": 0.0,
                "extraction_source": "unmatched",
                "reason": "sanity_check_failed"
            }
        elif matched_val is not None and best_overall_conf >= MIN_ACCEPTABLE_CONFIDENCE:
            # Apply sanity check for id_number fields that have no value_pattern (same-block path)
            if field_hint == "id_number" and not value_pattern and not _passes_id_sanity_check(matched_val):
                results[name] = {
                    "value": None,
                    "confidence": 0.0,
                    "extraction_source": "unmatched",
                    "reason": "sanity_check_failed"
                }
            else:
                results[name] = {
                    "value": matched_val,
                    "confidence": best_overall_conf,
                    "extraction_source": "deterministic"
                }
                if is_merged:
                    results[name]["value_merged"] = True
        else:
            results[name] = {
                "value": matched_val,
                "confidence": best_overall_conf,
                "extraction_source": "unmatched",
                "reason": "low_confidence" if matched_val is not None else "not_found"
            }
    return results


def extract_kv_from_table(table_blocks: list[dict], field_config: dict) -> dict[str, dict]:
    """Performs deterministic extraction on table structured layout regions."""
    results = {}
    for field in field_config.get("fields", []):
        if field.get("field_type", "form") != "table":
            continue
            
        name = field["name"]
        header_aliases = field.get("header_aliases") or []
        label_aliases = field.get("label_aliases") or []
        value_pattern = field.get("value_pattern")
        pattern_re = re.compile(value_pattern) if value_pattern else None
        
        matched_val = None
        best_overall_conf = 0.0
        extraction_reason = "not_found"
        
        for block in table_blocks:
            pred_html = block.get("pred_html") or ""
            if not pred_html:
                continue
            grid = parse_html_table(pred_html)
            if not grid:
                continue
                
            # Style 1: Column Header + Row Label intersection
            if header_aliases and label_aliases:
                header_row = grid[0]
                col_idx = -1
                best_header_score = 0.0
                for c_idx, cell in enumerate(header_row):
                    for h_alias in header_aliases:
                        if fuzz:
                            score = max(fuzz.token_sort_ratio(cell.lower(), h_alias.lower()), fuzz.ratio(cell.lower(), h_alias.lower()))
                        else:
                            score = 100 if cell.lower() == h_alias.lower() else 0
                        if score >= 80 and score > best_header_score:
                            best_header_score = score
                            col_idx = c_idx
                if col_idx != -1:
                    for r_idx in range(1, len(grid)):
                        row = grid[r_idx]
                        if not row or col_idx >= len(row):
                            continue
                        for c_idx in range(min(col_idx, len(row))):
                            cell = row[c_idx]
                            for l_alias in label_aliases:
                                if fuzz:
                                    score = max(fuzz.token_sort_ratio(cell.lower(), l_alias.lower()), fuzz.ratio(cell.lower(), l_alias.lower()))
                                else:
                                    score = 100 if cell.lower() == l_alias.lower() else 0
                                if score >= 80:
                                    val_cand = row[col_idx].strip()
                                    if value_pattern:
                                        match = pattern_re.search(val_cand)
                                        if match:
                                            matched_val = match.group(1) if match.groups() else match.group(0)
                                            best_overall_conf = min(score / 100.0, 1.0)
                                            extraction_reason = "pattern_match"
                                            break
                                        else:
                                            matched_val = None
                                            best_overall_conf = 0.0
                                            extraction_reason = "value_pattern_mismatch"
                                            break
                                    else:
                                        matched_val = val_cand
                                        best_overall_conf = min(score / 100.0, CONFIDENCE_NO_PATTERN_SAME_BLOCK)
                                        extraction_reason = "no_pattern_same_block"
                                        break
                            if extraction_reason != "not_found":
                                break
                        if extraction_reason != "not_found":
                            break
                            
            # Style 2: Row label lookup (finding the next cell in the matched row)
            # Run Style 2 if Style 1 did not match header/find anything, or if not configured for Style 1
            if extraction_reason == "not_found":
                for r_idx, row in enumerate(grid):
                    for c_idx, cell in enumerate(row):
                        for l_alias in label_aliases:
                            if fuzz:
                                score = max(fuzz.token_sort_ratio(cell.lower(), l_alias.lower()), fuzz.ratio(cell.lower(), l_alias.lower()))
                            else:
                                score = 100 if cell.lower() == l_alias.lower() else 0
                            if score >= 80:
                                label_conf = score / 100.0
                                for next_c in range(c_idx + 1, len(row)):
                                    val_cand = row[next_c].strip()
                                    if val_cand:
                                        if value_pattern:
                                            match = pattern_re.search(val_cand)
                                            if match:
                                                matched_val = match.group(1) if match.groups() else match.group(0)
                                                best_overall_conf = min(label_conf, 1.0)
                                                extraction_reason = "pattern_match"
                                                break
                                            else:
                                                matched_val = None
                                                best_overall_conf = 0.0
                                                extraction_reason = "value_pattern_mismatch"
                                                break
                                        else:
                                            matched_val = val_cand
                                            best_overall_conf = min(label_conf, CONFIDENCE_NO_PATTERN_SPATIAL)
                                            extraction_reason = "no_pattern_spatial"
                                            break
                                if extraction_reason != "not_found":
                                    break
                        if extraction_reason != "not_found":
                            break
                    if extraction_reason != "not_found":
                        break
            if extraction_reason in ("pattern_match", "no_pattern_same_block", "no_pattern_spatial") and best_overall_conf >= MIN_ACCEPTABLE_CONFIDENCE:
                break
                
        if extraction_reason == "value_pattern_mismatch":
            results[name] = {
                "value": None,
                "confidence": 0.0,
                "extraction_source": "unmatched",
                "reason": "value_pattern_mismatch"
            }
        elif matched_val is not None and best_overall_conf >= MIN_ACCEPTABLE_CONFIDENCE:
            results[name] = {
                "value": matched_val,
                "confidence": best_overall_conf,
                "extraction_source": "deterministic"
            }
        else:
            results[name] = {
                "value": matched_val,
                "confidence": best_overall_conf,
                "extraction_source": "unmatched",
                "reason": "low_confidence" if matched_val is not None else "not_found"
            }
    return results


def build_document_schema(field_config: dict) -> Type[BaseModel]:
    """Generates schema containing value fields and their companion self-report parameters."""
    fields_def = {}
    for field in field_config.get("fields", []):
        name = field["name"]
        desc = field.get("description") or ""
        
        fields_def[name] = (Optional[str], Field(default=None, description=desc))
        fields_def[f"{name}_confidence"] = (float, Field(default=0.0, description=f"Self-reported confidence (0.0-1.0) for '{name}'."))
        fields_def[f"{name}_note"] = (Optional[str], Field(default=None, description=f"Explanations or notes about extraction quality for '{name}'."))
        
    model_name = f"{field_config.get('type', 'GenericDocument')}Schema"
    return create_model(model_name, **fields_def)


def extract_kv_llm(ocr_text: str, schema: Type[BaseModel], field_config: dict) -> BaseModel:
    """Performs structured fallback extraction for unmatched fields, scoring self-reported confidence."""
    from services.llm_verifier import _instructor_ollama_client, _field_verifier_model
    
    system_prompt = (
        "You are a precise document extraction model. Your task is to extract field values from the provided OCR text.\n"
        "For each field, use the description and label aliases provided to locate the correct value.\n"
        "You MUST score your own confidence (0.0 - 1.0) for each field (set low confidence when text is garbled/ambiguous, and high when clear).\n"
        "Provide a note in the companion '{field_name}_note' field if there is any ambiguity or low confidence.\n"
        "IMPORTANT: If a field is not present in the OCR text, or if you are not sure about it, you MUST return null/None for that field, and 0.0 for its confidence. Do not guess."
    )
    
    user_content = "OCR text of the page:\n"
    user_content += "--------------------\n"
    user_content += f"{ocr_text}\n"
    user_content += "--------------------\n"
    user_content += "Fields to extract:\n"
    for field in field_config.get("fields", []):
        name = field["name"]
        desc = field.get("description", "")
        aliases = ", ".join(field.get("label_aliases", []))
        user_content += f"- Field: {name}\n  Description: {desc}\n  Label Aliases: [{aliases}]\n"
        
    user_content += "\nExtract the values, self-reported confidence, and notes for these fields."
    
    fallback_instance = schema()
    try:
        client = _instructor_ollama_client()
        model = _field_verifier_model()
        result = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_model=schema,
        )
        return result
    except Exception:
        return fallback_instance


def merge_extraction_results(deterministic_results: dict, llm_results: BaseModel) -> dict[str, dict]:
    """Merges deterministic & LLM extractions, marking fallback failures as 'not_found' instead of 'unmatched'."""
    merged = {}
    for field_name, det in deterministic_results.items():
        if det.get("extraction_source") == "deterministic":
            merged[field_name] = {
                "value": det["value"],
                "confidence": det["confidence"],
                "extraction_source": "deterministic"
            }
            if det.get("value_merged"):
                merged[field_name]["value_merged"] = True
        else:
            llm_val = getattr(llm_results, field_name, None)
            llm_conf = getattr(llm_results, f"{field_name}_confidence", 0.0)
            llm_note = getattr(llm_results, f"{field_name}_note", None)
            
            if llm_val not in (None, ""):
                merged[field_name] = {
                    "value": llm_val,
                    "confidence": llm_conf,
                    "extraction_source": "llm_fallback",
                    "note": llm_note
                }
            else:
                merged[field_name] = {
                    "value": None,
                    "confidence": 0.0,
                    "extraction_source": "not_found",
                    "reason": "both_paths_returned_null",
                    "note": llm_note
                }
    return merged


def summarize_extraction_sources(results: list[dict]) -> dict:
    """Utility to calculate source percentages per document type."""
    counts = {}
    for doc in results:
        doc_type = doc.get("document_type", "Unknown")
        fields = doc.get("fields", {})
        if doc_type not in counts:
            counts[doc_type] = {"deterministic": 0, "llm_fallback": 0, "not_found": 0, "unmatched": 0}
        for field_name, meta in fields.items():
            source = meta.get("extraction_source", "unmatched")
            if source in counts[doc_type]:
                counts[doc_type][source] += 1
            else:
                counts[doc_type]["unmatched"] += 1
                
    summary = {}
    for doc_type, source_counts in counts.items():
        total = sum(source_counts.values())
        if total == 0:
            summary[doc_type] = {"deterministic": 0.0, "llm_fallback": 0.0, "not_found": 0.0, "unmatched": 0.0}
        else:
            summary[doc_type] = {
                source: round((count / total) * 100.0, 2)
                for source, count in source_counts.items()
            }
    return summary
