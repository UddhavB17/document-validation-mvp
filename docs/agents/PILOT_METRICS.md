# Pilot metrics (ws-j-deploy-smoke)

Pilot window: 2026-09-15 → 2026-11-15 (two operations users, one admin).
Run every query with `psql` against the **pooled** Neon endpoint (read-only;
migrations always use the direct endpoint, see `docs/DEPLOY_NEON.md`):

```bash
psql "postgresql://<user>:<password>@<pooled-host>/<db>?sslmode=require" -f <query.sql>
```

All queries are PostgreSQL against the `0001_baseline` + `0002_worker_heartbeat`
schema. `pipeline_jobs.started_at/completed_at` are `TEXT` ISO-8601 columns, so
durations cast with `::timestamptz`. The brief calls the finish column
`finished_at`; the real column is `completed_at` (used below).
`validation_results` stores `rule_id`; the `code` column below is derived with
the contracts §11 family mapping (prefix/`LIKE` match, same families as
`scripts/eval_gemini_models.py`). `reviewer_decisions.decided_at` and
`applications.created_at` are `TIMESTAMPTZ`.

The brief says "five pilot KPIs"; the step list names seven items, so one
query each is given for all seven. Each query was run once against a local
PostgreSQL 18 seeded fixture (same DDL as `alembic upgrade head`); sample
output follows every query. Without cloud credentials the operator re-runs
the same statements against Neon and pastes the tables into the pilot review.

Seed used for verification: 3 applications (LN-001..LN-003), 4 jobs
(2 completed, 1 failed after 3 attempts, 1 completed with a retry),
5 validation rows, 2 reviewer decisions, 3 llm_calls rows, 4 object_refs rows.

## 1. Processing time per application (job `started_at` → `completed_at`)

```sql
SELECT a.id AS application_id,
       a.loan_id,
       MIN(j.started_at::timestamptz) AS started_at,
       MAX(j.completed_at::timestamptz) AS finished_at,
       EXTRACT(EPOCH FROM (MAX(j.completed_at::timestamptz)
                         - MIN(j.started_at::timestamptz)))::DOUBLE PRECISION AS seconds
FROM applications AS a
JOIN pipeline_jobs AS j ON j.application_id = a.id
WHERE j.status = 'completed'
  AND j.started_at IS NOT NULL
  AND j.completed_at IS NOT NULL
GROUP BY a.id, a.loan_id
ORDER BY a.id;
-- Overall average: wrap as SELECT AVG(seconds), PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY seconds) FROM (<above>) AS t;
```

Sample output:

```text
 application_id | loan_id |       started_at        |       finished_at       | seconds
----------------+---------+-------------------------+-------------------------+---------
              1 | LN-001  | 2026-09-15 10:00:00+00 | 2026-09-15 10:04:30+00 |     270
              3 | LN-003  | 2026-09-15 11:00:00+00 | 2026-09-15 11:12:00+00 |     720
(2 rows)
```

## 2. Failure rate

```sql
SELECT COUNT(*) AS jobs,
       COUNT(*) FILTER (WHERE status = 'completed') AS completed,
       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
       COUNT(*) FILTER (WHERE status IN ('queued', 'running', 'retrying')) AS in_flight,
       ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'failed')
             / NULLIF(COUNT(*), 0), 2) AS failure_pct
FROM pipeline_jobs;
```

Sample output:

```text
 jobs | completed | failed | in_flight | failure_pct
------+-----------+--------+-----------+-------------
    4 |         3 |      1 |         0 |       25.00
(1 row)
```

## 3. Retries

```sql
SELECT COUNT(*) AS jobs,
       ROUND(AVG(attempt), 2) AS avg_attempts,
       COUNT(*) FILTER (WHERE attempt > 1) AS jobs_retried,
       COUNT(*) FILTER (WHERE status = 'retrying') AS currently_retrying,
       COUNT(*) FILTER (WHERE status = 'failed' AND failure_reason IS NOT NULL) AS failed_with_reason
FROM pipeline_jobs;
```

Sample output:

```text
 jobs | avg_attempts | jobs_retried | currently_retrying | failed_with_reason
------+--------------+--------------+--------------------+--------------------
    4 |         1.75 |            2 |                  0 |                  1
(1 row)
```

## 4. Findings per application by code (§11 mapping)

