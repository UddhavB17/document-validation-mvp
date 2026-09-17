# NEEDS-COORDINATION: user portal UX reviewer workflow

The individual-exception reviewer workflow crosses the previously deferred
operations UI/API and persistence boundary. This implementation adds the
smallest coherent slice: `ops_review_items` stores a revision-scoped review
state, `routes/ops_reviews.py` exposes list/update endpoints, and every update
writes an audit row. The original `validation_results` rows and LLM dismissal
state remain unchanged.

Before production rollout, the operations/API and schema owners should agree
on the review-item vocabulary, retention policy, authorization model, and the
Postgres migration ownership. This note records coordination; it does not
change the shared contracts.

## User-authorized reprocessing repair (2026-09-17)

The user authorized fixing the reproduced foreign-key failure when replacing
validation findings. `services/exception_aggregator.py` now clears only that
application's dependent `ops_review_items` in the same transaction before
replacing `validation_results`. The existing audit records are retained; new
findings start pending even when their content is unchanged. A failed
replacement rolls back the review cleanup, findings, and application status
together. Other applications and NDC checklist checks are unaffected. This
cross-stream repair requires no API or schema change and does not reprocess
any saved application as part of delivery.
