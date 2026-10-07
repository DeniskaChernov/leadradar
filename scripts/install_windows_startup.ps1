param([switch]$Remove, [switch]$Preview)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$startupFolder = [Environment]::GetFolderPath('Startup')
if (-not $startupFolder) { throw 'The current user Windows Startup folder is unavailable.' }
$shortcutPath = Join-Path $startupFolder 'Lead Radar.lnk'
$powershellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$bootstrapPath = Join-Path $PSScriptRoot 'start_at_logon_windows.ps1'
if (-not (Test-Path -LiteralPath $bootstrapPath)) { throw 'The Lead Radar Windows startup script is missing.' }
$arguments = '-NoProfile -WindowStyle Hidden -File "' + $bootstrapPath + '"'
if ($Preview) {
    @{ shortcut = $shortcutPath; target = $powershellPath; arguments = $arguments; working_directory = $projectRoot; remove = [bool]$Remove } | ConvertTo-Json -Compress
    exit 0
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
if ((Test-Path -LiteralPath $shortcutPath) -and ($shortcut.WorkingDirectory -ne $projectRoot -or $shortcut.TargetPath -ne $powershellPath -or $shortcut.Arguments -ne $arguments)) {
    throw 'A different Lead Radar startup shortcut already exists. It was not changed.'
}
if ($Remove) {
    Remove-Item -LiteralPath $shortcutPath -ErrorAction SilentlyContinue
    Write-Output 'Lead Radar Windows sign-in startup removed.'
    exit 0
}
$shortcut.TargetPath = $powershellPath
$shortcut.Arguments = $arguments
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = 'Start Lead Radar server and protected Cloudflare access. Lead search is manual.'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Output ('Lead Radar will start at Windows sign-in: ' + $shortcutPath)
