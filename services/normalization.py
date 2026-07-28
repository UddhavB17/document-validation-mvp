from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Optional, Literal
from pydantic import BaseModel

logger = logging.getLogger("dmef.normalization")

class ExtractedField(BaseModel):
    field_name: str
    raw_value: str
    normalized_value: Optional[str]
    field_type: Literal["date", "text", "number", "currency"]
    confidence: float
    normalization_status: Literal["success", "failed", "not_applicable"]


def try_fast_path(raw_value: str) -> Optional[str]:
    """Highly optimized fast-path check for the 3-4 most common date formats in Indian documents."""
    val = raw_value.strip()
    if not val:
        return None

    # 1. YYYY-MM-DD
    if re.fullmatch(r"^\d{4}-\d{2}-\d{2}$", val):
        try:
            datetime.strptime(val, "%Y-%m-%d")
            return val
        except ValueError:
            return None

    # 2. DD/MM/YYYY or DD-MM-YYYY
    m = re.fullmatch(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$", val)
    if m:
        d, m_val, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = datetime(y, m_val, d)
            return dt.date().isoformat()
        except ValueError:
            return None

    # 3. DD.MM.YYYY
    m = re.fullmatch(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", val)
    if m:
        d, m_val, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dt = datetime(y, m_val, d)
            return dt.date().isoformat()
        except ValueError:
            return None

    # 4. DD/MM/YY or DD-MM-YY or DD.MM.YY (Two digit years)
    # Day-first DMY ordering is strictly assumed for ambiguous two-digit years (e.g. 03/04/25 -> 2025-04-03)
    m = re.fullmatch(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2})$", val) or re.fullmatch(r"^(\d{1,2})\.(\d{1,2})\.(\d{2})$", val)
    if m:
        d, m_val, y_short = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Pivot: year >= 40 is 1900s, else 2000s
        y = 1900 + y_short if y_short >= 40 else 2000 + y_short
        try:
            dt = datetime(y, m_val, d)
            return dt.date().isoformat()
        except ValueError:
            return None

    return None


def normalize_date(raw_value: str) -> tuple[Optional[str], str]:
    """Deterministic date normalization. No LLM calls.
    
    Returns:
        (normalized_iso_date_or_None, status) where status is "success" or "failed"
    """
    if not isinstance(raw_value, str):
        return None, "failed"
    val = raw_value.strip()
    if not val:
        return None, "failed"

    try:
        # Fast-path regex check
        fast_val = try_fast_path(val)
        if fast_val:
            return fast_val, "success"

        # Fallback to dateparser
        import dateparser
        parsed = dateparser.parse(
            val,
            settings={
                "DATE_ORDER": "DMY",
                "PREFER_DAY_OF_MONTH": "first",
            }
        )
        if parsed:
            return parsed.date().isoformat(), "success"
        
        logger.warning("Failed to parse date: %s", val)
        return None, "failed"
    except Exception as e:
        logger.error("Exception in normalize_date for %s: %s", val, e, exc_info=True)
        return None, "failed"


def normalize_extracted_fields(extracted_fields: dict[str, Any]) -> dict[str, Any]:
    """Normalize extracted fields.
    If a date normalization fails, routes the field to the LLM fallback path by adding metadata.
    """
    updated = {}
    for key, val in extracted_fields.items():
        if str(key).startswith("_") or val in (None, "", [], {}):
            updated[key] = val
            continue
            
        # Determine field type
        field_type = "text"
        if "date" in key or key == "dob":
            field_type = "date"
        elif "amount" in key or key == "emi":
            field_type = "currency"
        elif "count" in key or key == "tenure" or key == "age":
            field_type = "number"
            
        if field_type == "date":
            norm_val, status = normalize_date(str(val))
            if status == "failed":
                # Route into LLM fallback path
                updated["_llm_field_extraction"] = {
                    "status": "fields_extracted",
                    "reason": f"date_normalization_failed_{key}",
                }
            
            field_obj = ExtractedField(
                field_name=key,
                raw_value=str(val),
                normalized_value=norm_val,
                field_type="date",
                confidence=1.0 if status == "success" else 0.0,
                normalization_status=status
            )
            updated[key] = norm_val
            updated[f"_{key}_metadata"] = field_obj.model_dump()
        else:
            updated[key] = val
            
    return {**extracted_fields, **updated}
