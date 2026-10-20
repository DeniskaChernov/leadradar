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


@pytest.mark.parametrize("remaining", ["gone", "same", "replacement", "unknown"])
@pytest.mark.parametrize("powershell", [path for path in (POWERSHELL, POWERSHELL_CORE) if path])
def test_stop_handles_natural_exit_but_preserves_other_failures(tmp_path, powershell, remaining):
    result = _run(
        tmp_path,
        f"""
$global:stopCalls=0
$original=[pscustomobject]@{{ ProcessId=42; ExecutablePath='python.exe';
    CommandLine='python -m app.main --web-only'; CreationDate=[datetime]'2026-10-07T00:00:00Z' }}
function Get-CimInstance {{
    if ($global:stopCalls -gt 0 -and '{remaining}' -eq 'unknown') {{ throw 'Process lookup unavailable' }}
    if ($global:stopCalls -eq 0 -or '{remaining}' -eq 'same') {{ return $original }}
    if ('{remaining}' -eq 'replacement') {{
        return [pscustomobject]@{{ ProcessId=42; ExecutablePath='other.exe';
            CommandLine='other'; CreationDate=[datetime]'2026-10-07T01:00:00Z' }}
    }}
}}
function Stop-Process {{ $global:stopCalls++; throw 'Process already exited or access denied' }}
function Wait-Process {{ throw 'Must not wait after a failed Stop-Process' }}
$failed=$false
try {{ Stop-LeadRadarOwnedProcess $original }} catch {{ $failed=$true }}
@{{ failed=$failed; stops=$global:stopCalls }} | ConvertTo-Json -Compress
""",
        powershell=powershell,
    )
    assert result == {"failed": remaining != "gone", "stops": 1}


@pytest.mark.parametrize("second", ["gone", "owned", "replacement", "unknown", "first_unknown"])
@pytest.mark.parametrize("powershell", [path for path in (POWERSHELL, POWERSHELL_CORE) if path])
def test_partial_cim_identity_rechecked_before_stopping(tmp_path, powershell, second):
    result = _run(
        tmp_path,
        f"""
$global:lookups=0; $global:stops=0
$original=[pscustomobject]@{{ ProcessId=42; ExecutablePath='python.exe';
    CommandLine='python -m app.main --web-only'; CreationDate=[datetime]'2026-10-07T00:00:00Z' }}
function Get-CimInstance {{
    $global:lookups++
    if ('{second}' -eq 'first_unknown' -or ($global:lookups -gt 1 -and '{second}' -eq 'unknown')) {{ throw 'Lookup unavailable' }}
    if ($global:lookups -eq 1) {{ return [pscustomobject]@{{ ProcessId=42; CreationDate=$original.CreationDate }} }}
    if ('{second}' -eq 'owned') {{ return $original }}
    if ('{second}' -eq 'replacement') {{ return [pscustomobject]@{{ ProcessId=42; ExecutablePath='foreign.exe'; CreationDate=[datetime]'2026-10-08T00:00:00Z'; CommandLine='foreign' }} }}
}}
function Stop-Process {{ $global:stops++ }}
function Wait-Process {{ }}
$failed=$false
try {{ Stop-LeadRadarOwnedProcess $original }} catch {{ $failed=$true }}
@{{ failed=$failed; stops=$global:stops; lookups=$global:lookups }} | ConvertTo-Json -Compress
""",
        powershell=powershell,
    )
    assert result == {"failed": second not in {"gone", "owned"}, "stops": int(second == "owned"), "lookups": 1 if second == "first_unknown" else 2}


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


@pytest.mark.parametrize("command,owned", [
    ("python -m app.main", True), ("python -m app.main --web-only", True),
    ("python -m app.main --once", False),
    ("python -m app.main --web-only --once", False),
    ("python -m app.main.evil", False), ("python -m another.app", False),
])
def test_runtime_ownership_recognizes_full_and_web_only_but_never_once(tmp_path, command, owned):
    result = _run(tmp_path, f"""
@{{ owned=(Test-LeadRadarWebCommand {_ps_quote(command)}) }} | ConvertTo-Json -Compress
""")
    assert result == {"owned": owned}


