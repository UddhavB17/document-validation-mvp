# Performance Fix Log — running record

Companion to `docs/PERFORMANCE_FIX_PLAN.md` (plan) and
`docs/PERFORMANCE_AUDIT.md` (findings). One entry per solved item, written
immediately after verification. Protocol: implement → verify → log → **user
approval gate** → next item.

---

## Item 1 — P4: Classifier normalized the full page text once per registry rule (85×/page)

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low (pure CPU
restructure, no behavior change intended)

### What was solved

`services/document_classifier.py` scored every page against all 85 registry
rules, and each rule re-normalized the entire page OCR text (NFKC fold +
per-character category loop + whitespace squash), re-normalized the 24-line
heading area, and re-normalized every opening line twice. Per page that was
~85 full-text normalizations + 85 heading-area normalizations + 2 × lines × 85
line-normalizations — pure repeated CPU on the per-page hot path.

Now:

- `classify_page_with_candidates` computes the three per-page values **once**:
  - `normalized` (full text),
  - `heading_area` (first 24 lines, with the same `normalized[:2000]`
    fallback),
  - `normalized_opening_lines` (all lines normalized once, walrus form replacing
    the old listcomp that normalized each line twice — once for the filter and
    once for the value).
- `_score_rule(text, rule, *, normalized=None, heading_area=None,
  normalized_opening_lines=None)` accepts the precomputed values (keyword-only,
  optional, computed when omitted) — so `classify_page_with_candidates` passes
  them down, and the pre-existing two-argument caller
  `tests/test_classifier.py::…::_score_rule(text, rule)` keeps working
  unchanged.
- `_has_explicit_opening_heading(..., normalized_lines=None)` accepts the
  precomputed line list and slices inside (rules can request different
  `opening_heading_lines`, so slicing stays per rule).
- `_normalize_text` gains a small LRU fast path: strings ≤ 256 chars
  (headings, keywords, OCR lines — repeated across every page and rule) are
  served via `@lru_cache(maxsize=8192)`; full page texts stay uncached so the
  cache stays small and page-text-sized strings never occupy it. This also
  makes `_contains` term-normalization (line 564) and heading normalization
  (`_heading_score`, `_has_explicit_opening_heading`) near-free repeats.

Net effect: full-text normalization per page goes 85× → 1×; heading area
85× → 1×; opening lines 2×85×lines → 1×lines; all repeated short-string
normalizations (headings/terms/lines) become cache hits after the first page.

### Challenges

1. **`.env` carries the production Neon `DATABASE_URL`, and the suite's
   remote-DB guard refuses to run** (`tests/conftest.py:109-129` — correct and
   desirable: the suite truncates every table). Clearing the variable in the
   shell wasn't enough because an empty assignment removes it and
   `database/db.py`'s `load_dotenv()` (override=False) repopulates it from
   `.env` at import. Local full-suite runs need `DATABASE_URL` preset to a
   non-empty blank value (e.g. a single space, which `strip()`s to `""`) so
   dotenv leaves it alone and the wrapper falls back to SQLite temp files —
   the documented test configuration. This matters beyond tests: **the API as
   currently configured runs against Neon**, which makes every per-call
   connection / N+1 finding (A5, A7, A10) cost a network round trip, not just
   a local one.
2. **Full suite runtime:** the backend suite exceeds 15 minutes locally, so it
   runs in the background; the item was gated on the focused
   classification/pipeline tests plus ruff while it completes (result appended
   below when finished).
3. **Edit-tool exactness:** three match attempts failed on
   `matched: list[...]` typing and on assuming a blank line after `matched`
   (the real blank line is after `score = 0.0`) — trivial, but a reminder to
   match from the freshly read file rather than memory.

### Verification

- `pytest tests/test_classifier.py -q` — 59 passed (pre-full-suite gate).
- `pytest tests/test_classifier.py tests/test_document_classifier_registry.py
  tests/test_page_classification.py tests/test_page_sequence_classification.py
  tests/test_pipeline.py -q -p no:cacheprovider` — 95 tests, no failures.
- `ruff check .` — all checks passed.
- Full suite (`python -m pytest -q` with `DATABASE_URL` blanked): not
  completed; see appended result.

### Result appended after full suite

- Full suite: not completed in this run. `python -m pytest -vv --durations=20`
  reached `tests/test_auth.py::test_login_success_returns_token_and_user`
  and stopped producing output; the command was interrupted without a test
  summary. No failing assertion was reported.
- Fresh focused run: `tests/test_classifier.py` and
  `tests/test_document_classifier_registry.py` — passed (97 tests).
- `ruff check .` — all checks passed (Ruff also printed an access-denied
  warning while scanning a protected pytest temp directory).

---

## Item 2 — P16: Remove mid-loop `gc.collect()`

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low

Removed the explicit collection every five pages from
`services/pipeline/page_processing.py`. Python's normal garbage collection
continues to manage allocations; this avoids forcing a stop-the-world scan in
the latency-sensitive page loop. A source scan confirms no `gc.collect()`
remains in that module. Ruff passed for both changed backend modules. The
pipeline test module did not return a summary in this environment and was
interrupted; see the verification limitation above.

