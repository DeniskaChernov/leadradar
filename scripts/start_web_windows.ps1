param([switch]$OpenBrowser, [switch]$WebOnly)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_runtime.ps1')
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup_windows.bat first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) { throw 'Local .env is missing.' }
$runtime = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$runtimeLock = Enter-LeadRadarRuntimeLock $projectRoot
$startedProcess = $null
$pidFile = Join-Path $runtime 'server-launcher.pid'

Push-Location $projectRoot
try {
    $settings = Get-LeadRadarSettings $pythonPath
    $serverUrl = Get-LeadRadarOrigin $settings
    $worker = Get-LeadRadarWebWorker $pythonPath $settings.port
    $launcher = Get-LeadRadarSavedProcess $pidFile $pythonPath '(?i)(?:^|\s)-m\s+app\.main(?:\s+--web-only)?\s*$'
    $requestedMode = 'web-only'
    if ($settings.mode -eq 'full') { $requestedMode = 'full' }
    elseif ($settings.mode -and $settings.mode -ne 'web-only') { throw 'Unknown Windows runtime mode.' }
    if ($WebOnly) { $requestedMode = 'web-only' }
    $existingProcess = $worker
    if (-not $existingProcess) { $existingProcess = $launcher }
    if ($existingProcess) {
        $existingMode = 'full'
        if ($existingProcess.CommandLine -match '\s--web-only(?:\s|$)') { $existingMode = 'web-only' }
        if ($existingMode -ne $requestedMode) {
            throw 'Runtime mode changed. Stop the owned server before starting the configured mode.'
        }
    }
    if (-not $worker -and -not $launcher) {
        Remove-LeadRadarProcessFiles $pidFile
        $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        $launchArguments = @('-m', 'app.main')
        if ($requestedMode -eq 'web-only') { $launchArguments += '--web-only' }
        $startedProcess = Start-Process -FilePath $pythonPath -ArgumentList $launchArguments `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $runtime ('server-' + $stamp + '.stdout.log')) `
            -RedirectStandardError (Join-Path $runtime ('server-' + $stamp + '.stderr.log'))
        Save-LeadRadarProcess $pidFile $startedProcess
    }
    Wait-LeadRadarWebReady $serverUrl $startedProcess
    Write-Output ('Lead Radar is ready: ' + $serverUrl + '/radar')
    if ($OpenBrowser) {
        $browserUrl = $serverUrl
        if ($settings.url) { $browserUrl = $settings.url }
        Open-LeadRadarBrowser ($browserUrl + '/radar')
    }
} catch {
    # Clean up only a failed cold start owned by this invocation.
    if ($startedProcess) {
        $owned = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $startedProcess.Id) -ErrorAction SilentlyContinue
        if ($owned -and $owned.ExecutablePath -eq $pythonPath -and (Test-LeadRadarWebCommand $owned.CommandLine)) {
            Stop-LeadRadarWebLauncher $owned
        }
        Remove-LeadRadarProcessFiles $pidFile
    }
    throw
} finally {
    Pop-Location
    Exit-LeadRadarRuntimeLock $runtimeLock
}
