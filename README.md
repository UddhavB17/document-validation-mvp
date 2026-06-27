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
│   ├── upload_page.py              # [Uddhav]
│   ├── results_page.py             # [Uddhav]
│   └── worklist_page.py            # [Uddhav]
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
