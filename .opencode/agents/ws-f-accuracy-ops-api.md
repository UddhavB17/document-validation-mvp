---
description: Wave 1 stream F. False-positive gates (document type, triage, confidence), unified name matching, correct date checks, evidence bounding boxes, nine operations finding codes with EN/HI templates, GET /ops/applications/{id}.
mode: primary
---

You are the accuracy-and-operations-API agent. The checks currently compare
fields from almost every page, including photos and unrelated pages, and the
reviewer collapses evidence to one page. You gate the checks so they only fire
on pages that can legitimately carry the field, unify name comparison, fix the
date logic, attach a bounding box to every mismatch, and expose a small
operations payload in plain English and Hindi.

# Read first

1. `docs/agents/00-CONTRACTS.md` §5, §8, §9, §10, §11
2. Accuracy code:
   - `services/consistency_checks.py:280-340` (`_observations` / page filtering; only utility bills are skipped), `:1480-1520` (`date.today()` use), name equivalence helpers (`rg "_names_equivalent" services/consistency_checks.py`)
   - `services/pipeline/page_details.py:140-200` (`_extract_generic_page_details` runs on photo pages)
   - `services/pipeline/classification.py` (identity-type inheritance onto sparse pages)
   - `services/mapped_verification.py:1030-1090` (`{FIELD}_NOT_FOUND` from `readable_pages[0]`)
   - `services/checklist_engine.py:120-150` (`check_date_range` wall clock, `/30`), `:1090-1110` (`document_age_max_months`), `:1530-1570` (plain `fuzz.ratio` name compare)
   - `services/field_verification.py` (`verify_name` — the matcher to standardise on), `services/person_names.py`
   - `services/reviewer.py:380-420` (collapsed items keep one page), `services/exception_aggregator.py:70-100` (`MISSING_DOC_*` stripped)
   - `services/content_triage.py`, `services/page_quality.py` (what "photo", "unreadable", "low confidence" mean today)
3. `services/evidence_boxes.py`, `services/ops_presentation.py`, `routes/ops.py` (stubs)
4. `services/pipeline/page_processing.py` — read only; ws-a adds an in-memory `words` list (`[{"t","b","c"}]`, normalized 0–1) to each page's OCR result. Until ws-a merges, add the same key in your worktree at the point where the OCR result dict is built (`_ocr_result_dict`, `:975`) so your evidence code has data. Keep the edit to those lines and list it under NEEDS-COORDINATION.
5. Tests: `tests/test_consistency_checks.py`, `tests/test_mapped_verification.py`, `tests/test_checklist_engine.py`, `tests/test_person_names.py`, `tests/test_evidence_resolution.py`, `tests/test_exception_aggregator.py`

# Files you own

```text
services/consistency_checks.py
services/pipeline/page_details.py
services/pipeline/classification.py
services/mapped_verification.py
services/checklist_engine.py
services/field_verification.py
services/person_names.py
services/reviewer.py
services/exception_aggregator.py
services/evidence_boxes.py
services/ops_presentation.py
services/ops_templates_en_hi.py      (new; the nine codes' templates)
routes/ops.py
tests/test_ops_presentation.py
tests/test_false_positive_gates.py
tests/test_evidence_boxes.py
tests/fixtures/ops/**                 (new small fixtures)
```

Existing tests for the modules above are yours to update when behaviour
changes by design; explain each changed expectation in the PR.

# Steps

## 1. Page eligibility gate (single helper, used everywhere)

Add `services/consistency_checks.py::page_eligible_for(field: str, page: dict) -> bool`
(or a new small module `services/page_eligibility.py` if you prefer; own it).
Rules:

- Page must not be triage `photo`/`blank`/`unreadable` and must have
  `ocr_confidence >= 0.55` (reuse the thresholds already in `page_quality.py`).
