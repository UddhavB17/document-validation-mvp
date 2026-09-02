"""Typed shapes for review API payloads and domain boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict

FieldStatus = Literal["match", "mismatch", "attention"]
ApplicantRole = Literal["primary", "co_applicant", "guarantor"]
RelationshipRole = Literal["primary", "co_applicant", "guarantor", "family_member"]
RelationshipStatus = Literal["match", "mismatch", "attention", "n/a"]
DocumentStatus = Literal["Extracted", "Flagged"]


class ComparisonFieldRow(TypedDict):
    field_name: str
    label: str
    expected_value: str | None
    extracted_value: str | None
    status: FieldStatus
    source_pages: list[int]


class ApplicantComparisonSection(TypedDict):
    applicant_role: ApplicantRole
    applicant_label: str
    person_name: str
    fields: list[ComparisonFieldRow]


class ComparisonMatrix(TypedDict):
    core_parameters: list[ComparisonFieldRow]
    applicants: list[ApplicantComparisonSection]


class RelationshipNode(TypedDict, total=False):
    id: str
    name: str
    role: RelationshipRole
    relation_to_primary: str | None
    status: RelationshipStatus


class ComparisonAndRelationships(TypedDict):
    comparison_matrix: ComparisonMatrix
    relationships: list[RelationshipNode]


class WorklistItem(TypedDict):
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


class WorklistResponse(TypedDict):
    items: list[WorklistItem]


class AnomalyRow(TypedDict, total=False):
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
    id: int
    application_id: int
    page_number: int
    page_type: str
    document_type: str
    ocr_text: str
    extracted_fields: Mapping[str, object]
    _ocr_clean: str


class DocumentSummary(TypedDict):
    name: str
    type: str
    pages: str
    status: DocumentStatus
    firstPage: int


class ApplicationReviewData(TypedDict):
    application: dict[str, object]
    uploaded_file: dict[str, object]
    ground_truth: dict[str, object]
    anomalies: list[dict[str, object]]
    pages: list[dict[str, object]]
    page_events: list[dict[str, object]]
    documents_found: list[str]
    document_pages: dict[str, list[int]]
    documents_missing: list[object]
