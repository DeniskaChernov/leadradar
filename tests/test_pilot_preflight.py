"""QA smoke: controlled pilot preflight script без live API."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_prepare_controlled_pilot_script_runs():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.prepare_controlled_pilot"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    stdout = result.stdout + result.stderr
    assert result.returncode in {0, 1}
    assert "CONTROLLED RADAR PILOT" in stdout
    assert "Pilot contract" in stdout or "Pilot contract (manual)" in stdout
    assert "RESULT:" in stdout


def test_arm_controlled_pilot_module_exposes_main():
    from scripts import arm_controlled_pilot

    assert callable(arm_controlled_pilot.main)
    assert arm_controlled_pilot.PILOT_HANDLE == "aiko.uz"
    assert arm_controlled_pilot.DEFAULT_CREDITS == 5
