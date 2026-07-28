# Branch Changes (July 22, 2026 – Present)

This document summarizes all modifications, features, and fixes implemented in this branch from July 22, 2026, to today.

---

## Summary of Major Changes

### 1. UI & Frontend Enhancements (Evidence Viewer & Severity Styling)
* **Evidence Panel Hoisting & Stacked Views:** Hoisted `EvidenceViewer` into a global side panel beside tabs, allowing multi-page layouts with page tags and concatenated OCR text.
* **Interactive UI Integrations:** Clickable page tags are now wired into the checklist tables, manual reviewer summaries, and log history tables, enabling instant document review.
* **Severity & Visual Styling:** Distinct background and text coloring added for anomaly severity levels (`HIGH`, `MEDIUM`, `LOW`) inside checklists, AI findings banner, and table rows. Rule IDs and document type badges are displayed directly inside lists.
* **Collapsible App Layout:** Implemented collapsible sidebar navigation in `AppShell` to maximize screen real estate for document evidence.
* **Sticky Layout Adjustments:** Added sticky behavior to the sidebar and `SortableTable` headers, fixed items-start alignment in the evidence grid, and implemented automatic centering during page scrolling.

### 2. LLM, TOON Format, and Extraction Updates
* **LLM Summary & Page Classifier Migration to TOON:** Replaced legacy response schemas with structured Token-Oriented Object Notation (TOON) for application summaries and page classification. This includes TOON schemas and `toon.decode` parsing logic.
* **XML Signature Filtering:** Updated the text extraction process to filter out noisy XML signature code blocks.
* **Confidence & Budget Tuning:** Raised default classification confidence thresholds to `0.85` and max scanned page budget to `300` pages to prevent high-confidence LLM classification outcomes from being discarded.

### 3. Verification & Business Rule Optimization
* **Multi-person Identity Support:** Fixed identity-matching conflicts when validating loans with multiple applicants (primary borrower vs. co-applicants) by populating references properly.
* **False Positive Reduction:** Reduced pipeline anomalies originating from noisy OCR outputs and minor text matching differences.
* **Reprocessing Recovery Module:** Implemented a new background job runner in `reprocessing.py` to allow safe, automated recovery of crashed, stale, or incomplete PDF pipeline jobs.
* **Date Parsing & Canonical Aliases:** Enabled robust date parser variations and validation against canonical aliases for borrower identities.
* **Missing Documents Excluded from Lists:** Segregated missing checklist documents from standard field anomalies to provide a cleaner layout for active issues.

### 4. Operations & Settings Dashboard
* **Dynamic Configuration Dashboard:** Added a new Operations Settings panel page `/settings` with direct backend database bindings allowing users to configure system parameters dynamically.

---

## Detailed Commit Log

Below is the chronological log of commits and modified files since July 22, 2026:

### [cecf308d] feat: support stacked multi-page document views combined inside EvidenceViewer side panel with page tags and concatenated OCR text
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)

### [157fefa7] feat: hoist EvidenceViewer to global side panel next to tabs, and make pages interactive buttons in checklist, manual reviewer summary, and logs tables
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)

### [b3395108] feat: apply distinct background and text colors depending on anomaly severity levels
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)

### [fe88edf7] feat: display severity indicator inside AI findings banner and anomaly checklist tables
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)

### [ab35a231] feat: display anomaly category rule ID in AI page-by-page findings and add document type badges to anomaly checklists
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)

### [938accf0] feat: implement collapsible left navigation sidebar in AppShell and expand evidence page viewer size
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)
  * [frontend/components/AppShell.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/components/AppShell.tsx)

### [076c2339] fix: make sidebar sticky, fix evidence grid items-start alignment, add auto-scroll view centering, and make SortableTable headers sticky
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)
  * [frontend/components/AppShell.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/components/AppShell.tsx)
  * [frontend/components/SortableTable.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/components/SortableTable.tsx)

### [64b60551] fix: increase default confidence to 0.85 and raise default page budget to 300 to prevent LLM results from being discarded
* **Modified Files:** 
  * [services/llm_page_classifier.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/llm_page_classifier.py)

