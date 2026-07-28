# Output Quality Fixes Required

Review date: 2026-07-13

Scope: issues observed from the latest application run logs and generated output, especially application `41`. This document lists changes required to make the system more reliable, less noisy for reviewers, and clearer when processing is partial.

## Summary

The backend completed the 237-page run, but the output quality needs hardening. The main issues are:

- Legacy duplicate result rendering caused a UI crash.
- OCR timed out on some pages.
- One page recorded a hard OCR processing error.
- Many pages were classified as `Unknown`.
- Reviewer reports are noisy because low-confidence and unclassified-page warnings are shown as many separate issues.
- Missing-document decisions can be too strict when many pages are unclassified.

These are not new product features. They are reliability, reviewer-usability, and output-accuracy improvements.

## Required Changes

### 1. Keep Result Rendering Single-Path

Current issue:
- The legacy UI rendered the same result component more than once in one app run.
- This created duplicate widgets in that UI runtime.

Required change:
- Render uploaded application results only once after all upload tabs.
- Ensure all widgets inside results use stable keys based on `application_id`.

Why this is needed:
- The old tab runtime rendered all tab contents, including inactive tabs.
- Any repeated widget without a unique key can crash the page.
- A reviewer should never lose access to results after a long OCR run because of a UI widget collision.

Expected impact:
- Results page opens reliably after processing completes.
- Future duplicated widgets are less likely to crash the app.

Status:
- Implemented for the observed checkbox issue.

### 2. Show Partial OCR Failure Clearly in the UI

Current issue:
- Page `200` had:
  - `document_type = Property Image`
  - `ocr_confidence = 0.0`
  - `_processing_error = hi/en OCR exceeded hard timeout of 60s`
- The pipeline completed, but some OCR work failed.

Required change:
- Add a clear UI banner when any page has `_processing_error`.
- Show the affected page numbers and error reason.
- Label the overall run as `completed_with_processing_warnings` or similar when the pipeline completes with page-level failures.

Why this is needed:
- A completed pipeline is not always a fully successful pipeline.
- Reviewers need to know which pages need manual attention.
- Without this, a user may trust output that skipped or failed OCR on important pages.

Expected impact:
- Better reviewer trust.
- Faster manual review of failed pages.
- Less confusion between app failure and partial document-processing failure.

### 3. Add Page-Type-Aware OCR Failure Severity

Current issue:
- OCR failure on a `Property Image` page is treated similarly to failures on text-heavy documents.
- A property/GPS/photo page often should not require full text OCR.

Required change:
- Adjust severity by document/page type:
  - PAN, Aadhaar, bank statement, bureau report: high severity OCR failure.
  - Agreement/legal continuation: medium severity.
  - Property image/GPS/photo: low or medium severity, with manual image review.
- For detected image-heavy pages, skip expensive dual-language OCR when text extraction is unlikely to help.

Why this is needed:
- Not all OCR failures carry the same business risk.
- Property photos can be useful visually even when OCR fails.
- This prevents low-risk image pages from making the output look more broken than it is.

Expected impact:
- Cleaner risk scoring.
- Fewer false high-severity errors.
- Faster processing for image-heavy packets.

### 4. Reduce `Unknown` Page Rate

Observed output:
- Application `41` had:
  - Total pages: `237`
  - Unknown pages: `62`
  - Unknown rate: `26.2%`
  - Low OCR confidence pages: `9`

Required change:
- Improve classification rules for common unknown page patterns:
  - Stamp paper pages
  - Hindi legal pages
  - Notary / affidavit pages
  - Property schedule pages
  - GPS map camera pages
  - Legal agreement continuation pages
  - Generic loan-agreement clauses
- Add or tune entries in `data/document_type_registry.json`.
- Improve sequential inheritance for continuation pages.

Why this is needed:
- A high unknown rate weakens checklist confidence.
- Missing-document results may be false if required documents are present but classified as unknown.
- Reviewers get a less useful output when many pages are marked unknown without grouping or explanation.

Expected impact:
- Better checklist accuracy.
- Fewer false missing-document alerts.
- Less manual review effort.

### 5. Collapse Repeated Low-Value Anomalies

Current issue:
- Reports contain many repeated `UNCLASSIFIED_PAGE` and `LOW_OCR_CONFIDENCE` entries.
- These can bury important business issues such as missing documents or field mismatches.

Required change:
- Group repeated quality warnings into page ranges.
- Example:
  - `Pages 38-45: 7 unclassified stamp/legal pages`
  - `Pages 174-186: GPS/property image pages need visual review`
- Keep business exceptions separate from system-quality warnings.

Why this is needed:
- Reviewers need a concise action list.
- Repeated low-level warnings create noise and slow decisions.
- The UI should highlight what changes the loan decision, not every internal uncertainty equally.

Expected impact:
- More readable review screen.
- Better prioritization.
- Faster reviewer decisions.

### 6. Separate Business Checklist Failures From Processing Quality Warnings

Current issue:
- Missing documents, OCR confidence warnings, unclassified pages, and processing errors are shown in one anomaly stream.

