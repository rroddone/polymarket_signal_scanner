"""Manage the harvest.sh cron schedule and lock-file state."""

import os
import shutil
import subprocess
from pathlib import Path

from src.core.config import LOCK_FILE, PROJECT_ROOT

HARVEST_SH: str = str(PROJECT_ROOT / "harvest.sh")

# False on Streamlit Cloud and any environment without crontab in PATH
CRON_AVAILABLE: bool = shutil.which("crontab") is not None


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------

def is_processing() -> bool:
    return LOCK_FILE.exists()


def clear_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Cron expression builders / parsers
# ---------------------------------------------------------------------------

def make_cron_expression(hours: int, minutes: int) -> str:
    if hours == 0:
        return f"*/{minutes} * * * *"
    if hours == 24:
        return f"{minutes} 0 * * *"
    return f"{minutes} */{hours} * * *"


def parse_cron_to_hm(cron_str: str) -> tuple[int, int]:
    parts = cron_str.split()
    if len(parts) != 5:
        return 4, 0
    min_f, hr_f = parts[0], parts[1]

    if min_f.startswith("*/") and hr_f == "*":
        try:
            return 0, int(min_f[2:])
        except ValueError:
            return 4, 0

    if hr_f == "0":
        try:
            return 24, int(min_f)
        except ValueError:
            return 4, 0

    if hr_f.startswith("*/"):
        try:
            return int(hr_f[2:]), int(min_f)
        except ValueError:
            return 4, 0

    return 4, 0


# ---------------------------------------------------------------------------
# Crontab I/O
# ---------------------------------------------------------------------------

def _read_crontab() -> list[str]:
    # Streamlit Cloud sets this env var; skip the subprocess entirely
    if os.environ.get("STREAMLIT_RUNTIME_EXECUTABLE"):
        return []
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if result.returncode != 0:
            return []
        return result.stdout.splitlines()
    except Exception:
        return []


def _write_crontab(lines: list[str]) -> None:
    content = "\n".join(lines) + "\n" if lines else ""
    try:
        subprocess.run(["crontab", "-"], input=content, text=True, check=True)
    except Exception:
        pass


def get_current_schedule() -> dict:
    for line in _read_crontab():
        stripped = line.strip()
        if HARVEST_SH in stripped and not stripped.startswith("#"):
            parts = stripped.split()
            if len(parts) >= 6:
                hours, minutes = parse_cron_to_hm(" ".join(parts[:5]))
                return {"active": True, "hours": hours, "minutes": minutes}
    return {"active": False, "hours": 4, "minutes": 0}


def update_schedule(hours: int, minutes: int, active: bool) -> None:
    lines = [ln for ln in _read_crontab() if HARVEST_SH not in ln]
    if active:
        lines.append(f"{make_cron_expression(hours, minutes)} {HARVEST_SH}")
    _write_crontab(lines)
