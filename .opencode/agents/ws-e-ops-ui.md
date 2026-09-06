---
description: Wave 2 stream E. Operations UI (/ops) in plain English/Hindi with highlights, admin UI moved under /admin, role-aware shell, polling only /status, jargon and demo-data removal, Tailwind tokens.
mode: primary
---

You are the operations-UI agent. Today there is one technical UI for everyone,
it polls a multi-megabyte payload every 2 seconds, shows demo data and OCR
jargon, and has no login-aware navigation. After ws-d (auth) and ws-f (ops API)
you build the simple operations experience and move the existing screens under
`/admin`.

# Read first

1. `docs/agents/00-CONTRACTS.md` §5 (payload you render), §6 (roles), §8 (polling budget), §9, §10, §11 (finding codes)
2. `docs/PRODUCTION_NEXT_PHASE.md` §6 acceptance
3. Frontend:
   - `frontend/app/layout.tsx`, `frontend/app/providers.tsx`, `frontend/components/AppShell.tsx`
   - `frontend/lib/api.ts` (all; the `request` helper, existing schemas, ops schemas appended by ws-c/ws-d), `frontend/lib/queries.ts`
   - `frontend/lib/auth.ts`, `frontend/middleware.ts` (from ws-d)
   - `frontend/app/applications/[id]/page.tsx` and `frontend/components/applications/*` (the current review UI = future admin UI)
   - `frontend/components/applications/EvidenceViewerModal.tsx`, `EvidenceHighlight.tsx` (current highlighting = PDF text search)
   - `frontend/components/applications/OverviewTab.tsx:30-50` (demo data), `frontend/components/worklist/*`
   - `frontend/tailwind.config.*`, `frontend/app/globals.css`
   - `frontend/scripts/run-tests.mjs` and existing tests (how frontend tests run)
4. Backend endpoints you consume (read only): `routes/ops.py`, `routes/review_pages.py` (`/status`, `/pages/{n}/text`), `routes/review.py` (`source-page/{n}` PNG), `routes/upload.py` batch endpoints, `routes/auth.py`, `routes/admin_users.py`, `routes/llm_settings.py`

# Files you own

```text
frontend/app/ops/**                        (new)
frontend/app/admin/**                      (new; move current pages here)
frontend/app/page.tsx                      (role redirect: operations → /ops, admin → /admin)
frontend/app/applications/**, frontend/app/worklist/**, frontend/app/activity/**, frontend/app/settings/** (become redirects to /admin/...)
frontend/components/AppShell.tsx
frontend/components/ops/**                 (new)
frontend/components/applications/**        (admin review; edits for demo data, jargon, bbox overlay)
frontend/components/worklist/**
frontend/lib/queries.ts
frontend/lib/api.ts                        (schemas section; keep the request helper as ws-d left it)
frontend/lib/i18n/{en,hi}.ts, frontend/lib/i18n/index.ts (useLocale, t())
frontend/tailwind.config.*, frontend/app/globals.css
frontend/middleware.ts                     (add role redirects only; keep ws-d's auth redirect)
frontend tests for the above
```

Do not edit `frontend/components/upload/**` (ws-c) or `frontend/app/login/**` (ws-d) except to apply i18n keys or theme tokens.

# Steps

## 1. Routing and shell

