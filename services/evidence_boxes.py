"""Evidence bounding-box resolution. Owned by ``ws-f-accuracy-ops-api``."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

try:  # pragma: no cover - exercised when rapidfuzz is installed
    from rapidfuzz import fuzz as _fuzz
except ImportError:  # pragma: no cover - difflib fallback for lean envs
    from difflib import SequenceMatcher as _SequenceMatcher

    _fuzz = None

#: Minimum partial-ratio for fuzzy name/address window matches.
EVIDENCE_PARTIAL_THRESHOLD = 85


def _strip_accents(text: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


def _normalize_text(value: Any) -> str:
    """Casefolded, punctuation-free comparison form for names/addresses."""
    text = _strip_accents(str(value or "")).casefold()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_digits(value: Any) -> str:
    """Digits-only form for PAN/Aadhaar/account numbers."""
    return re.sub(r"\D", "", str(value or ""))


def _looks_numeric(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    alnum = re.sub(r"[\s\-/]", "", text)
    return bool(alnum) and sum(1 for char in alnum if char.isdigit()) >= max(
        4, len(alnum) // 2
    )


def _partial_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if _fuzz is not None:
        return float(_fuzz.partial_ratio(left, right))
    short, long = (left, right) if len(left) <= len(right) else (right, left)
    best = 0.0
    window = max(len(short), 1)
    step = max(1, window // 4)
    for start in range(0, len(long) - window + 1, step):
        chunk = long[start : start + window]
        best = max(
            best,
            _SequenceMatcher(None, short, chunk).ratio() * 100.0,
        )
    return best


def _word_text(word: dict) -> str:
    for key in ("t", "text", "w", "word"):
        value = word.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _word_box(word: dict) -> list[float] | None:
    for key in ("b", "bbox", "box"):
        value = word.get(key)
        if isinstance(value, (list, tuple)) and len(value) == 4:
            try:
                return [float(value[0]), float(value[1]), float(value[2]), float(value[3])]
            except (TypeError, ValueError):
                return None
    return None


def _union_box(boxes: list[list[float]]) -> list[float]:
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def find_value_bbox(words: list[dict], value: str) -> list[float] | None:
    """Return normalized ``[x0, y0, x1, y1]`` for ``value`` or ``None``.

    ``words`` is the in-memory OCR word list (``[{"t","b","c"}]``, normalized
    0-1 coordinates). Both sides are normalised (digits-only for
    PAN/Aadhaar/account numbers; casefold + punctuation-stripped otherwise);
    the shortest contiguous word window whose joined text contains the value
    (or reaches >= 85 partial ratio for names) wins; the union box is
    returned.
    """
    if not words or value in (None, ""):
        return None
    numeric = _looks_numeric(value)
    needle = _normalize_digits(value) if numeric else _normalize_text(value)
    if not needle:
        return None

    prepared: list[tuple[str, list[float] | None, str]] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        raw = _word_text(word)
        if not raw:
            continue
        key = _normalize_digits(raw) if numeric else _normalize_text(raw)
        if not key:
            continue
        prepared.append((key, _word_box(word), raw))
    if not prepared:
        return None

    best: tuple[bool, int, list[list[float]]] | None = None
    count = len(prepared)
    for start in range(count):
        running = ""
        boxes: list[list[float]] = []
        for end in range(start, min(count, start + 12)):
            key, box, raw = prepared[end]
            running = f"{running} {key}".strip() if running else key
            if box is not None:
                boxes.append(box)
            if not boxes:
                continue
            compact = running.replace(" ", "")
            needle_compact = needle.replace(" ", "")
            if numeric:
                if needle_compact and needle_compact in compact:
                    width = end - start
                    if best is None or not best[0] or width < best[1]:
                        best = (True, width, list(boxes))
                    break
                continue
            if needle in running or needle_compact in compact:
                # Exact containment always wins over a fuzzy window.
                width = end - start
                if best is None or not best[0] or width < best[1]:
                    best = (True, width, list(boxes))
                break
            score = _partial_ratio(needle, running)
            if score >= EVIDENCE_PARTIAL_THRESHOLD and (
                best is None or (not best[0] and (end - start) < best[1])
            ):
                best = (False, end - start, list(boxes))
    if best is None:
        return None
    return _union_box(best[2])


def page_words(page: dict) -> list[dict]:
    """Return the in-memory OCR word list for a page dict (any known key)."""
    for key in ("words", "ocr_words", "ocr_word_boxes", "word_boxes"):
        words = page.get(key)
        if isinstance(words, list) and words:
            return [word for word in words if isinstance(word, dict)]
    return []


def evidence_for_value(page: dict | None, value: Any) -> dict | None:
    """Build an ``evidence_json`` dict for ``value`` on ``page`` or None."""
    if not isinstance(page, dict) or value in (None, ""):
        return None
    words = page_words(page)
    if not words:
        return None
    bbox = find_value_bbox(words, str(value))
    if bbox is None:
        return None
    matched = str(value)
    return {
        "page": page.get("page_number"),
        "bbox": bbox,
        "text": matched,
    }


def attach_evidence_to_anomalies(
    anomalies: list[dict], pages: list[dict]
) -> list[dict]:
    """Write ``evidence_json = {"page","bbox","text"}`` on anomalies in place."""
    pages_by_number = {
        int(page.get("page_number") or 0): page
        for page in pages
        if isinstance(page, dict) and page.get("page_number") is not None
    }
    for anomaly in anomalies:
        if not isinstance(anomaly, dict) or anomaly.get("evidence_json"):
            continue
        page_number = anomaly.get("page_number")
        try:
            page = pages_by_number.get(int(page_number)) if page_number is not None else None
        except (TypeError, ValueError):
            page = None
        if page is None:
            continue
        value = anomaly.get("found_value")
        if value in (None, ""):
            value = anomaly.get("expected_value")
        evidence = evidence_for_value(page, value)
        if evidence is not None:
            anomaly["evidence_json"] = evidence
    return anomalies
