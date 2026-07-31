# DMEF Page Classification Diagnostics Report

This diagnostic report analyzes page classification behavior, keyword-matching thresholds, LLM-fallback classification paths, confusion groups, and runner-up candidate conflicts in the DMEF system.

---

## 1. Schema Analysis

We inspected the SQLite database schemas for the `pages` and `classification_review_log` tables in `data/dmef.db`.

### `pages` Table Schema
*   **Columns**: `id`, `application_id`, `page_number`, `page_type`, `image_path`, `is_readable`, `ocr_text`, `ocr_confidence`, `document_type`, `classification_confidence`, `detection_method`, `detected_page_number`, `extracted_fields`.
*   **Stage Guesses**: Only stores the final classification output (`document_type`) and confidence (`classification_confidence`). Initial keyword-stage guesses are not saved if the page falls back to the LLM stage.

### `classification_review_log` Table Schema
*   **Columns**: `id`, `application_id`, `page_number`, `predicted_type`, `confidence`, `reason`, `anchor_match_results`, `llm_document_type`, `created_at`.
*   **Stage Guesses**: This table stores the stage-level details side-by-side:
    *   `predicted_type`: Represents the initial keyword-stage guess.
    *   `llm_document_type`: Represents the LLM-stage override guess.
    *   `confidence`: Represents the keyword-stage confidence score.

---

## 2. Confidence Distribution by Resolution Path

We grouped historical page records from the `pages` table to identify whether they were resolved by the keyword matching stage (`confidence >= 0.85`) or fell back to the LLM classifier (`confidence < 0.85` or `0.0`):

| Document Type | Resolution Path | Page Count | Avg Confidence |
| :--- | :--- | :--- | :--- |
| **Loan Agreement** | `>= 0.85 (Keyword)` | 182 | 0.8965 |
| **Sanction Letter** | `>= 0.85 (Keyword)` | 139 | 0.8975 |
| **Unknown** | `< 0.85 (LLM)` | 139 | 0.0000 |
| **Aadhaar** | `>= 0.85 (Keyword)` | 107 | 0.9491 |
| **Application Form** | `>= 0.85 (Keyword)` | 78 | 0.8853 |
| **CIBIL Report** | `>= 0.85 (Keyword)` | 59 | 0.9881 |
| **Report** | `< 0.85 (LLM)` | 58 | 0.0000 |
| **Task** | `< 0.85 (LLM)` | 58 | 0.0000 |
| **CERSAI Report** | `>= 0.85 (Keyword)` | 45 | 0.9044 |
| **CRIF Report** | `>= 0.85 (Keyword)` | 33 | 0.9818 |
| **KFS** | `>= 0.85 (Keyword)` | 32 | 0.9094 |
| **Facility Agreement** | `>= 0.85 (Keyword)` | 31 | 0.9226 |
| **Technical Report** | `>= 0.85 (Keyword)` | 30 | 0.8750 |
| **Income Tax Return** | `>= 0.85 (Keyword)` | 29 | 0.9328 |
| **OTC PDD Document** | `>= 0.85 (Keyword)` | 22 | 0.9727 |
| **Guarantee Deed** | `>= 0.85 (Keyword)` | 17 | 0.9118 |
| **Loan Agreement** | `< 0.85 (LLM)` | 16 | 0.8137 |
| **PAN** | `>= 0.85 (Keyword)` | 13 | 1.0000 |
| **Property Image** | `>= 0.85 (Keyword)` | 13 | 0.9500 |
| **Valuation** | `< 0.85 (LLM)` | 13 | 0.0000 |
| **Consent Letter** | `>= 0.85 (Keyword)` | 12 | 0.9375 |
| **Facility Agreement** | `< 0.85 (LLM)` | 11 | 0.7650 |
| **Sanction Letter** | `< 0.85 (LLM)` | 11 | 0.7723 |
| **Cheque** | `>= 0.85 (Keyword)` | 9 | 0.9222 |
| **Insurance Form** | `< 0.85 (LLM)` | 9 | 0.7510 |
| **PAN** | `< 0.85 (LLM)` | 9 | 0.7120 |
| **Task 1** | `< 0.85 (LLM)` | 9 | 0.0000 |
| **Bank Statement** | `>= 0.85 (Keyword)` | 8 | 0.9187 |
| **Collateral** | `< 0.85 (LLM)` | 8 | 0.0000 |
| **Property Document** | `>= 0.85 (Keyword)` | 8 | 0.9750 |
| **Stamp Duty** | `>= 0.85 (Keyword)` | 8 | 0.9625 |
| **CIBIL Report** | `< 0.85 (LLM)` | 7 | 0.7650 |
| **Voter ID** | `>= 0.85 (Keyword)` | 7 | 0.9357 |
| **Bank Statement** | `< 0.85 (LLM)` | 6 | 0.7630 |
| **Insurance Form** | `>= 0.85 (Keyword)` | 5 | 1.0000 |
| **Property Document** | `< 0.85 (LLM)` | 4 | 0.7738 |

