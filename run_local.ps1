param(
    [int]$ApiPort = 8000,
    [int]$UiPort = 3000,
    [switch]$SkipHealth
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found. Run .\setup.ps1 first."
}

$Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $Npm) {
    throw "npm.cmd was not found. Install Node.js 20+ and rerun .\setup.ps1."
}

if (-not (Test-Path ".env")) {
    throw ".env not found. Run .\setup.ps1 first or copy .env.example to .env."
}

New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null

function Assert-PortAvailable {
    param(
        [int]$Port,
        [string]$ServiceName
    )

    $Listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($Listeners) {
        $ProcessIds = ($Listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
        throw "$ServiceName port $Port is already in use by PID(s) $ProcessIds. Stop the existing instance before starting DMEF again."
    }
}

Assert-PortAvailable -Port $ApiPort -ServiceName "Backend"
Assert-PortAvailable -Port $UiPort -ServiceName "Streamlit"

if (-not $SkipHealth) {
    Write-Host "Running local health check..." -ForegroundColor Cyan
    & $Python -m services.local_health --fail-on-error
    if ($LASTEXITCODE -ne 0) {
        throw "Local health check failed. Fix the ERROR items above, then rerun run_local.ps1."
    }
}

$BackendOut = Join-Path $ProjectRoot "data\logs\backend.out.log"
$BackendErr = Join-Path $ProjectRoot "data\logs\backend.err.log"
$UiOut = Join-Path $ProjectRoot "data\logs\next.out.log"
$UiErr = Join-Path $ProjectRoot "data\logs\next.err.log"

Write-Host ""
Write-Host "Starting FastAPI backend on http://127.0.0.1:$ApiPort" -ForegroundColor Cyan
$Backend = Start-Process `
    -FilePath $Python `
    -ArgumentList @("-m", "uvicorn", "main:app", "--reload", "--host", "127.0.0.1", "--port", "$ApiPort") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $BackendOut `
    -RedirectStandardError $BackendErr `
    -WindowStyle Hidden `
    -PassThru

Start-Sleep -Seconds 2

Write-Host "Starting Next.js UI on http://localhost:$UiPort" -ForegroundColor Cyan
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:$ApiPort"
$Ui = Start-Process `
    -FilePath $Npm.Source `
    -ArgumentList @("run", "dev", "--", "-p", "$UiPort") `
    -WorkingDirectory (Join-Path $ProjectRoot "frontend") `
    -RedirectStandardOutput $UiOut `
    -RedirectStandardError $UiErr `
    -WindowStyle Hidden `
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
