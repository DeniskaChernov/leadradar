"""Exercise Windows launcher ownership and cleanup in an isolated, mocked workspace."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("powershell.exe")
POWERSHELL_CORE = shutil.which("pwsh.exe")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not POWERSHELL, reason="Windows PowerShell lifecycle checks"
)


def _ps_quote(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _run(
    tmp_path: Path, code: str, *, timeout: float = 30, powershell: str | None = None
) -> dict:
    script = tmp_path / "probe.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        + ". "
        + _ps_quote(ROOT / "scripts" / "windows_runtime.ps1")
        + "\n"
        + code,
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [str(powershell or POWERSHELL), "-NoProfile", "-NonInteractive", "-File", str(script)],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    ("content", "executable", "command", "metadata_date", "owned"),
    [
        ("not-a-pid", "python.exe", "python -m app.main --web-only", "", False),
        ("-1", "python.exe", "python -m app.main --web-only", "", False),
        ("42", "foreign.exe", "python -m app.main --web-only", "", False),
        ("42", "python.exe", "python unrelated.py", "", False),
        ("42", "python.exe", "python -m app.main --web-only", "2000-01-01", False),
        ("42", "python.exe", "python -m app.main --web-only", "", True),
        (
            "42",
            "python.exe",
            "python -m app.main --web-only",
            "2026-10-07T00:00:00.0000000Z",
            True,
        ),
    ],
)
def test_pid_file_requires_owned_process_identity(
    tmp_path, content, executable, command, metadata_date, owned
):
    pid_file = tmp_path / "server.pid"
    pid_file.write_text(content, encoding="utf-8")
    if metadata_date:
        Path(str(pid_file) + ".json").write_text(
            json.dumps(
                {"process_id": 42, "executable": "python.exe", "created_at": metadata_date}
            ),
            encoding="utf-8",
        )
    result = _run(
        tmp_path,
        rf"""
function Get-CimInstance {{
    [pscustomobject]@{{ ProcessId=42; ExecutablePath={_ps_quote(executable)};
        CommandLine={_ps_quote(command)}; CreationDate=[datetime]'2026-10-07T00:00:00Z' }}
}}
$process = Get-LeadRadarSavedProcess {_ps_quote(pid_file)} 'python.exe' '(?:^|\s)-m\s+app\.main\s+--web-only(?:\s|$)'
@{{ owned=($null -ne $process) }} | ConvertTo-Json -Compress
""",
    )
    assert result["owned"] is owned


@pytest.mark.parametrize(
    "powershell",
    [
        pytest.param(POWERSHELL, id="powershell5"),
        pytest.param(
            POWERSHELL_CORE,
            id="powershell7",
            marks=pytest.mark.skipif(not POWERSHELL_CORE, reason="PowerShell 7 not installed"),
        ),
    ],
)
@pytest.mark.parametrize(
    ("created_at", "metadata_pid", "owned"),
    [
        ("2026-10-07T00:00:00.1234567Z", 42, True),
        ("2026-10-07T05:00:00.1234567+05:00", 42, True),
        ("2026-10-07T00:00:00.1234568Z", 42, False),
        ("2026-10-07T00:00:00.1234567Z", 99, False),
        ("2026-10-07T00:00:00.1234567", 42, False),
        ("invalid-date", 42, False),
        (None, 42, False),
        (1234567, 42, False),
        (False, 42, False),
    ],
)
def test_saved_process_creation_instant_across_powershell_versions(
    tmp_path, powershell, created_at, metadata_pid, owned
):
    pid_file = tmp_path / "server.pid"
    pid_file.write_text("42", encoding="utf-8")
    Path(str(pid_file) + ".json").write_text(
        json.dumps(
            {"process_id": metadata_pid, "executable": "python.exe", "created_at": created_at}
        ),
        encoding="utf-8",
    )
    result = _run(
        tmp_path,
        rf"""
