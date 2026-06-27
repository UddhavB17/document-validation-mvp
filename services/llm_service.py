"""LLM service boundary.

Provides a clean interface for generating natural-language summaries
of validation exceptions. The underlying model is swappable via the
LLM_PROVIDER environment variable.

Supported providers (set in .env):
  none   – rule-based fallback (no API key required)
  openai – OpenAI Chat Completions (requires LLM_API_KEY)
  gemini – Google Gemini (requires LLM_API_KEY)
"""

from __future__ import annotations

import os


def summarize_exceptions(exceptions: list[dict]) -> str:
    """Return a human-readable summary of validation exceptions.

    Args:
        exceptions: List of exception dicts from exception_aggregator.

    Returns:
        A plain-text summary suitable for displaying in the UI or
        embedding in the generated report.
    """
    provider = os.getenv("LLM_PROVIDER", "none").lower()

    if provider == "none" or not exceptions:
        return _rule_based_summary(exceptions)

    if provider == "openai":
        return _openai_summary(exceptions)  # type: ignore[return-value]

    if provider == "gemini":
        return _gemini_summary(exceptions)  # type: ignore[return-value]

    return _rule_based_summary(exceptions)


# ── Fallback (no LLM) ─────────────────────────

def _rule_based_summary(exceptions: list[dict]) -> str:
    if not exceptions:
        return "✅ No exceptions found. The loan file appears complete."

    high = sum(1 for e in exceptions if e.get("severity") == "high")
    medium = sum(1 for e in exceptions if e.get("severity") == "medium")
    low = sum(1 for e in exceptions if e.get("severity") == "low")

    parts = [f"{len(exceptions)} exception(s) require review:"]
    if high:
        parts.append(f"  • {high} high-severity")
    if medium:
        parts.append(f"  • {medium} medium-severity")
    if low:
        parts.append(f"  • {low} low-severity")

    missing = [e["document"] for e in exceptions if e.get("issue") == "missing"]
    if missing:
        parts.append(f"Missing documents: {', '.join(missing)}")

    return "\n".join(parts)


# ── LLM stubs (implement when provider is configured) ──

def _openai_summary(exceptions: list[dict]) -> str:  # pragma: no cover
    """Call OpenAI Chat Completions API.

    TODO: implement once LLM_API_KEY is configured.
    """
    raise NotImplementedError("OpenAI provider not yet implemented.")


def _gemini_summary(exceptions: list[dict]) -> str:  # pragma: no cover
    """Call Google Gemini API.

    TODO: implement once LLM_API_KEY is configured.
    """
    raise NotImplementedError("Gemini provider not yet implemented.")
