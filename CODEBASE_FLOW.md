# DMEF Codebase Flow Guide

This document explains how the Document Matching Early Finder codebase is connected, what happens behind the scenes, and where the flow starts and ends.

## Big Picture

DMEF is split into two running processes:

1. Streamlit frontend
   - Starts from `app.py`
   - Shows the Upload and Worklist screens
   - Sends HTTP requests to the backend
   - Reads processed results from SQLite for display

2. FastAPI backend
   - Starts from `main.py`
   - Exposes upload and reviewer-decision APIs
   - Saves uploaded files
   - Runs the PDF validation pipeline in the background
   - Writes results into SQLite

The main database is SQLite, normally at:

```text
data/dmef.db
```
That path is controlled by:

```text
.env -> DATABASE_PATH=data/dmef.db
```

## Runtime Starting Points

### Backend Start

Command:

```powershell
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Starting file:

```text
main.py
```

What `main.py` does:

1. Loads environment variables with `load_dotenv()`.
2. Creates the FastAPI app.
3. Initializes the database schema on startup.
4. Marks stuck `processing` applications as `pipeline_failed` if the server was restarted.
5. Registers API routers:
   - `routes/upload.py`
   - `routes/decisions.py`
6. Exposes `/health`.

Backend entry flow:

```text
main.py
  -> database.models.initialize_schema()
     -> database.db.init_db()
        -> creates SQLite tables from database/models.py
  -> app.include_router(upload.router)
  -> app.include_router(decisions.router)
```

### Frontend Start

Command:

```powershell
python -m streamlit run app.py
```

Starting file:

```text
app.py
```

What `app.py` does:

1. Configures the Streamlit page.
2. Hides default Streamlit menu/toolbars.
3. Creates the sidebar navigation.
4. Routes the user to:
   - Upload page: `views/upload_view.py`
   - Worklist page: `pages/worklist_page.py`

Frontend entry flow:

```text
app.py
  -> render_upload_page() from views/upload_view.py
  OR
  -> render_worklist_page() from pages/worklist_page.py
```

## Main User Flow: Upload PDF To Final Review

This is the most important flow in the project.

```text
User opens Streamlit
  -> app.py
  -> views/upload_view.py
  -> POST /upload
  -> routes/upload.py
  -> services/file_validator.py
  -> database/db.py
  -> background task
  -> services/pipeline.py
  -> PDF/text/OCR/classification/extraction/checklist/reporting
  -> database tables updated
  -> Streamlit reads results
  -> views/results_view.py
  -> reviewer decision
  -> routes/decisions.py
```

## Step By Step: PDF Upload

### 1. User opens Upload page

File:

```text
views/upload_view.py
```

Function:

```text
render_upload_page()
```

This renders two tabs:

1. PDF Upload
2. Partner JSON Intake

For normal PDF upload, the user enters:

- Loan ID
- Applicant Name
- Co-applicant Name
- Product Type
- Branch
- PDF file

When the user clicks Submit:

```text
render_upload_page()
  -> _submit_upload_form()
```

### 2. Frontend validates the file lightly

File:

```text
services/file_validator.py
```

Function:

```text
validate_upload(filename, file_size_bytes)
```

This checks:

- File has a name
- File extension is `.pdf`
- File is not over 100 MB

This is only a frontend-level check before sending the file to the backend.

### 3. Streamlit sends the file to FastAPI

File:

```text
views/upload_view.py
```

Function:

```text
_submit_upload_form()
```

It sends a POST request to:

```text
POST http://localhost:8000/upload
```

The backend route lives in:

```text
routes/upload.py
```

### 4. Backend receives the upload

File:

```text
routes/upload.py
```

Function:

```text
upload_file()
```

What happens:

1. Initializes the database.
2. Creates `data/uploads` if needed.
3. Reads the uploaded file bytes.
4. Saves the file as:

```text
data/uploads/<loan_id>_<timestamp>.pdf
```

5. Runs full file validation.
6. Inserts an application row.
7. Inserts an uploaded file row.
8. Writes an audit log row.
9. Sets application status to `processing`.
10. Queues the heavy pipeline as a background task.
11. Returns immediately to the UI.

This is why upload can look fast while processing continues behind the scenes.

### 5. Backend validates the PDF deeply

File:

```text
services/file_validator.py
```

Function:

```text
validate_file(file_path, file_size_bytes)
```

This checks:

- File extension is PDF
- File is not empty
- File is not larger than 100 MB
- PDF is readable by PyMuPDF
- PDF is not password protected
- PDF has pages
- Counts digital pages and scanned pages

The page type logic is:

```text
if page.get_text().strip() has more than 50 characters:
    page is digital