### [e6435f3a] fix: convert page classifier to TOON format and add alias-normalizer helper to prevent discarded classifications
* **Modified Files:** 
  * [services/llm_page_classifier.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/llm_page_classifier.py)
  * [tests/test_llm_page_classifier.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/tests/test_llm_page_classifier.py)

### [8548fa76] fix: resolve multi-person identity verification mismatches by populating reference_data in system_data
* **Modified Files:** 
  * [routes/upload.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/routes/upload.py)
  * [services/pipeline.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/pipeline.py)
  * [tests/test_checklist_engine.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/tests/test_checklist_engine.py)

### [ecd98357] fix: reduce false positive anomalies from OCR/classification noise
* **Modified Files:** 
  * [services/automatic_document_index.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/automatic_document_index.py)
  * [services/checklist_engine.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/checklist_engine.py)
  * [services/field_extractor.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/field_extractor.py)
  * [services/field_verification.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/field_verification.py)
  * [services/mapped_verification.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/mapped_verification.py)
  * [tests/test_field_extractor.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/tests/test_field_extractor.py)

### [8475e014] Implement structured LLM summary using TOON format and filter out XML signatures from text extraction
* **New Files:** 
  * [.agents/AGENTS.md](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/.agents/AGENTS.md)
  * [tests/test_llm_toon_summary.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/tests/test_llm_toon_summary.py)
* **Modified Files:** 
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)
  * [requirements.txt](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/requirements.txt)
  * [services/llm_service.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/llm_service.py)
  * [services/text_extractor.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/text_extractor.py)
  * [tests/test_text_extractor.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/tests/test_text_extractor.py)

### [1beb78d6] Improve review operations workflow
* **New Files:**
  * [services/reprocessing.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/reprocessing.py)
  * [tests/test_review_operations.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/tests/test_review_operations.py)
* **Modified Files:**
  * [frontend/app/applications/[id]/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/applications/[id]/page.tsx)
  * [frontend/app/upload/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/upload/page.tsx)
  * [frontend/app/worklist/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/worklist/page.tsx)
  * [frontend/components/ProgressPanel.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/components/ProgressPanel.tsx)
  * [frontend/lib/api.ts](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/lib/api.ts)
  * [frontend/lib/queries.ts](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/lib/queries.ts)
  * [routes/review.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/routes/review.py)
  * [services/progress_tracker.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/progress_tracker.py)
  * [services/reviewer.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/reviewer.py)
  * [tests/test_reviewer_exceptions.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/tests/test_reviewer_exceptions.py)

### [5746eeb9] feat: support canonical key aliases and validators in other owner resolution
* **Modified Files:**
  * [services/mapped_verification.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/mapped_verification.py)

### [33ade97c] feat: support robust date parsing in field verification
* **Modified Files:**
  * [services/field_verification.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/field_verification.py)

### [1827366a] feat: exclude missing documents from anomalies and flags list
* **Modified Files:**
  * [services/exception_aggregator.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/exception_aggregator.py)
  * [services/pipeline.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/pipeline.py)

### [39612b67] feat: implement operations settings dashboard and classifier accuracy improvements
* **New Files:**
  * [frontend/app/settings/page.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/app/settings/page.tsx)
  * [routes/settings.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/routes/settings.py)
* **Deleted Files:**
  * `data/logs/backend.err.log`
  * `data/logs/backend.out.log`
* **Modified Files:**
  * [.env.example](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/.env.example)
  * [.gitignore](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/.gitignore)
  * [database/db.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/database/db.py)
  * [database/models.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/database/models.py)
  * [frontend/components/AppShell.tsx](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/frontend/components/AppShell.tsx)
  * [main.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/main.py)
  * [services/config.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/config.py)
  * [services/field_extractor.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/field_extractor.py)
  * [services/llm_client.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/llm_client.py)
  * [services/llm_page_classifier.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/llm_page_classifier.py)
  * [services/mapped_verification.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/mapped_verification.py)
  * [services/ocr_engine.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/ocr_engine.py)
  * [services/pipeline.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/pipeline.py)
  * [services/structured_llm_classifier.py](file:///c:/Users/siddd/Documents/MS-fincap/document-validation-mvp/services/structured_llm_classifier.py)