function Get-CimInstance {{
    [pscustomobject]@{{ ProcessId=42; ExecutablePath='python.exe';
        CommandLine='python -m app.main --web-only';
        CreationDate=[datetime]::ParseExact('2026-10-07T00:00:00.1234567Z', 'o',
            [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind) }}
}}
$process = Get-LeadRadarSavedProcess {_ps_quote(pid_file)} 'python.exe' '(?:^|\s)-m\s+app\.main\s+--web-only(?:\s|$)'
@{{ owned=($null -ne $process) }} | ConvertTo-Json -Compress
""",
        powershell=powershell,
    )
    assert result["owned"] is owned


def test_recycled_pid_is_not_stopped(tmp_path):
    result = _run(
        tmp_path,
        """
$global:stops = 0
$original = [pscustomobject]@{ ProcessId=42; ExecutablePath='python.exe';
    CommandLine='python -m app.main --web-only'; CreationDate=[datetime]'2026-10-07T00:00:00Z' }
function Get-CimInstance {
    [pscustomobject]@{ ProcessId=42; ExecutablePath='python.exe';
        CommandLine='python unrelated.py'; CreationDate=[datetime]'2026-10-07T01:00:00Z' }
}
function Stop-Process { $global:stops++ }
$blocked=$false
try { Stop-LeadRadarOwnedProcess $original } catch { $blocked=$true }
@{ blocked=$blocked; stops=$global:stops } | ConvertTo-Json -Compress
""",
    )
    assert result == {"blocked": True, "stops": 0}


def test_foreign_port_is_rejected_without_stopping_it(tmp_path):
    result = _run(
        tmp_path,
        """
$global:stops=0
function Get-NetTCPConnection { [pscustomobject]@{ OwningProcess=42 } }
function Get-CimInstance {
    [pscustomobject]@{ ProcessId=42; ParentProcessId=10; ExecutablePath='foreign.exe'; CommandLine='foreign.exe' }
}
function Stop-Process { $global:stops++ }
$blocked=$false
try { Get-LeadRadarWebWorker 'python.exe' 8000 | Out-Null } catch { $blocked=$true }
@{ blocked=$blocked; stops=$global:stops } | ConvertTo-Json -Compress
""",
    )
    assert result == {"blocked": True, "stops": 0}


def test_health_wait_fails_immediately_when_launcher_exits(tmp_path):
    result = _run(
        tmp_path,
        """
$process = [pscustomobject]@{ HasExited=$true }
$process | Add-Member ScriptMethod Refresh { }
$global:requests=0
function Invoke-RestMethod { $global:requests++; throw 'network must not be reached' }
$blocked=$false
try { Wait-LeadRadarWebReady 'http://localhost:8000' $process 1 } catch { $blocked=$true }
@{ blocked=$blocked; requests=$global:requests } | ConvertTo-Json -Compress
""",
    )
    assert result == {"blocked": True, "requests": 0}


def test_browser_failure_does_not_fail_ready_server(tmp_path):
    result = _run(
        tmp_path,
        """
function Start-Process { throw 'No browser association' }
Open-LeadRadarBrowser 'http://127.0.0.1:8000/radar'
@{ continued=$true } | ConvertTo-Json -Compress
""",
    )
    assert result == {"continued": True}


def test_runtime_lock_excludes_other_process_and_allows_nested_start(tmp_path):
    child_script = tmp_path / "lock-child.ps1"
    child_script.write_text(
        ". "
        + _ps_quote(ROOT / "scripts" / "windows_runtime.ps1")
        + "\ntry { $lock = Enter-LeadRadarRuntimeLock "
        + _ps_quote(tmp_path)
        + "; Exit-LeadRadarRuntimeLock $lock; exit 9 } catch { exit 0 }\n",
        encoding="utf-8-sig",
    )
    result = _run(
        tmp_path,
        f"""
$first = Enter-LeadRadarRuntimeLock {_ps_quote(tmp_path)}
$nested = Enter-LeadRadarRuntimeLock {_ps_quote(tmp_path)}
& {_ps_quote(POWERSHELL)} -NoProfile -NonInteractive -File {_ps_quote(child_script)}
$childCode=$LASTEXITCODE
Exit-LeadRadarRuntimeLock $nested
Exit-LeadRadarRuntimeLock $first
$after = Enter-LeadRadarRuntimeLock {_ps_quote(tmp_path)}
Exit-LeadRadarRuntimeLock $after
@{{ child_code=$childCode; reacquired=$true }} | ConvertTo-Json -Compress
""",
    )
    assert result == {"child_code": 0, "reacquired": True}


def _fake_workspace(tmp_path: Path, *, fail_health: bool, existing: bool) -> Path:
    root = tmp_path / "fake lead radar"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (root / ".env").touch()
    python = root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.touch()
    (root / ".runtime").mkdir()
    helper = (ROOT / "scripts" / "windows_runtime.ps1").read_text(encoding="utf-8")
    helper += rf"""
$global:FakeStarts=0
$global:FakeStops=0
$global:FakeProcesses=@{{}}
$global:FakePython={_ps_quote(python)}
function Get-LeadRadarSettings {{ [pscustomobject]@{{ host='127.0.0.1'; port=8000; url=''; auth=$true }} }}
function Get-NetTCPConnection {{
    if ({'$true' if existing else '$false'}) {{ [pscustomobject]@{{ OwningProcess=501 }} }}
}}
function Get-CimInstance {{
    param($ClassName, $Filter)
    if ($Filter -match '^ProcessId=(\d+)$') {{ return $global:FakeProcesses[[int]$Matches[1]] }}
    if ($Filter -match '^ParentProcessId=(\d+)$') {{
        $parent=[int]$Matches[1]
        return @($global:FakeProcesses.Values | Where-Object ParentProcessId -EQ $parent)
    }}
}}
function New-FakeProcesses {{
    $global:FakeProcesses[500]=[pscustomobject]@{{ ProcessId=500; ParentProcessId=1;
        ExecutablePath=$global:FakePython; CommandLine='python -m app.main --web-only';
        CreationDate=[datetime]'2026-10-07T00:00:00Z' }}
    $global:FakeProcesses[501]=[pscustomobject]@{{ ProcessId=501; ParentProcessId=500;
        ExecutablePath='base-python.exe'; CommandLine='python -m app.main --web-only';
        CreationDate=[datetime]'2026-10-07T00:00:00Z' }}
}}
function Start-Process {{
    $global:FakeStarts++
    New-FakeProcesses
    return [pscustomobject]@{{ Id=500 }}
}}
function Stop-Process {{ param($Id); $global:FakeStops++; $global:FakeProcesses.Remove([int]$Id) }}
function Wait-Process {{ }}
function Wait-LeadRadarWebReady {{
    if ({'$true' if fail_health else '$false'}) {{ throw 'Simulated startup health failure' }}
}}
if ({'$true' if existing else '$false'}) {{
    New-FakeProcesses
    Save-LeadRadarProcess (Join-Path {_ps_quote(root / '.runtime')} 'server-launcher.pid') ([pscustomobject]@{{ Id=500 }})
}}
"""
    (scripts / "windows_runtime.ps1").write_text(helper, encoding="utf-8-sig")
    shutil.copyfile(ROOT / "scripts" / "start_web_windows.ps1", scripts / "start_web_windows.ps1")
    return root


@pytest.mark.parametrize(
    ("fail_health", "existing", "expected_starts", "expected_stops"),
    [(True, False, 1, 2), (False, True, 0, 0), (True, True, 0, 0)],
)
def test_web_launcher_cleans_only_its_own_failed_start(
    tmp_path, fail_health, existing, expected_starts, expected_stops
):
    root = _fake_workspace(tmp_path, fail_health=fail_health, existing=existing)
    result = _run(
        tmp_path,
        f"""
$failed=$false
try {{ & {_ps_quote(root / 'scripts' / 'start_web_windows.ps1')} }} catch {{ $failed=$true }}
@{{ failed=$failed; starts=$global:FakeStarts; stops=$global:FakeStops;
    pid_exists=(Test-Path -LiteralPath {_ps_quote(root / '.runtime' / 'server-launcher.pid')}) }} | ConvertTo-Json -Compress
""",
    )
    assert result["failed"] is fail_health
    assert result["starts"] == expected_starts
    assert result["stops"] == expected_stops
    assert result["pid_exists"] is existing


def test_existing_cold_start_is_reused_before_port_opens(tmp_path):
    root = _fake_workspace(tmp_path, fail_health=False, existing=True)
    helper = root / "scripts" / "windows_runtime.ps1"
    with helper.open("a", encoding="utf-8") as stream:
        stream.write("\nfunction Get-NetTCPConnection { }\n")
    result = _run(
        tmp_path,
        f"""
& {_ps_quote(root / 'scripts' / 'start_web_windows.ps1')}
@{{ starts=$global:FakeStarts; stops=$global:FakeStops }} | ConvertTo-Json -Compress
""",
    )
    assert result == {"starts": 0, "stops": 0}


def test_wildcard_bind_uses_loopback_for_health_and_tunnel(tmp_path):
    result = _run(
        tmp_path,
        """
@{ ipv4=(Get-LeadRadarOrigin ([pscustomobject]@{ host='0.0.0.0'; port=8000 }));
   ipv6=(Get-LeadRadarOrigin ([pscustomobject]@{ host='::'; port=8000 })) } | ConvertTo-Json -Compress
""",
    )
    assert result == {"ipv4": "http://127.0.0.1:8000", "ipv6": "http://127.0.0.1:8000"}


@pytest.mark.parametrize("reuse_tunnel", [False, True])
def test_cloudflare_reuses_owned_tunnel_or_cleans_failed_new_start(tmp_path, reuse_tunnel):
    root = _fake_workspace(tmp_path, fail_health=False, existing=reuse_tunnel)
    runtime = root / ".runtime"
    cloudflared = runtime / "bin" / "cloudflared.exe"
    cloudflared.parent.mkdir()
    cloudflared.touch()
    helper = root / "scripts" / "windows_runtime.ps1"
    with helper.open("a", encoding="utf-8") as stream:
        stream.write(
            rf"""
$global:FakeCloudflared={_ps_quote(cloudflared)}
function Get-LeadRadarSettings {{
    [pscustomobject]@{{ host='127.0.0.1'; port=8000; url='https://owned-test.trycloudflare.com'; auth=$true }}
}}
function Set-LeadRadarWebAccess {{ }}
function Assert-LeadRadarWebAuth {{ }}
function Assert-LeadRadarTunnelReady {{
    if ({'$false' if reuse_tunnel else '$true'}) {{ throw 'Simulated unreachable tunnel' }}
}}
function New-FakeTunnel {{
    $global:FakeProcesses[600]=[pscustomobject]@{{ ProcessId=600; ParentProcessId=1;
        ExecutablePath=$global:FakeCloudflared;
        CommandLine='cloudflared tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8000';
        CreationDate=[datetime]'2026-10-07T00:00:00Z' }}
}}
function Get-Process {{
    $process=[pscustomobject]@{{ Id=600; HasExited=$false }}
    $process | Add-Member ScriptMethod Refresh {{ }}
    return $process
}}
function Start-Process {{
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru,
        $RedirectStandardOutput, $RedirectStandardError)
    if ($FilePath -ne $global:FakeCloudflared) {{ throw 'No real processes allowed' }}
    $global:FakeStarts++
    New-FakeTunnel
    [IO.File]::WriteAllText($RedirectStandardError, 'https://owned-test.trycloudflare.com')
    return (Get-Process)
}}
if ({'$true' if reuse_tunnel else '$false'}) {{
    New-FakeTunnel
    Save-LeadRadarProcess {_ps_quote(runtime / 'cloudflare.pid')} ([pscustomobject]@{{ Id=600 }})
    Set-LeadRadarRuntimeText {_ps_quote(runtime / 'public-url.txt')} 'https://owned-test.trycloudflare.com'
}}
"""
        )
    # Server lifecycle is exercised separately above; isolate tunnel coordination here.
    (root / "scripts" / "start_web_windows.ps1").write_text(
        f"""
