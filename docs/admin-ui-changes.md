# Admin and reviewer UI changes (development branch)

## LLM settings and environment sync

- Admin **LLM provider** and **model** saves update `system_settings` and mirror to the local `.env` file (`DMEF_ENV_FILE`, default `.env`).
- The settings API returns `effective_value` and `env_override_active` for LLM keys; the LLM tab shows the **effective runtime** provider and model from `GET /settings/llm/providers`.
- In-process API and inline workers pick up `os.environ` immediately after save. **Restart the separate worker process/container** if it does not share the API process.

## Resume from checkpoint

- **Admin worklist**: prominent **Resume from checkpoint** when `pipeline_retryable` is true; recovery states without retry show a short hint to open Processing.
- **Processing tab** (`ProgressPanel`): resume is the primary action in an amber callout when the job is retryable.

## Admin desk themes

- Ledger / Slate / Ink theme chips in the **admin** sidebar (`localStorage` key `dmef_theme`, same as reviewer Preferences). Ops reviewers continue to use **Preferences** at `/ops/settings`.

## AI summaries for exceptions

- **Ops** findings prefer `ai_detail` from saved ops LLM exception review when present; template rule text remains underneath the rules engine.
- **Admin case review**: AI review summary on Overview; exception queue rows show per-item AI text when `llm_summary` is available; result basis prefers the AI executive summary when present.