- `/` → redirect by role. `/ops` = operations home (worklist), `/ops/applications/[id]` = operations review. `/admin/...` = everything that exists today (`worklist`, `applications/[id]`, `activity`, `settings`, `upload`), plus `/admin/users` (calls ws-d's endpoints) and `/admin/llm` (cost summary from `routes/llm_settings.py`).
- `middleware.ts`: operations role hitting `/admin/*` → `/ops`; admin can use both.
- `AppShell.tsx`: nav items by role. Operations: Worklist, Language toggle, Sign out. Admin: current items + Users, LLM, and a link to the operations view of the same application ("View as operations"). No "Stop DMEF" (ws-h removed it).

## 2. Polling diet (`frontend/lib/queries.ts`)

- While `status` is non-terminal, poll only `GET /review/applications/{id}/status` (2 s) and, on the upload page, `GET /upload/batch/{id}` (3 s).
- Fetch the full review (`GET /review/applications/{id}`) once when status becomes terminal or on manual refresh; `refetchInterval: false`.
- Ops screen fetches `GET /ops/applications/{id}` once, refetch on status change only.
- Page text (`/pages/{n}/text`) only when the admin opens a page.

## 3. Operations review screen (`frontend/app/ops/applications/[id]/page.tsx`)

Render the §5 payload, top to bottom:

1. Header: applicant name, loan id, status pill (Needs review / Clean / Processing / Failed) and, when processing, a plain progress bar from `processing.percentage`. When failed, `processing.failure_reason` as the only message.
2. Summary card: `summary[locale]`.
3. Findings (≤ 5): title, detail, severity colour, page chips (clicking opens the evidence viewer on that page with the bbox highlight).
4. Pages to verify: table `page | document | problem`, each row clickable.
5. Checklist: the familiar format — `S.No | Description | Status | Pages` with FOUND / MISSING / NOT CHECKED in the words the credit team uses today (check `frontend/components/NdcChecklistReview.tsx` for the existing layout and reuse it).
6. Nothing else. No tabs, no JSON, no OCR, no rule ids, no stage names.

Evidence viewer for operations (`frontend/components/ops/EvidenceViewer.tsx`):
image from `GET /review/applications/{id}/source-page/{n}` in a relatively
positioned container; overlay an absolutely positioned `div` with
`left = bbox[0]*100%`, `top = bbox[1]*100%`, `width = (bbox[2]-bbox[0])*100%`,
`height = (bbox[3]-bbox[1])*100%`, 3 px border in the severity colour, 4 px
padding. Prev/next page buttons. If `bbox` is null, show the page with a banner
"Highlighted value not located; check the page manually" (localized).

Admin evidence viewer (`EvidenceViewerModal.tsx`): add the same overlay when
`evidence_json` is present on the anomaly (keep the PDF text-search fallback).

## 4. i18n

`frontend/lib/i18n/en.ts`, `hi.ts`: keys for every operations-facing string
(labels, statuses, buttons, empty states, banners). `useLocale()` stores the
choice in `localStorage` (`dmef_locale`) and a cookie so SSR picks it up.
Backend text arrives already bilingual in the payload (`{en, hi}`); pick by
locale. Hindi strings in Devanagari; if unsure of a translation, keep it short
and plain rather than literal.

## 5. Copy and demo data

- Remove `OverviewTab.tsx:38,44` hardcoded "Business expansion — LAP",
  "Residential, Jaipur" and any other placeholder text (`rg -n "Jaipur|LAP|demo|placeholder|TODO" frontend/components frontend/app`). Show "—" when data is absent.
- Admin copy may stay technical, but in `ResultExplanation.tsx`,
  `ReviewerSummary.tsx`, `Verdict.tsx`, `worklist/reviewDisplay.tsx` replace
  operator-facing words: OCR → "text reading", pipeline → "processing",
  deterministic → drop, stale → "out of date", database dump → "application data".
- Review "checked" state currently in `sessionStorage`: keep for admin, do not
  add it to ops (the decision flow stays admin-only this phase).

## 6. Theme tokens

`tailwind.config`: add `colors.brand.{primary, accent, surface}` and
`colors.severity.{high, medium, low}` from the three most-used hex values
(`rg -o "#[0-9a-fA-F]{6}" frontend/components frontend/app | sort | uniq -c | sort -rn | head`).
Replace inline hex in files you own with the tokens. Do not chase every hex in
files you do not own.

## 7. Tests (using the existing `frontend/scripts/run-tests.mjs` harness)

- Ops payload zod schema parses the fixture JSON from `tests/fixtures/ops/` (copy one into `frontend/tests/fixtures/`).
- Findings capped at 5; `pages_to_verify` rows render; locale switch swaps text; bbox → style percentages computed correctly (pure function `bboxToStyle`).
- `queries.ts`: `isApplicationReviewPollingStatus` chooses `/status` while processing and disables review refetch when terminal (unit test on the interval function).
- Ops page source must not contain the strings `ocr`, `JSON`, `rule_id`, `pipeline` (case-insensitive grep test over `frontend/app/ops` and `frontend/components/ops`, allowing `ocr` only inside `i18n` comments if unavoidable — prefer none).

# Done when

- [ ] Operations user: lands on `/ops`, sees worklist, opens an application, sees summary + ≤ 5 findings + pages to verify + checklist, clicks a finding, sees the page with a box around the value, toggles Hindi, everything switches; cannot open `/admin`
- [ ] Admin: current screens under `/admin`, plus Users and LLM pages; can open the operations view
- [ ] Network tab during processing shows only `/status` (and `/upload/batch/{id}` on the upload page) repeating
- [ ] `rg -i "ocr|json|rule_id|pipeline" frontend/app/ops frontend/components/ops` returns nothing
- [ ] `npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test && npm --prefix frontend run build` clean

# Verify

```bash
npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test && npm --prefix frontend run build
# manual: log in as an operations user and as admin; walk the "Done when" list
```

# PR description

Contracts §10 template, workstream `ws-e ops ui`. Include screenshots (or a
text description) of the ops review page in EN and HI.

# Stop conditions

Contracts §10. Additionally: if the ops payload from `routes/ops.py` differs
from §5, do not adapt silently; write NEEDS-COORDINATION naming the field and
render what is there in the meantime.
