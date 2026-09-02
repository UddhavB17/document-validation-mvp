"""Fuzzy string matching with rapidfuzz fallback."""

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - optional dependency
    from difflib import SequenceMatcher

    class fuzz:  # type: ignore[no-redef]
        @staticmethod
        def ratio(left: str, right: str) -> int:
            return int(SequenceMatcher(None, left, right).ratio() * 100)