@pytest.mark.parametrize("existing", [False, True])
def test_windows_launcher_starts_or_reuses_full_mode(tmp_path, existing):
    root = _fake_workspace(tmp_path, fail_health=False, existing=existing)
    helper = root / "scripts/windows_runtime.ps1"
    with helper.open("a", encoding="utf-8") as stream:
        stream.write("""
function Get-LeadRadarSettings { [pscustomobject]@{ host='127.0.0.1'; port=8000; url=''; auth=$true; mode='full' } }
function Start-Process {
    param($FilePath, $ArgumentList)
    $global:FakeStarts++
    if (($ArgumentList -join ' ') -ne '-m app.main') { throw 'Full mode arguments lost' }
    New-FakeProcesses
    $global:FakeProcesses[500].CommandLine='python -m app.main'
    $global:FakeProcesses[501].CommandLine='python -m app.main'
    return [pscustomobject]@{ Id=500 }
}
foreach ($process in $global:FakeProcesses.Values) { $process.CommandLine='python -m app.main' }
""")
    result = _run(tmp_path, f"""
& {_ps_quote(root / 'scripts/start_web_windows.ps1')}
@{{ starts=$global:FakeStarts; stops=$global:FakeStops }} | ConvertTo-Json -Compress
""")
    assert result == {"starts": 0 if existing else 1, "stops": 0}


def test_explicit_web_only_launch_overrides_persisted_full_mode(tmp_path):
    root = _fake_workspace(tmp_path, fail_health=False, existing=False)
    with (root / "scripts/windows_runtime.ps1").open("a", encoding="utf-8") as stream:
        stream.write("""
function Get-LeadRadarSettings { [pscustomobject]@{ host='127.0.0.1'; port=8000; url=''; auth=$true; mode='full' } }
function Start-Process {
    param($FilePath, $ArgumentList)
    $global:FakeStarts++
    if (($ArgumentList -join ' ') -ne '-m app.main --web-only') { throw 'Explicit web-only mode lost' }
    New-FakeProcesses
    return [pscustomobject]@{ Id=500 }
}
""")
    result = _run(tmp_path, f"""
& {_ps_quote(root / 'scripts/start_web_windows.ps1')} -WebOnly
@{{ starts=$global:FakeStarts; stops=$global:FakeStops }} | ConvertTo-Json -Compress
""")
    assert result == {"starts": 1, "stops": 0}


def test_mode_change_refuses_to_replace_running_server_implicitly(tmp_path):
    root = _fake_workspace(tmp_path, fail_health=False, existing=True)
    with (root / "scripts/windows_runtime.ps1").open("a", encoding="utf-8") as stream:
        stream.write("""
function Get-LeadRadarSettings { [pscustomobject]@{ host='127.0.0.1'; port=8000; url=''; auth=$true; mode='full' } }
""")
    result = _run(tmp_path, f"""
$blocked=$false
try {{ & {_ps_quote(root / 'scripts/start_web_windows.ps1')} }} catch {{ $blocked=$true }}
@{{ blocked=$blocked; starts=$global:FakeStarts; stops=$global:FakeStops }} | ConvertTo-Json -Compress
""")
    assert result == {"blocked": True, "starts": 0, "stops": 0}


def test_wildcard_bind_uses_loopback_for_health_and_tunnel(tmp_path):
    result = _run(
        tmp_path,
        """
@{ ipv4=(Get-LeadRadarOrigin ([pscustomobject]@{ host='0.0.0.0'; port=8000 }));
   ipv6=(Get-LeadRadarOrigin ([pscustomobject]@{ host='::'; port=8000 })) } | ConvertTo-Json -Compress
""",
    )
    assert result == {"ipv4": "http://127.0.0.1:8000", "ipv6": "http://127.0.0.1:8000"}


