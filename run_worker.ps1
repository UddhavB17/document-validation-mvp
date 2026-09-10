#Requires -Version 5.1
<#
.SYNOPSIS
  Start the DMEF worker detached with file logs (standard way).

.DESCRIPTION
  Launches `python -m services.worker` detached from this terminal with
  stdout/stderr appended to data\logs\worker-out.log and
  data\logs\worker-err.log, so a crash leaves a traceback to diagnose.
  Prints the PID and log paths. The API + lifespan watchdog will also
  auto-start a worker (same log files) when jobs are pending and the
  heartbeat is stale; use this script for explicit manual starts.

  Stop with: Get-Process python | Where-Object { $_.CommandLine -like "*services.worker*" } | Stop-Process
#>

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $root "data\logs"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python venv not found at $python. Run .\setup.ps1 first."
}
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$outLog = Join-Path $logs "worker-out.log"
$errLog = Join-Path $logs "worker-err.log"

$proc = Start-Process -FilePath $python `
    -ArgumentList "-m services.worker" `
    -WorkingDirectory $root `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -WindowStyle Hidden `
    -PassThru

Write-Output "DMEF worker started (PID $($proc.Id))."
Write-Output "Logs: $outLog"
Write-Output "      $errLog"
Write-Output "Health: Invoke-RestMethod http://127.0.0.1:8000/health (worker should be ok within ~40s)"