if (-not $global:FakeProcesses.ContainsKey(500)) {{
    New-FakeProcesses
    Save-LeadRadarProcess {_ps_quote(runtime / 'server-launcher.pid')} ([pscustomobject]@{{ Id=500 }})
}}
""",
        encoding="utf-8-sig",
    )
    shutil.copyfile(
        ROOT / "scripts" / "start_cloudflare_windows.ps1",
        root / "scripts" / "start_cloudflare_windows.ps1",
    )
    result = _run(
        tmp_path,
        f"""
$failed=$false
try {{ & {_ps_quote(root / 'scripts' / 'start_cloudflare_windows.ps1')} }} catch {{ $failed=$true }}
@{{ failed=$failed; starts=$global:FakeStarts; stops=$global:FakeStops;
    server_pid=(Test-Path -LiteralPath {_ps_quote(runtime / 'server-launcher.pid')});
    tunnel_pid=(Test-Path -LiteralPath {_ps_quote(runtime / 'cloudflare.pid')});
    public_url=(Test-Path -LiteralPath {_ps_quote(runtime / 'public-url.txt')}) }} | ConvertTo-Json -Compress
""",
    )
    if reuse_tunnel:
        assert result == {
            "failed": False,
            "starts": 0,
            "stops": 0,
            "server_pid": True,
            "tunnel_pid": True,
            "public_url": True,
        }
    else:
        assert result == {
            "failed": True,
            "starts": 1,
            "stops": 3,
            "server_pid": False,
            "tunnel_pid": False,
            "public_url": False,
        }


def test_launcher_cleans_child_if_pid_persistence_fails(tmp_path):
    root = _fake_workspace(tmp_path, fail_health=False, existing=False)
    helper = root / "scripts" / "windows_runtime.ps1"
    with helper.open("a", encoding="utf-8") as stream:
        stream.write("\nfunction Save-LeadRadarProcess { throw 'Simulated disk error' }\n")
    result = _run(
        tmp_path,
        f"""
