# Admin-Configurable Website Audit

**Reviewed:** 2026-11-13
**Scope:** Existing admin settings UI/API, rule sources, configuration readers,
checklist and classifier data, and reviewer/admin presentation defaults.
**Purpose:** Identify which supported behavior changes could be made by an
administrator in the product UI, without a code edit and deployment. This is a
read-only architecture audit; no application behavior was changed.

## Summary

The application already has the beginnings of database-backed configuration:
the admin System Settings page edits rows in `system_settings`, several runtime
helpers read those settings, and the UI exposes classification thresholds,
OCR/LLM settings, and required-field toggles. Those controls are not yet a
general rule-management system. Important rules remain in JSON files, Python
constants, UI constants, or versioned code; some existing generic setting writes
are persisted as strings without a setting-specific schema or value validation.

The best next step is a reviewed configuration layer with typed schemas and
domain-specific editors. Start with checklist administration and safely
validated numeric thresholds. Then consider document-type registry management
and reviewer presentation defaults. Keep authentication, evidence requirements,
loan decision policy, and algorithmic safeguards in reviewed code.

“Dynamic” should mean an administrator can edit a bounded, validated setting,
see its effective value and impact, and publish or roll it back without a code
deployment. It should not mean arbitrary rules, prompts, or expressions can
execute from a database field.

## Existing building blocks

- `frontend/app/admin/settings/page.tsx` has tabs for Overview, Classification
  & Thresholds, Required Fields Matrix, OCR Provider, and LLM Verification.
- `routes/settings.py` exposes admin-only list/update endpoints for existing
  `system_settings` rows. The update payload is a string plus `clear_secret`;
  current routes do not validate a value against a typed per-setting schema or
  min/max range.
- `services/config.py` resolves environment, database setting, and defaults.
  Non-empty environment values override database values, so an admin change
  can be saved but not take effect while an environment override is active.
- `ClassificationSettings.tsx` exposes classification confidence, name fuzzy
  threshold, amount tolerance, and date tolerance controls. Other behavior
  behind similarly named validation and OCR settings is not necessarily
  represented in this tab.
- `RequiredFieldsMatrix.tsx` edits `required_fields.*` settings, but the
  document/field catalog comes from a frontend constant (`fieldSchemas.ts`).
  Its switches do not edit checklist items, document requirements, or every
  backend verification rule.
- `services/checklist_service.py` reads `data/checklist.json` from the
  deployment filesystem and caches it. Checklist items include product,
  enabled, required, document type, check type, applicability, severity,
  AI/manual-review, and scope fields. There is no admin CRUD API or editor for
  that catalog.
- `services/document_classifier.py` reads `data/document_type_registry.json`.
  The registry has document signals, OCR routing metadata, priorities and
  confidence cutoffs, while additional type-specific overrides are Python code.
- Several settings have database/env support, but important thresholds and
  rules remain constants. Examples are `services/content_triage.py`,
  `services/consistency_checks.py`, `services/evidence_boxes.py`,
  `services/evidence_resolution.py`, `services/ops_presentation.py`,
  `services/reviewer.py`, `services/field_verification.py`, and
  `services/pipeline/_shared.py`.
- Admin UI constants also govern worklist filters/sorts and navigation; these
  are presentation preferences, not business validation rules.

## Findings and recommended admin options

### 1. Checklist and product requirements are file-managed — highest value

**Current location:** `data/checklist.json`, loaded by `services/checklist_service.py`.

**Admin options to add:**

- Select product/checklist version and inspect grouped checklist items.
- Edit description, document types, required/optional, enabled, severity,
  AI-checkable/manual-review mode, person/loan scope, and supported
  applicability fields/operators.
- Create a new checklist version by cloning an existing version; validate it
  before publishing; compare revisions and roll back.
- Show which applications use each version and pin the selected version to new
  applications. Existing cases should retain their original version.

**Needed boundary:** Replace direct mutable JSON-file ownership with a
versioned checklist repository/API. Treat `check_type`, applicability
operators, and scope as enumerations backed by existing vetted Python handlers.
Reject unsupported fields, types, document names, and operators. Never allow
an admin-edited expression or arbitrary code to run in the checklist engine.

### 2. Document-type registry needs an admin editor and effective-state view

**Current location:** `data/document_type_registry.json`; loaded by
`services/document_classifier.py`. Some ranking adjustments are hard-coded in
`classify_page_with_candidates`.

**Admin options to add:**

- Edit document-type name/aliases, heading phrases, keyword groups, required
  signals, field patterns, OCR route, priority, and bounded confidence cutoff.
- Provide regex validation, duplicate/overlap warnings, sample-text preview,
  candidate score breakdown, and dry-run comparison against a fixed sample set.
