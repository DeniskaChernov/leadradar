"""Обновляет machine notes в State.md из текущего состояния репозитория."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "State.md"
PLAN_PATH = ROOT / "docs" / "SYSTEM_IMPROVEMENT_PLAN.md"
BASE_HTML = ROOT / "app" / "web" / "templates" / "base.html"


def _plan_progress() -> tuple[int, int]:
    text = PLAN_PATH.read_text(encoding="utf-8")
    done = len(re.findall(r"^- \[x\]", text, flags=re.MULTILINE))
    total = len(re.findall(r"^- \[[ x]\]", text, flags=re.MULTILINE))
    return done, total


def _ui_version() -> str:
    match = re.search(r'app\.css\?v=([^"]+)', BASE_HTML.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError("UI cache version not found in base.html")
    return match.group(1)


def _git_branch() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "branch", "--show-current"],
                cwd=ROOT,
                text=True,
            )
            .strip()
            or "unknown"
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _latest_wave_line() -> str:
    state = STATE_PATH.read_text(encoding="utf-8") if STATE_PATH.exists() else ""
    for line in state.splitlines():
        if line.startswith("- wave"):
            return line.removeprefix("- ").strip()
    return "wave: pending"


def build_state_md(*, wave_line: str | None = None) -> str:
    done, total = _plan_progress()
    ui = _ui_version()
    branch = _git_branch()
    tz = timezone(timedelta(hours=5))
    updated = datetime.now(tz).strftime("%Y-%m-%dT%H:%M%z")
    wave = wave_line or _latest_wave_line()
    return (
        "# Lead Radar — machine state\n\n"
        f"- updated: {updated}\n"
        f"- ui: {ui}\n"
        f"- plan: {done}/{total}\n"
        f"- {wave}\n"
        f"- branch: {branch}\n"
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh State.md machine notes")
    parser.add_argument(
        "--wave",
        help="Override wave line, e.g. 'wave17: I5 unseen-gate ...'",
    )
    args = parser.parse_args()
    STATE_PATH.write_text(build_state_md(wave_line=args.wave), encoding="utf-8")
    print(f"Updated {STATE_PATH}")


if __name__ == "__main__":
    main()
