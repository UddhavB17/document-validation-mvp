"""Checklist matching logic — compatibility facade.

Implementation is split across ``services.checklist`` by rule group.
"""

from services.checklist.anomalies import (
    check_date_range,
    check_field_match,
    check_presence_any,
    check_presence_min_count,
)
from services.checklist.anomaly_builder import build_anomaly
from services.checklist.bank_period import bank_statement_required_month_labels
from services.checklist.conditions import condition_applies, system_flag_state
from services.checklist.page_helpers import (
    _document_derived_system_data,
    _document_evidence_count,
)
from services.checklist.runner import evaluate_checklist, run_checks

__all__ = [
    "build_anomaly",
    "bank_statement_required_month_labels",
    "check_date_range",
    "check_field_match",
    "check_presence_any",
    "check_presence_min_count",
    "condition_applies",
    "evaluate_checklist",
    "run_checks",
    "system_flag_state",
    "_document_derived_system_data",
    "_document_evidence_count",
]
