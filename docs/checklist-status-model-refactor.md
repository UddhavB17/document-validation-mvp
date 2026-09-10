# DMEF — Checklist Status Model Refactor: Context & Decisions
This doc is the source of truth for an in-progress refactor. Read this before making or resuming any changes — it captures decisions already made so they don't get re-litigated or silently reversed.

## Goal
Replace the current 5-value checklist status (`verified`, `needs_review`, `missing`, `unknown`, `not_applicable`) — which has a silent catch-all defaulting ambiguous cases to "verified" — with an explicit status model that never silently passes an item through. Also add a proper `ocr_status` field so OCR-failed/empty pages route to manual review instead of generating anomalies, and digital/non-OCR pages don't get misrepresented as "OCR succeeded."

## Decision 1 — New checklist status enum (5 values)
Single source of truth in a new file: `services/checklist_status_map.py`

```python
DocumentChecklistStatus = Literal[
  "required_and_present",
  "required_and_missing",
  "not_applicable",
  "not_evaluated_by_engine",
  "manual_review",
]
```

Legacy → new mapping (also lives only in this file):
```
verified       -> required_and_present
missing        -> required_and_missing
not_applicable -> not_applicable
needs_review   -> manual_review
unknown        -> manual_review   # DECISION: ALL "unknown" maps to manual_review, no exceptions
```
- `map_legacy_checklist_status()` **raises** `ValueError` on any unmapped input — no silent pass-through, no `else: return v`.
- `not_evaluated_by_engine` has no legacy source. It's assigned fresh, going forward, to: old `NOT_CHECKED` rows, cases where `system_flag` is `None`, and cases where `applicability` is `None`. This is distinct from `manual_review` — see Decision 4.

Every place in the codebase that currently branches on the old 5 statuses must use **explicit case handling for all 5 new values** — no `else` branch that defaults to "approved"/"verified". An unrecognized status should raise, not silently pass.

## Decision 2 — Separate `ocr_status` field (do not conflate with checklist status)
```python
OcrStatus = Literal["success", "failed", "no_text_extracted", "not_applicable"]
```
This lives on the **page** record, not the checklist item. It answers "what happened during text extraction for this page," independently of the checklist verdict.

Why a separate field instead of reusing `ocr_confidence == None` as a signal: digital pages have no OCR confidence score at all, and letting `ocr_status` implicitly equal "success" for those pages makes the data ambiguous (was OCR skipped, or did it run and succeed?). Keeping `ocr_status` explicit avoids that ambiguity and avoids skewing any future OCR-accuracy metrics with digital pages counted as OCR successes.

### Assignment rules (confirmed)
| Page type | ocr_status |
|---|---|
| Digital page (text already available, no OCR needed) | `not_applicable` |
| DB Data page (sourced from system-of-record) | `not_applicable` |
| OCR ran, extraction threw an exception / processing error | `failed` |
| OCR ran, returned text but stripped length < 40 chars (or empty) | `no_text_extracted` |
| OCR ran, returned text ≥ 40 chars stripped | `success` |
| **Budget-skipped page (OCR never got a turn)** | **`no_text_extracted`** — see correction below |

**Important correction (do not use `not_applicable` for budget-skipped pages):** an earlier draft proposed mapping OCR-Skipped (budget skip) pages to `ocr_status=not_applicable`, the same as digital/DB Data pages. This was rejected. `not_applicable` must mean "OCR genuinely doesn't apply here" (content is available another way). A budget-skipped page's content is unknown — OCR should have run but didn't. Mapping it to `not_applicable` would make a required document on that page silently read as satisfied-by-absence instead of surfacing for review, which is exactly the silent-fallback failure this refactor is meant to eliminate. Budget-skipped pages must map to `no_text_extracted` (same downstream `manual_review` routing as an empty OCR result). If per-cause analytics are ever needed later, a distinct `skipped` value can be added that still routes identically downstream — not needed for this pass.

Threshold reuses the existing 40-char rule (`checklist_engine.py:1471`) and existing 50-char digital gate (`text_extractor.py:31`) — don't invent a new threshold.