- Surface code-owned overrides as read-only explanations until they are
  separately converted to named, tested processors.

**Needed boundary:** Validate registry shape and regex safety; publish immutable
versioned snapshots. Do not make arbitrary processor names executable or allow
admins to turn off intrinsic identity evidence and other anti-misclassification
gates.

### 3. Setting values are stored generically, without per-setting validation

**Current location:** `routes/settings.py` updates a `config_value` string after
checking only setting existence and secret handling. Settings metadata contains
type/category/label/description, but server-side validation is not derived from
a complete schema. UI range controls do not protect direct API calls or
malformed database values.

**Admin options to add:**

- Typed editor based on server-owned metadata: boolean, integer, decimal,
  enum, bounded text, secret, and structured JSON where explicitly supported.
- Display allowed range, default, current DB value, effective value, and
  environment override status together. Disable or clearly mark controls whose
  runtime value is environment-owned.
- Validate on the server, return field-specific errors, and provide reset to
  default where safe.
- Group editable settings by runtime behavior (classification, OCR, review,
  upload, retention, cost) rather than exposing arbitrary key/value rows.

**Needed boundary:** Maintain an explicit allowlist/schema of admin-editable
keys; never expose credentials or operational secrets as ordinary fields. Do
not imply an env-overridden DB value is active.

### 4. Important decision thresholds are split between settings and constants

**Examples found:** OCR/classification thresholds in
`services/consistency_checks.py`, `services/content_triage.py`,
`services/mapped_verification_rules.py`, `services/ocr_router.py`, and
`services/pipeline/_shared.py`; evidence thresholds in
`services/evidence_boxes.py` and `services/evidence_resolution.py`; matching
thresholds in `services/person_names.py`; display threshold in
`services/ops_presentation.py`; severity grouping in `services/reviewer.py`.

**Admin options to add, after each rule is proven safe to configure:**

- Bounded OCR low-confidence threshold and scanned-page handling profile.
- Classification review/auto-classification cutoffs, with separate controls
  for distinct stages rather than one ambiguous “confidence” slider.
- Name/amount/date tolerances, with document-family context and visible units.
- Evidence box/grouping confidence only if sample-based review demonstrates an
  operator need; default recommendation is keep this code-owned.
- Reviewer display grouping and warning thresholds, clearly labeled as
  presentation behavior rather than changing validation outcomes.

**Needed boundary:** For each candidate, document caller, unit, valid range,
fallback, and effect. Avoid a single shared threshold where current stages
have different meanings. Keep confidence floors and safeguards that prevent
false clean/accepted decisions fixed or tightly bounded and covered by tests.

### 5. Required-field switches are not a complete validation-rule editor

**Current location:** `RequiredFieldsMatrix.tsx` uses frontend
`ALL_FIELD_SCHEMAS`; the backend reads selected `required_fields.*` values.
Checklist presence, applicability, identity comparisons, consistency checks,
and evidence policies live in other modules/data.

**Admin options to add:**

- Make the field/document catalog come from a backend schema endpoint, not a
  duplicated frontend constant.
- Show each field’s owning check, supported document types, aliases, and
  whether disabling it changes checklist status, field matching, or both.
- Add product-specific profiles and publish/version semantics; preview which
  cases/new applications are affected.

**Needed boundary:** Keep field identities and supported normalization logic
code-owned. The UI may select from supported checks; it should not invent a
field comparator or bypass source evidence requirements.

### 6. Rule changes lack a visible lifecycle and audit history

**Current gap:** Existing settings save individually. The audited settings UI
does not provide a unified draft, validation preview, approval/publish state,
revision diff, rollback, or clear affected-version display for rule catalogs.

**Admin options to add:**

- Draft → validate → preview → publish flow for consequential catalogs.
- Immutable revision history (actor, timestamp, before/after, reason) and
  one-click rollback by publishing a prior revision.
- Effective version and configuration fingerprint on every new processing job
  and audit report. Store the checklist/classifier/rule versions on the
  application or job so reprocessing and investigations are reproducible.
- Safe cache invalidation/version switch at publish time; do not rely on process
  restart or local file mtime for production edits.

**Needed boundary:** Follow contracts for dialect-neutral schema/migrations,
JSON-as-TEXT, admin auth, and one-time schema initialization. Define what
happens to in-flight jobs before applying a published change.

### 7. Product, upload, retention, and operations behavior is fragmented

**Current locations:** Product types are accepted as strings in upload APIs;
the checklist loader only succeeds for configured product keys. Upload size,
retention and worker settings have environment/default sources, and some
retention controls are not ordinary admin-editable settings. Worklist filters
and sort values are frontend constants.

