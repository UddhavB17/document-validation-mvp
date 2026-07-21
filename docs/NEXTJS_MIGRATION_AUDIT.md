# DMEF Python UI to Next.js Audit

## Screens

- Upload: PDF upload form with loan ID, applicant, co-applicant, product type, branch, PDF file, upload response metrics, live processing progress, and final review link.
- Upload: Mapped Verification tab with mapped PDF upload and trusted manifest JSON text area.
- Upload: Partner JSON Intake tab with raw OCR/checklist JSON text area.
- Worklist: reviewer queue table, status filter, start review queue action, and open application action.
- Application Review: verdict banner, deterministic reviewer summary, review metrics, application data, result explanation, page processing table, anomalies, manual review list, reviewer decision actions, checklist table, and downloads.
- My Activity: same-day reviewer decision metrics and decision table.
- Sidebar: navigation, API address, and local health status.

## Legacy UI Inputs

- `loan_id`, `applicant_name`, `coapplicant_name`, `product_type`, `branch`, `file`.
- Mapped verification `file` and manifest JSON.
- Partner OCR JSON payload.
- Worklist filter and selected application.
- Manual review confirmation checkbox.
- Reviewer note, quick rejection reason, decision button, undo button.

## Existing FastAPI Calls

- `GET /health`
- `POST /upload`
- `POST /upload/mapped`
- `POST /upload/json`
- `GET /upload/{application_id}/progress`
- `GET /verification/summary/{application_id}`
- `GET /verification/checklist/{application_id}`
- `GET /verification/{application_id}`
- `GET /decision/{application_id}`
- `POST /decision`
- `POST /decision/{decision_id}/undo`

## Legacy Direct DB Reads Replaced By New Read-Only API

- `GET /review/worklist`
- `GET /review/activity/today`
- `GET /review/applications/{application_id}`
- `GET /review/applications/{application_id}/ocr-json`
