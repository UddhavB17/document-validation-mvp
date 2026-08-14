"""Read-only reviewer API routes used by the Next.js UI."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response

from database.db import get_connection, init_db
from services.checklist_service import get_ai_checkable_items, get_all_checklist_items, get_human_review_items
from services.checklist_status import build_checklist_status
from services.ocr_json_export import build_ocr_document_json
from services.progress_tracker import get_progress
from services.job_control import JobControlError, request_control
from services.reprocessing import (
    ReprocessConflictError,
    queue_application_reprocess,
    restart_application,
    resume_application,
)
from services.reviewer import load_reviewer_summary, summarize_for_display

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/worklist")
def get_worklist() -> dict[str, list[dict[str, Any]]]:
    """Return the reviewer worklist for the Next.js UI."""
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, loan_id, applicant_name, product_type, status, created_at
            FROM applications
            ORDER BY created_at DESC
            """
        ).fetchall()

        items = []
        for row in rows:
            item = dict(row)
            progress = get_progress(int(item["id"]))
            anomalies = connection.execute(
                """
                SELECT severity, rule_id, page_number, reason, document_type, expected_value, found_value
                FROM validation_results
                WHERE application_id = ?
                """,
                (item["id"],),
            ).fetchall()
            summary = summarize_for_display([dict(anomaly) for anomaly in anomalies])
            item["issues"] = summary["raw_count"]
            item["reviewer_issues"] = summary["reviewer_count"]
            item["business_issues"] = summary["business_count"]
            item["processing_warnings"] = summary["processing_warning_count"]
            item["pipeline_status"] = (
                progress.get("operational_status") if progress else "not_started"
            )
            item["pipeline_retryable"] = bool(progress and progress.get("retryable"))
            items.append(item)

    return {"items": items}


