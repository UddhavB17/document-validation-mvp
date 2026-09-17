# User Portal UX Spec — Vibe Coding Source (tmp/user-portal-ux)

Source: user-provided vibe prompts for the borrower / field-officer side.
Audience: 12th pass-out / non-technical field officer. Zero jargon, EN/HI only.
Route in this branch: `/portal?app=<id>` (demo fallback `APP-0004` when no backend data).

## Prompt 1 — User Dashboard Screen

> Create a super clean, ultra-simple User Dashboard for an Indian Loan Application platform called "DMEF". Keep UX extremely simple with zero technical jargon.
>
> Header: DMEF logo, Application ID "APP-0004", Borrower Name "Peeru Lal", Support Help Number, simple Language Switcher (EN / HI).
> Status Banner: Soft amber banner: "Action Required: 3 Quick Fixes Needed to Approve Your Loan (Progress: 75%)" + progress bar.
> Summary Cards: 3 big stat boxes (Loan Amount: ₹2,75,000, Pages Checked: 25, Action Required: 3 items).
> Applicant Roster: Cards showing "Peeru Lal (Main Applicant - Needs Fix)", "Unkar Lal (Co-applicant - Approved)", "Radha Bai (Co-applicant - Fix Needed)".
> Action Checklist (To-Do List):
> - Card 1: "PAN Card Name Mismatch" -> "Name on PAN card doesn't match Aadhaar." -> [Re-upload Clear PAN Card]
> - Card 2: "Disbursement Request Form Missing" -> "Signed loan payout form is missing." -> [Upload Form] [Download Template]
> - Card 3: "Aadhaar Address Check" -> "Address on Voter ID doesn't match Aadhaar." -> [Correct Address]
>
> Tailwind, soft rounded borders, Green/Amber/Red coding, high-contrast type.

## Prompt 2 — User Report & Document Fix Screen

> Split view.
> Left (Document Viewer): preview box (PAN card) with zoom in/out/rotate + highlight around issue field.
> Right (Guidance & Action Panel):
> - Title "PAN Card Verification", status badge "Issue Found"
> - "What is Wrong?" plain language: "PAN shows 'PEERU LAL', bank records show 'PEERU LAL MEENA'."
> - "How to Fix" checklist: clear original photo; affidavit (नाम शपथ पत्र) if name differs.
> - Dropzone: drag & drop + "Choose File or Take Photo".
> - Buttons: [Save & Submit Document], [Ask for Help].

## Reference implementation notes

- Original paste was a single `UserPortal.jsx` with `lucide-react` icons and mocked APP-0004 data.
- This branch adapts it to Next.js 14 + TypeScript under `frontend/components/portal/UserPortal.tsx` + `frontend/app/portal/page.tsx`:
  - No new npm deps (no `lucide-react`); inline SVG / emoji only.
  - EN/HI toggle local to portal (does not clash with ops `LanguageToggle`).
  - Data-driven when `?app=<id>` resolves via `GET /ops/applications/{id}` (`top_findings`, `pages_to_verify`, `checklist`, `summary`); demo fallback preserves APP-0004 content for design review.
  - Polling diet respected (contracts §8): only `useApplicationStatus` polls (2s while processing); ops payload fetched once.
  - No rule IDs / OCR text / stage names surfaced; plain-language titles only.

## UX changes made vs paste (reviewer: keep or revert)