---

## 3. Disagreement Pairings (Keyword vs. LLM)

Disagreements in `classification_review_log` show where the LLM stage overrode the initial keyword classification:

| Keyword Stage Guess | LLM Stage Override | Count |
| :--- | :--- | :--- |
| **Unknown** | Property Document | 78 |
| **Task** | Property Document | 27 |
| **Aadhaar** | Sanction Letter | 23 |
| **Application Form** | CERSAI Report | 20 |
| **PAN** | PAN Card | 20 |
| **Report** | Loan Agreement | 19 |
| **Unknown** | Loan Agreement | 18 |
| **CRIF Report** | CERSAI Report | 16 |
| **CIBIL Report** | CERSAI Report | 13 |
| **Report** | Sanction Letter | 13 |
| **Application Form** | Sanction Letter | 12 |
| **Report** | CERSAI Report | 12 |
| **KFS** | Loan Agreement | 11 |
| **Unknown** | Sanction Letter | 11 |
| **Application Form** | Loan Agreement | 10 |
| **OTC PDD Document** | Facility Agreement | 10 |
| **Report** | Facility Agreement | 10 |
| **Technical Report** | Property Document | 10 |
| **Aadhaar** | CERSAI Report | 9 |
| **Income Tax Return** | Bank Statement | 9 |

---

## 4. Analysis of Top 5 Confusion Pairings

### Pair 1: `Unknown` $\rightarrow$ `Property Document` (78 occurrences)
*   **Issue**: Scanned Hindi registry pages, stamp papers, or property valuation diagrams did not contain standard English keywords, resulting in low keyword confidence ($< 0.5$) and falling back to `Unknown`. The LLM correctly identified these as Property Documents.
*   **Sample snippets**:
    *   *App 61, Page 39*: `".2378206222 के क पौन प कोभता पिक ी पूका प ती समाज- के की समा आज पिमरे 2 6 222 को म्ववार महाेण मन््र हा ले हु है । जो ि छम आपस मै..."`
    *   *App 61, Page 42*: `"एम०के०जैन स्टाम्प वेन्डर, कालाबा लाoनं० 47/2005 अधिभार 30% ..."`
    *   *App 61, Page 174*: `"GPS Map Camera Semlibakta, Rajasthan, India Google Lat 24.413177° Long 75.923003° 16/06/2026 01:51 PM..."`

### Pair 2: `Task` $\rightarrow$ `Property Document` (27 occurrences)
*   **Issue**: Property registration presentation endorsements and boundary schedules (map/boundary notations) triggered keywords matching generic categories like `Task` or `Report`, which the LLM then overrode to `Property Document`.
*   **Sample snippets**:
    *   *App 65, Page 422*: `"तोमांकन : उत्तर 2भामलल का मन दक्षिण पर् जगारमती5 मा पश्िम ्ीश मम मानचित्र: अंहचित्ंेद्शित भूमि लाल स्याही से सीमाकित है।)"`
    *   *App 65, Page 423*: `"Presentation Endorsement आज दिनांक 05 मार 01 मन 2022 को 03:01 PM बजे भी/थीभती/मुथी UNKAर LAL पुच/पुथी/पडि थीKANHA..."`
    *   *App 65, Page 424*: `"Endorsement of Execution अनुक. पधकारों का नाम व पता..."`

