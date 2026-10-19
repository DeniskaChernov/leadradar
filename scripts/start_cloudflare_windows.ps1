param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_runtime.ps1')
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Run setup_windows.bat first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) { throw 'Local .env is missing.' }
$runtime = Join-Path $projectRoot '.runtime'
$cloudflared = Join-Path $runtime 'bin\cloudflared.exe'
New-Item -ItemType Directory -Path (Split-Path $cloudflared) -Force | Out-Null
$startLock = Enter-LeadRadarRuntimeLock $projectRoot
$newTunnel = $false
$webWasStarted = $false
$localReady = $false
$tunnel = $null
$pidFile = Join-Path $runtime 'cloudflare.pid'
$urlFile = Join-Path $runtime 'public-url.txt'

Push-Location $projectRoot
try {
    # The local cabinet must remain available even when DNS/Cloudflare is down.
    $settings = Get-LeadRadarSettings $pythonPath
    $origin = Get-LeadRadarOrigin $settings
    $worker = Get-LeadRadarWebWorker $pythonPath $settings.port
    if ($worker) {
        if (-not $settings.auth) { throw 'Stop the unprotected local server before opening a tunnel.' }
        Assert-LeadRadarWebAuth $origin
    }
    Set-LeadRadarWebAccess $pythonPath
    $webWasStarted = -not $worker
    & (Join-Path $PSScriptRoot 'start_web_windows.ps1')
    Assert-LeadRadarWebAuth $origin
    $localReady = $true
    $worker = Get-LeadRadarWebWorker $pythonPath $settings.port

    if (-not (Test-Path -LiteralPath $cloudflared)) {
        $release = Invoke-RestMethod 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest'
        $asset = $release.assets | Where-Object name -EQ 'cloudflared-windows-amd64.exe'
        if ($asset.digest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Missing release checksum.' }
        $download = $cloudflared + '.download'
        try {
            Invoke-WebRequest $asset.browser_download_url -OutFile $download -UseBasicParsing -TimeoutSec 60
            $actual = 'sha256:' + (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLower()
            if ($actual -ne $asset.digest) { throw 'Cloudflared checksum mismatch.' }
            Move-Item -LiteralPath $download -Destination $cloudflared
        } finally { Remove-Item -LiteralPath $download -ErrorAction SilentlyContinue }
    }
    $publicUrl = ''
    $savedTunnel = Get-LeadRadarSavedProcess $pidFile $cloudflared '(?i)(?:^|\s)tunnel(?:\s|$).*\s--url\s+http://'
    $originPattern = '\s--url\s+"?' + [regex]::Escape($origin) + '"?(?:\s|$)'
    if ($savedTunnel -and $savedTunnel.CommandLine -match $originPattern -and (Test-Path -LiteralPath $urlFile)) {
        $candidateUrl = (Get-Content -LiteralPath $urlFile -Raw).Trim()
        if ($candidateUrl -match '^https://[a-z0-9-]+\.trycloudflare\.com$') {
            $publicUrl = $candidateUrl
            $tunnel = Get-Process -Id $savedTunnel.ProcessId -ErrorAction SilentlyContinue
        }
    }
    if (-not $publicUrl) {
        Stop-LeadRadarOwnedProcess $savedTunnel
        Remove-LeadRadarProcessFiles $pidFile
        Remove-Item -LiteralPath $urlFile -ErrorAction SilentlyContinue
        $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
        $tunnelLog = Join-Path $runtime ('cloudflare-' + $stamp + '.stderr.log')
        $tunnel = Start-Process -FilePath $cloudflared -ArgumentList 'tunnel','--no-autoupdate','--protocol','auto','--url',$origin `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $runtime ('cloudflare-' + $stamp + '.stdout.log')) `
            -RedirectStandardError $tunnelLog
        $newTunnel = $true
        Save-LeadRadarProcess $pidFile $tunnel
        $tunnelConnected = $false
        for ($attempt = 0; $attempt -lt 45; $attempt++) {
            if (Test-Path $tunnelLog) {
                $logText = Get-Content $tunnelLog -Raw
                if ($logText) {
                    $match = [regex]::Match($logText, 'https://[a-z0-9-]+\.trycloudflare\.com')
                    if ($match.Success) { $publicUrl = $match.Value }
                    if ($publicUrl -and $logText -match 'Registered tunnel connection') {
                        $tunnelConnected = $true
                        break
                    }
                }
            }
            $tunnel.Refresh()
            if ($tunnel.HasExited) { throw 'Cloudflare stopped. See .runtime tunnel logs.' }
            Start-Sleep -Seconds 1
        }
        if (-not $publicUrl) { throw 'Cloudflare did not issue a URL. See .runtime tunnel logs.' }
        if (-not $tunnelConnected) { throw 'Cloudflare did not connect to its edge. The local server remains available.' }
        Set-LeadRadarRuntimeText $urlFile $publicUrl
    }
    if ($worker -and $settings.url -ne $publicUrl) {
        # A new hostname needs a reload of the exact allowed-host configuration.
        # Never interrupt a paid search/analysis just to replace its public URL.
        Assert-LeadRadarIdleForRestart $origin
        Stop-LeadRadarWeb $pythonPath $runtime
        Stop-LeadRadarOwnedProcess $worker
        $worker = $null
        $webWasStarted = $true
        $localReady = $false
    }
    Set-LeadRadarWebAccess $pythonPath $publicUrl
    & (Join-Path $PSScriptRoot 'start_web_windows.ps1')
    Assert-LeadRadarWebAuth $origin
    $localReady = $true
    Assert-LeadRadarTunnelReady $publicUrl
    Write-Output ('Cloudflare URL: ' + $publicUrl + '/radar')
    Write-Output ('Password is stored locally: ' + (Join-Path $runtime 'web-access.txt'))
    if ($OpenBrowser) { Open-LeadRadarBrowser ($publicUrl + '/radar') }
} catch {
    # Cleanup an unhealthy cold start, never a ready cabinet after a tunnel error.
    if ($webWasStarted -and -not $localReady) { Stop-LeadRadarWeb $pythonPath $runtime }
    if ($newTunnel -and $tunnel) {
        $ownedTunnel = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $tunnel.Id) -ErrorAction SilentlyContinue
        if ($ownedTunnel -and $ownedTunnel.ExecutablePath -eq $cloudflared -and $ownedTunnel.CommandLine -match $originPattern) { Stop-LeadRadarOwnedProcess $ownedTunnel }
        Remove-LeadRadarProcessFiles $pidFile
        Remove-Item -LiteralPath $urlFile -ErrorAction SilentlyContinue
    }
    throw
} finally {
    Pop-Location
    Exit-LeadRadarRuntimeLock $startLock
}
