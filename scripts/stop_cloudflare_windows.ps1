$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_runtime.ps1')
$runtime = Join-Path $projectRoot '.runtime'
$cloudflared = Join-Path $runtime 'bin\cloudflared.exe'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeLock = Enter-LeadRadarRuntimeLock $projectRoot
Push-Location $projectRoot
try {
    $pidFile = Join-Path $runtime 'cloudflare.pid'
    $tunnel = Get-LeadRadarSavedProcess $pidFile $cloudflared '(?i)(?:^|\s)tunnel(?:\s|$).*\s--url\s+http://'
    Stop-LeadRadarOwnedProcess $tunnel
    Remove-LeadRadarProcessFiles $pidFile
    Remove-Item -LiteralPath (Join-Path $runtime 'public-url.txt') -ErrorAction SilentlyContinue
    Stop-LeadRadarWeb $pythonPath $runtime
    # Recover an owned worker whose venv launcher already exited or lost its PID file.
    if ((Test-Path -LiteralPath $pythonPath) -and (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
        $settings = Get-LeadRadarSettings $pythonPath
        $worker = Get-LeadRadarWebWorker $pythonPath $settings.port
        if ($worker) { Stop-LeadRadarOwnedProcess $worker }
    }
    Write-Output 'Lead Radar and its Cloudflare tunnel are stopped.'
} finally {
    Pop-Location
    Exit-LeadRadarRuntimeLock $runtimeLock
}
