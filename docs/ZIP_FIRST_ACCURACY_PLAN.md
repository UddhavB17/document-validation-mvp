# ZIP-first intake and evidence accuracy

Requested 12 September 2026. This plan precedes implementation and assigns
independent work to GPT-5.6 Luna agents; the coordinating agent integrates and
reviews the combined changes.

## Outcome

Original-document ZIP intake is the default program workflow. Source files keep
their boundaries and page context. Low-confidence evidence produces a specific
review request rather than an unsupported missing-document finding. AI review
completion is distinguishable from a successful provider response.

## Existing work to preserve

The checkout already contains uncommitted repairs in automatic_document_index,
consistency_checks, field_extractor, field_verification, person_names, pipeline
classification/page_processing/persistence and application validation regression
tests. Preserve these changes, test them with the new work, and do not overwrite
or claim them as newly implemented. Existing saved applications are not rerun.

## Implementation order and ownership

1. **Intake UI (agent intake_ui).** Own frontend/app/admin/upload/page.tsx,
   frontend/components/upload/* and focused frontend intake tests. Make ZIP
   Package Intake the default and first option; retain Mapped Verification as a
   secondary option. Remove PDF Upload and Partner JSON Intake from navigation
   without deleting their backend interfaces or unrelated code. Clarify the
   prepare → inspect original-file inventory → trusted-data verification flow.
   Preserve form state when switching modes and prevent stale result display.
   Verify file selection, busy/error/reset states and keyboard accessibility.
2. **Presence accuracy (agent presence_accuracy).** Own services/page_quality.py,
   services/checklist_engine.py, services/checklist_status.py,
   services/checklist_output.py, services/checklist_status_map.py and their
   focused tests. Introduce an evidence assessment shared by presence findings
   and checklist rows: accepted evidence, candidate evidence requiring review,
   insufficient scan coverage, or no evidence found. Retain candidate pages and
   reasons, including borrower uncertainty; do not let another borrower's
   document satisfy a requirement. Use existing manual_review/REVIEW_REQUIRED
   vocabulary where possible. Keep thresholds and content anchors for verified
   presence. Test scoped, alternative, all-document and minimum-count checks,
   incomplete/unreadable scans and real absence. Presence does not certify
   execution, validity or required field values.
3. **AI review reliability (agent ai_review).** Own services/ops_llm_review.py,
   services/llm_service.py, services/review_prompts.py and focused tests. Diagnose
   invalid-output handling, retain successful bounded exception batches, make
   partial/failed/completed review explicit with actual model and bounded safe
   failure categories in the object-store audit. Repair recoverable malformed
   output without inventing evidence or weakening dismissal gates. Ensure a
   failed summary/translation does not erase valid reviewed-batch evidence.
   No new whole-file model pass, secret changes, live provider calls or automatic
   loan acceptance. Expose clear user summary text using existing payload fields.
4. **Boundary integrity and integration (coordinator).** Own source-boundary
   fixes only where necessary in pipeline/evidence resolution plus new
   benchmark fixtures/tests, operations presentation alignment, runtime startup
   documentation and this plan. Verify original-file ranges survive normal and
   cached processing and prevent cross-file inheritance. Add a controlled
   ZIP-versus-combined-document regression benchmark with fixed OCR, explicit
   expected facts, and real mismatches that must remain flagged. Inspect the
   existing targeted recovery path and repair concrete gaps without introducing
   a blanket second model review. Make the selected runtime model unambiguous
   in launch instructions; do not silently override configured operator choices.

## Verification gates

- Each agent runs meaningful tests for its observable behavior using isolated
  SQLite and local temporary storage, never the configured production database.
- Coordinator reviews all diffs and runs the combined backend suite, Ruff,
  frontend typecheck/lint/tests and whitespace checks.
- Check the real intake interface in the local browser, including default ZIP,
  mapped alternative, responsive rendering and error/reset transitions.
- Validate ZIP preparation/verification end to end against a temporary local
  app/test fixture; do not submit real customer files or modify saved decisions.
- Measure improvement by corrected evidence and retained real discrepancies,
  not by an arbitrary reduction in exception count.

## NEEDS-COORDINATION

The user's 12 September request authorizes these cross-stream changes and makes
the owners above authoritative for this task. Preserve existing DB, object-store,
auth and payload contracts. Prefer existing review states; coordinate any new
field before adding it. No push, deployment, live worker restart or saved-case
reprocessing is included in this request.

## Results

Implemented in the working checkout. All three agents were started as
GPT-5.6 Luna with xhigh reasoning, as requested. They hit the account usage
limit before completion; the coordinator reviewed their partial work,
simplified the presence implementation, finished integration, and verified it.

- Intake opens on ZIP Package Intake with Mapped Verification as the only
  alternate tab. Preparation, original-file inventory and trusted-data
  verification are explicit steps. File selection survives mode changes;
  results are cleared between flows and busy operations disable navigation.
- Cached pages recover source provenance before sequence smoothing; source
  inventory starts also reset context when a caller omits a separate starts set.
- Low-confidence candidates, uncertain borrower ownership, and unreadable
  unidentified pages yield review-required findings with page evidence.
  Confident presence thresholds, real missing documents and unique-cheque
  minimum checks remain enforced. This does not certify document execution or
  validity and does not deduplicate arbitrary document-count requirements.
- AI exception review retains valid batches when another batch or summary
  fails. Invalid batches receive one bounded retry with the validation reason.
  The durable report records coverage, reviewed/unreviewed references, actual
  configured runtime model and safe failure categories. Summaries state
  completed/partial/failed review; fallback English/Hindi text remains matched.
  Evidence quotation and conservative automatic-dismissal gates remain intact.
- Operations checklist reconstruction restores saved ownership and trusted
  applicability inputs and preserves candidate page links.

### Verification evidence

- Backend: **1,218 passed, 3 skipped, 1 deselected** in isolated SQLite and local
  temporary storage. The deselected test is the live GCS roundtrip; no live
  provider calls were made. Two fixtures were clarified: the scanned-language
  test now supplies OCR confidence, and the mocked Ollama classifier test
  explicitly selects Ollama rather than inheriting an operator's provider.
- Frontend: **83 tests passed**, typecheck and lint passed. Ruff and
  `git diff --check` passed.
- Real browser: ZIP default and two-tab navigation confirmed; choosing a
  synthetic ZIP enables preparation; switching modes preserves that selection.
  The 390-pixel mobile layout was visually checked. Test selection and viewport
  were reset afterward. No upload was submitted to the configured live backend.
- Existing isolated route tests passed for background preparation/progress,
  stable inventory persistence, mapping validation, verification queueing and
  duplicate-submission rejection. Browser preparation/error/reset transitions
  after a submitted upload were not exercised against the live backend.
- New fixed-OCR regression covers ZIP and combined PDF classification,
  extraction, borrower evidence resolution, indexing and mapped comparison,
  including cached processing. A deliberately wrong DOB remains flagged.
- A read-only replay of the saved 375-page case's presence checks now produces
  `REVIEW_REQUIRED_S22` for insurance pages **173–174**, with a `manual_review`
  checklist row. This specifically verifies the former false missing-document
  claim; it is not a measured whole-program false-positive rate.

### Runtime boundary

The running app reported Gemini 2.5 Flash as the active provider model even
while another settings section displayed Gemini 3.8 Flash. Launch guidance in
`run.md` now specifies the existing Gemini 3.8 wrapper for both API and worker.
No environment values were changed, workers restarted, saved applications
reprocessed, or production decisions changed. A fresh run under the intended
runtime is still needed to verify live Gemini 3.8 output quality. The checked-in
regression fixtures establish deterministic behavior, not live model quality.
