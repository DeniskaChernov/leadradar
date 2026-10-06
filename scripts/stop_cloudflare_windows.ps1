$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $projectRoot '.runtime'
$cloudflared = Join-Path $runtime 'bin\cloudflared.exe'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$pidFile = Join-Path $runtime 'cloudflare.pid'
if (Test-Path $pidFile) {
    $tunnel = Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue
    if ($tunnel -and $tunnel.Path -eq $cloudflared) { Stop-Process -Id $tunnel.Id }
}
# Only stop this checkout's Python worker, never unrelated apps.
$pidFile = Join-Path $runtime 'server-launcher.pid'
if (Test-Path $pidFile) {
    $launcher = Get-CimInstance Win32_Process -Filter ('ProcessId=' + [int](Get-Content $pidFile))
    if ($launcher -and $launcher.ExecutablePath -eq $pythonPath) {
        $workers = Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $launcher.ProcessId)
        foreach ($worker in $workers) {
            if ($worker.CommandLine -match '-m app.main --web-only') { Stop-Process -Id $worker.ProcessId }
        }
    }
}
Write-Output 'Lead Radar and its Cloudflare tunnel are stopped.'
