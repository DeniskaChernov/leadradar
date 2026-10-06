param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtime = Join-Path $projectRoot '.runtime'
$cloudflared = Join-Path $runtime 'bin\cloudflared.exe'
New-Item -ItemType Directory -Path (Split-Path $cloudflared) -Force | Out-Null
$startLock = New-Object System.Threading.Mutex($false, 'Local\LeadRadarCloudflareStart')
try { $lockHeld = $startLock.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $lockHeld = $true }
if (-not $lockHeld) { $startLock.Dispose(); throw 'Lead Radar startup is already in progress.' }
$newTunnel = $false

Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $cloudflared)) {
        $release = Invoke-RestMethod 'https://api.github.com/repos/cloudflare/cloudflared/releases/latest'
        $asset = $release.assets | Where-Object name -EQ 'cloudflared-windows-amd64.exe'
        if ($asset.digest -notmatch '^sha256:[a-f0-9]{64}$') { throw 'Missing release checksum.' }
        $download = $cloudflared + '.download'
        Invoke-WebRequest $asset.browser_download_url -OutFile $download
        $actual = 'sha256:' + (Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $asset.digest) { throw 'Cloudflared checksum mismatch.' }
        Move-Item -LiteralPath $download -Destination $cloudflared
    }
    $settings = ('import json; from app.config import get_settings; s=get_settings(); print(json.dumps(dict(host=s.web_host,port=s.web_port,auth=s.web_auth_enabled,url=s.web_public_url)))' | & $pythonPath -) | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read Lead Radar settings.' }
    $listener = Get-NetTCPConnection -State Listen -LocalPort $settings.port -ErrorAction SilentlyContinue
    $worker = $null
    if ($listener) {
        $worker = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener[0].OwningProcess)
        $launcher = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $worker.ParentProcessId)
        if ($launcher.ExecutablePath -ne $pythonPath -or $worker.CommandLine -notmatch '-m app.main --web-only') {
            throw 'The configured port belongs to another application.'
        }
        if (-not $settings.auth) { throw 'Stop the unprotected local server before opening a tunnel.' }
        $authStatus = 0
        try { $authStatus = (Invoke-WebRequest ('http://{0}:{1}/api/radar/feed' -f $settings.host, $settings.port) -UseBasicParsing -TimeoutSec 5).StatusCode }
        catch { if ($_.Exception.Response) { $authStatus = [int]$_.Exception.Response.StatusCode } }
        if ($authStatus -ne 401) { throw 'The running server must require login before publishing.' }
    }
    & $pythonPath -m scripts.configure_web_access
    if ($LASTEXITCODE -ne 0) { throw 'Cannot configure browser access.' }

    $pidFile = Join-Path $runtime 'cloudflare.pid'
    $urlFile = Join-Path $runtime 'public-url.txt'
    $tunnel = $null
    $publicUrl = ''
    if ((Test-Path $pidFile) -and (Test-Path $urlFile)) {
        $tunnel = Get-Process -Id ([int](Get-Content $pidFile)) -ErrorAction SilentlyContinue
        if ($tunnel -and $tunnel.Path -eq $cloudflared) { $publicUrl = (Get-Content $urlFile -Raw).Trim() }
    }
    if (-not $publicUrl) {
        # Do not expose an origin still using a previous host/configuration.
        if ($worker) { Stop-Process -Id $worker.ProcessId; $worker = $null }
        $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        $tunnelLog = Join-Path $runtime ('cloudflare-' + $stamp + '.stderr.log')
        $origin = 'http://{0}:{1}' -f $settings.host, $settings.port
        $tunnel = Start-Process -FilePath $cloudflared -ArgumentList 'tunnel','--no-autoupdate','--protocol','http2','--url',$origin `
            -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $runtime ('cloudflare-' + $stamp + '.stdout.log')) `
            -RedirectStandardError $tunnelLog
        $tunnel.Id | Set-Content -LiteralPath $pidFile
        $newTunnel = $true
        for ($attempt = 0; $attempt -lt 45; $attempt++) {
            if (Test-Path $tunnelLog) {
                $logText = Get-Content $tunnelLog -Raw
                if ($logText) {
                    $match = [regex]::Match($logText, 'https://[a-z0-9-]+\.trycloudflare\.com')
                    if ($match.Success) { $publicUrl = $match.Value; break }
                }
            }
            if ($tunnel.HasExited) { throw 'Cloudflare stopped. See .runtime tunnel logs.' }
            Start-Sleep -Seconds 1
        }
        if (-not $publicUrl) { throw 'Cloudflare did not issue a URL. See .runtime tunnel logs.' }
        $publicUrl | Set-Content -LiteralPath $urlFile
    }
    & $pythonPath -m scripts.configure_web_access --public-url $publicUrl
    if ($LASTEXITCODE -ne 0) { throw 'Cannot configure the public URL.' }
    if ($worker -and $settings.url -ne $publicUrl) { Stop-Process -Id $worker.ProcessId }
    & (Join-Path $PSScriptRoot 'start_web_windows.ps1')
    Write-Output ('Cloudflare URL: ' + $publicUrl + '/radar')
    Write-Output ('Password is stored locally: ' + (Join-Path $runtime 'web-access.txt'))
    if ($OpenBrowser) { Start-Process ($publicUrl + '/radar') }
} catch {
    if ($newTunnel -and $tunnel -and -not $tunnel.HasExited) { Stop-Process -Id $tunnel.Id }
    throw
} finally {
    Pop-Location
    $startLock.ReleaseMutex()
    $startLock.Dispose()
}
