I want to restructure our document classification pipeline for LAP (Loan Against Property) document sets. Currently everything gets pushed through the same OCR → classify → extract flow regardless of content type, which is causing misclassifications (e.g. CIBIL reports flagged as CRIF reports) and wasted compute on non-text content like property photos.
Before writing any code, investigate our current pipeline and report back:

Where the current classification logic lives (file/function names)
What the current flow looks like end-to-end: ingestion → OCR → classification → extraction
What signals (if any) we currently use to distinguish document types
What OCR confidence scores / layout metadata PP-StructureV3 already gives us that we're not using

Then implement the following changes, in this order, as separate reviewable steps:
Step 1: Add a content-type triage stage before detailed classification
Before running full document-type classification, add a lightweight triage step that buckets each incoming file/page into one of three categories:

photo — property images, site photos (low/near-zero usable OCR text, image-like metadata/EXIF, aspect ratio typical of camera photos)
printed_scan — typed/printed documents (dense structured text, high OCR confidence)
handwritten — handwritten bills/notes (sparse/irregular text, low OCR confidence, high character-level uncertainty)

Use OCR confidence scores and text density from our existing PaddleOCR output as the primary signal for this — don't add a new ML model yet, use what our pipeline already produces. Show me the thresholds you pick and why, based on samples from our actual documents.
Step 2: Route each bucket differently

photo → skip text extraction/classification entirely; tag with category metadata (e.g. "property_image") and send straight to storage. Don't waste an LLM call on these.
printed_scan → run through our existing/improved document-type classifier (CIBIL, CRIF, sale deed, etc.)
handwritten → if OCR confidence is below a defined threshold, flag the page as "low_confidence_needs_review" instead of forcing a classification guess. Surface this flag through to the UI/worklist so a human can review it.

Step 3: Fix CIBIL vs CRIF classification specifically using structural anchors
Within the printed_scan bucket, tighten the CIBIL/CRIF distinction using deterministic anchors before falling back to the LLM:

Exact bureau name string match ("TransUnion CIBIL" vs "CRIF High Mark") from OCR text
Score range/format patterns specific to each bureau
Header/layout region matching using PP-StructureV3's layout output, not just raw text search
Only use the LLM as a tiebreaker when these deterministic anchors don't produce a confident match. Show me a few real examples from our documents where CIBIL/CRIF are currently confused, and confirm your anchor logic actually resolves them before finalizing.

Step 4: Add a misclassification logging mechanism
Log every case where the deterministic anchors disagree with the LLM's classification, or where classification confidence is below a threshold, into a simple structured log/table (document id, predicted type, confidence, anchor match results, timestamp). This is for us to build a "confusion set" we can review periodically — don't build a UI for it yet, just make sure the data is captured.
Implement these one step at a time, show me the diff/plan for each step before moving to the next, and don't change unrelated parts of the extraction or validation logic.