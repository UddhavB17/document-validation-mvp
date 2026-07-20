# Document Validation MVP

Private collaboration repo for DMEF, the Document Matching Early Finder.

## Goal

Build an exception-based document validation workflow:

1. Upload loan-file PDF.
2. Validate the file.
3. Extract ground-truth data from the digital text pages.
4. Preprocess scanned pages.
5. Run OCR.
6. Classify documents.
7. Extract document fields.
8. Match extracted fields against checklist JSON from the system.
9. Aggregate exceptions.
10. Show only flagged items for human review.

## Important PDF Assumption

The uploaded PDF has two sections:

1. First pages: digital text pages containing the loan application form and ground-truth applicant details.
2. Remaining pages: scanned document images such as PAN, Aadhaar, bank statements, salary slips, and property papers.

Siddhant owns PDF processing, OCR, document classification, and field extraction. Uddhav owns upload UI, database, checklist loading/evaluation, exception aggregation, reports, LLM summary, audit logging, and reviewer flow.

## Setup

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.11.x** | ⚠️ Must be 3.11 — `paddlepaddle` has no wheel for 3.12+ |
| Git | any | — |

Download Python 3.11 from [python.org/downloads](https://www.python.org/downloads/release/python-3119/).

---

### Fast Windows setup

From PowerShell in the project root:

```powershell
.\setup.ps1
.\run_local.ps1
```

`setup.ps1` creates the Python 3.11 virtual environment, installs dependencies, creates `.env` if needed, prepares local folders, and runs a local health check.

`run_local.ps1` starts both FastAPI and Streamlit using `python -m ...` commands, which avoids Windows Application Control blocking launcher executables such as `uvicorn.exe`.

---

### 1. Clone the repo

```bash
git clone https://github.com/UddhavB17/document-validation-mvp.git
cd document-validation-mvp
```

### 2. Create a virtual environment using Python 3.11

**Windows**
```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python --version  # must print Python 3.11.x
```

> If `py -3.11` is not found on Windows, use the full path to the Python 3.11 executable, e.g.:
> `& "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe" -m venv .venv`

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs all packages including `paddlepaddle`, `paddleocr`, `opencv-python`, `pymupdf`, FastAPI, Streamlit, and test tools.  
First-time install may take a few minutes (~200 MB download).

### 4. Configure environment variables

```bash
cp .env.example .env   # macOS/Linux
copy .env.example .env  # Windows
```

Edit `.env` and fill in any values specific to your machine (the defaults work for local development as-is).

### Switching from local Ollama to an API-key LLM

The app defaults to `auto`, which uses an API key when one is present and otherwise falls back to local Ollama:

```env
LLM_PROVIDER=auto
LOCAL_LLM_API_URL=http://localhost:11434/api/generate
LOCAL_LLM_MODEL=llama3.1
```

When you get an API key, fill in environment values only:

```env
LLM_API_KEY=your_api_key_here
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-5.6-luna
```

You can still force a provider with `LLM_PROVIDER=ollama`, `LLM_PROVIDER=openai`, or `LLM_PROVIDER=openai_compatible`.

### 5. Run the app

**FastAPI backend** (terminal 1):
```bash
uvicorn main:app --reload
```

**Streamlit UI** (terminal 2):
```bash
streamlit run app.py
```

### Trusted JSON + mapped-page verification

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

The same workflow is available through `POST /upload/mapped` as multipart form
data with:

- `file`: the PDF
- `manifest`: the JSON manifest encoded as a string

Poll the returned `progress_url`, then retrieve the final deterministic summary
from the returned `summary_url`.

The preferred versioned contract uses `people` and `document_index`. Every
observation retains its person ID, document type, field, page, and OCR
confidence. This allows primary applicants and any number of co-applicants to
be verified independently, detects contradictory values across mapped pages,
and flags pages that appear indexed to the wrong person. The older
`reference_data` + `documents` structure remains accepted for compatibility.

Until the company API and index format are available, paste the example JSON
manually. `services/company_data_provider.py` separates trusted company values
from `services/document_index_provider.py`, which handles manual indexing now
and the future index-PDF format later. Both inputs are composed into the same
`VerificationManifest`, so the OCR and comparison pipeline does not need to be
rewritten during integration.

### 6. Run tests

```bash
pytest
```

All tests should pass. The first run of any OCR test will download PaddleOCR model weights (~100 MB, cached locally after that).

---

### ⚠️ Python Version Note

`paddlepaddle` (the OCR compute backend) does **not** publish wheels for Python 3.12 or 3.13 or 3.14.  
**You must use Python 3.11.** Using any other version will result in OCR being silently disabled.



## Part 2: File System Diagram

```text
document-validation-mvp/
├── app.py                          # Streamlit entry point [Uddhav]
├── main.py                         # FastAPI app [Uddhav]
├── requirements.txt                # [Both]
├── .env.example                    # Example environment config [Uddhav]
├── .gitignore                      # [Both]
├── README.md                       # [Uddhav]
│
├── routes/
│   ├── __init__.py
│   ├── upload.py                   # POST /upload [Uddhav]
│   └── decisions.py                # POST /decision [Uddhav]
│
├── services/
│   ├── __init__.py
│   ├── file_validator.py           # [Uddhav]
│   ├── pdf_processor.py            # [Siddhant] detects digital vs scanned pages
│   ├── text_extractor.py           # [Siddhant] digital pages to ground truth
│   ├── preprocessing.py            # [Siddhant] deskew, denoise
│   ├── ocr_engine.py               # [Siddhant] PaddleOCR on scanned pages
│   ├── document_classifier.py      # [Siddhant]
│   ├── field_extractor.py          # [Siddhant]
│   ├── pipeline.py                 # [Siddhant] wires extraction together
│   ├── checklist_service.py        # [Uddhav] loads checklist from system JSON
│   ├── checklist_engine.py         # [Uddhav]
│   ├── exception_aggregator.py     # [Uddhav]
│   ├── llm_service.py              # [Uddhav]
│   ├── report_generator.py         # [Uddhav]
│   └── audit_service.py            # [Uddhav]
│
├── database/
│   ├── __init__.py
│   ├── db.py                       # [Shared - Uddhav builds, Siddhant reads]
│   └── models.py                   # [Shared - Uddhav builds, Siddhant reads]
│
├── pages/
│   └── worklist_page.py            # [Uddhav] reviewer worklist with inline results
│
├── views/
│   ├── __init__.py
│   ├── upload_view.py              # [Uddhav] PDF + partner JSON intake
│   ├── results_view.py             # [Uddhav] reusable inline results view
│   └── status_helpers.py           # [Uddhav] processing/failed result guards
│
├── tests/
│   ├── __init__.py
│   ├── test_file_validator.py      # [Uddhav]
│   ├── test_text_extractor.py      # [Siddhant]
│   ├── test_pdf_processor.py       # [Siddhant]
│   ├── test_ocr_engine.py          # [Siddhant]
│   ├── test_classifier.py          # [Siddhant]
│   ├── test_field_extractor.py     # [Siddhant]
│   ├── test_checklist_engine.py    # [Uddhav]
│   ├── test_llm_service.py         # [Uddhav]
│   └── fixtures/
│       └── sample_checklist.json
│
├── docs/
│   └── document_validation_architecture.png
│
└── data/
    ├── uploads/                    # gitignored except .gitkeep
    ├── pages/                      # gitignored except .gitkeep
    └── reports/                    # gitignored except .gitkeep
```

## Architecture

See `docs/document_validation_architecture.png`.

Results are rendered inline on the Upload and Worklist views; there is no
separate Results tab/page.

## Document Type Classification

Page classification is deterministic and registry-driven. The type rules live
in `data/document_type_registry.json`; each document type can define heading
phrases, keywords, required keywords, regex field patterns, negative keywords,
priority, and a minimum confidence. To add a new document type, add a new entry
to that JSON file rather than editing classifier code.

The classifier scores every configured type and assigns the best candidate only
when it crosses the configured confidence threshold. Pages that do not match
any known signal stay in the explicit `Unknown` bucket.

Multi-page documents are handled in `services/pipeline.py` with a sequential
state machine. Pages are processed in PDF order. A high-confidence detection
starts or reconfirms the current document type. A low-confidence or unmatched
page inherits the most recent detected type when one exists, and stores
classification metadata showing `detection_method = inherited` plus the page
number where the type was last detected. If the sequence starts with unknown
pages, those pages remain unknown until a real high-confidence detection is
found.

## Collaboration Rules

- Keep `main` stable.
- Create `development` from `main`.
- Create feature branches from `development`, not directly from `main`.
- Merge feature branches into `development` by pull request.
- Merge `development` into `main` only after the phase works and tests pass.
- Do not commit real customer documents, PAN/Aadhaar files, loan files, API keys, or internal data.

## Suggested Branches

- `feature/project-skeleton`
- `feature/database-setup`
- `feature/file-validator`
- `feature/upload-ui`
- `feature/pdf-processor`
- `feature/text-extractor`
- `feature/ocr-pipeline`
- `feature/document-classifier`
- `feature/field-extractor`
- `feature/pipeline-integration`
- `feature/checklist-service`
- `feature/checklist-engine`
- `feature/exception-aggregator`
- `feature/results-ui`
- `feature/export-report`
- `feature/llm-service`
- `feature/reviewer-flow`
- `feature/audit-log`
- `feature/testing`

## Data Safety

Use only dummy or approved sample documents. Uploaded files, extracted pages, generated reports, and local `.env` files are ignored by Git.
