"""Report generator.

Builds a structured report dict from an application's exception list.
The report can be:
  - Rendered as JSON via the API
  - Serialised to an HTML file in data/reports/
  - Displayed directly in the Streamlit results page
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPORTS_DIR = Path("data/reports")


def build_report(
    application_id: int,
    loan_id: str,
    exceptions: list[dict],
    llm_summary: str = "",
) -> dict:
    """Assemble a validation report dict.

    Args:
        application_id: DB primary key of the application record.
        loan_id:        Human-readable loan reference.
        exceptions:     Sorted exception list from exception_aggregator.
        llm_summary:    Optional summary string from llm_service.

    Returns:
        Report dict with metadata and exceptions.
    """
    return {
        "application_id": application_id,
        "loan_id": loan_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_exceptions": len(exceptions),
        "high_severity_count": sum(1 for e in exceptions if e.get("severity") == "high"),
        "llm_summary": llm_summary,
        "exceptions": exceptions,
    }


def save_report_json(report: dict) -> Path:
    """Persist *report* as a JSON file under data/reports/.

    Returns:
        Path to the written file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"report_{report['application_id']}_{report['loan_id']}.json"
    output_path = REPORTS_DIR / filename
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return output_path