---

## Item 3 — P13: Cache required-status fallback normalization per page

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low

The required-status accuracy check now computes `_page_status` once per page
for its accepted/rejected status term batch. Passing-status checks,
unverifiable-fallback diagnostics, rejection-term checks, and the final
anomaly value reuse that cached normalized value. The optional status
arguments preserve existing helper call behavior for other callers.

Added a regression test asserting one status computation per document page.
`tests/test_checklist_engine.py` — 41 passed, including existing status
behavior tests. Ruff passed for the implementation and test module.

---

## Item 4 — P9: Precompute compacted page text for evidence lookup

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low-medium

`run_consistency_checks` now builds a page-number-to-compacted-OCR map once
per run and threads it through observation collection to supporting-page
search. `_page_text_supports_value` accepts a precompacted page value, keeping
the prior normalization path for callers that do not supply one. This removes
repeated whole-page compaction while preserving the same substring and name
fallback checks.

Added a focused test proving the precompacted value is used. The full
`tests/test_consistency_checks.py` module passed, and Ruff passed for both
changed files.

---

## Item 5 — P10: Memoize field reliability decisions per processing run

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** medium

`field_reliable_for_validation` now accepts an optional cache and uses a
context-scoped cache when invoked through the consistency, mapped-verification,
or ownership entry points. Keys include the page identity and OCR text hash,
canonical field, value, and effective document type so one page's decision is
reused without crossing page or validation contexts. Nested operations share
the outer run's cache, which resets on exit, including exceptions.

Added a test proving repeated calls hit once inside the scope and recompute
after the scope closes. `tests/test_validation_gates.py` and
`tests/test_consistency_checks.py` passed; Ruff passed for all touched backend
modules and tests.

---

## Item 6 — A3: Replace batch-status N+1 queries with one join

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** medium

`GET /upload/batch/{id}` now loads each job with its latest uploaded filename
and progress percentage using one query with a progress join and filename
subquery. The separate rejection query remains, so batches containing rejected
files retain the same response behavior. Added a direct route test that
verifies the two-query bound and response fields without depending on auth
startup. The test passed; Ruff passed for the route and test.

---

## Item 7 — A10: Hoist ZIP limits and snapshot upload settings

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low

ZIP member validation now reads the maximum expanded bytes and file count once
before walking archive entries; page-count limits are read once before the
normalization loop. Added `with_cached_settings` for sync/async operation
scopes and applied it to upload endpoints, so their settings lookups share a
single short-lived snapshot. ZIP normalization also owns a snapshot when used
outside the routes.

`tests/test_zip_package.py` — 9 passed. FastAPI app import succeeded with 18
registered routes, and Ruff passed for the changed modules.

---

## Item 9 — F4: Make ZIP preparation polling visibility-aware and non-overlapping

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low

Replaced the fixed interval with an immediate, self-scheduling timeout loop.
The hook skips requests while the tab is hidden, polls immediately when it
becomes visible, and uses an in-flight guard to prevent overlapping requests.
Terminal progress and errors stop the loop; cleanup cancels the timer and
visibility listener.

Frontend typecheck and lint passed; the frontend test suite passed (86 tests).

---

## Item 10 — F5: Debounce worklist search URL updates

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low

The worklist search now keeps immediate input state and updates the URL after
300 ms of inactivity. Browser navigation synchronizes the input from the URL,
and clearing the search follows the same debounced path. Filter and sort
updates remain immediate.

Frontend typecheck, lint, and tests passed (86 tests).

---

## Item 12 — F7: Cache parsed LLM summaries

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low

`parseLlmSummary` now keeps a 64-entry LRU-style cache keyed by the trimmed
summary string, including cached parse failures. Repeated issue rows reuse the
same parsed summary object; older entries are evicted when the cap is reached.

Added a parser cache regression test. Frontend typecheck and lint passed; the
frontend test suite passed (87 tests).

---

## Item 11 — F6: Stop the decision undo countdown after expiry

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low

`useUndoRemainingSeconds` now avoids starting its interval when the decision is
already expired or has an invalid timestamp, and clears the interval on the
first tick at the expiry boundary. Cleanup still clears active timers when the
decision changes or the component unmounts.

Frontend typecheck, lint, and tests passed (86 tests).

---

## Item 8 — A9: Add missing query indexes

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low-medium

Added six indexes for job heartbeats, loan IDs, validation status, OCR event
time/type, and audit timestamps to SQLite `INDEX_STATEMENTS` and added
Alembic revision `0009_performance_indexes` for Postgres parity. Index names
and definitions are aligned between both dialects.

`tests/test_schema_parity.py` initialized the SQLite schema and skipped its
Postgres comparison because this test run uses SQLite. Ruff passed. A scratch
Postgres migration check was not available because no test Postgres endpoint
was configured.

---

## Item 13 — F8 + A14: Admin-only health polling and a short server cache

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** low-medium