else:
    page is scanned
```

### 6. Background task starts the pipeline

File:

```text
routes/upload.py
```

Function:

```text
_run_pipeline_task()
```

It calls:

```text
services.pipeline.run_pipeline()
```

If the pipeline crashes, this function catches the exception and sets:

```text
applications.status = pipeline_failed
```

It also writes the failure into `audit_log`.

## The Pipeline: What Happens Behind The Back

Main file:

```text
services/pipeline.py
```

Main function:

```text
run_pipeline(pdf_path, application_id, ...)
```

Pipeline order:

```text
run_pipeline()
  -> process_pdf_structure()
  -> _extract_digital_text_by_page()
  -> extract_ground_truth()
  -> _build_page_records()
     -> run_ocr_on_page() for scanned pages
     -> classify_page()
     -> extract_fields()
  -> _save_ground_truth()
  -> _save_pages()
  -> _update_uploaded_file_counts()
  -> _run_checklist_with_fallback()
     -> run_checks()
  -> aggregate()
     -> save_aggregation()
  -> summarize_exceptions()
  -> optional generate_explanation()
  -> save_report_json()
  -> log_action()
```

### 1. PDF structure detection

File:

```text
services/pdf_processor.py
```

Function:

```text
process_pdf_structure(pdf_path, output_dir)
```

This opens the PDF and loops page by page.

For each page:

1. Calls `detect_page_type(page)`.
2. Marks the page as `digital` or `scanned`.
3. If scanned, renders the page into a PNG image.

Scanned page images are written under:

```text
data/processed/application_<application_id>/pages/
```

Output from this step looks like:

```python
{
    "total_pages": 10,
    "digital_pages": 3,
    "scanned_pages": 7,
    "pages": [
        {"page_number": 1, "page_type": "digital", "image_path": None},
        {"page_number": 4, "page_type": "scanned", "image_path": "...png"},
    ],
}
```

### 2. Digital text extraction

Files:

```text
services/pipeline.py
services/text_extractor.py
```

Functions:

```text
_extract_digital_text_by_page()
extract_digital_text()
extract_ground_truth()
```

Digital pages contain selectable text. The app extracts that text directly with PyMuPDF, without OCR.

`extract_ground_truth()` reads all digital pages and extracts fields such as:

- applicant_name
- pan_number
- loan_amount
- phone
- address
- product_type
- raw_text

This ground truth becomes the system-side information used to compare scanned documents against the loan application.

### 3. Scanned page OCR

Files:

```text
services/ocr_engine.py
services/preprocessing.py
```

Function:

```text
run_ocr_on_page(image_path)
```

This runs only for scanned pages.

Flow:

```text
run_ocr_on_page()
  -> check_readability()
  -> if blurry, return unreadable result
  -> PaddleOCR model reads the image
  -> OCR text and confidence are extracted