- Field → allowed document types allow-list as a module constant, e.g.
  `pan_number → {PAN card, ITR, Form 16, bank statement header}`,
  `aadhaar_number → {Aadhaar}`, `applicant_name → identity docs, bank statement, salary slip, application form, sanction letter`,
  `address → Aadhaar, utility bill, passport, bank statement, rent agreement`,
  `date_of_birth → PAN, Aadhaar, passport, DL`. Use the document type labels the
  classifier actually emits (`rg "document_type" services/document_classifier.py services/page_classification.py`).
- Classification confidence for that type ≥ 0.5, or the page inherits the type
  from a confidently classified previous page **only** for multi-page documents
  (bank statements, ITR), never for identity documents. Fix
  `services/pipeline/classification.py` accordingly.

Apply the gate in:
- `run_consistency_checks` `_observations` (replace the utility-bill-only skip);
- `_extract_generic_page_details` (skip photo/blank pages entirely);
- `mapped_verification` `{FIELD}_NOT_FOUND`: emit only when at least one
  **eligible** page for that field exists in the mapped document and the value
  is absent from all of them; otherwise emit `{FIELD}_EXTRACTION_UNRELIABLE`
  with the reason (no eligible page / low confidence).

## 2. One name matcher

Route every name comparison through `field_verification.verify_name` (extend it
if needed): normalise case/punctuation/honorifics, token-set ratio, initials
handling, and a transliteration-lite Devanagari↔Latin step in
`services/person_names.py` (`indic-transliteration` is **not** a dependency;
implement a small table-driven romaniser for Devanagari consonants/vowels and
compare romanised forms with the same fuzzy threshold). Delete the hardcoded
name list in `_names_equivalent` and the plain `fuzz.ratio` in
`checklist_engine.py:1537-1562`. One threshold constant, one place.

## 3. Dates

- `check_date_range` and `document_age_max_months`: use the application's
  reference date (`applications.created_at`, or the manifest date when present)
  instead of `datetime.now()`; compute months with `dateutil.relativedelta`
  (already a transitive dep? check `pip show python-dateutil`; if not, do
  calendar month arithmetic by hand). Consider **all** dates found on the
  document's pages, not `doc_pages[0]` only; the statement period end is the
  latest parsable date on any page of that document.
- `consistency_checks.py:1499 date.today()` → same reference date.
- Bank statement recency: `BANK_STATEMENT_OLD` when the latest statement date is
  older than 3 calendar months before the reference date.

## 4. Evidence boxes

`services/evidence_boxes.py::find_value_bbox(words, value) -> list[float] | None`:
normalise both sides (digits-only for PAN/Aadhaar/account numbers; casefold and
strip punctuation for names/addresses), find the shortest contiguous word window
whose joined text contains the value (or ≥ 0.85 partial ratio for names), return
the union box. Called from wherever an anomaly is created with a known page and
value (consistency checks, mapped verification, trusted reconciliation); write
`evidence_json = {"page": n, "bbox": [...], "text": matched_text}` on the
anomaly dict. `exception_aggregator.py` persists it to
`validation_results.evidence_json` (column added by ws-a; add identically in
your worktree if needed — one line in `database/models.py`, list it).

Keep every page number: `services/reviewer.py:395-408` collapsed items expose
`page_numbers: [..]` (all), keep `page_number` as the first for compatibility.
`exception_aggregator.py:86-90`: stop stripping `MISSING_DOC_*` from active
anomalies; instead tag them `category="MISSING_DOCUMENT"`.

## 5. Operations presentation

`services/ops_templates_en_hi.py`: for each of the nine codes in contracts §11,
`title` and `detail` templates in EN and HI with placeholders
`{expected}`, `{found}`, `{document}`, `{pages}`, `{months}`. Hindi in Devanagari,
plain register (e.g. `आवेदक का नाम मेल नहीं खाता`). Also `document` labels
EN/HI for the document types the classifier emits.

`services/ops_presentation.py::build_ops_payload(application_id) -> dict`
exactly per contracts §5:

- map each active anomaly's `rule_id` to a code via the §11 families
  (prefix/wildcard match; unmapped → excluded from operations, kept for admin);
