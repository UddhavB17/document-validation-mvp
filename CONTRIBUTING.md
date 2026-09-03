# Contributing to DMEF

DMEF is an MVP for local document-processing development. Keep changes focused,
preserve the distinction between observed document evidence and trusted input,
and make the result easy for another intern to verify.

## Before editing

1. Follow the [README quickstart](README.md#canonical-quickstart) and confirm
   the `/health` response.
2. Read [`docs/MAINTAINING.md`](docs/MAINTAINING.md) to find the owning module.
3. Check the worktree and preserve unrelated changes:

```bash
git status --short --branch
```

## Change boundaries

- Keep request validation and response serialization in `routes/` and document
  processing in `services/` or `services/pipeline/`.
- Preserve existing response keys and compatibility facades unless a deliberate
  migration includes tests.
- Do not let trusted manifests overwrite observed OCR values.
- Never commit customer documents, OCR output, local databases, logs, `.env`
  files, API keys, or service-account files.
- Tests must not call Google Vision, Ollama, or another external service; mock
  provider boundaries instead.

## Verification

With `.venv` active, run the checks relevant to the change. Backend checks:

```bash
python -m pytest -q
python -m compileall -q main.py database routes services tests
ruff check routes/review.py services/paths.py services/review tests/test_paths.py tests/test_compatibility_facades.py tests/test_review_boundary.py tests/test_low_memory.py
ruff format --check routes/review.py services/paths.py services/review tests/test_paths.py tests/test_compatibility_facades.py tests/test_review_boundary.py tests/test_low_memory.py
mypy services/paths.py services/review
```

For frontend-facing changes:

```bash
npm --prefix frontend run typecheck
npm --prefix frontend run lint
npm --prefix frontend run build
```

For documentation-only changes, validate referenced commands against the
scripts/configuration they mention and run:

```bash
git diff --check
git status --short --ignored
```

If a check needs credentials, an approved document, or an unavailable optional
service, report that limitation rather than claiming the check passed.

## Before committing

Inspect the staged file list and content:

```bash
git diff --cached --stat
git diff --cached
```

Use a short subject describing the focused change. When handing work back,
include the commit hash, files changed, verification performed, and checks not
run.
