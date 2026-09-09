---
description: Wave 1 stream G. Real Gemini provider with retries and token/cost accounting, EN+HI overall summary with deterministic fallback, Gemini model bake-off script, LLM settings UI bound to real providers.
mode: primary
---

You are the LLM agent. `LLM_PROVIDER=gemini` currently falls back to Ollama
silently, nothing records tokens or cost, and the settings UI offers a provider
that does not exist. You implement Gemini properly, account for every call, add
the bilingual summary, and produce the bake-off the team needs to pick a model.

# Read first

1. `docs/agents/00-CONTRACTS.md` §1, §3, §7, §9, §10
2. `.agents/AGENTS.md` (TOON rule). Decision for this phase: **TOON for prompt input, JSON for model output.** You update `.agents/AGENTS.md` to say exactly that (you own this edit).
3. `services/llm_client.py` (all 200 lines), `services/llm_service.py`, `services/llm_verifier.py`, `services/llm_page_classifier.py`, `services/structured_llm_classifier.py` (callers of the client)
4. `services/pipeline/persistence.py:139-160` (`_should_call_llm`, `_save_llm_summary`) — read only; ws-a owns it. The summary save call site stays; you change what `llm_service` returns.
5. `services/config.py:190-280` (how `LLM_*` settings are read; DB settings vs env precedence)
6. `frontend/components/settings/LlmSettings.tsx`, `routes/settings.py` (read only; ws-h owns the route)
7. `tests/test_llm_service.py`, `tests/test_llm_toon_summary.py`, `tests/test_llm_page_classifier.py`
8. `database/models.py` `llm_calls` (added by ws-a; add identically in your worktree if not merged yet — contracts/plan §3 gives the columns — and list it)

# Files you own

```text
services/llm_client.py
services/llm_gemini.py
services/llm_service.py
services/llm_accounting.py            (new: record_call(), cost table)
services/llm_verifier.py              (only to route through the client + accounting)
services/llm_page_classifier.py       (same)
services/structured_llm_classifier.py (same)
scripts/eval_gemini_models.py
tests/fixtures/eval/**                (gold labels)
tests/test_llm_gemini.py, tests/test_llm_accounting.py
frontend/components/settings/LlmSettings.tsx
.agents/AGENTS.md
```

Shared appends: `requirements.txt` (`google-genai` is already added by ws-0; add nothing unless needed), `.env.example` (`GEMINI_*` present; add `GEMINI_PRICING_JSON` if you externalise prices).

# Steps

## 1. Provider dispatch (`services/llm_client.py`)

- `llm_provider()` returns exactly one of `ollama | openai | openai_compatible | gemini | none`. Unknown value → raise `LLMConfigError` at first use with the allowed list. `none` → every call returns `None` immediately and records nothing.
- `call_llm_messages(messages, *, purpose, application_id=None, max_tokens, timeout, response_format="json"|"text")` becomes the single entry point; `call_llm_api(prompt)` wraps it. Every caller passes a `purpose` (`summary_en`, `summary_hi`, `page_classification`, `verification`, `eval`).
- Retries: 3 attempts with exponential backoff (1 s, 3 s) on timeouts, 429, 5xx; no retry on 4xx other than 429. Timeout default 60 s.
- Every attempt result (success or final failure) goes through `llm_accounting.record_call(...)`.

## 2. Gemini (`services/llm_gemini.py`)

Use `google-genai` (`from google import genai`). Auth: `GEMINI_API_KEY` if set,
else ADC (Vertex) with `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION`. Expose
`generate(messages, *, model, max_tokens, timeout, response_format) -> {"text", "tokens_in", "tokens_out", "model", "duration_ms", "finish_reason"}` reading `usage_metadata`. When `response_format="json"` set
`response_mime_type="application/json"`. Map SDK exceptions to
`LLMTransientError` / `LLMPermanentError` so the client's retry policy applies.
`list_models()` for the settings dropdown and the eval script.

## 3. Accounting (`services/llm_accounting.py`)

`record_call(provider, model, purpose, tokens_in, tokens_out, duration_ms, application_id, ok, error=None)` inserts an `llm_calls` row and computes
`est_cost_usd` from a price table `{model_prefix: (usd_per_1M_in, usd_per_1M_out)}`
kept in this module with a `# prices as of <date>` comment and overridable by
`GEMINI_PRICING_JSON`. Unknown model → cost `NULL`, not an error. Provide
`summarise_costs(since=None) -> [{model, calls, tokens_in, tokens_out, usd}]`
for the admin UI (ws-e) and the eval script.

## 4. Bilingual summary (`services/llm_service.py`)

`generate_summaries(application_id, context) -> {"en": str, "hi": str}`:

