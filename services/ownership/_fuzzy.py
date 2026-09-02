"""Fuzzy matching with rapidfuzz fallback."""

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    class fuzz:  # type: ignore[no-redef]
        @staticmethod
        def token_sort_ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100

        @staticmethod
        def token_set_ratio(left: str, right: str) -> float:
            return SequenceMatcher(None, left, right).ratio() * 100