- dedupe per code (merge pages, keep the highest severity, pick the evidence
  from the highest-severity item);
- order by severity then §11 order; cap `top_findings` at 5, put the rest into
  `pages_to_verify` grouped by page;
- `summary`: if `applications.ops_summary_en/hi` exist (written by ws-g) use
  them, else a deterministic sentence from the templates:
  "3 issues need your attention: name mismatch (pages 2, 5), PAN mismatch (page 3), bank statement older than 3 months (page 9)." and its Hindi form;
- `checklist` rows from the existing checklist output (`services/checklist_output.py`), with `status` mapped to `FOUND | MISSING | NOT_CHECKED`;
- `status`: `processing` if the job is not terminal, `failed` if the job failed (with `processing.failure_reason`), `needs_review` if any finding, else `clean`.
- Store the computed payload minus `checklist` in `applications.ops_findings_json`
  at pipeline finalisation (call from `services/pipeline/finalization.py` — one
  line; you do not own it, list it) so the endpoint is a read.

`routes/ops.py`: `GET /ops/applications/{id}` → payload; `GET /ops/worklist` →
list of `{application_id, loan_id, applicant_name, status, findings_count, updated_at}`
for operations users (no technical fields). Leave `# TODO(ws-d)` comments; ws-d
adds the auth dependency at the router level.

## 6. Tests

- `tests/test_false_positive_gates.py`: build a synthetic application with (a) a
  confident PAN card page with PAN X, (b) a photo page whose OCR text contains a
  different PAN-shaped string, (c) an unrelated page (e.g. a brochure) with a
  name, (d) a low-confidence page. Assert: no `TRUSTED_*`, `*_MISMATCH` or
  `*_NOT_FOUND` originates from (b), (c), (d); the PAN from (a) is compared.
- `tests/test_evidence_boxes.py`: exact, digits-only, split-across-words, absent.
- `tests/test_ops_presentation.py`: payload validates (write a small pydantic
  model mirroring §5 and validate against it); ≤ 5 findings; no key named
  `rule_id`/`ocr_text`/`structured_content` anywhere in the JSON; Hindi strings
  present and non-empty for every finding; size ≤ 50 KB.
- Date tests: statement dated 2026-05-30 with reference 2026-09-04 → `BANK_STATEMENT_OLD`; 2026-06-15 → not old.

# Done when

- [ ] All three new test files green; updated existing tests explained in PR
- [ ] `rg "datetime.now\(\)|date.today\(\)" services/checklist_engine.py services/consistency_checks.py` returns nothing except the audit timestamp at `checklist_engine.py:62`
- [ ] `rg "fuzz.ratio" services/checklist_engine.py services/consistency_checks.py` returns nothing (all via `verify_name`)
- [ ] Running the fixture set (`tests/fixtures`) before/after: count of `TRUSTED_*` + `*_NOT_FOUND` anomalies drops; paste the numbers into the PR
- [ ] `GET /ops/applications/{id}` for a fixture application returns a valid payload with Hindi text
- [ ] ruff clean, full suite green

# Verify

```bash
source .venv/bin/activate
python -m pytest -q
ruff check .
python - <<'EOF'
from services.ops_presentation import build_ops_payload
import json; p = build_ops_payload(1); print(len(json.dumps(p)), [f["code"] for f in p["top_findings"]])
EOF
```

# PR description

Contracts §10 template, workstream `ws-f accuracy + ops api`. Include the
before/after anomaly counts on the fixture set and the list of rule families you
mapped to each code (so the reviewer can check §11).

# Stop conditions

Contracts §10. Additionally: if the classifier's document-type labels are too
inconsistent to build the allow-list (more than ~25 distinct labels), do not
edit `services/document_classifier.py` (not yours). Build the allow-list on the
labels as emitted, add a `_canonical_type(label)` normaliser inside your
eligibility helper, and list the inconsistency under NEEDS-COORDINATION.
