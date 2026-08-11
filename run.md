# Running DMEF Locally

DMEF runs as two local processes:

| Process | What it does | Default URL |
|---|---|---|
| FastAPI backend | Uploads, processing jobs, decisions, and data APIs | `http://127.0.0.1:8000` |
| Next.js UI | Browser interface | `http://localhost:3000` |

## One-Command Local Run

On macOS, use the laptop-friendly launcher:

```bash
./scripts/start_mvp.sh
```

It starts Ollama when needed, verifies or pulls the configured model, and then
starts the backend and frontend. Page-level LLM classification remains limited
to Unknown pages and scanned pages below the configured OCR-confidence threshold.

From PowerShell in the project root:

```powershell
.\setup.ps1
.\run_local.ps1
```

The run script starts the backend and frontend and writes logs to `data/logs/`.

## Manual Run

Backend terminal:

```powershell
cd C:\Users\siddd\Documents\MS-fincap\document-validation-mvp
.\.venv\Scripts\Activate.ps1
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Frontend terminal:

```powershell
cd C:\Users\siddd\Documents\MS-fincap\document-validation-mvp\frontend
npm.cmd run dev -- -p 3000
```

Open `http://localhost:3000`.

## Useful Links

- UI: `http://localhost:3000`
- API health: `http://127.0.0.1:8000/health`
- API docs: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Common Issues

### Python version error

The backend requires Python 3.11.x. Recreate `.venv` with:

```powershell
py -3.11 -m venv .venv
```

### Frontend cannot reach backend

Make sure the FastAPI backend is running on `http://127.0.0.1:8000`. The frontend uses `NEXT_PUBLIC_API_BASE_URL`, defaulting to that backend URL.

### Port already in use

Use different ports:

```powershell
.\run_local.ps1 -ApiPort 8001 -UiPort 3001
```

If you change the API port, set `NEXT_PUBLIC_API_BASE_URL` for the frontend before starting it.

### Node or npm missing

Install Node.js 20+ and rerun:

```powershell
.\setup.ps1
```

### Ollama unavailable

On macOS, rerun `./scripts/start_mvp.sh`. The launcher starts Ollama and refuses
to start the application if the configured model cannot be made ready.

## Stopping Servers

If started manually, press `Ctrl+C` in each terminal.

If started with `run_local.ps1`, use the `Stop-Process` command printed by the script.