```

Important detail:

`services/ocr_engine.py` creates the PaddleOCR model at module import time. That means when the backend first imports OCR code, model loading can take time. Once loaded, the model is reused for later pages.

If PaddleOCR is missing or fails to load:

```text
ocr_model = None
```

Then OCR returns an error-like result instead of crashing the whole app.

### 4. Page classification

File:

```text
services/document_classifier.py
```

Function:

```text
classify_page(text)
```

This looks at extracted text and decides what kind of document the page is.

Examples:

- PAN Card
- Aadhaar
- Passport
- Driving License
- Voter ID
- Sanction Letter
- Loan Agreement
- NACH Form
- CRIF Report
- Bank Statement
- Salary Slip
- Property Document
- Application Form
- None

The classifier is rule-based. It checks keywords and patterns in priority order.

Example:

```text
If text contains a PAN-like pattern, classify as PAN Card.
If text contains Aadhaar/UIDAI indicators, classify as Aadhaar.
If nothing matches, return document_type = None.
```

`pipeline.py` normalizes some classifier outputs:

```text
PAN Card -> PAN
None -> Unknown
```

### 5. Field extraction

File:

```text
services/field_extractor.py
```

Function:

```text
extract_fields(document_type, text)
```

Once a page is classified, the app extracts fields based on the document type.

Examples:

- PAN:
  - pan_number
  - applicant_name
  - dob

- Aadhaar:
  - aadhaar_number
  - applicant_name
  - dob

- Sanction Letter:
  - loan_amount
  - tenure
  - emi
  - roi
  - applicant_name

- Bank Statement:
  - account_number
  - statement_period_start
  - statement_period_end

The field extractor is regex/rule based. It does not use an LLM.

### 6. Page records are created

File:

```text
services/pipeline.py
```

Function:

```text
_build_page_records()
```

For every page, the pipeline creates a record with:

- page_number
- page_type
- image_path
- is_readable
- ocr_text
- ocr_confidence
- document_type
- classification_confidence
- extracted_fields

These records are saved to the `pages` table.

### 7. Ground truth and pages are saved

File:

```text
services/pipeline.py
```

Functions:

```text
_save_ground_truth()
_save_pages()
_update_uploaded_file_counts()
```

Database tables updated:

```text
ground_truth
pages
uploaded_files
```

Before saving, old rows for the same `application_id` are deleted so reruns do not duplicate rows.

### 8. Checklist is loaded

Files:

```text
services/checklist_service.py
data/checklist.json
```

Functions:

```text
load_checklist()
get_ai_checkable_items()
get_human_review_items()
```

The checklist tells the system what it should validate for the product type.

There are two kinds of items:

1. AI-checkable items
   - The system can automatically check them.

2. Human review items
   - The UI shows them to the reviewer, but the app does not automatically validate them.

### 9. Checklist checks run

File:

```text
services/checklist_engine.py
```

Main function:

```text
run_checks(pages, ground_truth, system_data, product_type)
```

The checklist engine checks things like:

- Required document is present
- Any one document from a group is present
- Extracted field matches system data
- Bank statement date is recent enough
- PAN format is valid
- PAN number matches ground truth
- Name match is acceptable
- OCR confidence is acceptable
- Page is classified

When something fails, it creates an anomaly with:

- rule_id
- severity
- document_type
- expected_value
- found_value
- page_number
- reason

An anomaly is a validation issue that the reviewer may need to look at.

### 10. Exceptions are aggregated

File:

```text
services/exception_aggregator.py
```

Function:

```text
aggregate(pages, anomalies, ground_truth, application_id)
```

This function:

1. Sorts anomalies by severity.
2. Finds documents found.
3. Finds missing documents.
4. Finds pages with issues.
5. Decides final status.

Final status rules:

```text
No anomalies -> CLEAN
Any HIGH anomaly -> CRITICAL
Otherwise -> NEEDS_REVIEW
```

Then it saves results into:

```text
validation_results
applications.status
```

### 11. Summary and report are generated

Files:

```text
services/llm_service.py
services/report_generator.py
```

Pipeline calls:

```text
summarize_exceptions()
save_report_json()
```

The app always creates a normal summary from anomalies.

It only calls the local LLM if enabled through:

```text
ENABLE_LLM_SUMMARY=true
```

JSON reports are saved under:

```text
data/reports/
```

Excel reports are generated later only when the user clicks the download button in the UI.

## Partner JSON Flow

The app also supports a second input path where a partner provides OCR/extraction JSON directly.

Frontend:

```text
views/upload_view.py
  -> Partner JSON Intake tab
  -> _submit_partner_json()