## Decision 3 — Explicit branch logic, no catch-all "verified"
Example of the corrected pattern (`services/checklist_output.py`):
```python
if applicability is False:
    status = "not_applicable"
elif missing_anomalies:
    status = "required_and_missing"
elif any(p.get("ocr_status") == "failed" for p in matched_pages):
    status = "manual_review"; flagged_reason = "ocr_failed"
elif review_anomalies:
    status = "manual_review"
elif matched_pages or system_state is True:
    status = "required_and_present"
elif applicability is None or system_state is None:
    status = "not_evaluated_by_engine"
else:
    status = "manual_review"   # explicit final case — never silently "verified"
```
Same exhaustive, no-catch-all treatment applies to:
- confidence scoring (match all 5 statuses explicitly, no fallthrough to "medium confidence")
- summary counting (raise on any unexpected `item.status` instead of ignoring it)
- the uppercase UI-row mapping (`FOUND`/`MISSING`/`NOT_APPLICABLE`/`NOT_CHECKED` → new names, exhaustive if/elif/.../else: raise)
- narration logic (only skip narration text when status is exactly `required_and_present`; treat all other 4 statuses as needing a message)

## Decision 4 — `manual_review` vs `not_evaluated_by_engine` (why both exist)
- `manual_review` = something is actively wrong or ambiguous and a human should look: legacy `unknown`, legacy `needs_review`, OCR failure, unresolved review anomalies.
- `not_evaluated_by_engine` = the engine simply hasn't produced a verdict yet (no anomaly, nothing wrong detected, just not run/resolved): old `NOT_CHECKED`, `system_flag is None`, `applicability is None`.

Keeping these separate avoids polluting the manual-review queue with items that aren't actually broken, just unevaluated.

## Decision 5 — OCR-failed pages must not generate anomalies
Pages with `ocr_status == "failed"` route to `manual_review` and must not produce duplicate quality anomalies for the same page. Implemented as a skip in `services/checklist_engine.py::_run_quality_checks` (plus `ocr_failed` routing in `services/checklist_output.py::_build_item`), not in `services/exception_aggregator.py` — same observable behavior (routed to manual review, still visible in `pages_with_issues`/quality warnings, just not as anomalies). Same treatment extends to `no_text_extracted` pages resulting from budget-skips (per Decision 2 correction) — these also must not generate spurious "missing document" anomalies when the real cause is "OCR never ran."

## Files touched (from the applied proposal)
- **New:** `services/checklist_status_map.py` — legacy mapping + raise-on-unmapped, single source of truth
- `database/models.py` — new `ChecklistStatus` and `OcrStatus` Literal types; `pages` table gets an `ocr_status` column
- `frontend/generated/checklistTypes.ts` — mirrored `ChecklistStatus` and `OcrStatus` types
- `services/pipeline/page_processing.py` — `_ocr_status()` helper, called when building `completed_page` dict
- `services/pipeline/persistence.py` (`_insert_page`) — persist `ocr_status`
- `services/checklist_output.py` — explicit branch logic (status assignment, confidence scoring, summary counting)
- `services/checklist_status.py` — uppercase UI-row exhaustive mapping
- `services/checklist_narration.py` — narration skip logic keyed to `required_and_present` only
- `services/exception_aggregator.py` — unchanged (Decision 5 implemented in `checklist_engine.py` instead; see above)
- Frontend: `lib/api.ts` (zod enum instead of loose string), `NdcChecklistReview.tsx`, `Checklist.tsx`, `StatusBadge.tsx`, `format.ts`, `decisionPolicy.ts`, `fixtures/checklistMock.ts`

## Explicitly out of scope (do not touch without separate confirmation)
These are case/field-level states, not checklist-level, and were intentionally left alone in this pass:
- `reviewer.py` case states (`CLEAN`/`CRITICAL`/`HIGH_RISK`/...)
- `routes/decisions.py` (`verified_with_override`/`incomplete`)
- `review/types.py` (`Extracted`/`Flagged`)
- `mapped_verification.py` observation statuses (`MATCH`/`MISMATCH`/`NOT_CHECKED`)

## Tests required
- Update `tests/test_checklist_output.py`: replace `"unknown"` assertions with `"manual_review"` / `"not_evaluated_by_engine"` as appropriate per Decision 4.
- New `tests/test_document_status_model.py`:
  - `test_legacy_unknown_maps_to_manual_review`
  - `test_unmapped_legacy_status_raises` — confirms no silent else
  - `test_ocr_failed_routes_to_manual_review_not_anomaly` — page `ocr_status=failed` → `manual_review`, no anomaly generated
  - `test_ocr_status_thresholds` — empty/short text → `no_text_extracted`; exception → `failed`; digital page → `not_applicable`; **budget-skipped page → `no_text_extracted`, not `not_applicable`**

## Status as of this doc
All decisions above are confirmed and implemented (branch `formalize-status-model`, merged into `development` 2026-09-10), including the budget-skipped → `no_text_extracted` correction.
