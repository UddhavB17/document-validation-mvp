# Codebase Review Improvements

Review date: 2026-07-13

Scope: review the existing codebase for correctness, maintainability, reliability, security hygiene, and development practices. These recommendations intentionally avoid new product features.

## Overall Assessment

The codebase is in a solid MVP state. It has a clear domain split between API routes, Streamlit views, database helpers, services, data registries, and tests. The app also shows good signs of defensive engineering: upload size limits, PDF validation, persistent pipeline progress, registry-driven document classification, structured Pydantic models, and a meaningful test suite.

The main improvement need is not more functionality. The main need is hardening: make the environment reproducible, reduce risk in the large orchestration modules, centralize configuration, pin dependencies, and make failures easier to reason about.

## High Priority Improvements

### 1. Make the development environment reproducible

Evidence:
- `pytest` is not available on PATH in this checkout.
- `python` is not available on PATH in this shell.
- `.venv`, `.venv311`, and `.codex-venv` contain `python.exe`, but each points to a missing Python install path.
- `pyproject.toml` only declares basic project metadata and Python version.

Why it matters:
Developers should be able to run tests and local checks reliably from a fresh clone. Broken local virtual environments make code review and regression testing less trustworthy.

Recommended improvements:
- Document one canonical setup path and one canonical test command.
- Move dependencies into `pyproject.toml` or generate a lock file from `requirements.txt`.
- Add a lightweight health command for developers, separate from app startup.
- Avoid committing or relying on local virtual environment folders.
- Consider adding `Makefile`, `justfile`, or PowerShell task commands for setup, test, lint, and run.

### 2. Pin dependency versions more safely

Evidence:
- `requirements.txt` uses broad lower bounds such as `fastapi>=0.111.0`, `streamlit>=1.35.0`, `paddleocr>=2.7.0`, and `pymupdf>=1.24.0`.

Why it matters:
OCR, PDF parsing, FastAPI, Streamlit, and Pydantic can change behavior across minor releases. Broad lower bounds can break the app even when no code changed.

Recommended improvements:
- Use upper bounds or a compiled lock file.
- Split runtime dependencies from development/test dependencies.
- Keep heavyweight OCR dependencies isolated so non-OCR tests can run quickly.
- Document known-good dependency versions for Python 3.11.

### 3. Break down the pipeline module

Evidence:
- `services/pipeline.py` is about 62 KB.
- Key responsibilities live in one file: PDF structure handling, digital text extraction, OCR page processing, sequential classification, verification, persistence, checklist execution, reporting, progress updates, and LLM summary orchestration.
- Important entry points include `run_pipeline` at `services/pipeline.py:127`, `_build_page_records` at `services/pipeline.py:437`, `_run_document_verification` at `services/pipeline.py:1391`, and `_save_pages` at `services/pipeline.py:1474`.

Why it matters:
Large orchestration files are difficult to test, review, and change safely. Small fixes can accidentally affect unrelated stages.

Recommended improvements:
- Extract pipeline stages into focused modules, for example:
  - `pipeline_structure.py`
  - `pipeline_pages.py`
  - `pipeline_verification.py`
  - `pipeline_persistence.py`
  - `pipeline_reporting.py`
- Keep `run_pipeline` as a thin orchestrator.
- Introduce typed stage result objects instead of passing large untyped dictionaries everywhere.
- Add focused tests around each stage boundary.

### 4. Centralize configuration loading

Evidence:
- `.env` is loaded in multiple places: `main.py`, `database/db.py`, `services/local_health.py`, and `services/llm_service.py`.
- Some settings use `services/config.py`, while many modules still call `os.getenv` directly.

Why it matters:
Scattered environment parsing makes defaults harder to audit and can create startup-order surprises.

Recommended improvements:
- Load `.env` once at app startup or in a dedicated settings module.
- Extend `services/config.py` into the single source of truth for all runtime settings.
- Replace direct `os.getenv` calls with typed config accessors.
- Validate required paths and URLs during startup.

### 5. Improve exception handling boundaries

Evidence:
- Several broad `except Exception` blocks are used in upload handling, OCR loading, OCR execution, PDF validation, checklist parsing, LLM calls, and pipeline page processing.
- One major page-processing broad catch appears at `services/pipeline.py:711`.

Why it matters:
Broad exception handling is sometimes acceptable around external engines, but it should preserve enough context for debugging and avoid hiding programmer errors.

Recommended improvements:
- Keep broad catches only at clear boundary points: external OCR, LLM HTTP calls, PDF parsing, background job execution.
- Convert unexpected failures into typed internal error objects where possible.
- Add consistent structured logging fields: `application_id`, `page_number`, `stage`, `document_type`.
- Avoid swallowing exceptions without recording the original exception type.

## Medium Priority Improvements

### 6. Add linting, formatting, and static checks

