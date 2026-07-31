# DMEF (Document Matching Early Finder) - Project Context

DMEF is an exception-based document validation and matching system designed for loan-file validation. It processes large multi-page PDF files, classifies each page, performs Optical Character Recognition (OCR), extracts key fields, runs deterministic checks against borrower ground-truth/checklist rules, aggregates exceptions, and presents them in a reviewer-facing Next.js dashboard.

---

## 1. High-Level Architecture & Tech Stack

The project is structured as a decoupled web application with a Python backend and a TypeScript/Next.js frontend:

```
┌────────────────────────────────────────────────────────┐
│                      Next.js UI                        │
│          (TypeScript, Tailwind CSS, TanStack Query)     │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP REST APIs
                           ▼
┌────────────────────────────────────────────────────────┐
│                     FastAPI Backend                    │
│                     (Python 3.11.x)                    │
└──────┬───────────────────┬──────────────────────┬──────┘
       │ Reads/Writes      │ Calls                │ Extracts
       ▼                   ▼                      ▼
┌──────────────┐     ┌───────────┐         ┌─────────────┐
│    SQLite    │     │ PaddleOCR │         │ LLM Engines │
│ (dmef.db /   │     │ (PyMuPDF) │         │ (Ollama,    │
│ WAL mode)    │     └───────────┘         │ Gemini, etc)│
└──────────────┘                           └─────────────┘
```

- **Backend**: FastAPI web framework running on Python 3.11.x.
- **Database**: SQLite database (`data/dmef.db`) in WAL (Write-Ahead Logging) mode, with automated migrations, schema initialisation, and dynamic settings seeding.
- **Text & OCR Extraction**: PyMuPDF (`fitz`) for digital layout and text extraction; PaddleOCR/PaddlePaddle for scanned page OCR.
- **LLM Integrations**: Ollama, OpenAI, or Gemini for page classification and result summaries using Token-Oriented Object Notation (TOON) schemas.
- **Frontend**: Next.js 14 App Router, React, Tailwind CSS, TanStack Query (React Query) for state management/caching, and Zod for client-side API validation.

---

## 2. Directory Structure

```
document-validation-mvp/
├─ .agents/
│  └─ AGENTS.md               # Project-scoped agent rules & instructions
├─ data/                      # SQLite databases, processing caches, reports
├─ database/                  # SQLite schema definitions & models
│  ├─ db.py                   # DB connection setup and seeding
│  └─ models.py               # SQLite tables & Pydantic data schemas
├─ docs/                      # Technical documentation and specifications
├─ frontend/                  # Next.js 14 frontend application
│  ├─ app/                    # UI routers (upload, worklist, application, settings)
│  ├─ components/             # Reusable UI widgets
│  ├─ generated/              # Generated TypeScript API contracts
│  └─ lib/                    # API client layer (React Query & Fetch)
├─ routes/                    # FastAPI endpoint controllers
├─ services/                  # Backend business logic services
├─ tests/                     # Comprehensive pytest test suite
├─ main.py                    # FastAPI entrypoint
├─ requirements.txt           # Python dependency file (Python 3.11.x)
├─ run_local.ps1              # Start backend and frontend dev servers
├─ setup.ps1                  # PowerShell installation & setup script
└─ stop_local.ps1             # Local environment shutdown helper
```

---

## 3. Database Schema

The SQLite schema initialized in [database/models.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/database/models.py) consists of the following tables:

*   **`applications`**: Represents a loan application run. Stores the `loan_id`, applicant/co-applicant names, status, and LLM-generated summaries.
*   **`uploaded_files`**: Tracks individual PDF files uploaded to an application, caching physical file parameters (size, page counts).
*   **`intake_packages`** & **`intake_documents`**: Handles document packages, supporting ZIP-compressed intake schemas.
*   **`ground_truth`**: Stores borrower reference data (typically extracted from trusted sources or Graviton pages) used to evaluate verification matches.
*   **`pages`**: The main page-level processing ledger. Stores page type (`digital` vs. `scanned`), image paths, raw OCR/digital text, classification confidence, predicted document type, and individual page extracted fields.
*   **`validation_results`**: Stores the output of individual checklist checks (rule ID, severity, expected/found values, and failure descriptions).
*   **`reviewer_decisions`**: Logs reviewer actions (`ACCEPT`, `OVERRIDE`, `REQUEST_DOCS`) and matching reviewer notes.
*   **`exceptions`**: Structured business exceptions aggregated from the results stream.
*   **`pipeline_progress`** & **`pipeline_jobs`**: Orchestrates backend processing states, tracking overall progress percentages and retry metadata.
*   **`pipeline_page_events`**: Page-level performance and telemetry logs (execution times, page status).
*   **`classification_review_log`**: Logs differences and details of page classification checks.
*   **`document_verification_reports`**: Caches the final JSON reports.
*   **`reviewer_summaries`**: Caches compiled dashboard summaries.
*   **`system_settings`**: Dynamically seeded key-value operational configuration table.

---