1. Progress = `checklist.found / checklist.total` when live; 75% only in demo fallback.
2. Roster reduced to live applicant + generic co-applicant slots in demo (backend ops payload has no roster; avoids inventing data).
3. Fix buttons are anchors that deep-link to report view (`#fix-<index>`), not dead `onClick` stubs.
4. (Reverted) Upload dropzone, Submit button, Ask-for-Help link, and header Helpdesk button removed per user request — fix panel now ends at the guidance checklist.
5. Viewer highlight uses finding `evidence.bbox` percentages when present; PAN mock only in demo.
6. Report Summary card shows the ops `summary.en/hi` (Gemini text with deterministic fallback), following the portal EN/HI toggle.
7. File Health card: SVG donut of `checklist.found/total` (green ≥90, amber ≥60, red below), legend + stacked bar of found/missing/not-checked, and a fixability verdict derived from finding severities (HIGH=needs branch help): Easy / Mostly easy / Needs branch support / All good.
8. Project wiring: the new UI *is* the ops portal — `/ops` renders the portal worklist and `/ops/applications/[id]` renders the portal dashboard (both behind login; `chrome={false}` hides the portal header since AppShell provides it, keeping a slim language toggle). The old staff review page is replaced; `/portal` remains the public demo + live `?app=` view with full chrome. Sidebar offers Worklist (`/ops`) and "My loan file / मेरी ऋण फ़ाइल" (`nav.portal`). No borrower-view button anywhere.
9. Worklist first screen: `/portal` without `?app=` shows "Choose your loan file" (`frontend/components/portal/PortalWorklist.tsx`) — live rows from `GET /ops/worklist` when logged in, sample rows otherwise; tapping a row opens `/portal?app=<id>`.
10. Silent portal readers (`fetchPortalWorklist/Application/Status` + `usePortal*` hooks in `frontend/lib/api.ts`, `frontend/lib/queries.ts`): portal API failures never trigger the global 401 → `/login` redirect — visitors stay on the page and see sample content.
11. All pending things listed: action list = all `top_findings` plus every `pages_to_verify` page not already covered (deduped by page, amber "re-upload a clear scan" cards) — nothing actionable hides behind the 5-finding cap. Banner/donut show checklist health (`found/total`, amber 60% for 18/30) once checking finishes; legend middle row is "Missing papers" (checklist gaps), not action items.
12. Ops NDC checklist (paper MSFC/NDC/MAY'26/VER.1.4): `services/ops_ndc.py` maps the 43 pipeline rows by `s_no` (+ manual row 44 "Other"); FOUND rows pre-tick, the rest need CSO/BOPS + COPS hand ticks persisted in `ops_ndc_checks` (`GET/PUT /ops/applications/{id}/ndc`, migration `0009`). All 44 complete → "Mark verified" posts ACCEPT (status `verified`) → "Print checklist" (`window.print` + print CSS). UI in `frontend/components/ops/NdcChecklist.tsx`, shown on the ops review page (`/ops/applications/[id]`, below the checklist), in the admin case workspace (`/admin/applications/[id]`, inside the checklist tab), and at the bottom of the portal dashboard (fully tickable for logged-in sessions; hidden for logged-out visitors so the public demo never bounces to `/login`).
13. Real page preview in the fix-document view: renders `source-page/{n}` through the authenticated evidence proxy with the finding `bbox` as a highlight overlay (logged-in sessions); mock box remains only as fallback (demo / logged-out / render failure).
14. Working preview controls: zoom −/+ (100–300% with live % readout), rotate 90° steps, reload (re-fetches the render and retries after failure); spinner loader with bilingual "Loading page…" text while the render arrives.
15. No mid-check logouts: JWT + cookie lifetime 12h → 30 days (`services/auth/tokens.py`, `frontend/app/api/session/route.ts`), cookie slides forward on every successful session check, and session hydration retries through transient backend blips (~1 min) instead of bouncing to `/login`. NEEDS-COORDINATION at merge: shared contract §6 still says 12h; explicit logout still clears the cookie and deactivation is still enforced per request, but a copied bearer now lives up to 30 days.
16. Mumbai-first LLM: `GEMINI_MODEL=gemini-3.5-flash` (newest Flash generation actually served in `asia-south1`; 3.6/3.8 are global/EU-US only, so Mumbai latency stays in-region). Code default + known list + cost table (`$1.50/$9.00` per 1M) updated. Summaries rewritten for slow readers: 2–4 sentences under 12 words, easy everyday words (EN + simple Devanagari Hindi), only what is wrong + what to do next — applied to the exception-review prompts, the short summary prompt, checklist narration, and all deterministic fallbacks.
17. Resume stuck files: `pipeline_resumable` worklist flag (`services/reprocessing.py:can_resume_application/is_resumable`, one extra batched job query in `load_worklist_data`) drives the admin worklist Resume button, which now also shows for crash-stuck `processing` rows (stale `running` heartbeat) — resume reaps the dead job and requeues from the last checkpoint; a live worker still gets a 409.
