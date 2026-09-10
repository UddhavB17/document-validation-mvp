"""Typed shapes for review API payloads and domain boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypedDict

FieldStatus = Literal["match", "mismatch", "attention"]
ApplicantRole = Literal["primary", "co_applicant", "guarantor"]
RelationshipRole = Literal["primary", "co_applicant", "guarantor", "family_member"]
RelationshipStatus = Literal["match", "mismatch", "attention", "n/a"]
DocumentStatus = Literal["Extracted", "Flagged"]


# Comparison matrix and relationship graph payloads.
class ComparisonFieldRow(TypedDict):
    """One expected-versus-extracted field comparison and its source pages."""

    field_name: str
    label: str
    expected_value: str | None
    extracted_value: str | None
    status: FieldStatus
    source_pages: list[int]


class ApplicantComparisonSection(TypedDict):
    """Comparison fields grouped under one applicant label."""

    applicant_role: ApplicantRole
    applicant_label: str
    person_name: str
    fields: list[ComparisonFieldRow]


class ComparisonMatrix(TypedDict):
    """Application-level and applicant-level comparison sections."""

    core_parameters: list[ComparisonFieldRow]
    applicants: list[ApplicantComparisonSection]


class RelationshipNode(TypedDict, total=False):
    """One applicant or related family member in the relationship graph."""

    id: str
    name: str
    role: RelationshipRole
    relation_to_primary: str | None
    status: RelationshipStatus


class ComparisonAndRelationships(TypedDict):
    """Combined response returned by comparison and relationship construction."""

    comparison_matrix: ComparisonMatrix
    relationships: list[RelationshipNode]


# Worklist payloads.
class WorklistItem(TypedDict):
    """One application row displayed in the reviewer worklist."""

    id: int
    loan_id: str
    applicant_name: str | None
    product_type: str | None
    status: str
    created_at: str
    issues: int
    reviewer_issues: int
    business_issues: int
    processing_warnings: int
    pipeline_status: str
    pipeline_retryable: bool
    pipeline_processed_pages: int | None
    pipeline_total_pages: int | None
    pipeline_percentage: float | None


class WorklistResponse(TypedDict):
    """Top-level reviewer worklist response."""

    items: list[WorklistItem]


# Database-backed review rows.
class AnomalyRow(TypedDict, total=False):
    """Validation anomaly row with optional persisted metadata."""

    id: int
    application_id: int
    rule_id: str
    s_no: int | None
    severity: str
    document_type: str
    expected_value: str
    found_value: str
    page_number: int | None
    reason: str
    status: str
    created_at: str
    person_id: str
    person_role: str
    field_name: str


class PageRow(TypedDict, total=False):
    """Persisted page row with decoded extracted fields."""

    id: int
    application_id: int
    page_number: int
    page_type: str
    document_type: str
    ocr_text: str
    extracted_fields: Mapping[str, object]
    _ocr_clean: str


class DocumentSummary(TypedDict):
    """Document overview row used by the application review page."""

    name: str
    type: str
    pages: str
    status: DocumentStatus
    firstPage: int


class ApplicationReviewData(TypedDict):
    """Repository result containing all data needed by review services."""

    # These rows contain persisted JSON with schema that varies by document
    # type. Keep the dynamic part at this repository boundary; service outputs
    # below remain explicitly typed.
    application: dict[str, Any]
    uploaded_file: dict[str, Any]
    ground_truth: dict[str, Any]
    anomalies: list[dict[str, Any]]
    pages: list[dict[str, Any]]
    page_events: list[dict[str, Any]]
    documents_found: list[str]
    document_pages: dict[str, list[int]]
    documents_missing: list[object]