```

Backend:

```text
routes/upload.py
  -> ingest_partner_json()
  -> services.pipeline.run_partner_json_pipeline()
```

This skips PDF parsing and OCR.

Flow:

```text
Partner JSON
  -> run_partner_json_pipeline()
  -> _build_partner_pages()
  -> run_checks()
  -> aggregate()
  -> save report
  -> display results
```

Use this path when OCR/text extraction happens outside this app.

## Results Display Flow

File:

```text
views/results_view.py
```

Main function:

```text
render_application_results(application_id)
```

It loads data from SQLite:

```text
applications
uploaded_files
ground_truth
validation_results
pages
```

Then it displays:

- Loan file title
- Ground truth fields
- Summary metrics
- AI summary, if available
- Anomalies table
- OCR used true/false
- Manual review checklist
- Documents found/missing
- Pages requiring review
- Excel report download button
- Reviewer decision form

Important helper:

```text
_load_application_result(application_id)
```

This is where the UI pulls together all stored backend results.

## Worklist Flow

File:

```text
pages/worklist_page.py
```

Main function:

```text
render_worklist_page()
```

It loads all applications with:

```text
_load_worklist()
```

That query joins:

```text
applications
validation_results
```

It shows each application with:

- Loan ID
- Applicant
- Product
- Status
- Issue count
- Upload time

When the user selects one and clicks Show Results:

```text
render_worklist_page()
  -> render_result_status_guard()
  -> render_application_results(application_id)
```

## Processing Status Guard

File:

```text
views/status_helpers.py
```

Purpose:

The upload API returns before OCR and validation are finished. This helper checks the current application status before trying to show results.

Expected statuses:

- `processing`: still running
- `pipeline_failed`: pipeline failed
- `CLEAN`: processing finished with no issues
- `NEEDS_REVIEW`: processing finished with non-high issues
- `CRITICAL`: processing finished with high issues
- `verified`: reviewer accepted
- `verified_with_override`: reviewer overrode issues
- `incomplete`: reviewer requested documents

## Reviewer Decision Flow

Frontend:

```text
views/results_view.py
  -> _render_reviewer_decision()
```

Backend:

```text
routes/decisions.py
  -> create_decision()
