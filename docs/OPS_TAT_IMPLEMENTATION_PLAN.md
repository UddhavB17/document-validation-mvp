# Ops turnaround time implementation plan

## Goal

Reduce the time between a LAP case becoming ready for Ops review and Ops recording its outcome. The workflow covers the Ops queue, evidence review, document follow-up, and handoff within Ops. Lending decisions and other departments' workflows are outside this scope.

Reuse the Ops worklist, application detail, evidence viewer, reviewer decisions, and audit log. Treat the processing state, Ops workflow state, and recorded decision as separate fields.

## Phase 0. Establish the baseline

- Capture server timestamps for when a case becomes reviewable, when a reviewer starts, when a document request opens or is resolved, when a case returns to review, and when Ops records its outcome.
- Report median and 90th percentile time from ready to first review, first review to first outcome, and ready to final Ops completion. Show time waiting for documents separately while retaining it in total elapsed time. Time between start and outcome includes idle time unless active work is instrumented separately.
- Record document request rounds, reopened cases, and quality corrections. Compare similar LAP cases by branch and complexity. Label missing historical timestamps and establish a prospective baseline where needed.

**Done when:** Ops can identify which stage contributes most to delays and agrees on the baseline, pilot cohort, and quality measures.

## Phase 1. Add queue age, ownership, and handoff

- Extend the Ops worklist with ready time, owner, next action, and waiting reason. Add **Ready**, **My cases**, **Waiting for documents**, and **Completed** views. Sort ready cases oldest first within the agreed priority rules.
- Add **Claim**, **Release**, and authorized **Reassign** actions. Claim atomically on the server so two reviewers cannot take the same case. Record reassignment reason and actor in history. Agree who can reclaim unattended work before enabling that action.
- Add **Review next** to the Ops worklist. Select the next eligible case server-side using the current filters and permissions. Preserve the reviewer’s current case and saved progress when they return.

**Done when:** Two reviewers claiming the same case produce one owner, waiting cases stay out of the actionable queue, and a handoff carries the reason and unfinished work.

## Phase 2. Review findings beside the source evidence

- Extend the existing Ops case page with a list of unresolved findings and required checks beside the PDF viewer. Selecting an item opens its source page and highlight where available. Group repeated findings while keeping individual items accessible.
- Let reviewers record **Checked**, **Exception confirmed**, or **Needs help**. Save progress on the server against the case, check, and evidence revision. Keep required checks visible and show why any decision is blocked.
- Reuse the existing decision actions. On success, show the outcome, remaining follow-up if any, and **Review next**. If evidence or ownership changed since opening the case, ask the reviewer to refresh before submitting a stale decision.

**Done when:** A reviewer can open the cited page, record a check, resume on another device, and submit the existing Ops decision from one screen.

## Phase 3. Track document requests and returning cases

- Extend **Request documents** to save individual requested items, an editable message, the Ops owner, and an optional follow-up date. Show open items in the case and the waiting queue. Keep using the existing communication and upload channels.
- Allow authorized Ops users to link incoming documents to the request and mark each item received or still outstanding. Return the case to the actionable queue when its blocking items are resolved and any required processing finishes.
- Highlight what changed. Carry forward completed checks only when their evidence and applicable rule are unchanged. Start with clear invalidation rules, and add selective reprocessing once dependencies are reliable.

**Done when:** A partial response leaves unresolved items open, a completed response returns to the correct queue once, and changed evidence reopens the checks that depend on it.

## Phase 4. Pilot and expand

- Pilot with one Ops team. Review median and 90th percentile Ops TAT, first-touch time, document request rounds, and reopened cases against the baseline. Sample decisions for missed findings and review corrections before expanding.
- If queue wait dominates, adjust routing and ownership first. If review time dominates, prioritize evidence navigation and repeated findings. If document wait dominates, improve request clarity and follow-up.

## Implementation order and dependencies

1. Add the timestamp and workflow model, migration, access checks, and audit events. Preserve existing decisions. Represent unknown historical dates as unknown.
2. Extend the existing worklist and add claim and handoff actions.
3. Build the evidence review screen and server-side draft progress.
4. Add tracked document requests and return-to-queue handling.
5. Pilot, review the metrics with Ops, and expand once quality and turnaround targets are met.

The first implementation ticket should cover **queue age, case ownership, and claim conflicts**. That gives Ops a measurable improvement to pilot before expanding the review screen and follow-up workflow.

## Implementation notes

- The Ops workflow layer stores ownership, workflow events, durable review checks, and document request rounds separately from pipeline status and existing reviewer decisions.
- Prospective timestamps begin when the Ops queue first observes an eligible case. Existing application or upload timestamps are not substituted for missing historical Ops events.
- Reopened cases retain their original ready timestamp for total TAT and use a separate queue-entry timestamp for current queue age.
- Review checks are keyed to a fingerprint of the current finding/checklist content. A changed or missing fingerprint returns the check to the reviewer and displays a recheck notice.
- Incoming files can be linked by their existing uploaded-file ID. Selective reprocessing is not automatic because file-to-rule dependencies are not yet reliable; if a required pipeline run is active, the case remains unavailable to Review next until it completes.
- The dashboard reports prospective p50/p90 stage times, total and document-wait time, request rounds, reopened cases, and recorded decision undos as a quality signal. It does not claim a quality-correction rate; Ops still needs to sample decisions during the pilot.
- The existing full review/decision panel is restricted to admin by the current auth contract, while Ops users receive the bounded Ops summary. This implementation exposes the latest recorded decision to Ops and keeps the existing decision API/audit trail connected, but does not add a second Accept/Override surface that could weaken those review gates.
- **NEEDS-COORDINATION:** implementation adds Ops workflow endpoints in `routes/ops.py`, records existing decision/undo events in `routes/decisions.py`, extends the Ops screens/API schemas, and registers a new schema module through `database/__init__.py`. These cross-workstream edits are limited to the Ops workflow integration; core authentication and storage contracts remain unchanged.
- **NEEDS-COORDINATION:** if Ops users should record ACCEPT/OVERRIDE directly from the Ops page, explicitly extend the role contract with a safe Ops decision payload and server-side decision/check validation. Reusing the admin-only `/review/applications/{id}` payload would expose data beyond the current Ops contract.

The pilot and its targets remain an Ops rollout decision. Start with one team, compare the prospective baseline and quality sample, then expand only after the team agrees that turnaround improved without increased corrections.