Moved `useHealth()` into the admin-only API health widget, so operations users
do not poll an indicator they cannot see. `/health` now caches its payload and
HTTP status for five seconds per process; cached failures retain HTTP 503.
Health tests reset the module cache and use an in-memory healthy store to avoid
external storage calls.

Five health endpoint tests passed, covering cached probe reuse, expiry,
degraded worker status, and both database/storage 503 paths. Ruff and frontend
typecheck, lint, and tests passed (87 tests).

---

## Item 14 — A1: Move blocking upload work off the event loop

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** medium-high

Converted the upload HTTP handlers and their upload-byte helpers to synchronous
functions. FastAPI now dispatches their PDF/ZIP validation, database,
object-store, and queued-work setup through its sync threadpool. Bounded reads
still enforce the configured byte limits. The batch endpoint continues to
create and enqueue one job for each accepted file while building the same
response shape.

Added a route invariant asserting there are no coroutine upload endpoints.
That check and the upload-limit tests passed (6 tests total); Ruff passed for
all touched files. Full route integration tests that start the configured
storage backend remain part of final verification.

---

## Item 15 — A2: Defer PDF checksum work to the worker

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** medium

`persist_job_input` no longer rereads the entire PDF in the enqueue request; it
stores an empty checksum placeholder. The worker's first `load_job_input`
records the checksum for the source it stages, and later recovery runs verify
against that persisted checksum. Settings snapshots now read through the
request's `cached_settings()` scope, so multiple jobs in one batch share the
same settings table scan.

Added a regression test that fails if enqueue calls `_source_checksum`.
Recovery, object-store restore/integrity, pipeline task, and config lookup
performance tests passed (15 tests); Ruff passed for the changed backend files.

---

## Item 16 — A4: Cache checklist parsing and persist comparison matrices

**Status:** solved · **Date:** 2026-11-12 · **Risk class:** medium

Checklist JSON is cached by resolved path, modification timestamp, and size;
callers receive deep copies so downstream checklist mutations cannot corrupt
the shared cached value. Added a `reviewer_comparisons` table with a matching
Alembic migration, archive registration, and schema parity coverage. Pipeline
finalization persists the generated matrix and relationships; completed review
requests reuse that result, while active applications continue to compute from
current data. Persistence errors are logged and remain recoverable by rebuilding
the view.

The checklist cache tests and comparison/schema tests passed (9 passed, 1
Postgres-only skip). Ruff passed. A Postgres migration run was unavailable in
this environment.

---

## Items 17–25 and 27–28, 30, 32, 38–40 — additional scoped optimizations

**Status:** partial · **Date:** 2026-11-12

Implemented the following parts from later plan items:

- Item 17: ops page loading no longer selects `ocr_text`; parsed ops AI
  assessments are reused for 30-second windows. The requested single-connection
  payload load and skip-when-empty assessment shortcut remain outstanding.
- Item 18: ops worklist accepts bounded `limit`/`offset` pagination and a total
  count; reviewer anomaly dedupe uses recursively frozen tuple keys instead of
  JSON serialization. Other review lists still need pagination.
- Item 19: spend rollups share one DB connection, use it for table checks, and
  cache results for 30 seconds keyed by active database engine.
- Item 20: verification queries select named page and anomaly columns, avoiding
  OCR text in the result set.
- Item 21: spend table checks reuse their caller's connection; intake document
  rows use `executemany`.
- Items 22–23: Gemini model lists have a ten-minute TTL; JWT signing secrets are
  cached per process.
- Item 24: session bootstrap returns the verified profile in the same response;
  verification shares in-flight and 60-second cached outcomes keyed by a
  SHA-256 token digest. Outage outcomes are evicted.
- Item 25: evidence image fetches accept DPI and AbortSignal; source-page proxy
  responses receive content-derived ETags and return 304 on a match.
- Item 26: evidence modal, ops evidence wizard, and settings tab panels are
  dynamically imported so their code is loaded on demand.
- Item 27: removed body blend mode and reduced header blur. Item 28: relationship
  connectors animate only while hovered, with keyframes in global CSS.
- Item 29: classification and OCR controls use optimistic local values and a
  300 ms save debounce; explicit API key and language-hint save buttons remain
  immediate.
- Item 30: removed two unreferenced evidence/checklist components.
- Item 32: ADC Vision client is cached by endpoint; REST batch requests remain
  outstanding.
- Item 38: language profiles are computed once per application page in the
  second-language check.
- Item 39: fast OCR reuses a bounded module-level executor; image-dimension
  header reuse remains outstanding.
- Item 40: finding document-type regexes are compiled once per finding.

Frontend typecheck, lint, and tests passed (87 tests). Backend Ruff passed.
Focused spend, checklist, comparison, and consistency tests passed; a broader
backend run stalled after 43 tests without a summary. A Google Vision test run
printed a Windows fatal-exception diagnostic while pytest still returned zero,
so that run is not considered clean. Items 31 and 33–37, and the outstanding
subparts above still need implementation.