@router.get("/activity/today")
def get_today_activity() -> dict[str, Any]:
    """Return today's reviewer decision summary."""
    init_db()
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT
                reviewer_decisions.id,
                reviewer_decisions.application_id,
                applications.loan_id,
                reviewer_decisions.decision,
                reviewer_decisions.decided_at
            FROM reviewer_decisions
            JOIN applications ON applications.id = reviewer_decisions.application_id
            WHERE date(reviewer_decisions.decided_at) = date('now', 'localtime')
            ORDER BY reviewer_decisions.decided_at DESC
            """
        ).fetchall()

    decision_rows = [dict(row) for row in rows]
    return {
        "total": len(decision_rows),
        "accepted": sum(1 for row in decision_rows if row["decision"] == "ACCEPT"),
        "overridden": sum(1 for row in decision_rows if row["decision"] == "OVERRIDE"),
        "sent_back": sum(1 for row in decision_rows if row["decision"] == "REQUEST_DOCS"),
        "rows": decision_rows,
    }


def _find_source_pages_for_value(pages: list[dict[str, Any]], value: str, field_name: str, person_id: str | None = None, page_to_person: dict[int, str] | None = None) -> list[int]:
    if not value or len(value.strip()) < 3:
        return []
    val_clean = value.strip().replace(" ", "").lower()
    source_pages = []
    
    for p in pages:
        page_no = p.get("page_number")
        if page_no is None:
            continue
        page_no = int(page_no)
        
        # If page_to_person mapping is provided, filter out pages belonging to other people
        if person_id and page_to_person:
            mapped_person = page_to_person.get(page_no)
            if mapped_person and mapped_person != person_id:
                continue
            
        # 1. Check extracted fields
        is_match = False
        extracted = p.get("extracted_fields") or {}
        
        # Check specific field key
        f_val = extracted.get(field_name) or (extracted.get("_mapped_extraction") and extracted.get("_mapped_extraction").get(field_name))
        if f_val:
            if str(f_val).strip().replace(" ", "").lower() == val_clean:
                is_match = True
                
        # Check all extracted field values
        if not is_match:
            for k, v in extracted.items():
                if k.startswith("_"):
                    continue
                if str(v).strip().replace(" ", "").lower() == val_clean:
                    is_match = True
                    break
                    
        # 2. Check if the value appears in the cached clean text of the page
        if not is_match and p.get("_ocr_clean"):
            if val_clean in p["_ocr_clean"]:
                is_match = True
                
        if is_match:
            source_pages.append(page_no)
            
    return sorted(list(set(source_pages)))


def _get_field_status(person_id: str, field_name: str, expected_value: str | None, actual_value: str | None, anomalies: list[dict[str, Any]], page_to_person: dict[int, str]) -> str:
    if not expected_value or expected_value == "None":
        return "match"
    if not actual_value or actual_value == "None":
        return "attention"

    has_mismatch = False
    has_attention = False

    for vr in anomalies:
        rule_id = str(vr.get("rule_id", "")).upper()
        page_no = vr.get("page_number")
        
        # Check if this anomaly is related to this field
        is_field_related = False
        if field_name == "applicant_name" and "NAME" in rule_id:
            is_field_related = True
        elif field_name == "pan_number" and "PAN" in rule_id:
            is_field_related = True
        elif field_name == "date_of_birth" and ("DOB" in rule_id or "DATE" in rule_id):
            is_field_related = True
        elif field_name == "phone_number" and "PHONE" in rule_id:
            is_field_related = True
        elif field_name == "address" and "ADDRESS" in rule_id:
            is_field_related = True
        elif field_name == "pin_code" and "PIN" in rule_id:
            is_field_related = True
        elif field_name == "aadhaar_last4" and "AADHAAR" in rule_id:
            is_field_related = True

        if is_field_related:
            applies_to_person = False
            if page_no is not None:
                if page_to_person.get(page_no) == person_id:
                    applies_to_person = True
            else:
                reason = str(vr.get("reason", "")).lower()
                if person_id in reason or (person_id == "primary" and "coapplicant" not in reason):
                    applies_to_person = True

            if applies_to_person:
                if "MISMATCH" in rule_id or "FAIL" in rule_id or "ERROR" in rule_id:
                    has_mismatch = True
                else:
                    has_attention = True

    if has_mismatch:
        return "mismatch"
    if has_attention:
        return "attention"
    return "match"


def _build_comparison_matrix_and_relationships(application_id: int, data: dict[str, Any]) -> dict[str, Any]:
    ground_truth = data.get("ground_truth") or {}
    raw_json_str = ground_truth.get("raw_json")
    
    comparison_matrix = {
        "core_parameters": [],
        "applicants": []
    }
    relationships = []
    
    if not raw_json_str:
        return {"comparison_matrix": comparison_matrix, "relationships": relationships}
        
    try:
        gt_json = json.loads(raw_json_str)
    except Exception:
        return {"comparison_matrix": comparison_matrix, "relationships": relationships}
        
    # Get people
    people = gt_json.get("people") or gt_json.get("reference_data") or {}
    if not people and gt_json.get("applicant_name"):
        people = {
            "primary": {
                "person_id": "primary",
                "role": "primary",
                "applicant_name": gt_json.get("applicant_name"),
                "pan_number": gt_json.get("pan_number"),
                "date_of_birth": gt_json.get("date_of_birth"),
                "phone_number": gt_json.get("phone_number"),
                "address": gt_json.get("address"),
                "pin_code": gt_json.get("pin_code"),
                "aadhaar_last4": gt_json.get("aadhaar_last4"),
                "gender": gt_json.get("gender"),
                "father_name": gt_json.get("father_name"),
                "mother_name": gt_json.get("mother_name"),
                "relationship": "Self"
            }
        }

    raw_pages = data.get("pages") or []
    anomalies = data.get("anomalies") or []
    
    ocr_data = _load_saved_document_ocr_json(application_id) or {}
    combined_extracted = ocr_data.get("combined_extracted_fields") or {}

    # Build page to person lookup map from ocr_data mapping manifest
    page_to_person = {}
    for doc_mapping in ocr_data.get("documents", []):
        person_id = doc_mapping.get("applicant_role") or doc_mapping.get("person_id")
        if person_id:
            for page_num in doc_mapping.get("pages", []):
                page_to_person[int(page_num)] = person_id
                
    # Pre-clean OCR text for pages once to speed up lookups (30x speedup for large files)
    pages = []
    for p in raw_pages:
        p_dict = dict(p)
        ocr_text = p_dict.get("ocr_text")
        p_dict["_ocr_clean"] = str(ocr_text).replace(" ", "").lower() if ocr_text else ""
        pages.append(p_dict)
        
    pages_by_number = {int(p["page_number"]): p for p in pages if p.get("page_number") is not None}

    # 1. CORE PARAMETERS
    core_fields = [
        ("loan_id", "Loan ID / Application Number"),
        ("sanction_amount", "Sanction Amount"),
        ("loan_amount", "Loan Amount"),
        ("roi", "Rate of Interest (ROI)"),
        ("tenure", "Tenure (Months)"),
        ("emi", "EMI"),
        ("installment_count", "Installment Count"),
        ("branch", "Branch"),
        ("product_type", "Product Type"),
        ("case_type", "Case Type"),
    ]
    
    for field_name, label in core_fields:
        expected = gt_json.get(field_name)
        if expected is None:
            continue
        expected = str(expected)
        
        extracted = combined_extracted.get(field_name)
        if extracted is None:
            extracted = data.get("application", {}).get(field_name)
            
        if extracted is not None:
            extracted = str(extracted)
        else:
            extracted = None
            
        source_pages = []
        if extracted is not None:
            source_pages = _find_source_pages_for_value(pages, extracted, field_name)
            
        status = "match"
        has_mismatch = False
        has_attention = False
        for vr in anomalies:
            rule_id = str(vr.get("rule_id", "")).upper()
            if field_name.upper() in rule_id or (field_name == "loan_id" and "APPLICATION_NUMBER" in rule_id):
                if "MISMATCH" in rule_id or "FAIL" in rule_id or "ERROR" in rule_id:
                    has_mismatch = True
                else:
                    has_attention = True
        
        if has_mismatch:
            status = "mismatch"
        elif has_attention:
            status = "attention"
        elif extracted is None:
            status = "attention"
            
        comparison_matrix["core_parameters"].append({
            "field_name": field_name,
            "label": label,
            "expected_value": expected,
            "extracted_value": extracted,
            "status": status,
            "source_pages": source_pages
        })
        
    # 2. DEMOGRAPHICS FOR EACH PERSON
    dem_fields = [
        ("applicant_name", "Applicant Name"),
        ("pan_number", "PAN Number"),
        ("date_of_birth", "Date of Birth"),
        ("phone_number", "Phone Number"),
        ("address", "Address (Permanent)"),
        ("pin_code", "Pin Code"),
        ("aadhaar_last4", "Aadhaar Last 4"),
        ("gender", "Gender"),
        ("father_name", "Father / Spouse Name"),
    ]
    
    # Sort people to guarantee primary applicant is always first, then coapplicants
    sorted_people = sorted(
        people.items(),
        key=lambda item: 0 if item[0] == "primary" or item[1].get("role") == "primary" else 1
    )
    
    comparison_matrix["applicants"] = []
    coapplicant_count = 0
    
    for person_id, profile in sorted_people:
        person_name = profile.get("applicant_name")
        if not person_name:
            continue
            
        role = profile.get("role") or ("primary" if person_id == "primary" else "coapplicant")
        role_mapped = "primary" if role == "primary" else ("guarantor" if role == "guarantor" else "co_applicant")
        
        # Calculate label
        if role_mapped == "primary":
            label = "Primary Applicant"
        elif role_mapped == "guarantor":
            label = "Guarantor"
        else:
            coapplicant_count += 1
            label = f"Co-applicant {coapplicant_count}"
            
        applicant_entry = {
            "applicant_role": role_mapped,
            "applicant_label": label,
            "person_name": person_name,
            "fields": []
        }
        
        has_any_mismatch = False
        has_any_attention = False
        
        for field_name, label_field in dem_fields:
            expected = profile.get(field_name)
            if expected is not None:
                expected = str(expected)
            else:
                if field_name == "father_name":
                    expected = profile.get("related_person_name")
                if expected is not None:
                    expected = str(expected)
                    
            if expected is None or expected == "None":
                continue
                
            extracted = None
            for p in pages:
                p_no = p.get("page_number")
                if p_no is not None and page_to_person.get(int(p_no)) == person_id:
                    extracted_fields = p.get("extracted_fields") or {}
                    val = extracted_fields.get(field_name)
                    if val is None:
                        if field_name == "applicant_name":
                            val = extracted_fields.get("name") or extracted_fields.get("borrower_name")
                        elif field_name == "date_of_birth":
                            val = extracted_fields.get("dob")
                        elif field_name == "phone_number":
                            val = extracted_fields.get("phone")
                        elif field_name == "pin_code":
                            val = extracted_fields.get("pincode")
                        elif field_name == "address":
                            val = extracted_fields.get("permanent_address") or extracted_fields.get("communication_address")
                    if val is not None:
                        extracted = str(val)
                        break
            
            if extracted is None and person_id == "primary":
                extracted = combined_extracted.get(field_name)
                if extracted is not None:
                    extracted = str(extracted)
                    
            source_pages = []
            if extracted is not None:
                source_pages = _find_source_pages_for_value(pages, extracted, field_name, person_id, page_to_person)
            elif expected is not None:
                source_pages = _find_source_pages_for_value(pages, expected, field_name, person_id, page_to_person)
                
            status = _get_field_status(person_id, field_name, expected, extracted, anomalies, page_to_person)
            
            if status == "mismatch":
                has_any_mismatch = True
            elif status == "attention":
                has_any_attention = True
                
            applicant_entry["fields"].append({
                "field_name": field_name,
                "label": label_field,
                "expected_value": expected,
                "extracted_value": extracted,
                "status": status,
                "source_pages": source_pages
            })
            
        profile["_computed_status"] = "mismatch" if has_any_mismatch else ("attention" if has_any_attention else "match")
        comparison_matrix["applicants"].append(applicant_entry)
            
    # 3. RELATIONSHIP GRAPH NODES
    node_lookup = {}
    primary_profile = people.get("primary")
    if primary_profile:
        name = primary_profile.get("applicant_name")
        status = primary_profile.get("_computed_status", "match")
        node_lookup[name.lower().strip()] = {
            "id": "p1",
            "name": name,
            "role": "primary",
            "relation_to_primary": None,
            "status": status
        }
        
    co_index = 0
    fam_index = 0
    for person_id, profile in sorted_people:
        name = profile.get("applicant_name")
        if not name:
            continue
        name_key = name.lower().strip()
        role = profile.get("role") or ("primary" if person_id == "primary" else "coapplicant")
        role_mapped = "primary" if role == "primary" else ("guarantor" if role == "guarantor" else "co_applicant")
        relation = profile.get("relationship") or (None if role_mapped == "primary" else "co-applicant")
        status = profile.get("_computed_status", "match")
        
        if name_key not in node_lookup:
            if role_mapped in ("co_applicant", "guarantor"):
                co_index += 1
                nid = f"c{co_index}"
            else:
                fam_index += 1
                nid = f"f{fam_index}"
                
            node_lookup[name_key] = {
                "id": nid,
                "name": name,
                "role": role_mapped,
                "relation_to_primary": relation if relation and relation.lower() != "self" else None,
                "status": status
            }
        else:
            if relation and relation.lower() != "self":
                node_lookup[name_key]["relation_to_primary"] = relation
            if status != "match":
                node_lookup[name_key]["status"] = status
                
        father = profile.get("father_name")
        if father and father.lower() != "none" and father.strip():
            father_key = father.lower().strip()
            if father_key not in node_lookup:
                fam_index += 1
                node_lookup[father_key] = {
                    "id": f"f{fam_index}",
                    "name": father,
                    "role": "family_member",
                    "relation_to_primary": "father" if role_mapped == "primary" else ("father-in-law" if relation == "WIFE" else "father"),
                    "status": "n/a"
                }
            elif role_mapped == "primary":
                node_lookup[father_key]["relation_to_primary"] = "father"
                
        mother = profile.get("mother_name")
        if mother and mother.lower() != "none" and mother.strip():
            mother_key = mother.lower().strip()
            if mother_key not in node_lookup:
                fam_index += 1
                node_lookup[mother_key] = {
                    "id": f"f{fam_index}",
                    "name": mother,
                    "role": "family_member",
                    "relation_to_primary": "mother" if role_mapped == "primary" else "mother",
                    "status": "n/a"
                }
            elif role_mapped == "primary":
                node_lookup[mother_key]["relation_to_primary"] = "mother"

    relationships = list(node_lookup.values())
    
    return {
        "comparison_matrix": comparison_matrix,
        "relationships": relationships
    }


@router.get("/applications/{application_id}")
def get_application_review(application_id: int) -> dict[str, Any]:
    """Return the full reviewer detail payload for one application."""
    init_db()
    data = _load_application_result(application_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Application not found")

    application = data["application"]
    product_type = str(application.get("product_type") or "LAP")
    anomalies = data["anomalies"]
    summary = summarize_for_display(anomalies)
    reviewer_summary = load_reviewer_summary(application_id)
    checklist_items = get_all_checklist_items(product_type)
    checklist_rows = build_checklist_status(checklist_items, data["pages"], anomalies)
    manual_items = get_human_review_items(product_type)
    ai_items = get_ai_checkable_items(product_type)
    failed_ai_snos = {anomaly.get("s_no") for anomaly in anomalies if anomaly.get("s_no") is not None}

    matrix_and_rels = _build_comparison_matrix_and_relationships(application_id, data)

    doc_pages_dict = data.get("document_pages") or {}
    documents = []
    for doc_type, pages_arr in doc_pages_dict.items():
        if not pages_arr:
            continue
        pages_arr = sorted([int(p) for p in pages_arr])
        first_page = pages_arr[0]
        if len(pages_arr) > 1:
            page_range = f"{pages_arr[0]}–{pages_arr[-1]}"
        else:
            page_range = str(pages_arr[0])
            
        doc_status = "Extracted"
        for vr in anomalies:
            vr_page = vr.get("page_number")
            if vr_page is not None and int(vr_page) in pages_arr:
                doc_status = "Flagged"
                break
                
        filename = f"{doc_type.lower().replace(' ', '_')}.pdf"
        documents.append({
            "name": filename,
            "type": doc_type,
            "pages": page_range,
            "status": doc_status,
            "firstPage": first_page
        })
    documents.sort(key=lambda d: d["firstPage"])

    return {
        **data,
        "summary": summary,
        "reviewer_summary": reviewer_summary,
        "manual_review_items": manual_items,
        "checklist": {
            "total": len(checklist_rows),
            "found": len([row for row in checklist_rows if row["status"] == "FOUND"]),
            "missing": len([row for row in checklist_rows if row["status"] == "MISSING"]),
            "not_checked": len([row for row in checklist_rows if row["status"] == "NOT_CHECKED"]),
            "rows": checklist_rows,
        },
        "ai_checklist": {
            "passed": len([item for item in ai_items if item.get("s_no") not in failed_ai_snos]),
            "total": len(ai_items),
        },
        "latest_decision": _load_latest_decision(application_id),
        "progress": get_progress(application_id),
        "comparison_matrix": matrix_and_rels["comparison_matrix"],
        "relationships": matrix_and_rels["relationships"],
        "documents": documents
    }


@router.get("/applications/{application_id}/source-pdf", summary="View the original PDF evidence")
def get_application_source_pdf(application_id: int) -> FileResponse:
    init_db()
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT file_path, original_filename
            FROM uploaded_files
            WHERE application_id = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    if row is None or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Source PDF not found")
    file_path = Path(str(row["file_path"]))
    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Source PDF not found")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=str(row["original_filename"] or file_path.name),
        content_disposition_type="inline",
    )


@router.get(
    "/applications/{application_id}/source-page/{page_number}",
    summary="Render one source PDF page for evidence review",
)
def get_application_source_page(application_id: int, page_number: int) -> Response:
    if page_number < 1:
        raise HTTPException(status_code=422, detail="Page number must be one or greater")
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT file_path FROM uploaded_files
            WHERE application_id = ?
            ORDER BY uploaded_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    if row is None or not row["file_path"]:
        raise HTTPException(status_code=404, detail="Source PDF not found")
    file_path = Path(str(row["file_path"]))
    if not file_path.is_file() or file_path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Source PDF not found")

    import fitz

    try:
        with fitz.open(file_path) as document:
            if page_number > document.page_count:
                raise HTTPException(status_code=404, detail="Source page not found")
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image_bytes = pixmap.tobytes("png")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Source PDF could not be rendered") from exc
    return Response(
        content=image_bytes,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/applications/{application_id}/reprocess", summary="Retry a stale or failed PDF pipeline")
def reprocess_application(application_id: int) -> dict[str, Any]:
    init_db()
    try:
        return queue_application_reprocess(application_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except ReprocessConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _authorize_job_control(request: Request, token: str | None) -> None:
    """Require a configured control token, or limit development mode to localhost."""
    configured = os.getenv("DMEF_JOB_CONTROL_TOKEN", "").strip()
    if configured:
        if token is None or not secrets.compare_digest(token, configured):
            raise HTTPException(status_code=403, detail="Invalid job-control credentials")
        return
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="Job control is restricted to localhost")


@router.post("/applications/{application_id}/pause", summary="Pause at the next safe boundary")
def pause_application(
    application_id: int,
    request: Request,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return request_control(application_id, "pause")
    except JobControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/applications/{application_id}/cancel", summary="Cancel at the next safe boundary")
def cancel_application(
    application_id: int,
    request: Request,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return request_control(application_id, "cancel")
    except JobControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/applications/{application_id}/resume", summary="Resume from the last checkpoint")
def resume_pipeline_application(
    application_id: int,
    request: Request,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return resume_application(application_id)
    except (JobControlError, ReprocessConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


@router.post("/applications/{application_id}/restart", summary="Start a new controlled attempt")
def restart_pipeline_application(
    application_id: int,
    request: Request,
    from_checkpoint: bool = True,
    refresh_cached_ocr: bool = False,
    control_token: str | None = Header(default=None, alias="X-Job-Control-Token"),
) -> dict[str, Any]:
    _authorize_job_control(request, control_token)
    try:
        return restart_application(
            application_id,
            from_checkpoint=from_checkpoint,
            refresh_cached_ocr=refresh_cached_ocr,
        )
    except ReprocessConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (LookupError, FileNotFoundError) as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc


@router.get("/applications/{application_id}/ocr-json")
def get_application_ocr_json(application_id: int) -> dict[str, Any]:
    """Return the OCR JSON payload for frontend download."""
    data = _load_application_result(application_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Application not found")
    saved = _load_saved_document_ocr_json(application_id)
    if saved is not None:
        return saved
    return build_ocr_document_json(
        application_id,
        data.get("pages") or [],
        page_events=data.get("page_events") or [],
    )


def _load_application_result(application_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        application = connection.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if application is None:
            return None
        uploaded_file = connection.execute(
            "SELECT * FROM uploaded_files WHERE application_id = ? ORDER BY uploaded_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        ground_truth = connection.execute(
            "SELECT * FROM ground_truth WHERE application_id = ? ORDER BY extracted_at DESC LIMIT 1",
            (application_id,),
        ).fetchone()
        anomalies = connection.execute("SELECT * FROM validation_results WHERE application_id = ?", (application_id,)).fetchall()
        pages = connection.execute("SELECT * FROM pages WHERE application_id = ? ORDER BY page_number", (application_id,)).fetchall()
        page_events = connection.execute(
            """
            SELECT page_number, total_pages, page_type, document_type, status,
                   elapsed_seconds, error, extracted_fields, completed_at
            FROM pipeline_page_events
            WHERE application_id = ?
            ORDER BY page_number
            """,
            (application_id,),
        ).fetchall()

    page_dicts = [_coerce_json_row(row) for row in pages]
    anomaly_dicts = [dict(row) for row in anomalies]
    document_pages: dict[str, list[int]] = {}
    for page in page_dicts:
        doc_type = page.get("document_type")
        if doc_type and doc_type != "Unknown":
            document_pages.setdefault(str(doc_type), []).append(page.get("page_number"))

    return {
        "application": dict(application),
        "uploaded_file": dict(uploaded_file) if uploaded_file else {},
        "ground_truth": dict(ground_truth) if ground_truth else {},
        "anomalies": anomaly_dicts,
        "pages": page_dicts,
        "page_events": [_coerce_json_row(row) for row in page_events],
        "documents_found": sorted(document_pages),
        "document_pages": document_pages,
        "documents_missing": [
            anomaly.get("document_type")
            for anomaly in anomaly_dicts
            if str(anomaly.get("rule_id", "")).startswith("MISSING_DOC") and anomaly.get("document_type")
        ],
    }


def _load_latest_decision(application_id: int) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT id, application_id, decision, reviewer_note, decided_at
            FROM reviewer_decisions
            WHERE application_id = ?
            ORDER BY decided_at DESC
            LIMIT 1
            """,
            (application_id,),
        ).fetchone()
    return dict(row) if row else None


def _coerce_json_row(row: Any) -> dict[str, Any]:
    payload = dict(row)
    raw_fields = payload.get("extracted_fields")
    try:
        decoded = json.loads(raw_fields) if raw_fields else {}
    except (TypeError, json.JSONDecodeError):
        decoded = {}
    payload["extracted_fields"] = decoded if isinstance(decoded, dict) else {}
    return payload


def _load_saved_document_ocr_json(application_id: int) -> dict[str, Any] | None:
    path = Path("data/processed") / f"application_{application_id}" / "document_ocr_data.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