## 4. End-to-End Processing Pipeline

The backend core processing pipeline runs inside [services/pipeline.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/pipeline.py). When a PDF is uploaded, it transitions through these stages:

```
[ Upload PDF ]
      │
      ▼
[ PDF Structure Triage ] ──► Detect digital text pages vs. scanned image pages
      │
      ▼
[ Text & OCR Engine ]   ───► If digital: Extract text & filter XML signatures
      │                      If scanned: Render page to image & run PaddleOCR
      ▼
[ Classification ]       ──► 1. Match type using keywords (e.g. "PAN Card")
      │                      2. If low confidence: Structured LLM classification (TOON)
      ▼
[ Field Extraction ]     ──► Extract fields (e.g. PAN number, DOB) via regex & parsers
      │
      ▼
[ Checklist Evaluation ] ──► Compare extracted values against ground_truth
      │                      Runs validation rules & business checks
      ▼
[ Aggregation & Report ] ──► Populate validation_results and generate summaries
      │                      Creates JSON report; updates UI via long-polling
```

### Key Operations & Subservices:

1.  **PDF Processing (`pdf_processor.py`)**: Evaluates PDF structures, counting digital vs scanned pages, and rendering scanned pages to PNG format.
2.  **Text Extraction (`text_extractor.py`)**: Performs digital text retrieval while filtering out noisy embedded blocks (e.g., XML signature tags).
3.  **OCR Processing (`ocr_engine.py`)**: Runs PaddleOCR to process scanned pages. Utilises soft and hard timeouts to prevent execution locks on extremely busy pages.
4.  **Keyword Classifier (`document_classifier.py`)**: Maps text content to document types using keyword-matching dictionaries.
5.  **LLM Classifier (`llm_page_classifier.py`)**: If keyword confidence falls below threshold (`0.85`), the pipeline runs a structured LLM classifier using Token-Oriented Object Notation (TOON) parsing.
6.  **Field Extractor (`field_extractor.py`)**: Detects and extracts specific details (such as dates, account numbers, names, PAN numbers) from raw page strings.
7.  **Checklist Engine (`checklist_engine.py`)**: Runs the business rules matching extracted details against borrower files and system settings.
8.  **Reprocessing (`reprocessing.py`)**: Allows recovering, resuming, or retrying aborted or partially completed pipeline jobs.

---

## 5. System Configuration Settings

DMEF features a dynamic configurations dashboard that binds options to the `system_settings` table. Key configurations include:

*   `llm_enabled`: Toggles active LLM verification features.
*   `llm_provider`: Specifies the LLM engine (`ollama`, `openai`, `gemini`).
*   `llm_model`: Name of the target model (default: `llama3.2`).
*   `min_confidence`: Minimum confidence score required to auto-classify pages (default: `0.85`).
*   `required_fields.<document_type>`: Configurable JSON arrays listing required validation fields for each document type (e.g. PAN, Aadhaar, Salary Slip, NACH Form, Bank Statement).

DMEF also supports runtime configuration profiles defined in [services/config.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/config.py):
*   **Fast**: Low timeouts, relaxed confidence boundaries.
*   **Balanced**: Recommended default thresholds for OCR and LLM classification.
*   **Strict**: High OCR confidence boundaries and aggressive document mapping checks.

---

## 6. Frontend App Structure & Layout

The Next.js 14 frontend lives under `frontend/` and contains these main screens:

1.  **Upload (`/upload`)**: Allows importing PDF loan files. Supports automatic verification workflows (parsing layout, classifying ownership automatically) and mapped-page verification workflows (user defines page ranges for specific documents).
2.  **Worklist (`/worklist`)**: Displays processed, processing, and failed applications with live polling status. Highlights total business issues and technical processing warnings for each application.
3.  **Review (`/applications/[id]`)**: The central workspace for reviewing exceptions.
    *   **Collapsible Sidebar Layout**: Maximises space for viewing documents.
    *   **Evidence Viewer side panel**: Displays a stacked multi-page document view with page tags and concatenated OCR text.
    *   **Checklist Table**: Features interactive page buttons that automatically scroll to and center the corresponding evidence in the viewer. Shows severity-coded badges (`HIGH`, `MEDIUM`, `LOW`) for anomalies.
    *   **Reviewer Decisions**: Form for reviewers to input their final verdict (`ACCEPT`, `OVERRIDE`, `REQUEST_DOCS`).
4.  **My Activity (`/activity`)**: Summarises decisions recorded today.
5.  **Settings (`/settings`)**: Direct database-bound Operations Settings panel for managing system configurations, required fields, and LLM providers.

---

## 7. Testing Suite

The pytest suite in `tests/` covers the entire end-to-end backend logic, including:
-   **Unit Tests**: Date normalization, file validation, text extraction, OCR engine timeouts.
-   **Integration Tests**: Upload endpoints, pipeline workflows, checklist matching rules, LLM TOON parser outputs.
-   **Execution**: Run with `pytest` inside the active Python 3.11 virtual environment.