**Admin options to consider:**

- Product catalog (enabled products, display names, default checklist version),
  constrained to products with a valid published checklist.
- Upload limits within platform hard caps, allowed upload modes, and batch
  limits, with clear “effective value” where environment overrides apply.
- Retention policy durations with legal/contractual minimum/maximum constraints
  and a dry-run impact count before a shorter retention is published.
- Worklist saved views, default filters/sort, and table visibility as per-user
  preferences; these should not be global business rules.

**Needed boundary:** Infrastructure-only controls (bucket, database URL,
secrets, auth policy, worker process management) remain deployment-owned. Do
not expose arbitrary product strings that lack a valid checklist or pipeline
support.

### 8. Bilingual templates and finding presentation are partly code-owned

**Current location:** Ops vocabulary, summary phrases, language templates,
severity ordering and reviewer wording are distributed among
`services/ops_presentation.py`, template modules, and reviewer/UI code.

**Admin options to consider:** Edit approved English/Hindi display copy and
selected non-policy labels in a translation editor with key completeness,
length checks, preview, revisioning, and fallback behavior. Offer a preview of
finding grouping/order.

**Needed boundary:** Keep the mapping from validation rule to severity, finding
code, status, and loan decision consequence code-owned. Admin-edited copy must
not be able to hide a finding, change its severity, or turn an exception into
an approval.

### 9. Static admin navigation and worklist options are low-risk UI settings

**Current location:** Navigation metadata is in
`frontend/lib/appNavigation.ts`; filter and sort choices are in
`frontend/app/admin/worklist/page.tsx`.

**Potential options:** Per-user default worklist view, default sort, visible
columns, page size from a bounded list, and saved named filters. Dynamic route
authorization should remain in backend role checks; hiding a nav item is not
security.

## What should remain code-owned

- Authentication, roles, user provisioning, and authorization.
- Supported check handler implementations, comparison algorithms, validators,
  and input grammar.
- Evidence provenance rules, manifest trust, source-page requirements, and
  conservative unassigned ownership behavior.
- Decision-policy gates (accept/override/request-documents), severity/status
  semantics, and anti-false-clean conditions.
- File size hard caps, regex/input safety limits, encryption, and infrastructure
  credentials/endpoints.
- Any rule whose change would need legal/compliance approval should use a
  reviewed release/publish process; it should not be a casual free-form toggle.

## Suggested delivery order

1. Specify setting schemas, allowed keys, min/max validation, effective-value
   display, audit log, and tests. This closes the gap in the existing settings
   surface before adding more controls.
2. Build versioned checklist administration, including product/version
   selection, validation, preview, audit, publish, and rollback.
3. Add a safe document-type registry editor with sample preview and
   versioned activation; retain protected Python post-processors.
4. Inventory constants and map each one to its owner, runtime reader, unit,
   safe range, and consequence. Promote only operator-needed thresholds into
   typed settings, in small groups.
5. Add product catalog and per-user worklist preferences, then approved copy
   management if operations staff need it.
6. Track configuration fingerprints on jobs and reports; test in-flight,
   cached, rollback, and reprocessing behavior.

## Implementation progress: `codex/dynamic-admin-config`

The first implementation slice adds server-owned setting type/range/enum
validation, exposes safe editor constraints and effective values through the
settings API, and warns admins when environment variables override saved
values. Invalid saves now surface the API validation message in the admin UI.
The existing classification confidence setting now feeds the classifier; the
existing name, amount, and date tolerance controls are seeded and connected to
field verification. The UI range controls consume server-provided bounds.

This does not yet implement checklist or classifier-registry CRUD, version
history, draft/publish/rollback, configuration fingerprints, product catalog
management, or user-specific worklist settings. Those remain follow-up work in
the order above. With the current default cutoff of 0.70, lower-confidence
classifications such as the registry's 0.55 Acceptance Letter profile remain
unknown and available for review; the registry-focused test sets the 0.50
registry cutoff explicitly to test that profile independently.

## Constraints and open design decisions

- Existing environment values take precedence over the database; product UI
  must show this clearly or operators will mistake a saved value for an active
  one.
- Product checklists and classifier registries are currently deployment-file
  based. Supporting multi-replica production edits requires a shared durable
  store and explicit cache/version invalidation.
- Existing applications need pinned rule versions or a deliberate migration
  strategy; silently applying today's rules during a later review can make
  results irreproducible.
- The system currently distinguishes AI-checkable and manual items, but the
  policy and evidence gates associated with those modes are not arbitrary
  administrator-defined workflows.
- This audit is based on source inspection. It does not claim every listed
  setting is active in every deployment profile; environment overrides and
  profile selection must be verified when implementation is planned.
