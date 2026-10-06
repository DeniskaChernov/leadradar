param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup_windows.bat first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) { throw 'Local .env is missing.' }

Push-Location $projectRoot
try {
    $settingsJson = 'import json; from app.config import get_settings; s=get_settings(); print(json.dumps(dict(host=s.web_host,port=s.web_port,url=s.web_public_url)))' | & $pythonPath -
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read server settings.' }
    $settings = $settingsJson | ConvertFrom-Json
    $serverUrl = 'http://{0}:{1}' -f $settings.host, $settings.port
    $listener = Get-NetTCPConnection -State Listen -LocalPort $settings.port -ErrorAction SilentlyContinue
    if ($listener) {
        $worker = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener[0].OwningProcess)
        $launcher = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $worker.ParentProcessId)
        if ($launcher.ExecutablePath -ne $pythonPath -or $worker.CommandLine -notmatch '-m app.main --web-only') {
            throw ('Port {0} belongs to a different process. No second server was started.' -f $settings.port)
        }
    } else {
        $runtime = Join-Path $projectRoot '.runtime'
        New-Item -ItemType Directory -Path $runtime -Force | Out-Null
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $process = Start-Process -FilePath $pythonPath -ArgumentList '-m','app.main','--web-only' `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $runtime ('server-' + $stamp + '.stdout.log')) `
            -RedirectStandardError (Join-Path $runtime ('server-' + $stamp + '.stderr.log'))
        $process.Id | Set-Content -LiteralPath (Join-Path $runtime 'server-launcher.pid')
    }
    $healthy = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri ($serverUrl + '/health') -TimeoutSec 2
            $healthy = $health.ok -and ($health.PSObject.Properties.Name -contains 'radar_live_armed')
        } catch { $healthy = $false }
        if ($healthy) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) { throw 'Lead Radar did not become healthy. See .runtime server logs.' }
    Write-Output ('Lead Radar is ready: ' + $serverUrl + '/radar')
    if ($OpenBrowser) {
        $browserUrl = $serverUrl
        if ($settings.url) { $browserUrl = $settings.url }
        Start-Process ($browserUrl + '/radar')
    }
} finally {
    Pop-Location
}