### Pair 3: `Aadhaar` $\rightarrow$ `Sanction Letter` (23 occurrences)
*   **Issue**: Legal agreement or sanction letter pages that contain standard KYC compliance paragraphs mentioning Aadhaar (e.g. *"Borrower agrees to provide Aadhaar and PAN"*) trigger keyword-matching rules for Aadhaar identity cards.
*   **Sample snippets**:
    *   *App 61, Page 54*: `".नवे( के 1लए, न ही .कसी सpा, असामाAजक #ा..."`
    *   *App 61, Page 88*: `"R. Compliance of ‘Know your customer ("KYC”) Policy": The Borrower agrees to provide to the Lender Aadhaar, PAN and such further documents as may be required..."`

### Pair 4: `Application Form` $\rightarrow$ `CERSAI Report` (20 occurrences)
*   **Issue**: Digital agreement/indemnity pages containing terms related to the creation of charges or applicant representations triggered keyword filters for the `Application Form` but were resolved as CERSAI search reports.
*   **Sample snippets**:
    *   *App 61, Page 153*: `"(vi) #Vद उ ारक0ा$ अ2वा 5;#ाभू.0..."`
    *   *App 61, Page 156*: `"5ा कारी भी सîàम1ल0..."`

### Pair 5: `PAN` $\rightarrow$ `PAN Card` (20 occurrences)
*   **Issue**: DigiLocker PAN Verification records matched keywords for the keyword category `PAN`, but normalizes to `PAN Card` after classification overrides/aliasing.
*   **Sample snippets**:
    *   *App 61, Page 7*: `"PAN VERIFICATION RECORD Permanent Account Number BCXPL9010K NAME PEERU LAL GENDER MALE..."`
    *   *App 61, Page 181*: `"आयकर विभाग INCOME TAX DEPARTMENT भारत सरकार GOVT OF INDIA Permanent Account Number Card BCXPL9010K..."`

---

## 5. Close Runner-Up Matching Conflicts

The keyword classification engine `document_classifier.py` exposes top candidates and their scores via `candidate_scores` in its return dictionary. However, this is not stored historically in the database.

By re-running `classify_page` over the OCR text of all **892 keyword-resolved pages** (confidence $\ge 0.85$), we identified **9 pages** where the second-best score was within `0.1` of the winning score:

| App ID | Page Number | Winner Type (Score) | Runner-Up Type (Score) | Diff |
| :--- | :--- | :--- | :--- | :--- |
| **61** | 55 | KFS (1.0) | Loan Agreement (1.0) | 0.000 |
| **61** | 195 | Passbook (1.0) | Cheque (1.0) | 0.000 |
| **63** | 55 | KFS (1.0) | Loan Agreement (1.0) | 0.000 |
| **63** | 195 | Passbook (1.0) | Cheque (1.0) | 0.000 |
| **64** | 55 | KFS (1.0) | Loan Agreement (1.0) | 0.000 |
| **64** | 195 | Passbook (1.0) | Cheque (1.0) | 0.000 |
| **65** | 28 | KFS (1.0) | Loan Agreement (1.0) | 0.000 |
| **65** | 158 | KFS (1.0) | Loan Agreement (1.0) | 0.000 |
| **65** | 288 | KFS (1.0) | Loan Agreement (1.0) | 0.000 |

### Key Observations:
*   In all 9 conflict cases, the difference was exactly `0.000`, meaning both classification rules scored a maximum confidence of `1.0` simultaneously.
*   This represents a rule design collision:
    *   **KFS vs. Loan Agreement**: Both rules match text structures on the same page with maximum confidence.
    *   **Passbook vs. Cheque**: Both rules match header keywords on the same page with maximum confidence.

---

## Summary Diagnostic Findings

1.  **Skew of Wrong Labels**: 
    *   Most classification corrections originate from pages that fall back to the low-confidence LLM stage (`confidence < 0.85` or `0.0`) because they represent scanned registry pages, property photos, or documents in regional languages (Hindi) that do not match the keyword rules.
    *   There is a minor set of conflicts on high-confidence keyword matches (confidence $\ge 0.85$) due to overlaps in KYC warning text across agreements or literal keyword clashes (e.g. KFS vs. Loan Agreement).
2.  **Exposing runner-up metrics**:
    *   The `document_classifier.py` script already computes and exposes the second-best candidate scores, but the database schema does not persist them.
    *   We were able to extract this metric by running the classification function on demand against the database's cached page `ocr_text`.
