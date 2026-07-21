param(
    [switch]$SkipInstall,
    [switch]$SkipHealth
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Require-Python311 {
    $python = Get-Command py -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Python launcher 'py' was not found. Install Python 3.11 from python.org and rerun setup.ps1."
    }

    & py -3.11 --version | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 was not found. Install Python 3.11 and make sure 'py -3.11' works."
    }
}

function Require-Node {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $node -or -not $npm) {
        throw "Node.js/npm were not found. Install Node.js 20+ and rerun setup.ps1."
    }

    & node --version | Out-Host
    & npm.cmd --version | Out-Host
}

Write-Step "Checking Python 3.11"
Require-Python311

Write-Step "Checking Node.js"
Require-Node

Write-Step "Creating virtual environment"
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & py -3.11 -m venv .venv
} else {
    Write-Host ".venv already exists"
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment Python was not created at $VenvPython"
}

Write-Step "Checking virtual environment Python"
& $VenvPython --version

if (-not $SkipInstall) {
    Write-Step "Installing dependencies"
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r requirements.txt

    Write-Step "Installing frontend dependencies"
    Push-Location (Join-Path $ProjectRoot "frontend")
    & npm.cmd install
    Pop-Location
} else {
    Write-Host "Skipping dependency install because -SkipInstall was provided"
}

Write-Step "Creating .env if missing"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example"
} else {
    Write-Host ".env already exists"
}

Write-Step "Creating local data folders"
$Folders = @(
    "data",
    "data\uploads",
    "data\pages",
    "data\reports",
    "data\processed",
    "data\logs"
)
foreach ($Folder in $Folders) {
    New-Item -ItemType Directory -Force -Path $Folder | Out-Null
}

if (-not $SkipHealth) {
    Write-Step "Running local health check"
    & $VenvPython -m services.local_health --fail-on-error
    if ($LASTEXITCODE -ne 0) {
        throw "Local health check failed. Fix the ERROR items above, then rerun setup.ps1."
    }
} else {
    Write-Host "Skipping health check because -SkipHealth was provided"
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Run .\run_local.ps1 to start DMEF."
