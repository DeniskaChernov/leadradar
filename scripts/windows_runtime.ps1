# Shared ownership and lifecycle checks for the manual Windows launchers.
# Runtime files are advisory; executable, command and creation time establish ownership.
function Enter-LeadRadarRuntimeLock {
    param([string]$ProjectRoot)
    $normalized = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\').ToLowerInvariant()
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($normalized))).Replace('-', '') }
    finally { $sha.Dispose() }
    $mutex = New-Object Threading.Mutex($false, ('Local\LeadRadarRuntime-' + $hash.Substring(0, 24)))
    try {
        try { $held = $mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $held = $true }
        if (-not $held) { throw 'Lead Radar startup or shutdown is already in progress. Wait for it to finish.' }
        return $mutex
    } catch { $mutex.Dispose(); throw }
}

function Exit-LeadRadarRuntimeLock {
    param($Mutex)
    if ($Mutex) { $Mutex.ReleaseMutex(); $Mutex.Dispose() }
}

function Set-LeadRadarRuntimeText {
    param([string]$Path, [string]$Value)
    $temporary = $Path + '.' + [guid]::NewGuid().ToString('N') + '.tmp'
    try {
        [IO.File]::WriteAllText($temporary, $Value, (New-Object Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    } finally { Remove-Item -LiteralPath $temporary -ErrorAction SilentlyContinue }
}

function Get-LeadRadarSettings {
    param([string]$PythonPath)
    $json = 'import json; from app.config import get_settings; s=get_settings(); print(json.dumps(dict(host=s.web_host,port=s.web_port,auth=s.web_auth_enabled,url=s.web_public_url)))' | & $PythonPath -
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read Lead Radar settings.' }
    return ($json | ConvertFrom-Json)
}

function Set-LeadRadarWebAccess {
    param([string]$PythonPath, [string]$PublicUrl = '')
    if ($PublicUrl) { & $PythonPath -m scripts.configure_web_access --public-url $PublicUrl }
    else { & $PythonPath -m scripts.configure_web_access }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot configure browser access.' }
}

function Get-LeadRadarOrigin {
    param($Settings)
    $hostname = $Settings.host
    if ($hostname -in @('0.0.0.0', '::', '[::]')) { $hostname = '127.0.0.1' }
    if ($hostname -match ':' -and -not $hostname.StartsWith('[')) { $hostname = '[' + $hostname + ']' }
    return ('http://{0}:{1}' -f $hostname, $Settings.port)
}

function Test-LeadRadarWebCommand {
    param([string]$CommandLine)
    return ($CommandLine -match '(?i)(?:^|\s)-m\s+app\.main\s+--web-only(?:\s|$)')
}

function Get-LeadRadarWebWorker {
    param([string]$PythonPath, [int]$Port)
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    $workers = @()
    foreach ($listener in $listeners) {
        $worker = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener.OwningProcess) -ErrorAction SilentlyContinue
        if (-not $worker) { throw ('Port {0} ownership could not be verified.' -f $Port) }
        $launcher = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $worker.ParentProcessId) -ErrorAction SilentlyContinue
        $ownsExecutable = ($worker.ExecutablePath -eq $PythonPath) -or ($launcher -and $launcher.ExecutablePath -eq $PythonPath -and (Test-LeadRadarWebCommand $launcher.CommandLine))
        if (-not $ownsExecutable -or -not (Test-LeadRadarWebCommand $worker.CommandLine)) {
            throw ('Port {0} belongs to another application. No process was stopped.' -f $Port)
        }
        if ($workers.ProcessId -notcontains $worker.ProcessId) { $workers += $worker }
    }
    if ($workers.Count -gt 1) { throw 'Several workers own the configured port. Stop this checkout before restarting.' }
    if ($workers.Count -eq 1) { return $workers[0] }
    return $null
}

function Save-LeadRadarProcess {
    param([string]$PidFile, $Process)
    $snapshot = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $Process.Id) -ErrorAction SilentlyContinue
    if (-not $snapshot) { throw 'The new process exited before startup completed. See .runtime logs.' }
    $identity = @{ process_id = [int]$snapshot.ProcessId; executable = $snapshot.ExecutablePath; created_at = $snapshot.CreationDate.ToUniversalTime().ToString('o') }
    Set-LeadRadarRuntimeText ($PidFile + '.json') ($identity | ConvertTo-Json -Compress)
    Set-LeadRadarRuntimeText $PidFile ([string]$snapshot.ProcessId)
}