Required change:
- Split output into two sections:
  - `Checklist Exceptions`: missing docs, field mismatches, date failures, identity mismatch.
  - `Processing Quality Warnings`: OCR timeout, low OCR confidence, unclassified pages, skipped pages.

Why this is needed:
- A missing PAN and a low-confidence property-photo OCR warning are different types of work.
- Reviewers need to know which issues affect approval and which require manual evidence review.

Expected impact:
- Cleaner UI.
- Better reviewer comprehension.
- Fewer accidental rejections due to technical warnings.

### 7. Add “Possibly Present On Unknown Pages” Logic

Current issue:
- Missing checklist items are declared missing even when many pages remain unknown.
- In application `41`, missing checklist items appeared alongside 62 unknown pages.

Required change:
- Before declaring a required document missing, search unknown pages for weak signals.
- If weak signals exist, show:
  - `Needs manual confirmation`
  - `Possibly present on pages X-Y`
- Keep hard `Missing` only when there is no signal at all.

Why this is needed:
- Prevents false missing-document alerts.
- Makes checklist output more honest when classification confidence is incomplete.
- Helps reviewers inspect the right pages.

Expected impact:
- Better accuracy.
- Fewer false negatives.
- More useful manual review guidance.

### 8. Improve OCR Timeout Strategy

Observed issue:
- Several pages exceeded soft timeout.
- Some pages reached hard timeout.
- Dual-language OCR can double the cost on difficult pages.

Required change:
- Add early triage before OCR:
  - image-heavy/photo page
  - blank/near-blank page
  - stamp/legal page
  - digital text already available
- Run only the needed OCR mode:
  - Hindi only
  - English only
  - dual-language only when justified
- Consider per-page timeout policy based on page type.

Why this is needed:
- Current OCR cost is too high for large 200+ page packets.
- Timeouts reduce output completeness.
- Faster OCR improves user trust and UI responsiveness.

Expected impact:
- Faster processing.
- Fewer hard OCR failures.
- Better runtime predictability.

### 9. Add a Retry Path for Failed Pages

Current issue:
- If one page fails OCR, the whole run completes but that page stays failed.

Required change:
- Add a backend helper to retry failed pages for an application.
- Store retry attempts and final result.
- Add a UI action:
  - `Retry failed OCR pages`

Why this is needed:
- OCR failures can be transient or timeout-related.
- Users should not need to re-upload and reprocess the full 237-page packet for one failed page.

Expected impact:
- Faster recovery.
- Lower compute cost.
- Better operational workflow.

### 10. Make Final Status Reflect Partial Failures

Current issue:
- The backend can complete while page-level failures exist.
- Users may interpret `completed` as “everything worked.”

Required change:
- Use distinct pipeline outcomes:
  - `completed`
  - `completed_with_warnings`
  - `partial_failed`
  - `failed`
- Surface this status in Upload, Worklist, and reports.

Why this is needed:
- Accurate status language prevents overtrust.
- Reviewers can quickly decide whether manual review is required.

Expected impact:
- More honest pipeline state.
- Better auditability.

### 11. Add Output Quality Metrics to the Result Screen

Current issue:
- Quality metrics exist implicitly in page data, but reviewers do not get a compact quality summary.

Required change:
- Add metrics:
  - Total pages
  - Classified pages
  - Unknown pages
  - Low OCR confidence pages
  - OCR failed pages
  - Pages needing manual visual review

Why this is needed:
- Reviewers need to understand confidence before trusting checklist results.
- A single summary helps identify poor-quality uploads.

Expected impact:
- Faster review.
- Better confidence calibration.

### 12. Fix Local Test Execution

Current issue:
- Test commands failed with:
  - `No installed Python found`
- The app appears to run from `.venv`, but the command environment cannot find Python.

Required change:
- Fix Python launcher/path or document the exact test command.
- Add a script such as:
  - `.\run_tests.ps1`
- The script should call the project venv directly.

Why this is needed:
- Code changes cannot be verified reliably.
- Regression risk is higher.
- Future fixes should be backed by automated tests.

Expected impact:
- Safer changes.
- Faster debugging.
- Better confidence before demos.

## Recommended Implementation Order

1. Keep result rendering single-path and add unique widget keys.
2. Add UI banner for page-level processing errors.
3. Split checklist exceptions from processing quality warnings.
4. Collapse repeated `UNCLASSIFIED_PAGE` and `LOW_OCR_CONFIDENCE` anomalies.
5. Add output quality metrics to the result screen.
6. Tune document registry rules for stamp/legal/property/GPS pages.
7. Add “possibly present on unknown pages” logic for missing checklist items.
8. Add page-type-aware OCR severity.
9. Add OCR retry for failed pages.
10. Fix local test execution.

## Acceptance Criteria

The improvements should be considered successful when:

- The result page does not crash after a completed upload.
- Page-level OCR failures are visible and actionable.
- Reports do not list dozens of duplicate unclassified-page warnings.
- Missing documents are not marked hard-missing when likely candidates exist in unknown pages.
- Unknown page rate is lower or at least grouped into explainable categories.
- Reviewers can distinguish business exceptions from processing warnings.
- Tests can run from one documented command.

