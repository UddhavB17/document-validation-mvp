"""Checklist evaluation engine.

Core decision logic owned by this team.

Inputs consumed (from partner JSON):
  - digital_text  : dict of form fields extracted from the loan application pages.
  - scanned_docs  : dict mapping document name → content/metadata from scanned pages.

The engine compares both against the loaded checklist and produces a list of
exception dicts that feed into exception_aggregator → report_generator.
"""

from __future__ import annotations


# ── Exception types ───────────────────────────
ISSUE_MISSING = "missing"
ISSUE_MISMATCH = "mismatch"
ISSUE_UNREADABLE = "unreadable"


def evaluate_checklist(
    checklist: dict,
    digital_text: dict,
    scanned_docs: dict,
) -> list[dict]:
    """Evaluate the partner's extracted data against the product checklist.

    Args:
        checklist:     Loaded checklist dict (from checklist_service.load_checklist).
        digital_text:  Form fields extracted from the digital pages of the PDF.
        scanned_docs:  Documents classified from the scanned pages of the PDF.

    Returns:
        List of exception dicts with keys:
          document   – name of the document / field
          issue      – one of ISSUE_* constants
          detail     – human-readable description
          severity   – "high" | "medium" | "low"
    """
    exceptions: list[dict] = []

    # ── 1. Required document presence check ──
    required_docs: list[str] = checklist.get("required_documents", [])
    found_docs = set(scanned_docs.keys())

    for doc_name in required_docs:
        if doc_name not in found_docs:
            exceptions.append(
                {
                    "document": doc_name,
                    "issue": ISSUE_MISSING,
                    "detail": f"Required document '{doc_name}' was not found in scanned pages.",
                    "severity": "high",
                }
            )

    # ── 2. Field-level rule checks (digital form) ──
    field_rules: dict = checklist.get("field_rules", {})
    for field_name, rules in field_rules.items():
        actual_value = digital_text.get(field_name)
        _check_field(field_name, actual_value, rules, exceptions)

    # ── 3. Cross-checks (digital vs scanned) ──
    # TODO: implement name / date / amount cross-validation between
    #       digital_text fields and their scanned document counterparts.

    return exceptions


def _check_field(
    field_name: str,
    actual_value: object,
    rules: dict,
    exceptions: list[dict],
) -> None:
    """Apply field-level rules and append any exceptions found."""
    # Missing required field
    if actual_value is None:
        exceptions.append(
            {
                "document": "loan_application_form",
                "issue": ISSUE_MISSING,
                "detail": f"Required field '{field_name}' is absent from the application form.",
                "severity": "high",
            }
        )
        return

    # Numeric range check
    expected_type = rules.get("type")
    if expected_type == "number":
        try:
            value = float(actual_value)
        except (TypeError, ValueError):
            exceptions.append(
                {
                    "document": "loan_application_form",
                    "issue": ISSUE_MISMATCH,
                    "detail": f"Field '{field_name}' must be numeric; got '{actual_value}'.",
                    "severity": "medium",
                }
            )
            return

        min_val = rules.get("min")
        max_val = rules.get("max")
        if min_val is not None and value < min_val:
            exceptions.append(
                {
                    "document": "loan_application_form",
                    "issue": ISSUE_MISMATCH,
                    "detail": f"Field '{field_name}' value {value} is below minimum {min_val}.",
                    "severity": "medium",
                }
            )
        if max_val is not None and value > max_val:
            exceptions.append(
                {
                    "document": "loan_application_form",
                    "issue": ISSUE_MISMATCH,
                    "detail": f"Field '{field_name}' value {value} exceeds maximum {max_val}.",
                    "severity": "medium",
                }
            )
