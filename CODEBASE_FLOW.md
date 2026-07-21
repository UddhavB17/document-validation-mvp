# DMEF Codebase Flow

## Runtime

DMEF now uses:

1. Next.js frontend in `frontend/`
2. FastAPI backend in `main.py`
3. SQLite persistence through `database/db.py`
4. OCR, classification, checklist, reporting, and review services under `services/`

The legacy Python UI has been removed. All reviewer-facing screens are in the Next.js app.

## Frontend Flow

`frontend/app/layout.tsx` renders the shared admin shell.

Main routes:

- `/upload`: PDF upload, mapped verification, partner JSON intake.
- `/worklist`: reviewer worklist with filters and sortable table.
- `/applications/[id]`: full application review workflow.
- `/activity`: same-day reviewer activity.

Data fetching is centralized in:

- `frontend/lib/api.ts`: typed fetch client and Zod response schemas.
- `frontend/lib/queries.ts`: TanStack Query hooks.

## Backend Flow

`main.py` creates the FastAPI app, installs local CORS for the Next.js dev server, initializes the database on startup, and includes these routers:

- `routes/upload.py`
- `routes/verification.py`
- `routes/decisions.py`
- `routes/review.py`

## Upload Path

1. User submits a PDF or JSON payload in the Next.js UI.
2. The frontend calls `POST /upload`, `POST /upload/mapped`, or `POST /upload/json`.
3. The backend validates and stores the file or payload.
4. A background pipeline job is queued.
5. The frontend polls `GET /upload/{application_id}/progress`.
6. Review details are loaded from `GET /review/applications/{application_id}`.

## Review Path

1. Worklist calls `GET /review/worklist`.
2. Review page calls `GET /review/applications/{application_id}`.
3. Decisions are submitted with `POST /decision`.
4. Recent decisions can be undone with `POST /decision/{decision_id}/undo`.
5. Activity page calls `GET /review/activity/today`.

## Processing Pipeline

The backend pipeline still owns document processing:

- PDF validation and page splitting
- Digital text extraction
- OCR on selected scanned pages
- Document classification
- Field extraction
- Checklist evaluation
- Exception aggregation
- Reviewer summary generation
- Report and OCR JSON output

The frontend does not duplicate processing logic; it only calls backend APIs and renders reviewer workflows.
