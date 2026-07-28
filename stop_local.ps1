param(
    [int]$ApiPort = 8000,
    [int]$UiPort  = 3000
)

$ErrorActionPreference = "Continue"

function Stop-Port {
    param([int]$Port, [string]$ServiceName)
    $Listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($Listeners) {
        $ProcessIds = $Listeners | Select-Object -ExpandProperty OwningProcess -Unique
        Write-Host "Stopping $ServiceName (PID: $($ProcessIds -join ', ')) on port $Port..." -ForegroundColor Yellow
        $ProcessIds | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        Write-Host "$ServiceName stopped." -ForegroundColor Green
    } else {
        Write-Host "$ServiceName (port $Port) is not running." -ForegroundColor Gray
    }
}

Stop-Port -Port $ApiPort -ServiceName "Backend"
Stop-Port -Port $UiPort  -ServiceName "UI (Next.js)"
Write-Host ""
Write-Host "All DMEF services stopped." -ForegroundColor Green
