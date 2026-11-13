# DMEF production readiness plan

**Baseline:** `main` at `f246019e`, reviewed 2026-11-13.
**Goal:** Release a document validation service that reviewers can trust, operators can recover, and the business can audit.

The repository has deployment manifests, PostgreSQL migrations, a durable worker, CI jobs for SQLite and PostgreSQL, and a batch smoke script. Reuse those assets. The most recent merge passed focused backend checks and Ruff. The preceding full local backend run stalled, and this review did not inspect live deployment state or CI results. Use [the previous cutover plan](PRODUCTION_NEXT_PHASE.md) for architecture decisions and [the shared contracts](agents/00-CONTRACTS.md) for current interfaces.

## 1. Close release blockers

| Work | Suggested owner | Exit evidence |
| --- | --- | --- |
| Provision admin settings on PostgreSQL. `database/db.py:init_db` seeds SQLite and returns early on PostgreSQL. The three new tolerance keys are seeded in Python and do not appear in the Alembic migrations. PostgreSQL tests separately call the seed function, so test setup can mask a missing production release step. | Backend / DB | Fresh and upgraded PostgreSQL databases expose the three keys through the admin API. An idempotent release step preserves existing values. Confirm the deployed database separately. |
| Review the effective classification cutoff and matching tolerances. Activating the saved 0.70 cutoff can send previously classified pages to manual review. Assess name, amount and DOB tolerance changes against a labeled baseline. | Validation / Operations | Reviewers sign off on the default profile and supported ranges. Malformed values fall back safely, and incomplete evidence still routes to human review. |
| Verify authorization and handling of loan data. Agree who may see each case and source file, including whether reviewers are scoped by branch or assignment. Review API, evidence, export and decision access against that policy. Check log redaction, least privilege for service accounts, secret rotation, and approved OCR/LLM data handling. | Security / Platform | Signed access matrix, documented data flows and retention, and staging checks covering reviewer, admin and unauthenticated access. |
| Require release checks for the candidate commit. CI has SQLite and PostgreSQL jobs, but its push triggers list main and version tags. Use PR checks for development and main, and confirm required checks in GitHub. Diagnose the stalled suite with per-test timings and bounded external calls. | Engineering | Both backend suites, frontend typecheck/lint/tests/build, and migration checks pass on the exact release commit. Credential-gated checks are tracked separately. |

## 2. Rehearse deployment and recovery in staging

1. Use a staging Neon database, private GCS bucket, dedicated identities and synthetic or approved de-identified packets. Validate startup configuration, migration revision, API and worker health, and frontend API routing. Follow the [Neon setup](DEPLOY_NEON.md) and [Cloud Run runbook](../deploy/cloudrun/README.md).
2. Exercise the full browser workflow with a representative 10-file batch. Verify upload, queue progress, evidence preview, English/Hindi findings, reviewer decisions and undo. Include a malformed packet, an unreadable page, a provider failure and a retry. Extend the staging run around [the existing smoke script](../scripts/smoke_batch.py).
3. Restart the worker during a job and check that it resumes or retries without losing the case or duplicating decisions or findings. Measure behavior during OCR/LLM outages and under expected peak batch volume.
4. Rehearse rolling back API, worker and frontend revisions. Verify that the previous version can run with the migrated schema or document the recovery sequence. Restore database records and matching stored objects in staging and record the time and any data loss. Dry-run retention and confirm it handles reports, exports and source files as intended.

**Exit evidence:** One staging run record with the commit and image versions, migration revision, smoke results, recovery timings and owners for any remaining issues.

## 3. Run a controlled pilot

- Use a small reviewer group and agreed daily volume. Include digital and scanned packets, multilingual documents, co-applicant cases, and documents with deliberately missing or ambiguous evidence. Have reviewers independently label a sample of clean cases and high-severity exceptions.
- Agree pass thresholds before the pilot for missed high-severity exceptions, false positives, review effort, processing time, retry and failure rate, oldest queued job, and OCR/LLM cost per case. Use the [pilot metrics queries](agents/PILOT_METRICS.md) as a starting point and record denominators and sample size.
- Alert on stale worker heartbeat, growing queue age, repeated job or provider failures, elevated API errors and failed retention runs. Assign an owner and a response for each alert. Pause intake or roll back if cases are incorrectly marked clean, evidence becomes inaccessible, access boundaries fail, or the agreed service thresholds are breached.

**Exit evidence:** Operations signs off on review accuracy and workload. Platform signs off on alerts and recovery. The release owner records the rollout or rollback decision.

## 4. Expand admin configuration with release controls

Before enabling routine production edits to validation rules, add change history with actor and reason, a preview against labeled cases, and a way to restore the last approved settings. Record the effective configuration or version used for each processing run. Define how queued and retried jobs pick up versions so a single case can be explained later. Keep checklist and classifier registry editors as follow-up work unless the pilot depends on them. [Admin configuration audit](DYNAMIC_ADMIN_CONFIGURATION_AUDIT.md)

## First implementation ticket

Added in `0011_admin_validation_settings`: seed the three admin validation settings on PostgreSQL while preserving existing values. A migration regression test applies the upgrade twice and verifies that an existing customized value survives. The admin read/update flow still needs verification against a migrated PostgreSQL database without the test fixture's extra seed step. Pair that check with a decision on the production classification cutoff and a comparison against labeled packets before cutting the pilot release.
