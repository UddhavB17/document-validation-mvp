# Running DMEF Locally

The canonical install and first health-check path is in
[`README.md`](README.md#canonical-quickstart). This page covers day-to-day
start/stop commands, port overrides, runtime modes, and troubleshooting after
the dependencies are installed.

## Processes and URLs

DMEF uses an API, UI, and worker process:

| Process | Responsibility | Default URL |
|---|---|---|
| FastAPI backend | Upload, processing, review, verification, decision, settings, and health APIs | <http://127.0.0.1:8000> |
| Next.js UI | Browser interface | <http://localhost:3000> |
| Worker | Claims queued document-processing jobs | No browser URL |

The API health endpoint reports database, storage, and worker status. A stale
worker produces `status: degraded`; a database or storage error returns HTTP
503. Processing is ready when all four statuses are `ok`.

API docs: <http://127.0.0.1:8000/docs>. ReDoc:
<http://127.0.0.1:8000/redoc>.

## Start after setup

### macOS: two terminals

Terminal 1, from the repository root:

```bash
source .venv/bin/activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2, from any directory:

```bash
npm --prefix /absolute/path/to/document-validation-mvp/frontend run dev -- -p 3000
```

Replace the placeholder with this checkout's path. If Terminal 2 is already in
the repository root, use `npm --prefix frontend run dev -- -p 3000`.

Run `python -m services.worker` in a third activated terminal to start the
worker explicitly. Local uploads can also start it automatically. Check the
backend from another terminal:

```bash
curl -fsS http://127.0.0.1:8000/health
```

Press `Ctrl+C` in each manual terminal to stop its process.

### Windows PowerShell: supported launcher

From the repository root:

```powershell
.\run_local.ps1
```

The script runs the local health check, starts FastAPI and Next.js in separate
background processes, sets the frontend API base URL, and prints their PIDs and
log paths. Use `-SkipHealth` only when you have already diagnosed the setup:

```powershell
.\run_local.ps1 -SkipHealth
```

Stop listeners on the default ports with:

```powershell
.\stop_local.ps1
```

Both scripts force-stop processes listening on the ports they target. Do not
run them while unrelated services own those ports.

### macOS laptop launcher (optional)

```bash
./scripts/start_mvp.sh
```

This launcher is a different mode from the manual start. It requires the
`ollama` command, starts Ollama if needed, pulls configured models, forces
low-memory settings, force-stops listeners on ports `8000` and `3000`, and
starts both app processes in the background. It is useful for a small Mac when
Ollama is intentionally part of the run; it is not needed for the credential-
free health/UI smoke path.

Logs:

- `data/logs/ollama.log`
- `data/logs/uvicorn.log`
- `data/logs/frontend.log`

The launcher has no matching macOS stop script. Identify the PIDs printed by the
launcher or inspect the listeners with `lsof` before stopping anything. Do not
kill an unrelated process just because it uses a common development port.

## Port overrides

The Windows launcher accepts separate API and UI ports and automatically passes
the API port to Next.js:

```powershell
.\run_local.ps1 -ApiPort 8001 -UiPort 3001
```

For a manual macOS run, use the same API port in Uvicorn and
`NEXT_PUBLIC_API_BASE_URL`:

Terminal 1:

```bash
source .venv/bin/activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8001
```

Terminal 2:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8001 npm --prefix frontend run dev -- -p 3001
```

The frontend variable is read when Next.js starts. Restart the frontend after
changing it. The default UI code falls back to
`http://127.0.0.1:8000`, so no frontend `.env` file is needed for the default
ports.

## Health and diagnostics

Run the prerequisite check from an active Python 3.11 environment:

```bash
python -m services.local_health --no-ollama
```

To include the optional provider probe, omit `--no-ollama`:

```bash
python -m services.local_health
```

`--fail-on-error` changes the exit status for required errors and is what the
Windows setup/run scripts use:

```bash
python -m services.local_health --no-ollama --fail-on-error
```

On a fresh checkout, warnings about a not-yet-created database or processed
directory are expected. FastAPI initializes the database schema during startup.
The health command checks imports and paths; it does not perform live Google
Vision OCR or prove that an LLM model is usable.

PowerShell equivalent for the HTTP check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Windows launcher logs:

- `data/logs/backend.out.log`
- `data/logs/backend.err.log`
- `data/logs/next.out.log`
- `data/logs/next.err.log`

## Configuration choices

### Scanned pages

The normal application route is Google Vision:

```dotenv
OCR_PROVIDER=google_vision
```

Digital pages use their embedded text. Scanned pages require Google Vision API
credentials and network access; failures are recorded as page-processing errors
and are not silently converted into local OCR.

### LLM calls

LLM calls are optional. To make a local smoke run explicit and avoid Ollama or
API calls, set this in the ignored `.env` file and restart the backend:

```dotenv
LLM_PROVIDER=none
```

The final `LLM_PROVIDER` entry in `.env.example` selects Gemini. Set the
provider explicitly for your run; `auto` selects an API-compatible provider
when a key exists and otherwise selects Ollama. The macOS launcher explicitly
selects Ollama and enables limited page-classification features.

### Local OCR test mode

Do not use `OCR_PROVIDER=local` alone. The full backend only honors local OCR
when `DMEF_LOCAL_OCR_TEST_MODE=true` is also set. Prefer the isolated command,
which sets both values and runs one input page without calling Google Vision:

```bash
python scripts/test_offline_ocr.py /absolute/path/to/sample.pdf --page 1 --lang hi
```

Install its separate dependencies with `requirements-ocr-local.txt`; they are
not part of normal setup.

## Common issues

### `main.py` rejects the Python version

Use the Python 3.11 executable inside `.venv`:

macOS:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python --version
```

Windows:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

The expected version starts with `3.11`.

### `services.local_health` cannot import a module

Activate the environment and install the normal requirements from the
repository root:

```bash
python -m pip install -r requirements.txt
```

Do not install the heavyweight local OCR requirements just to start the normal
Google Vision-backed application.

### Frontend cannot reach the backend

Confirm the backend check succeeds at
`http://127.0.0.1:8000/health`. For a non-default API port, set
`NEXT_PUBLIC_API_BASE_URL` in the same shell that starts Next.js and restart the
frontend. Check the backend error log if the health request itself fails.

### Port already in use

On Windows, pass different ports to `run_local.ps1` as shown above. On macOS,
pass the new API port to Uvicorn and match it in
`NEXT_PUBLIC_API_BASE_URL`. Confirm ownership with `lsof` (macOS) or
`Get-NetTCPConnection` (Windows) before stopping a listener.

### Ollama is unavailable

This is only required for an Ollama-enabled mode. Set `LLM_PROVIDER=none` for a
credential-free local run, or install/start Ollama and make the configured model
available before using `scripts/start_mvp.sh`.

### Google Vision OCR fails

Check `OCR_PROVIDER`, the selected `GOOGLE_VISION_AUTH` mode, the credential
location, API enablement, billing, and network access. The prerequisite health
check only proves that `google-cloud-vision` is importable. Review the backend
log for the provider error; the app does not silently fall back to local OCR.

### A document upload is rejected

The upload validator enforces configured size and file/package limits. Use a
valid PDF for the normal upload, or follow the mapped ZIP rules and manifest
example in the README. Do not use password-protected PDFs or encrypted ZIP
members; those inputs are rejected by the current validator.

## Stop and clean up safely

Stop manual processes with `Ctrl+C`. On Windows, use `stop_local.ps1` for the
default or explicitly selected ports. Runtime files under `data/` may contain
document content, OCR text, reports, logs, and applicant data; inspect before
sharing or deleting. The repository ignores them, but ignore rules do not
protect copies made elsewhere.