$failed=$false
try {{ & {_ps_quote(root / 'scripts' / 'start_web_windows.ps1')} }} catch {{ $failed=$true }}
@{{ failed=$failed; starts=$global:FakeStarts; stops=$global:FakeStops;
    remaining=$global:FakeProcesses.Count }} | ConvertTo-Json -Compress
""",
    )
    assert result == {"failed": True, "starts": 1, "stops": 2, "remaining": 0}


def test_windows_lifecycle_and_logon_scripts_parse(tmp_path):
    names = [
        "windows_runtime.ps1",
        "start_web_windows.ps1",
        "start_cloudflare_windows.ps1",
        "stop_cloudflare_windows.ps1",
        "start_at_logon_windows.ps1",
        "install_windows_startup.ps1",
    ]
    paths = ",".join(_ps_quote(ROOT / "scripts" / name) for name in names)
    result = _run(
        tmp_path,
        f"""
$errorCount=0
foreach ($path in @({paths})) {{
    $tokens=$null; $parseErrors=$null
    [Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors) | Out-Null
    $errorCount += $parseErrors.Count
}}
@{{ errors=$errorCount }} | ConvertTo-Json -Compress
""",
    )
    assert result == {"errors": 0}


@pytest.mark.parametrize(("fail_until", "exit_code", "attempts"), [(2, 0, 3), (9, 1, 4)])
def test_logon_bootstrap_retries_are_bounded_and_do_not_open_browser(
    tmp_path, fail_until, exit_code, attempts
):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    waits = tmp_path / "waits.txt"
    count_file = tmp_path / "attempts.txt"
    bootstrap = (ROOT / "scripts" / "start_at_logon_windows.ps1").read_text(encoding="utf-8")
    bootstrap = (
        "function Start-Sleep { param($Seconds); Add-Content -LiteralPath "
        + _ps_quote(waits)
        + " -Value $Seconds }\n"
        + bootstrap
    )
    (scripts / "start_at_logon_windows.ps1").write_text(bootstrap, encoding="utf-8-sig")
    (scripts / "start_cloudflare_windows.ps1").write_text(
        f"""
param([switch]$OpenBrowser)
if ($OpenBrowser) {{ throw 'Autostart must not open a browser' }}
$attempt=0
if (Test-Path -LiteralPath {_ps_quote(count_file)}) {{ $attempt=[int](Get-Content -LiteralPath {_ps_quote(count_file)}) }}
$attempt++
Set-Content -LiteralPath {_ps_quote(count_file)} -Value $attempt
if ($attempt -le {fail_until}) {{ throw 'Simulated network not ready' }}
""",
        encoding="utf-8-sig",
    )
    completed = subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(scripts / "start_at_logon_windows.ps1"),
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == exit_code, completed.stderr
    assert int(count_file.read_text().strip()) == attempts
    assert [int(value) for value in waits.read_text().splitlines()] == [20] + [
        20 * attempt for attempt in range(1, attempts)
    ]
