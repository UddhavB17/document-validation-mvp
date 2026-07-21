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
