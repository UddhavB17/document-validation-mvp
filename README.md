# Document Validation MVP

Private collaboration repo for the loan-document validation MVP.

## Goal

Build an exception-based document validation workflow:

1. Upload scanned loan-file PDF.
2. Validate the file.
3. Preprocess pages.
4. Run OCR.
5. Classify documents.
6. Match detected documents against checklist.
7. Aggregate exceptions.
8. Show only flagged items for human review.

## Architecture

See `docs/document_validation_architecture.png`.

## Collaboration Rules

- Keep `main` stable.
- Create feature branches for work.
- Open pull requests before merging.
- Do not commit real customer documents, PAN/Aadhaar files, loan files, API keys, or internal data.

## Suggested Branches

- `feature/upload-ui`
- `feature/ocr-pipeline`
- `feature/document-classifier`
- `feature/checklist-engine`
- `feature/reviewer-worklist`

## Data Safety

Use only dummy or approved sample documents. Uploaded files and generated outputs are ignored by Git.