function Get-LeadRadarSavedProcess {
    param([string]$PidFile, [string]$Executable, [string]$CommandPattern)
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    $processId = 0
    if (-not [int]::TryParse((Get-Content -LiteralPath $PidFile -Raw).Trim(), [ref]$processId) -or $processId -le 0) { return $null }
    $process = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $processId) -ErrorAction SilentlyContinue
    if (-not $process -or $process.ExecutablePath -ne $Executable -or $process.CommandLine -notmatch $CommandPattern) { return $null }
    $metadataFile = $PidFile + '.json'
    if (Test-Path -LiteralPath $metadataFile) {
        try { $identity = Get-Content -LiteralPath $metadataFile -Raw | ConvertFrom-Json } catch { return $null }
        if ($identity.process_id -ne $process.ProcessId -or $identity.executable -ne $Executable) { return $null }
        # Windows PowerShell keeps JSON dates as strings; PowerShell 7 can deserialize
        # them as DateTime. Compare the exact UTC instant in either representation.
        try {
            $createdAt = $identity.created_at
            if ($createdAt -is [string]) {
                $parsedCreatedAt = [datetime]::MinValue
                if (-not [datetime]::TryParseExact($createdAt, 'o', [Globalization.CultureInfo]::InvariantCulture,
                        [Globalization.DateTimeStyles]::RoundtripKind, [ref]$parsedCreatedAt)) { return $null }
                $createdAt = $parsedCreatedAt
            }
            if ($createdAt -isnot [datetime] -or $createdAt.Kind -eq [DateTimeKind]::Unspecified) { return $null }
            if ($createdAt.ToUniversalTime().Ticks -ne $process.CreationDate.ToUniversalTime().Ticks) { return $null }
        } catch { return $null }
    }
    return $process
}

function Remove-LeadRadarProcessFiles {
    param([string]$PidFile)
    Remove-Item -LiteralPath $PidFile, ($PidFile + '.json') -ErrorAction SilentlyContinue
}

function Stop-LeadRadarOwnedProcess {
    param($Process)
    if (-not $Process) { return }
    $current = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $Process.ProcessId) -ErrorAction SilentlyContinue
    if (-not $current) { return }
    if ($current.ExecutablePath -ne $Process.ExecutablePath -or $current.CreationDate -ne $Process.CreationDate -or $current.CommandLine -ne $Process.CommandLine) {
        throw 'Process identity changed. The replacement process was not stopped.'
    }
    Stop-Process -Id $current.ProcessId -ErrorAction Stop
    Wait-Process -Id $current.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
}

function Stop-LeadRadarWebLauncher {
    param($Launcher)
    if ($Launcher) {
        $workers = @(Get-CimInstance Win32_Process -Filter ('ParentProcessId=' + $Launcher.ProcessId) -ErrorAction SilentlyContinue)
        foreach ($worker in $workers) {
            if (Test-LeadRadarWebCommand $worker.CommandLine) { Stop-LeadRadarOwnedProcess $worker }
        }
        Stop-LeadRadarOwnedProcess $Launcher
    }
}

function Stop-LeadRadarWeb {
    param([string]$PythonPath, [string]$Runtime)
    $pidFile = Join-Path $Runtime 'server-launcher.pid'
    $launcher = Get-LeadRadarSavedProcess $pidFile $PythonPath '(?i)(?:^|\s)-m\s+app\.main\s+--web-only(?:\s|$)'
    Stop-LeadRadarWebLauncher $launcher
    Remove-LeadRadarProcessFiles $pidFile
}

function Wait-LeadRadarWebReady {
    param([string]$Origin, $StartedProcess = $null, [int]$Attempts = 60)
    for ($attempt = 0; $attempt -lt $Attempts; $attempt++) {
        if ($StartedProcess) {
            $StartedProcess.Refresh()
            if ($StartedProcess.HasExited) { throw 'Lead Radar stopped during startup. See .runtime server logs.' }
        }
        try {
            $health = Invoke-RestMethod -Uri ($Origin + '/health') -TimeoutSec 2
            if ($health.ok -and ($health.PSObject.Properties.Name -contains 'radar_live_armed')) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'Lead Radar did not become healthy. See .runtime server logs.'
}

function Assert-LeadRadarWebAuth {
    param([string]$Origin)
    $authStatus = 0
    try { $authStatus = (Invoke-WebRequest ($Origin + '/api/radar/feed') -UseBasicParsing -TimeoutSec 5).StatusCode }
    catch { if ($_.Exception.Response) { $authStatus = [int]$_.Exception.Response.StatusCode } }
    if ($authStatus -ne 401) { throw 'The running server must require login before publishing.' }
}

function Assert-LeadRadarTunnelReady {
    param([string]$PublicUrl)
    for ($attempt = 0; $attempt -lt 12; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri ($PublicUrl + '/health') -TimeoutSec 5
            if ($health.ok -and ($health.PSObject.Properties.Name -contains 'radar_live_armed')) { return }
        } catch { }
        Start-Sleep -Seconds 1
    }
    throw 'Local Lead Radar is healthy, but the Cloudflare URL is unavailable. See .runtime tunnel logs and check the internet connection.'
}

function Open-LeadRadarBrowser {
    param([string]$Url)
    try { Start-Process $Url }
    catch { Write-Warning ('Lead Radar is running. Open the browser manually: ' + $Url) }
}