- Prompt input in TOON (keep the existing encoder), instruct the model to answer
  in **JSON** `{"en": "...", "hi": "..."}`, 2–3 sentences each, no technical
  terms (give the model the nine finding titles from
  `services/ops_templates_en_hi.py` when available — import lazily and fall back
  to a local list so you do not depend on ws-f merging first).
- Validate: JSON parses, both keys present, each ≤ 600 characters, Hindi
  contains Devanagari. On any failure (or provider `none`) return the
  deterministic fallback built from the finding counts (same wording as ws-f's
  fallback: keep a copy here, mark `# keep in sync with ops_presentation`).
- Persist to `applications.ops_summary_en/hi` (columns from ws-a; add
  identically in your worktree if needed and list it). Keep the existing
  `reviewer_summaries` summary write untouched.

Update the callers you own (`llm_verifier`, `llm_page_classifier`,
`structured_llm_classifier`) to pass `purpose` and to request JSON output;
replace TOON **output** parsing with `json.loads` + schema check, keeping TOON
for the prompt side. Update `tests/test_llm_toon_summary.py` expectations
accordingly and say so in the PR.

## 5. Bake-off (`scripts/eval_gemini_models.py`)

```bash
python scripts/eval_gemini_models.py --models gemini-2.5-flash,gemini-2.5-pro --fixtures tests/fixtures/eval --out outputs/gemini_eval_<timestamp>.csv
```

- `tests/fixtures/eval/gold.json`: for each fixture application id (reuse the
  existing fixture PDFs already in `tests/fixtures`), the expected set of
  finding codes (§11 vocabulary) and expected extracted values for
  `applicant_name`, `pan_number`, `address` where known. Start with the fixtures
  that exist; document how to add a case.
- For each model × fixture: run the pipeline with `LLM_PROVIDER=gemini`,
  `GEMINI_MODEL=<model>` (use the in-process runner with `DMEF_INLINE_WORKER=1`),
  then compute: `accuracy` (fraction of expected codes present), `false_positives`
  (codes present but not expected), `seconds` (wall), `tokens_in`, `tokens_out`,
  `usd` (from `llm_calls` for that application), `llm_calls` count.
- CSV columns exactly: `model,file,accuracy,false_positives,seconds,tokens_in,tokens_out,usd,calls,notes`.
  Print a per-model summary table at the end.
- The script must be `skipif`-friendly: with no credentials it prints the plan
  and exits 0.

## 6. Settings UI (`frontend/components/settings/LlmSettings.tsx`)

Providers list comes from `GET /settings/llm/providers` — you may not edit
`routes/settings.py` (ws-h); add the endpoint to a new `routes/llm_settings.py`
you own, registered via one line in `main.py`. It returns providers + for gemini
the `list_models()` result + current cost summary. Dropdown shows only real
providers; model field becomes a select for Gemini.

## 7. Tests

- `tests/test_llm_gemini.py`: fake the SDK client; success, 429 → retry →
  success, permanent 400 → no retry; JSON mode set; usage parsed.
- `tests/test_llm_accounting.py`: rows written per attempt; cost computed for a
  known prefix, `NULL` for unknown; `summarise_costs` aggregation.
- `tests/test_llm_service.py`: bilingual JSON happy path; malformed → fallback;
  provider `none` → fallback, zero `llm_calls` rows.

# Done when

- [ ] `LLM_PROVIDER=gemini GEMINI_MODEL=gemini-2.5-flash python -c "from services.llm_client import llm_provider, llm_model; print(llm_provider(), llm_model())"` prints `gemini gemini-2.5-flash` and never touches Ollama
- [ ] `LLM_PROVIDER=bogus` raises `LLMConfigError` with the allowed list
- [ ] Every LLM call writes one `llm_calls` row per attempt
- [ ] With credentials: `scripts/eval_gemini_models.py` runs two models over the fixtures and writes the CSV; without: exits 0 with the plan
- [ ] `.agents/AGENTS.md` states the input-TOON / output-JSON rule
- [ ] Full suite green; ruff clean; frontend typecheck/lint/test clean

# Verify

```bash
source .venv/bin/activate
python -m pytest -q
ruff check .
npm --prefix frontend run typecheck && npm --prefix frontend run lint && npm --prefix frontend test
LLM_PROVIDER=none python scripts/eval_gemini_models.py --models gemini-2.5-flash --fixtures tests/fixtures/eval --out /tmp/eval.csv
```

# PR description

Contracts §10 template, workstream `ws-g gemini + llm`. Attach the CSV summary
table if credentials were available; otherwise say so.

# Stop conditions

Contracts §10. Additionally: if `google-genai`'s API for usage metadata differs
from what you expect, read the installed package source
(`python -c "import google.genai, inspect; print(google.genai.__file__)"`) rather
than guessing field names.