```

When the reviewer submits a decision:

1. UI sends POST `/decision`.
2. Backend validates the decision.
3. Backend inserts into `reviewer_decisions`.
4. Backend updates `applications.status`.
5. Backend logs the action in `audit_log`.

Decision to status mapping:

```text
ACCEPT -> verified
OVERRIDE -> verified_with_override
REQUEST_DOCS -> incomplete
```

## Database Tables

Defined in:

```text
database/models.py
```

Connection helper:

```text
database/db.py
```

### applications

Main loan/application record.

Important fields:

- id
- loan_id
- applicant_name
- product_type
- branch
- status
- llm_summary
- created_at

### uploaded_files

Tracks uploaded PDF details.

Important fields:

- application_id
- file_path
- original_filename
- file_size_kb
- total_pages
- digital_pages
- scanned_pages

### ground_truth

Stores extracted data from digital pages and user/system data.

Important fields:

- application_id
- applicant_name
- pan_number
- loan_amount
- phone
- address
- product_type
- raw_json

### pages

Stores per-page extraction/classification results.

Important fields:

- application_id
- page_number
- page_type
- image_path
- is_readable
- ocr_text
- ocr_confidence
- document_type
- classification_confidence
- extracted_fields

### validation_results

Stores anomalies/checklist failures.

Important fields:

- application_id
- rule_id
- severity
- document_type
- expected_value
- found_value
- page_number
- reason
- status

### reviewer_decisions

Stores final human reviewer decisions.

Important fields:

- application_id
- decision
- reviewer_note
- decided_at

### audit_log

Stores important backend events.

Examples:

- file uploaded
- pipeline completed
- pipeline failed
- reviewer decision made

## Directory Purpose

```text
app.py
```

Streamlit app entry point.

```text
main.py
```

FastAPI app entry point.

```text
routes/
```

Backend API endpoints.

```text
views/
```

Streamlit UI components.

```text
pages/
```

Streamlit page-level views, currently the worklist.

```text
services/
```

Business logic: validation, PDF processing, OCR, classification, extraction, checklist checks, reporting.

```text
database/
```

SQLite schema and connection helpers.

```text
data/
```

Runtime data: database, checklist JSON, uploads, processed images, reports.

```text
tests/
```

Automated tests for API routes, services, UI helpers, pipeline, and reports.

```text
docs/
```

Architecture/user-flow images.

## File-To-File Flow Map

### Normal PDF upload

```text
app.py
  -> views/upload_view.py
     -> services/file_validator.validate_upload()
     -> requests.post(API_BASE_URL + "/upload")
        -> main.py
           -> routes/upload.py upload_file()
              -> services/file_validator.validate_file()
              -> database.db.get_connection()
              -> background_tasks.add_task(_run_pipeline_task)
                 -> services.pipeline.run_pipeline()
                    -> services.pdf_processor.process_pdf_structure()
                    -> services.text_extractor.extract_ground_truth()
                    -> services.ocr_engine.run_ocr_on_page()
                       -> services.preprocessing.check_readability()
                       -> services.preprocessing.preprocess_image()
                    -> services.document_classifier.classify_page()
                    -> services.field_extractor.extract_fields()
                    -> services.checklist_engine.run_checks()
                       -> services.checklist_service.get_ai_checkable_items()
                    -> services.exception_aggregator.aggregate()
                       -> services.exception_aggregator.save_aggregation()
                    -> services.llm_service.summarize_exceptions()
                    -> services.report_generator.build_report()
                    -> services.report_generator.save_report_json()
                    -> services.audit_service.log_action()
     -> views/status_helpers.render_result_status_guard()
     -> views/results_view.render_application_results()
```

### Worklist review

```text
app.py
  -> pages/worklist_page.py
     -> _load_worklist()
        -> database.db.get_connection()
     -> views.status_helpers.render_result_status_guard()
     -> views.results_view.render_application_results()
        -> _load_application_result()
           -> database.db.get_connection()
```

### Reviewer decision

```text
views/results_view.py
  -> requests.post(API_BASE_URL + "/decision")
     -> main.py
        -> routes/decisions.py create_decision()
           -> database.db.get_connection()
           -> services.audit_service.log_action()
```

### Partner JSON intake

```text
views/upload_view.py
  -> _submit_partner_json()
     -> POST /upload/json
        -> routes/upload.py ingest_partner_json()
           -> services.pipeline.run_partner_json_pipeline()
              -> _build_partner_pages()
              -> services.checklist_engine.run_checks()
              -> services.exception_aggregator.aggregate()
              -> services.report_generator.save_report_json()
```

## Where The Flow Ends

For a normal PDF upload, the flow ends in these places:

1. Database
   - `applications.status` contains the final status.
   - `pages` contains per-page OCR/classification/extraction results.
   - `ground_truth` contains digital-page extracted fields.
   - `validation_results` contains anomalies.
   - `audit_log` contains events.

2. Reports
   - JSON report saved to `data/reports/`.
   - Excel report created on demand when the reviewer clicks download.

3. UI
   - `views/results_view.py` reads the database and shows final output to the user.

4. Reviewer decision
   - If reviewer submits a decision, `routes/decisions.py` updates `reviewer_decisions` and final application status.

## Mental Model

Think of the app like this:

```text
Streamlit is the face.
FastAPI is the gate.
Pipeline is the engine.
SQLite is the memory.
Checklist is the rulebook.
Results view is the final report screen.
```

The core processing path is:

```text
Upload PDF
  -> Save file
  -> Validate PDF
  -> Split pages into digital/scanned
  -> Extract digital ground truth
  -> OCR scanned pages
  -> Classify each page
  -> Extract document fields
  -> Run checklist rules
  -> Save anomalies
  -> Show reviewer results
  -> Reviewer accepts/overrides/requests docs
```
