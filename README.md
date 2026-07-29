# Document Validation MVP

Private collaboration repo for DMEF, the Document Matching Early Finder.

## Goal

Build an exception-based document validation workflow:

1. Upload a loan-file PDF.
2. Validate the file.
3. Extract ground-truth data from digital text pages.
4. Preprocess scanned pages.
5. Run OCR.
6. Classify documents.
7. Extract document fields.
8. Match extracted fields against checklist JSON from the system.
9. Aggregate exceptions.
10. Show only flagged items for human review.

## App Structure

- `main.py`: FastAPI backend.
- `routes/`: upload, verification, decision, and reviewer data APIs.
- `services/`: PDF processing, OCR, classification, checklist evaluation, reports, LLM integration, and review helpers.
- `database/`: SQLite schema and connection helpers.
- `frontend/`: Next.js 14 App Router UI with TypeScript, Tailwind CSS, TanStack Query, and Zod.

The Python UI has been removed. The browser interface is now the Next.js app in `frontend/`.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11.x | Required because PaddleOCR/PaddlePaddle are not supported here on Python 3.12+ |
| Node.js | 20+ | Runs the Next.js UI |
| Git | any | Source control |

## Fast Windows Setup

From PowerShell in the project root:

```powershell
.\setup.ps1
.\run_local.ps1
```

`setup.ps1` creates the Python virtual environment, installs backend and frontend dependencies, creates `.env` if needed, prepares local folders, and runs the local health check.

`run_local.ps1` starts both the FastAPI backend and the Next.js UI.

## Manual Setup

Create and activate the Python environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
cd frontend
npm.cmd install
cd ..
```

Create environment config:

```powershell
copy .env.example .env
```

## Run Locally

Default config (`.env.example`) is **full power**: hybrid OCR with PP-StructureV3
escalation and optional LLM helpers enabled. On ~8GB machines only, set
`DMEF_LOW_MEMORY=true` or use `scripts/start_mvp.sh` to force the light path.

Terminal 1, backend:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, frontend:

```powershell
cd frontend
npm.cmd run dev -- -p 3000
```

Open:

- UI: `http://localhost:3000`
- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

## Main Screens

- Upload: PDF upload, mapped verification, and partner JSON intake.
- Worklist: reviewer queue and status filters.
- Application Review: verdict, reviewer summary, anomalies, checklist, manual review, decisions, and OCR JSON download.
- My Activity: decisions recorded today.

For the trusted-company-data workflow, open **Document Intake → Automatic
Verification**. Upload a PDF (or prepare a ZIP) and paste trusted people data
based on `docs/mapped_manifest.example.json`. Leave `document_index` empty to
have the shared OCR/classification pipeline identify document types, group
continuation pages, and infer applicant ownership automatically.

Automatic mode processes every page, uses embedded text where available and
OCR for scans, predicts each document type, and assigns the document to a person
using extracted identity evidence. Match/mismatch decisions remain
deterministic. Low-confidence or ambiguous ownership is surfaced for manual
review instead of being silently guessed. Explicit one-based `pages` mappings
remain supported as an override when a trusted index is available.

## Structured OCR

Scanned pages use deterministic hybrid OCR routing. A lightweight PaddleOCR
text-detection/recognition pass supplies the existing classifier. Its resolved
document type is then looked up in `data/document_type_registry.json`:

- `ocr_route: "fast"` retains plain text, confidence, and bounding boxes.
- `ocr_route: "structured"` runs PP-StructureV3 and retains reading-order
  layout regions plus table HTML/Markdown in `structured_content`.
- Missing `ocr_route` values default to `structured`. `has_tabular_data: true`
  or `multi_column: true` always forces the structured route.
- Fast results below `OCR_FAST_PATH_MIN_CONFIDENCE` (default `0.85`) escalate
  to PP-StructureV3. Escalations and per-page route timing are recorded in
  `ocr_route_events`; `get_ocr_route_metrics(document_id)` aggregates time by
  route.

To add another fast-path type, edit its registry entry without changing code:

```json
{
  "type": "Example Declaration",
  "ocr_route": "fast",
  "has_tabular_data": false,
  "multi_column": false
}
```

The OCR models are lazy-loaded and make no external inference calls. Model
weights must be cached locally for a zero-egress deployment. On an RTX 3050
with 6 GB VRAM, keeping the lightweight OCR and full PP-StructureV3 pipelines
resident together can exhaust memory, especially with table/seal modules.
Prefer route-homogeneous batches or separate workers with one model family per
GPU; otherwise unload between batches. Per-page load/unload is usually too
expensive. Table and seal modules can be controlled through the
`PADDLE_STRUCTURE_*` settings in `.env`.

## Trusted JSON + Mapped-Page Verification

For deterministic company workflow, open `Document Intake -> Mapped Verification`. Upload the PDF and paste a manifest based on `docs/mapped_manifest.example.json`.

The `pages` values are one-based PDF page numbers. The mapped path renders and OCRs only those pages, uses the supplied `document_type` instead of predicting it, compares supported fields against trusted reference data, and does not use an LLM to make match/mismatch decisions.

The same workflow is available through `POST /upload/mapped` as multipart form data:

- `file`: the PDF
- `manifest`: the JSON manifest encoded as a string

Poll the returned `progress_url`, then retrieve the final deterministic summary from the returned `summary_url`.

## Tests

With the Python environment active:

```powershell
pytest
```

Frontend checks:

```powershell
cd frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
```

## Data Safety

Use only dummy or approved sample documents. Uploaded files, extracted pages, generated reports, local databases, and `.env` files are ignored by Git.
