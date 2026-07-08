param(
    [int]$ApiPort = 8000,
    [int]$UiPort = 8501,
    [switch]$SkipHealth
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\setup.ps1 first."
}

if (-not (Test-Path ".env")) {
    throw ".env not found. Run .\setup.ps1 first or copy .env.example to .env."
}

New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null

if (-not $SkipHealth) {
    Write-Host "Running local health check..." -ForegroundColor Cyan
    & $Python -m services.local_health --fail-on-error
    if ($LASTEXITCODE -ne 0) {
        throw "Local health check failed. Fix the ERROR items above, then rerun run_local.ps1."
    }
}

$BackendOut = Join-Path $ProjectRoot "data\logs\backend.out.log"
$BackendErr = Join-Path $ProjectRoot "data\logs\backend.err.log"
$UiOut = Join-Path $ProjectRoot "data\logs\streamlit.out.log"
$UiErr = Join-Path $ProjectRoot "data\logs\streamlit.err.log"

Write-Host ""
Write-Host "Starting FastAPI backend on http://127.0.0.1:$ApiPort" -ForegroundColor Cyan
$Backend = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "main:app", "--reload", "--host", "127.0.0.1", "--port", "$ApiPort") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $BackendOut `
    -RedirectStandardError $BackendErr `
    -PassThru

Start-Sleep -Seconds 2

Write-Host "Starting Streamlit UI on http://localhost:$UiPort" -ForegroundColor Cyan
$Ui = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "streamlit", "run", "app.py", "--server.port", "$UiPort") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $UiOut `
    -RedirectStandardError $UiErr `
    -PassThru

Write-Host ""
Write-Host "DMEF is starting." -ForegroundColor Green
Write-Host "Backend PID: $($Backend.Id)"
Write-Host "UI PID:      $($Ui.Id)"
Write-Host ""
Write-Host "Open:"
Write-Host "  UI:      http://localhost:$UiPort"
Write-Host "  API:     http://127.0.0.1:$ApiPort"
Write-Host "  API docs http://127.0.0.1:$ApiPort/docs"
Write-Host ""
Write-Host "Logs:"
Write-Host "  $BackendOut"
Write-Host "  $BackendErr"
Write-Host "  $UiOut"
Write-Host "  $UiErr"
Write-Host ""
Write-Host "To stop later, close the processes from Task Manager or run:"
Write-Host "  Stop-Process -Id $($Backend.Id),$($Ui.Id)"