def _fake_cloudflare_workspace(
    tmp_path, *, reuse_tunnel=False, failure="", existing_server=None,
    initial_url="https://owned-test.trycloudflare.com",
):
    root = _fake_workspace(
        tmp_path, fail_health=False,
        existing=reuse_tunnel if existing_server is None else existing_server,
    )
    runtime = root / ".runtime"
    cloudflared = runtime / "bin" / "cloudflared.exe"
    cloudflared.parent.mkdir()
    if failure != "download":
        cloudflared.touch()
    helper = root / "scripts" / "windows_runtime.ps1"
    with helper.open("a", encoding="utf-8") as stream:
        stream.write(
            rf"""
$global:FakeCloudflared={_ps_quote(cloudflared)}
$global:FakeConfigUrl={_ps_quote(initial_url)}
function Get-LeadRadarSettings {{
    [pscustomobject]@{{ host='127.0.0.1'; port=8000; url=$global:FakeConfigUrl; auth=$true }}
}}
function Get-NetTCPConnection {{
    if ($global:FakeProcesses.ContainsKey(501)) {{ [pscustomobject]@{{ OwningProcess=501 }} }}
}}
function Set-LeadRadarWebAccess {{
    param($PythonPath, $PublicUrl='')
    if ($PublicUrl) {{ $global:FakeConfigUrl=$PublicUrl }}
}}
function Assert-LeadRadarWebAuth {{
    if ({'$true' if failure == 'auth' else '$false'}) {{ throw 'Simulated unprotected server' }}
}}
function Invoke-RestMethod {{
    param($Uri)
    if ($Uri -eq 'http://127.0.0.1:8000/health') {{
        return [pscustomobject]@{{ ok=$true; cycle_running={'$true' if failure == 'busy' else '$false'};
            analysis_queue=0; analysis_in_flight=0 }}
    }}
    throw 'Simulated network unavailable'
}}
function Assert-LeadRadarTunnelReady {{
    if ({'$true' if failure == 'probe' else '$false'}) {{ throw 'Simulated unreachable tunnel' }}
}}
function New-FakeTunnel {{
    $global:FakeProcesses[600]=[pscustomobject]@{{ ProcessId=600; ParentProcessId=1;
        ExecutablePath=$global:FakeCloudflared;
        CommandLine='cloudflared tunnel --no-autoupdate --protocol auto --url http://127.0.0.1:8000';
        CreationDate=[datetime]'2026-10-07T00:00:00Z' }}
}}
function Get-Process {{
    $process=[pscustomobject]@{{ Id=600; HasExited={'$true' if failure == 'edge' else '$false'} }}
    $process | Add-Member ScriptMethod Refresh {{ }}
    return $process
}}
function Start-Process {{
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru,
        $RedirectStandardOutput, $RedirectStandardError)
    if ($FilePath -ne $global:FakeCloudflared) {{ throw 'No real processes allowed' }}
    if (($ArgumentList -join ' ') -ne 'tunnel --no-autoupdate --protocol auto --url http://127.0.0.1:8000') {{
        throw 'Use automatic transport negotiation for the configured local origin'
    }}
    $global:FakeStarts++
    New-FakeTunnel
    [IO.File]::WriteAllText($RedirectStandardError, 'https://owned-test.trycloudflare.com {'unconnected' if failure == 'edge' else 'Registered tunnel connection'}')
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
    return root


@pytest.mark.parametrize("reuse_tunnel,failure", [
    (True, ""), (False, ""), (True, "probe"), (False, "probe"),
    (False, "edge"), (False, "download"),
])
def test_tunnel_failure_preserves_authenticated_local_server(tmp_path, reuse_tunnel, failure):
    root = _fake_cloudflare_workspace(tmp_path, reuse_tunnel=reuse_tunnel, failure=failure)
    runtime = root / ".runtime"
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
    new_tunnel = not reuse_tunnel and failure != "download"
    cleaned_tunnel = new_tunnel and bool(failure)
    assert result == {
        "failed": bool(failure), "starts": int(new_tunnel), "stops": int(cleaned_tunnel),
        "server_pid": True, "tunnel_pid": not cleaned_tunnel and failure != "download",
        "public_url": not cleaned_tunnel and failure != "download",
    }


@pytest.mark.parametrize("failure", ["edge", "download", "busy", ""])
def test_new_hostname_restarts_only_after_edge_connection_and_while_idle(tmp_path, failure):
    initial_url = "https://previous-test.trycloudflare.com"
    root = _fake_cloudflare_workspace(
        tmp_path, existing_server=True, failure=failure, initial_url=initial_url,
    )
    result = _run(tmp_path, f"""
$failed=$false
try {{ & {_ps_quote(root / 'scripts/start_cloudflare_windows.ps1')} }} catch {{ $failed=$true }}
@{{ failed=$failed; stops=$global:FakeStops;
    server_pid=(Test-Path -LiteralPath {_ps_quote(root / '.runtime/server-launcher.pid')});
    configured_url=$global:FakeConfigUrl }} | ConvertTo-Json -Compress
""")
    assert result == {
        "failed": bool(failure), "stops": 2 if not failure else int(failure != "download"),
        "server_pid": True,
        "configured_url": initial_url if failure else "https://owned-test.trycloudflare.com",
    }


@pytest.mark.parametrize("stale,sync_failure", [(False, False), (True, False), (True, True)])
def test_gateway_reconnect_keeps_permanent_url_and_running_backend(tmp_path, stale, sync_failure):
    public = "https://leadradar-gateway.example.workers.dev"
    tunnel_url = "https://owned-test.trycloudflare.com"
    root = _fake_cloudflare_workspace(tmp_path, reuse_tunnel=True, initial_url=public)
    runtime = root / ".runtime"
    helper = root / "scripts/windows_runtime.ps1"
    with helper.open("a", encoding="utf-8") as stream:
        stream.write(rf"""
$global:FakeSync=''
$global:FakeWatches=0
$global:FakeProcesses[600].CommandLine='cloudflared tunnel --no-autoupdate --protocol auto --http-host-header leadradar-gateway.example.workers.dev --url http://127.0.0.1:8000'
Set-LeadRadarRuntimeText {_ps_quote(runtime / 'public-url.txt')} {_ps_quote(public)}
Set-LeadRadarRuntimeText {_ps_quote(runtime / 'cloudflare-origin-url.txt')} {_ps_quote(tunnel_url)}
function Get-LeadRadarGateway {{
    [pscustomobject]@{{ public_url={_ps_quote(public)}; host='leadradar-gateway.example.workers.dev' }}
}}
function Sync-LeadRadarGateway {{
    param($PythonPath,$OriginUrl)
    $global:FakeSync=$OriginUrl
    if ({'$true' if sync_failure else '$false'}) {{ throw 'Simulated route update failure' }}
}}
function Start-LeadRadarGatewayWatchdog {{ $global:FakeWatches++ }}
function Invoke-RestMethod {{
    param($Uri)
    if ($Uri -eq {_ps_quote(tunnel_url + '/health')} -and {'$true' if stale else '$false'}) {{ throw 'Stale tunnel' }}
    return [pscustomobject]@{{ ok=$true; radar_live_armed=$true; cycle_running=$false; analysis_queue=0; analysis_in_flight=0 }}
}}
function Start-Process {{
    param($FilePath,$ArgumentList,$WorkingDirectory,$WindowStyle,[switch]$PassThru,$RedirectStandardOutput,$RedirectStandardError)
    if ($FilePath -ne $global:FakeCloudflared -or ($ArgumentList -join ' ') -ne 'tunnel --no-autoupdate --protocol auto --http-host-header leadradar-gateway.example.workers.dev --url http://127.0.0.1:8000') {{ throw 'Unexpected process or origin host header' }}
    $global:FakeStarts++
    New-FakeTunnel
    $global:FakeProcesses[600].CommandLine='cloudflared ' + ($ArgumentList -join ' ')
    [IO.File]::WriteAllText($RedirectStandardError, '{tunnel_url} Registered tunnel connection')
    return (Get-Process)
}}
""")
    result = _run(tmp_path, f"""
$failed=$false
try {{ & {_ps_quote(root / 'scripts/start_cloudflare_windows.ps1')} }} catch {{ $failed=$true }}
@{{ failed=$failed; starts=$global:FakeStarts; stops=$global:FakeStops;
    backend=$global:FakeProcesses.ContainsKey(501); configured_url=$global:FakeConfigUrl;
    public_url=(Get-Content -LiteralPath {_ps_quote(runtime / 'public-url.txt')} -Raw).Trim();
    origin_file=(Test-Path -LiteralPath {_ps_quote(runtime / 'cloudflare-origin-url.txt')});
    synced=$global:FakeSync; watches=$global:FakeWatches }} | ConvertTo-Json -Compress
""")
    assert result == {
        "failed": sync_failure, "starts": int(stale), "stops": int(stale) + int(sync_failure),
        "backend": True, "configured_url": public, "public_url": public,
        "origin_file": not sync_failure, "synced": tunnel_url, "watches": int(not sync_failure),
    }


def test_gateway_watchdog_recovers_after_two_failures_and_stops_when_disabled(tmp_path):
    root = tmp_path / "watchdog"
    (root / "scripts").mkdir(parents=True)
    runtime = root / ".runtime"
    runtime.mkdir()
    config = runtime / "cloudflare-gateway.json"
    config.write_text("{}")
    shutil.copyfile(ROOT / "scripts/watch_cloudflare_gateway.ps1", root / "scripts/watch_cloudflare_gateway.ps1")
    (root / "scripts/start_cloudflare_windows.ps1").write_text("$global:Recoveries++", encoding="utf-8-sig")
    (root / "scripts/windows_runtime.ps1").write_text(f"""
$global:Sleeps=0; $global:Recoveries=0; $global:Probes=0
function Start-Sleep {{
    param($Seconds)
    if ($Seconds -ne 60) {{ throw 'Unexpected backoff' }}
    $global:Sleeps++
    if ($global:Sleeps -eq 3) {{ Remove-Item -LiteralPath {_ps_quote(config)} }}
}}
function Get-LeadRadarSettings {{ [pscustomobject]@{{ port=8000 }} }}
function Get-LeadRadarOrigin {{ 'http://127.0.0.1:8000' }}
function Get-LeadRadarGateway {{ [pscustomobject]@{{ public_url='https://unit.example.workers.dev' }} }}
function Invoke-RestMethod {{
    param($Uri)
    if ($Uri -eq 'http://127.0.0.1:8000/health') {{ return [pscustomobject]@{{ ok=$true }} }}
    $global:Probes++
    throw 'Simulated public outage'
}}
""", encoding="utf-8-sig")
    result = _run(tmp_path, f"""
& {_ps_quote(root / 'scripts/watch_cloudflare_gateway.ps1')}
@{{ probes=$global:Probes; recoveries=$global:Recoveries; sleeps=$global:Sleeps }} | ConvertTo-Json -Compress
""")
    assert result == {"probes": 2, "recoveries": 1, "sleeps": 3}


def test_cold_start_with_failed_auth_is_stopped_without_publishing(tmp_path):
    root = _fake_cloudflare_workspace(tmp_path, failure="auth")
    result = _run(tmp_path, f"""
$failed=$false
try {{ & {_ps_quote(root / 'scripts/start_cloudflare_windows.ps1')} }} catch {{ $failed=$true }}
@{{ failed=$failed; starts=$global:FakeStarts; stops=$global:FakeStops;
    server_pid=(Test-Path -LiteralPath {_ps_quote(root / '.runtime/server-launcher.pid')}) }} | ConvertTo-Json -Compress
""")
    assert result == {"failed": True, "starts": 0, "stops": 2, "server_pid": False}


@pytest.mark.parametrize("state", [
    {"ok": True, "cycle_running": False, "analysis_queue": 0, "analysis_in_flight": 0},
    {"ok": True, "cycle_running": True, "analysis_queue": 0, "analysis_in_flight": 0},
    {"ok": True, "cycle_running": False, "analysis_queue": 1, "analysis_in_flight": 0},
    {"ok": True, "cycle_running": False, "analysis_queue": 0, "analysis_in_flight": 1},
    {"ok": True},
    {"ok": False, "cycle_running": False, "analysis_queue": 0, "analysis_in_flight": 0},
])
def test_restart_requires_complete_idle_health_snapshot(tmp_path, state):
    payload = json.dumps(state)
    result = _run(tmp_path, f"""
function Invoke-RestMethod {{ {_ps_quote(payload)} | ConvertFrom-Json }}
$blocked=$false
try {{ Assert-LeadRadarIdleForRestart 'http://127.0.0.1:8000' }} catch {{ $blocked=$true }}
@{{ blocked=$blocked }} | ConvertTo-Json -Compress
""")
    assert result == {"blocked": state != {
        "ok": True, "cycle_running": False, "analysis_queue": 0, "analysis_in_flight": 0,
    }}


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
        "watch_cloudflare_gateway.ps1",
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
