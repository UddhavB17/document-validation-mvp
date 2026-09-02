# Backend domain module map

This note explains where loan-file validation logic lives after the domain
decomposition. Public callers should keep importing the compatibility facades in
`services/field_extractor.py`, `services/checklist_engine.py`,
`services/consistency_checks.py`, and `services/person_ownership.py`.

## Layering

1. **Low-level helpers** — normalization, fuzzy fallbacks, text/date parsing.
   These modules must not import high-level services.
   - `services/extraction/_shared.py`
   - `services/ownership/_helpers.py`
   - `services/checklist/_dates.py`, `services/checklist/_fuzzy.py`

2. **Document family / rule group implementations** — one reason to change.
   - Extraction: `services/extraction/loan_terms.py`, `identity.py`, `banking.py`,
     `application.py`, `bureau.py`, `property_compliance.py`
   - Checklist: `services/checklist/presence_runner.py`, `accuracy_runner.py`,
     `quality_runner.py`, `bank_period.py`, `conditions.py`
   - Consistency: `services/consistency/matching.py`, `trusted.py`,
     `cross_document.py`, `bureau.py`, `language.py`, `affidavit.py`
   - Ownership: `services/ownership/resolution.py`, `assignment.py`, `cersai.py`,
     `matching.py`, `observations.py`

3. **Dispatch / orchestration** — wire families together, preserve ordering.
   - `services/extraction/dispatcher.py`
   - `services/checklist/runner.py`
   - `services/consistency/runner.py`

4. **Compatibility facades** — stable import paths for routes, pipeline, and tests.

## Adding a new document rule

| If you are adding… | Start in… | Then expose via… |
| --- | --- | --- |
| OCR field parsing for a new document type | `services/extraction/<family>.py` + register in `dispatcher.py` | `services.field_extractor.extract_fields` |
| Checklist presence/accuracy/quality item | matching `services/checklist/*_runner.py` or `bank_period.py` | `services.checklist_engine.run_checks` |
| Trusted vs document comparison | `services/consistency/matching.py` or a focused rule module | `services.consistency_checks.run_consistency_checks` |
| Person ownership evidence | `services/ownership/observations.py` or `matching.py` | `services.person_ownership.resolve_person_owner` / `assign_page_owners` |

Keep dynamic OCR/LLM payloads as plain `dict[str, Any]` at boundaries; use the
`*_types.py` modules only for stable internal shapes.

## Local quality checks

```bash
python3 -m pytest tests/test_field_extractor.py tests/test_checklist_engine.py \
  tests/test_consistency_checks.py tests/test_person_ownership.py tests/test_domain_packages.py

python3 -m compileall services
python3 -m ruff check services tests
python3 -m ruff format --check services tests
python3 -m mypy
git diff --check
```

Install tooling once (offline after download):

```bash
pip install -e ".[dev]"  # or: pip install ruff mypy pytest
```
