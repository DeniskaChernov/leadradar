# Start the server and tunnel at Windows sign-in; paid scans remain manual.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtime = Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$logFile = Join-Path $runtime 'windows-logon.log'
Start-Sleep -Seconds 20
for ($attempt = 1; $attempt -le 4; $attempt++) {
    try {
        & (Join-Path $PSScriptRoot 'start_cloudflare_windows.ps1') *>> $logFile
        Add-Content -LiteralPath $logFile -Value ((Get-Date -Format o) + ' Server ready after Windows sign-in.')
        exit 0
    } catch {
        Add-Content -LiteralPath $logFile -Value ((Get-Date -Format o) + ' Startup attempt ' + $attempt + ' failed: ' + $_.Exception.Message)
        if ($attempt -lt 4) { Start-Sleep -Seconds (20 * $attempt) }
    }
}
exit 1