```sql
SELECT code,
       COUNT(*) AS findings,
       COUNT(DISTINCT application_id) AS applications,
       ROUND(COUNT(*)::DOUBLE PRECISION
             / NULLIF(COUNT(DISTINCT application_id), 0), 2) AS avg_per_application
FROM (SELECT application_id,
             CASE
               WHEN UPPER(rule_id) LIKE '%%APPLICANT_NAME_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%TRUSTED%%NAME%%MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%NAME_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%APPLICATION_NAME_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%CROSS_DOCUMENT_APPLICANT_NAME%%'
                 THEN 'NAME_MISMATCH'
               WHEN UPPER(rule_id) LIKE '%%PAN_NUMBER_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%AADHAAR_NUMBER_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%TRUSTED_PAN%%'
                 OR UPPER(rule_id) LIKE '%%TRUSTED_AADHAAR%%'
                 OR UPPER(rule_id) LIKE '%%DATE_OF_BIRTH_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%INVALID_PAN_FORMAT%%'
                 THEN 'ID_MISMATCH'
               WHEN UPPER(rule_id) LIKE '%%ADDRESS_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%AADHAAR_ADDRESS_MISMATCH%%'
                 OR UPPER(rule_id) LIKE '%%CROSS_DOCUMENT_ADDRESS%%'
                 THEN 'ADDRESS_MISMATCH'
               WHEN UPPER(rule_id) LIKE '%%MISSING_DOC_S%%' THEN 'MISSING_DOCUMENT'
               WHEN UPPER(rule_id) LIKE '%%PERIOD_%%'
                 OR UPPER(rule_id) LIKE '%%DATE_CHECK_S%%' THEN 'BANK_STATEMENT_OLD'
               WHEN UPPER(rule_id) LIKE '%%UNREADABLE_PAGE%%'
                 OR UPPER(rule_id) LIKE '%%DOCUMENT_NOT_READABLE%%' THEN 'PAGE_UNREADABLE'
               WHEN UPPER(rule_id) LIKE '%%LOW_OCR_CONFIDENCE%%'
                 OR UPPER(rule_id) LIKE '%%LOW_CONFIDENCE_PAGE%%'
                 OR UPPER(rule_id) LIKE '%%OCR_BUDGET_PARTIAL_SCAN%%' THEN 'OCR_FAILED'
               WHEN UPPER(rule_id) LIKE '%%NOT_FOUND%%'
                 OR UPPER(rule_id) LIKE '%%EXTRACTION_UNRELIABLE%%'
                 OR UPPER(rule_id) LIKE '%%FIELD_VALUE_MISSING_S%%' THEN 'DATA_MISSING'
               WHEN UPPER(rule_id) LIKE '%%PAGE_PROCESSING_ERROR%%' THEN 'PROCESSING_ERROR'
               ELSE 'UNMAPPED_ADMIN_ONLY'
             END AS code
      FROM validation_results) AS mapped
GROUP BY code
ORDER BY findings DESC, code;
```

Sample output:

```text
      code      | findings | applications | avg_per_application
----------------+----------+--------------+---------------------
 ID_MISMATCH    |        2 |            2 |                1.00
 NAME_MISMATCH  |        1 |            1 |                1.00
 MISSING_DOCUMENT |      1 |            1 |                1.00
 DATA_MISSING   |        1 |            1 |                1.00
(4 rows)
```

Rows mapped to `UNMAPPED_ADMIN_ONLY` never appear in the ops payload
(contracts §11, last paragraph) and are triaged by an admin.

## 5. Manual-review effort proxy (`reviewer_decisions` per application, time to decision)

```sql
SELECT a.id AS application_id,
       a.loan_id,
       COUNT(d.id) AS decisions,
       MIN(d.decided_at) AS first_decision_at,
       EXTRACT(EPOCH FROM (MIN(d.decided_at) - a.created_at))::DOUBLE PRECISION
         AS seconds_to_decision
FROM applications AS a
LEFT JOIN reviewer_decisions AS d ON d.application_id = a.id
GROUP BY a.id, a.loan_id, a.created_at
ORDER BY a.id;
```

Sample output:

```text
 application_id | loan_id | decisions |     first_decision_at     | seconds_to_decision
----------------+---------+-----------+---------------------------+---------------------
              1 | LN-001  |         2 | 2026-09-15 10:30:00+00    |                1800
              2 | LN-002  |         0 |                           |
              3 | LN-003  |         1 | 2026-09-15 12:00:00+00    |                3600
(3 rows)
```

Track `AVG(decisions)` and `AVG(seconds_to_decision)` (over decided apps)
week over week; rising time-to-decision means the findings are getting harder
to review.

## 6. LLM cost per application (`llm_calls`)

```sql
SELECT a.id AS application_id,
       a.loan_id,
       COUNT(c.id) AS calls,
       COALESCE(SUM(c.tokens_in), 0) AS tokens_in,
       COALESCE(SUM(c.tokens_out), 0) AS tokens_out,
       ROUND(COALESCE(SUM(c.est_cost_usd), 0)::NUMERIC, 6) AS usd
FROM applications AS a
LEFT JOIN llm_calls AS c ON c.application_id = a.id
GROUP BY a.id, a.loan_id
ORDER BY a.id;
```

Sample output:

```text
 application_id | loan_id | calls | tokens_in | tokens_out |   usd
----------------+---------+-------+-----------+------------+----------
              1 | LN-001  |     2 |      1500 |        400 | 0.001200
              2 | LN-002  |     0 |         0 |          0 | 0.000000
              3 | LN-003  |     1 |      2000 |        600 | 0.002100
(3 rows)
```

## 7. Storage per application (`object_refs.size_bytes`)

```sql
SELECT owner_id::BIGINT AS application_id,
       COUNT(*) AS objects,
       COALESCE(SUM(size_bytes), 0) AS bytes,
       PG_SIZE_PRETTY(COALESCE(SUM(size_bytes), 0)) AS pretty
FROM object_refs
WHERE owner_table = 'applications'
  AND owner_id ~ '^[0-9]+$'
GROUP BY owner_id::BIGINT
ORDER BY owner_id::BIGINT;
```

Sample output:

```text
 application_id | objects |  bytes   | pretty
----------------+---------+----------+--------
              1 |       2 |  5242880 | 5120 kB
              3 |       2 | 12582912 | 12 MB
(2 rows)
```

The `owner_id ~ '^[0-9]+$'` guard keeps non-numeric owners (e.g. intake
package ids under other `owner_table` values) from failing the cast.
Compare against the diet budget: ~1 MB in Neon per application, 25–50 MB in
GCS for the source PDF/ZIP only (`docs/PRODUCTION_NEXT_PHASE.md` §2).
