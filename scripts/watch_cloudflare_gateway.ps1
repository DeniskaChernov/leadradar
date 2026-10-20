# Embedded transport recovery only. Never starts paid scans, AI or Telegram sends.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
. (Join-Path $PSScriptRoot 'windows_runtime.ps1')
$failures = 0
Push-Location $projectRoot
try {
    while (Test-Path -LiteralPath (Join-Path $projectRoot '.runtime\cloudflare-gateway.json')) {
        Start-Sleep -Seconds 60
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.runtime\cloudflare-gateway.json'))) { break }
        try {
            $settings = Get-LeadRadarSettings $pythonPath
            $origin = Get-LeadRadarOrigin $settings
            $local = Invoke-RestMethod ($origin + '/health') -TimeoutSec 5
            if (-not $local.ok) { continue }
            $gateway = Get-LeadRadarGateway $pythonPath
            if (-not $gateway) { break }
            try {
                $public = Invoke-RestMethod ($gateway.public_url + '/health') -TimeoutSec 10
                if ($public.ok -and ($public.PSObject.Properties.Name -contains 'radar_live_armed')) { $failures = 0; continue }
            } catch { }
            $failures++
            if ($failures -lt 2) { continue }
            # The launcher owns the runtime mutex and preserves a busy local server.
            & (Join-Path $PSScriptRoot 'start_cloudflare_windows.ps1')
            $failures = 0
        } catch {
            Write-Output ((Get-Date -Format o) + ' Gateway recovery deferred; local server was preserved.')
            # Avoid creating tunnels repeatedly during an Internet outage.
            Start-Sleep -Seconds 120
        }
    }
} finally { Pop-Location }