Current state:
- No visible formatter/linter/type-check configuration is present in `pyproject.toml`.

Recommended improvements:
- Add `ruff` for linting and formatting.
- Add `mypy` or `pyright` gradually for typed service boundaries.
- Add `pytest` configuration for test paths, markers, and warnings.
- Add pre-commit hooks for formatting and basic checks.

### 7. Strengthen database migration practices

Current state:
- Schema and migrations are embedded as SQL strings in `database/models.py`.
- Migrations are currently additive and catch duplicate-column errors.

Recommended improvements:
- Add a schema version table.
- Make migrations named, ordered, and idempotent.
- Keep table creation separate from migration history.
- Add tests for migrating an older database shape to the latest schema.

### 8. Reduce untyped dictionary contracts

Current state:
- Many services pass dictionaries with implicit keys, such as pages, anomalies, progress payloads, OCR results, and checklist items.

Recommended improvements:
- Introduce Pydantic models, dataclasses, or `TypedDict` objects for core internal records.
- Start with the highest-value contracts: page records, anomalies, pipeline results, and progress snapshots.
- Keep serialization at the edges, not throughout the core logic.

### 9. Improve API response consistency

Current state:
- Some route responses are plain dictionaries without explicit response models.
- Background job and pipeline status strings appear in multiple places.

Recommended improvements:
- Add Pydantic response models for upload, progress, decision, and verification routes.
- Define status constants or enums for application status, job status, and pipeline outcome.
- Ensure API errors follow one predictable shape.

### 10. Separate UI styling from app logic

Current state:
- `app.py` contains a large inline CSS string and app navigation logic.
- Streamlit views use `unsafe_allow_html` for layout/styling.

Recommended improvements:
- Move CSS to a dedicated view/theme module.
- Keep `unsafe_allow_html` usage limited and reviewed.
- Avoid interpolating untrusted text into HTML strings unless escaped.

## Low Priority Improvements

### 11. Clean up documentation encoding

Current state:
- Some README and source comments render as garbled characters in this shell, likely from encoding mismatch or mojibake.

Recommended improvements:
- Normalize docs and source files to UTF-8.
- Replace decorative box-drawing comments if they are not necessary.
- Add an editor config to standardize charset and line endings.

### 12. Improve repository hygiene

Current state:
- `.gitignore` correctly excludes `.env`, virtual environments, uploaded files, generated outputs, local databases, and generated processing folders.
- `MVP_IMPROVEMENT_RECOMMENDATIONS.md` is ignored, but future review reports are not clearly categorized.

Recommended improvements:
- Add a `docs/reviews/` or `docs/engineering/` folder for review artifacts.
- Keep generated reports and local-only notes out of the repo unless intentionally shared.
- Add a short `CONTRIBUTING.md` with setup, branch, test, and commit expectations.

### 13. Make tests easier to run selectively

Current state:
- There are 27 test files, which is a good base.
- OCR/PDF/LLM-heavy tests can make full test runs expensive or environment-sensitive.

Recommended improvements:
- Add pytest markers such as `unit`, `integration`, `ocr`, `llm`, and `slow`.
- Make default tests avoid downloading OCR models.
- Add a documented command for fast local checks.
- Add a second command for full OCR/integration validation.

## Positive Practices Already Present

- Good separation between routes, views, services, database, tests, and data registries.
- The document classifier is registry-driven instead of hard-coded only in Python.
- Upload handling streams files to disk with a size limit.
- SQLite connections enable foreign keys and WAL mode.
- Pipeline progress is persisted and visible to callers.
- Sensitive local files and generated outputs are mostly ignored by Git.
- Tests cover many important domains: validators, OCR, classification, checklist logic, reports, routes, and UI helper behavior.
- Runtime config profiles exist for fast, balanced, and strict processing behavior.

## Suggested Implementation Order

1. Fix local setup reproducibility and test execution.
2. Add dependency locking or upper bounds.
3. Add lint/format tooling and apply it once.
4. Centralize runtime configuration.
5. Extract `services/pipeline.py` into smaller stage modules.
6. Add typed internal models for page records, anomalies, and pipeline results.
7. Introduce database migration versioning.
8. Add API response models and shared status enums.
9. Move UI CSS/styling helpers out of entry-point files.
10. Normalize documentation encoding and add contribution notes.

## Verification Notes

Commands attempted during review:

```powershell
pytest
python -m pytest
.\.venv\Scripts\python.exe -m pytest
.\.venv311\Scripts\python.exe -m pytest
```

Result:
- `pytest` was not found.
- `python` was not found.
- Both local virtual environments pointed to a missing Python 3.11 installation path.

Because of that, test results could not be verified from this shell. The highest-priority operational fix is to restore a reproducible Python 3.11 environment and make the test command work from a fresh checkout.
