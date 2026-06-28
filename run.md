# Running DMEF Locally

DMEF has two processes that must both be running at the same time:

| Process | What it does | Default URL |
|---|---|---|
| **FastAPI backend** | Handles file uploads, decisions, and data APIs | `http://localhost:8000` |
| **Streamlit UI** | The browser interface you interact with | `http://localhost:8501` |

---

## Prerequisites

Before running for the first time, make sure you have completed the [Setup steps in README.md](README.md#setup).

Quick checklist:
- [ ] Python **3.11** installed
- [ ] `.venv` created with Python 3.11
- [ ] `pip install -r requirements.txt` done
- [ ] `.env` file exists (copied from `.env.example`)

---

## Step 1 — Activate the virtual environment

Open a terminal in the project root and activate the venv.

**Windows (PowerShell)**
```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
source .venv/bin/activate
```

You'll see `(.venv)` at the start of your prompt when it's active.

---

## Step 2 — Start the FastAPI backend

In your **first terminal** (with the venv active):

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Expected output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Application startup complete.
```

> The `--reload` flag auto-restarts the server whenever you change a `.py` file.  
> Leave this terminal open and running.

**Useful API links once the backend is running:**

| Link | What it shows |
|---|---|
| `http://localhost:8000/health` | Quick health check — should return `{"status":"ok"}` |
| `http://localhost:8000/docs` | Interactive Swagger UI for all API endpoints |
| `http://localhost:8000/redoc` | ReDoc API documentation |

---

## Step 3 — Start the Streamlit UI

Open a **second terminal**, activate the venv again, then run:

```bash
streamlit run app.py
```

Expected output:
```
  You can now view your Streamlit app in your browser.
  Local URL:  http://localhost:8501
  Network URL: http://192.168.x.x:8501
```

Your browser should open automatically. If not, navigate to `http://localhost:8501` manually.

---

## Step 4 — Use the app

The sidebar has three views:

| Page | What to do |
|---|---|
| **Upload** | Upload a loan-file PDF, fill in applicant details, submit |
| **Worklist** | See all uploaded applications and their status |
| **Results** | View checklist results, exceptions, and the LLM summary for an application |

---

## Running the test suite

With the venv active, from the project root:

```bash
pytest
```

To run a specific test file:
```bash
pytest tests/test_pdf_processor.py -v
pytest tests/test_ocr_engine.py -v
```

All 141 tests should pass.

> **First run note:** The first time OCR tests execute, PaddleOCR will download model weights (~100 MB). This is a one-time download and will be cached at `~/.paddleocr/` automatically.

---

## Stopping the servers

Press `Ctrl+C` in each terminal to stop the FastAPI backend and the Streamlit UI.

---

## Common Issues

### `ModuleNotFoundError: No module named 'paddle'`
Your venv is using the wrong Python version.  
Recreate the venv with Python 3.11 — see [README.md Setup](README.md#setup).

### `Address already in use` on port 8000
Another process is using port 8000. Either kill it or run the backend on a different port:
```bash
uvicorn main:app --reload --port 8001
```
Then update `API_BASE_URL=http://localhost:8001` in your `.env`.

### `.env` file not found / config errors
Make sure you have copied `.env.example` to `.env`:
```bash
copy .env.example .env   # Windows
cp .env.example .env     # macOS/Linux
```

### Streamlit can't connect to backend
Make sure the FastAPI backend is running first (Step 2) before opening the Streamlit UI.  
Check `http://localhost:8000/health` — if it doesn't respond, the backend isn't running.

### PaddleOCR model download hangs
This is a one-time download over your internet connection (~100 MB). If it hangs, check your network. The cache is stored at `~/.paddleocr/` and won't be downloaded again.
