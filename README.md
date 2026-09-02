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

Backend module ownership, filesystem configuration, and Python quality commands
are documented in [`docs/MAINTAINING.md`](docs/MAINTAINING.md).

The Python UI has been removed. The browser interface is now the Next.js app in `frontend/`.

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11.x | Supported backend runtime |
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

Create and activate the Python environment on Windows PowerShell:

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

On macOS Terminal:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..
cp .env.example .env
```

## Run Locally

The default `.env.example` uses Google Vision for scanned-page OCR. Configure
an API key or Application Default Credentials before processing scans. Digital
PDF pages continue to use embedded text without an OCR API call.

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

Both normalized ZIP packages and merged PDFs use a second evidence-resolution
pass. It can promote an Unknown page only when intrinsic document anchors are
strong, group continuation/front-back pages, match exact identity evidence to
the correct trusted person, and rerun the appropriate extractor over the whole
document group. Application forms and CAMs are treated as multi-person
containers. Observed OCR values, resolved document/person metadata, and trusted
JSON remain separate; trusted JSON is never copied over an observed value.

## OCR API Setup (macOS and Windows)

Google Vision is the API OCR provider currently implemented. When
`OCR_PROVIDER=google_vision`, each scanned page is sent to Google once and the
same response is reused for classification and field extraction. Local
OCR is not called for those pages. Digital pages continue to use their
embedded PDF text and do not incur OCR API usage.

Before setup, enable the Vision API and billing in your Google Cloud project.
Never paste a real API key or service-account JSON into source code, README
examples, screenshots, issues, or commits. Keep `.env` and credential files
outside Git; only `.env.example` should be committed.

### Option A: Google Vision API key

Create `.env` from `.env.example` and use placeholder values like these:

```dotenv
OCR_PROVIDER=google_vision
GOOGLE_VISION_AUTH=api_key
GOOGLE_VISION_API_KEY=replace_with_your_secret_key
GOOGLE_VISION_FEATURE=DOCUMENT_TEXT_DETECTION
GOOGLE_VISION_TIMEOUT_SECONDS=60
GOOGLE_VISION_MAX_ATTEMPTS=3
```

Restart the backend after changing `.env`.

### Option B: Google service account / Application Default Credentials

Service-account or workload credentials are preferred for production. Put the
credential JSON outside the repository and configure an absolute path.

macOS `.env` example:

```dotenv
OCR_PROVIDER=google_vision
GOOGLE_VISION_AUTH=adc
GOOGLE_APPLICATION_CREDENTIALS=/Users/your-user/.config/dmef/google-vision.json
```

Windows `.env` example:

```dotenv
OCR_PROVIDER=google_vision
GOOGLE_VISION_AUTH=adc
GOOGLE_APPLICATION_CREDENTIALS=C:\Users\your-user\.config\dmef\google-vision.json
```

For local development with the Google Cloud CLI, run the same command from
macOS Terminal or Windows PowerShell:

```text
gcloud auth application-default login
```

Then leave `GOOGLE_APPLICATION_CREDENTIALS` blank and use
`GOOGLE_VISION_AUTH=adc`.

### Verify the selected OCR provider

Start the backend and open **Settings → OCR Provider**. Select **Google Vision
API only**, choose the authentication mode, save, and process a test document
containing approved dummy data. Backend page metadata should show:

```json
{
  "ocr_provider": "google_vision",
  "ocr_route": "google_vision"
}
```

Google Vision mode never silently falls back to local OCR; API failures are
recorded as page-processing errors so incomplete validation cannot look like a
successful result.

## Multilingual and Regional-Language Documents

The system treats **script detection** and **language identification** as two
different operations. This is essential for North Indian documents: Hindi,
Haryanvi, Bhojpuri, Maithili, Magahi, Marathi, Nepali, and other languages may
all appear in Devanagari. A Devanagari page is therefore never labelled Hindi
from its characters alone.

Each processed page can carry four separate forms of evidence:

1. `scripts`: deterministic Unicode observations such as `devanagari`,
   `gurmukhi`, `gujarati`, `bengali`, `tamil`, or `arabic`.
2. `language_candidates`: possible languages for those scripts, explicitly not
   treated as detected languages.
3. `declared_languages`: a printed value such as `Second language: Haryanvi`.
4. `provider_languages`: language metadata reported by the OCR API.

Document type classification continues to use identifiers, document structure,
field labels, and page sequence; it does not require the complete packet to have
one language. Preserve the original Unicode OCR text and classify each page or
document group independently. For exact language-sensitive rules, use a printed
language declaration or trusted template metadata and send unresolved cases to
manual review.

Trusted input may declare an application template's languages when that fact is
known independently of OCR:

```json
{
  "application_form_languages": ["English", "Haryanvi"]
}
```

The application-form second-language check runs only on digital pages. Hindi is
accepted as a second language. Evidence may come from a printed declaration,
trusted template metadata, provider metadata, or English plus another script in
the selectable text. Scanned application forms do not produce this anomaly.
See `docs/multilingual_document_policy.md` for the evidence and decision model.

## Optional Offline OCR Smoke Test

Normal setup and production continue to use Google Vision. Local PaddleOCR is
an isolated developer test path and is not installed by `requirements.txt`.
Create a separate environment so its large native dependencies do not affect
the API-backed app:

```bash
python3.11 -m venv .venv-ocr
source .venv-ocr/bin/activate
pip install -r requirements-ocr-local.txt
python scripts/test_offline_ocr.py /absolute/path/to/sample.pdf --page 1 --lang bgc
```

On Windows PowerShell, activate with
`.\.venv-ocr\Scripts\Activate.ps1` and run the same `pip` and `python`
commands. Useful Paddle language values are:

| Language | `--lang` |
|---|---:|
| Haryanvi | `bgc` |
| Bihari language group | `bh` |
| Bhojpuri | `bho` |
| Maithili | `mai` |
| Magahi | `mah` |
| Hindi | `hi` |
| Urdu | `ur` |
| Tamil | `ta` |
| Telugu | `te` |

The first run downloads Paddle models into its cache. Run each model once while
online before testing without a network connection. The smoke-test command
directly calls local OCR and cannot call Google Vision. The full backend can
only select local OCR when both `DMEF_LOCAL_OCR_TEST_MODE=true` and
`OCR_PROVIDER=local` are present; do not use that override in production.

PaddleOCR v5 does not provide dedicated Gujarati, Bengali, Gurmukhi, Odia,
Kannada, or Malayalam recognizers in this test adapter. Use Google Vision for
those in the application. If a fully offline cross-India test is later needed,
add a Tesseract adapter and the appropriate trained-data files rather than
pretending the Devanagari model supports those scripts.

### Adding Amazon Textract, Azure AI Vision, or another OCR API

The extraction pipeline expects every provider adapter to return the same
internal result contract:

```python
{
    "ocr_text": "observed document text",
    "confidence": 0.0,
    "is_readable": True,
    "ocr_provider": "provider_name",
    "bounding_boxes": [],
    "layout_blocks": [],
    "tables": [],
}
```

To add another API, create a provider module beside
`services/google_vision_ocr.py`, translate the provider response into this
contract, register the provider in `services/ocr_router.py`, add non-secret
settings to `.env.example`, and add mocked tests that make no external calls.
Provider SDK credentials must come from environment variables, the cloud
provider's standard credential chain, or a secret manager—not from committed
configuration. Until an adapter is registered, setting an arbitrary provider
name will not activate that API.

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

Use only dummy or approved sample documents. Uploaded files, extracted pages,
generated reports, local databases, `.env` files, API keys, and service-account
credentials must remain untracked. Before committing, inspect staged changes
for identifiers and secrets.
