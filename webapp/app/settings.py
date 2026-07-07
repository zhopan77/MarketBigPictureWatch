"""
Central configuration.  Everything can be overridden with environment
variables (or a .env file next to the project root), which is what makes the
same code run on a Windows box today and a hosting service tomorrow.
"""

import os
from pathlib import Path

# Load .env if present (optional dependency-free parser)
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.is_file():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

BASE_DIR = Path(__file__).resolve().parent.parent

# Where the pickle, figure JSON, and metadata live.
DATA_DIR = Path(os.environ.get("MW_DATA_DIR", BASE_DIR / "data"))

# Run the daily update inside the web process (simplest for a single
# Windows box).  Set to "0" when an external scheduler (Windows Task
# Scheduler, cron, a hosting service's cron job) runs `python -m app.update`.
ENABLE_SCHEDULER = os.environ.get("MW_ENABLE_SCHEDULER", "1") == "1"

# Local time hour (0-23) for the in-process daily update.
UPDATE_HOUR = int(os.environ.get("MW_UPDATE_HOUR", "6"))

# ------------------------------------------------------------------
# Future subscription support.
# Today: AUTH_ENABLED=0 -> everyone is treated as a subscriber.
# Later: flip to 1 and implement the TODOs in app/auth.py.
# ------------------------------------------------------------------
AUTH_ENABLED = os.environ.get("MW_AUTH_ENABLED", "0") == "1"

# Shared secret for the manual-refresh endpoint (POST /api/update).
# Empty string disables the endpoint entirely.
ADMIN_TOKEN = os.environ.get("MW_ADMIN_TOKEN", "")

HOST = os.environ.get("MW_HOST", "0.0.0.0")
PORT = int(os.environ.get("MW_PORT", "8000"))
