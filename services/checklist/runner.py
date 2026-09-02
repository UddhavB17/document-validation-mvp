"""Checklist engine submodule."""

from __future__ import annotations

from services import checklist_service
from services.checklist.accuracy_runner import _run_accuracy_checks
from services.checklist.page_helpers import (
    _document_derived_system_data,
    _non_loan_relevance_anomaly,
)
from services.checklist.presence_runner import _accuracy_checks_enabled, _run_presence_checks
from services.checklist.quality_runner import _run_quality_checks
from services.consistency_checks import run_consistency_checks


def run_checks(
    pages: list[dict],
    ground_truth: dict,
    system_data: dict | None,
    product_type: str,
) -> list[dict]:
    from services.person_ownership import assign_page_owners, ownership_anomalies_for_unassigned

    system_data = {
        **(ground_truth or {}),
        **_document_derived_system_data(pages),
        **(system_data or {}),
    }
    if "people" not in system_data and isinstance(system_data.get("reference_data"), dict):
        system_data["people"] = system_data["reference_data"]
    # Resolve page owners before presence/accuracy/consistency so TRUSTED_*
    # never compares co-applicant OCR against primary by accident.
    assign_page_owners(pages, system_data)
    checklist_items = checklist_service.get_all_checklist_items(product_type)
    relevance_anomaly = _non_loan_relevance_anomaly(pages, checklist_items)
    if relevance_anomaly is not None:
        return [relevance_anomaly]
    anomalies = _run_presence_checks(pages, checklist_items, system_data)

    if _accuracy_checks_enabled():
        accuracy_items = checklist_service.get_accuracy_check_items(product_type)
        anomalies.extend(_run_accuracy_checks(pages, ground_truth, system_data, accuracy_items))

        anomalies.extend(run_consistency_checks(pages, system_data))

    anomalies.extend(_run_quality_checks(pages, ground_truth))
    anomalies.extend(ownership_anomalies_for_unassigned(pages))
    return anomalies


def evaluate_checklist(checklist: dict, extracted_documents: dict) -> list[dict]:
    required_docs = checklist.get("required_documents", [])
    found_docs = set(extracted_documents.keys())
    return [
        {"document": doc_name, "issue": "missing"}
        for doc_name in required_docs
        if doc_name not in found_docs
    ]
