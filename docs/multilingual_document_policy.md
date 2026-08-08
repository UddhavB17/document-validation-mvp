# Multilingual Document Classification Policy

## Core rule

Do not infer a language from its script when the script is shared by multiple
languages. OCR and Unicode analysis can reliably say that text is Devanagari;
they cannot reliably say that a short name, address, or form label is Hindi,
Haryanvi, Bhojpuri, Maithili, or Magahi.

## Evidence layers

| Layer | Example | Meaning | Validation weight |
|---|---|---|---|
| Script | `devanagari` | Characters observed in OCR text | Deterministic, but not an exact language |
| Printed declaration | `Second language: Bhojpuri` | Document explicitly names its language | Strong |
| Trusted template/case data | `application_form_languages` | Company knows which template was issued | Strong when source-controlled |
| OCR-provider metadata | `bho`, `mai`, `bgc` | Provider's language estimate | Supporting evidence; retain source |
| Semantic language ID | Probabilities over longer text blocks | Model-based language estimate | Optional; threshold and review required |

Keep the sources separate. Never overwrite OCR text or a printed declaration
with a language inferred from state, branch, applicant address, or stamp-duty
jurisdiction.

## Page and document classification

1. OCR the page with automatic multilingual API detection in production.
2. Preserve original Unicode text and provider metadata.
3. Detect all scripts per page; a page may contain more than one.
4. Classify document type using stable identifiers and structure first: PAN,
   Aadhaar patterns, certificate numbers, account tables, headings, page
   sequence, and continuation evidence.
5. Apply localized keyword packs only as additional evidence. A missing
   translation must reduce confidence, not force `Unknown` when structural
   evidence is strong.
6. Aggregate pages into a document before applying language requirements. One
   page may be English and another regional-language content.
7. For an exact language requirement, prefer the printed declaration or trusted
   template metadata. If only a shared script is available, emit an unverified
   finding for human review.

## Application-form rule

The checklist asks for a second language other than Hindi.

- English plus Gujarati/Gurmukhi/Tamil/etc. script: requirement supported by a
  distinct regional script.
- `Second language: Haryanvi/Bhojpuri/Maithili/Magahi/Bihari`: requirement
  supported by an explicit declaration.
- Devanagari with no declaration/provider/template language: emit
  `APPLICATION_REGIONAL_LANGUAGE_UNVERIFIED`.
- English only, or an explicit Hindi/English declaration with no other evidence:
  emit `APPLICATION_SECOND_LANGUAGE_MISSING`.

## Jurisdiction remains independent

State-specific stamp duty is selected from the observed stamp certificate,
trusted loan/property state, and instrument context. A document's language must
not be used as a substitute for jurisdiction: an Urdu document can be executed
in Haryana, and an English agreement can be stamped in any state.

## Extending coverage

- Add new scripts/ranges and language candidates in
  `services/language_detection.py`.
- Add language names and provider-code aliases without changing validation
  logic.
- Add localized document-keyword packs to the document registry when verified
  examples are available.
- Evaluate OCR and classification separately per script/language/state using a
  labelled test set. Track character/word error rate, document-type accuracy,
  field extraction accuracy, and false validation findings.
