"""
Central configuration.

config.ini IS THE SOURCE OF TRUTH. Precedence, first match wins:

    1. config.ini next to this project    [marketwatch] fred_api_key = ...
    2. a real environment variable        MW_FRED_API_KEY=...
    3. the legacy .env file
    4. the default in this file

Note the order: a value written in config.ini beats an environment variable,
which is the opposite of the usual convention and is deliberate (v6.2.2). The
point of the file is that what you can see in it is what the app uses. A
stale MW_FRED_API_KEY left in a shell profile or a Windows user variable
silently overriding the key you just pasted into the file is exactly the
confusion this app has already been through once.

An environment variable still works for anything the file leaves EMPTY, so
nothing is lost; and `python run.py doctor` flags any setting where both are
present, naming the one that won.

config.ini is a plain visible file in the project folder -- not a dotfile --
so it shows up in Explorer, in `ls`, and in any editor, and it is read
identically on Windows and Linux.

Keys are the MW_ names without the prefix, lower-cased:
MW_FRED_API_KEY -> fred_api_key. Both spellings are accepted.
"""

import configparser
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.ini"

# ---------------------------------------------------------------------
# Layer 2: config.ini.  configparser is stdlib on every supported Python,
# so this adds no dependency and behaves the same on both operating systems.
# Read as UTF-8 explicitly: Windows would otherwise decode with the locale
# ANSI codepage, and a non-ASCII character (an accented path in data_dir, a
# smart quote pasted from a browser) would either decode to a different
# string or raise at import time.
# ---------------------------------------------------------------------
_file_cfg: dict[str, str] = {}


def _load_config_ini() -> dict[str, str]:
    if not CONFIG_PATH.is_file():
        return {}
    cp = configparser.ConfigParser(interpolation=None)   # keep % and $ literal
    try:
        # utf-8-SIG, not utf-8. Windows Notepad writes a UTF-8 BOM, and
        # configparser reading that as plain utf-8 sees the BOM as part of the
        # first line, fails with MissingSectionHeaderError, and every setting
        # -- including the FRED key -- silently falls back to its default.
        # utf-8-sig strips a BOM if present and is identical to utf-8 if not.
        cp.read(CONFIG_PATH, encoding="utf-8-sig")
    except (configparser.Error, UnicodeDecodeError) as exc:
        print(f"WARNING: could not read {CONFIG_PATH.name} ({exc}); "
              f"using defaults", flush=True)
        return {}
    out = {}
    for section in cp.sections():
        for k, v in cp.items(section):
            key = k.strip().lower()
            if not key.startswith("mw_"):
                key = "mw_" + key
            # inline "# comment" is NOT stripped by configparser by default;
            # a trailing comment on a value is a very easy mistake to make
            v = v.split("#", 1)[0].split(";", 1)[0].strip() if "#" in v or ";" in v \
                else v.strip()
            out[key.upper()] = v.strip('"').strip("'")
    return out


_file_cfg = _load_config_ini()      # config.ini -- highest
_legacy_cfg: dict[str, str] = {}    # .env -- below the environment

# ---------------------------------------------------------------------
# Layer 2b: legacy .env, kept working for existing installs.  Same explicit
# encoding for the same reason.
# ---------------------------------------------------------------------
_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    try:
        _lines = _env_file.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError:
        _lines = _env_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        print("WARNING: .env is not valid UTF-8; some characters were replaced",
              flush=True)
    for _line in _lines:
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            k, _, v = _line.partition("=")
            _legacy_cfg.setdefault(k.strip().upper(), v.strip())


def cfg(name: str, default: str = "") -> str:
    """One setting, resolved through the precedence above.

    Every MW_* setting goes through here so the layers cannot drift apart --
    an earlier version read some straight from os.environ, which meant those
    silently ignored the config file.
    """
    v = _file_cfg.get(name, "").strip()
    if v:
        return v
    v = os.environ.get(name)
    if v is not None and v != "":
        return v
    v = _legacy_cfg.get(name, "").strip()
    if v:
        return v
    return default


def config_source(name: str) -> str:
    """Where a setting actually came from, and whether anything lost.

    `run.py doctor` prints this. A key that is present but not being used is
    the single most annoying failure mode for a file-driven config, so it is
    made visible rather than left to be discovered.
    """
    in_file = bool(_file_cfg.get(name, "").strip())
    in_env = bool(os.environ.get(name))
    in_legacy = bool(_legacy_cfg.get(name, "").strip())
    if in_file:
        return (f"{CONFIG_PATH.name} (env var ignored)" if in_env
                else CONFIG_PATH.name)
    if in_env:
        return "environment"
    if in_legacy:
        return ".env (legacy)"
    return "default"

# FRED API key. Optional: without it the code falls back to pandas_datareader's
# fredgraph.csv scrape, which is unauthenticated and throttled per IP -- the
# cause of the read timeouts on long update runs. Free from
# https://fredaccount.stlouisfed.org/apikey
# Build a second set of variants with the volatility brake OFF, so the panel
# can toggle it. The brake is PATH-DEPENDENT -- it reads the strategy's own
# trailing realised vol -- so the alternative cannot be derived in the browser
# the way a sleeve fraction can; it has to be backtested. That doubles the
# strategy work (3 kinds x 6 fractions x 2 = 36 runs). Set to 0 to skip it;
# the checkbox then hides itself.
STRATEGY_VT_AB = cfg("MW_STRATEGY_VT_AB", "1") == "1"

FRED_API_KEY = (cfg("MW_FRED_API_KEY") or cfg("FRED_API_KEY")).strip()

# Where the pickle, figure JSON, and metadata live.
DATA_DIR = Path(cfg("MW_DATA_DIR") or (BASE_DIR / "data"))

# Run the daily update inside the web process (simplest for a single
# Windows box).  Set to "0" when an external scheduler (Windows Task
# Scheduler, cron, a hosting service's cron job) runs `python -m app.update`.
ENABLE_SCHEDULER = cfg("MW_ENABLE_SCHEDULER", "1") == "1"

# Local-time hours (0-23) for the in-process update, comma separated.
# Default: early morning for the overnight data, and 19:00 so the evening
# view already reflects the day's close.
#
# MW_UPDATE_HOUR is the older single-hour setting. If it is set it is merged
# in rather than ignored, so an existing .env keeps working and still gains
# the evening run.
def _parse_hours(raw: str) -> list[int]:
    out = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            h = int(part)
        except ValueError:
            continue
        if 0 <= h <= 23 and h not in out:
            out.append(h)
    return sorted(out)


UPDATE_HOURS = _parse_hours(cfg("MW_UPDATE_HOURS", "6,19"))
_legacy = cfg("MW_UPDATE_HOUR")
if _legacy:
    UPDATE_HOURS = sorted(set(UPDATE_HOURS) | set(_parse_hours(_legacy)))
if not UPDATE_HOURS:
    UPDATE_HOURS = [6, 19]

# Backwards compatible alias for anything still reading the single value.
UPDATE_HOUR = UPDATE_HOURS[0]

# Minute past the hour for the scheduled runs. Off :00 on purpose -- that is
# when every other scheduled job on a machine tends to fire, and Yahoo/FRED
# are measurably slower right on the hour.
try:
    UPDATE_MINUTE = max(0, min(59, int(cfg("MW_UPDATE_MINUTE", "20"))))
except ValueError:
    UPDATE_MINUTE = 20

# Timezone the update_hours are interpreted in. Empty = the machine's own
# local time, which is the historical behaviour.
#
# This matters more than it looks. A Linux server is normally set to UTC while
# a desktop is on local time, so the SAME config fires at different real
# moments on the two machines -- 06:20 UTC on one and 06:20 America/Chicago on
# the other, five hours apart. Naming a zone here makes both fire together
# whatever the host clocks say.
#
# Any IANA name: America/Chicago, Europe/London, Asia/Shanghai. Invalid or
# unavailable names fall back to local time with a warning rather than
# stopping the server.
UPDATE_TIMEZONE = cfg("MW_UPDATE_TIMEZONE", "").strip()


def update_tzinfo():
    """The configured zone as a tzinfo, or None for local time."""
    if not UPDATE_TIMEZONE:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(UPDATE_TIMEZONE)
    except Exception as exc:                       # unknown name, no tzdata
        print(f"WARNING: update_timezone {UPDATE_TIMEZONE!r} unusable "
              f"({type(exc).__name__}); using this machine's local time",
              flush=True)
        return None


def schedule_tz_name() -> str:
    """What the schedule is actually anchored to, for display."""
    tz = update_tzinfo()
    if tz is not None:
        return UPDATE_TIMEZONE
    from datetime import datetime
    return datetime.now().astimezone().tzname() or "local"


# If the cache is older than this many hours at startup, update immediately
# instead of waiting for the next scheduled slot. This is what covers a
# machine that was off, asleep, or rebooting when the slot came round -- the
# reason a cron job would otherwise be needed. 0 disables it.
try:
    STARTUP_CATCHUP_HOURS = max(0.0, float(cfg("MW_STARTUP_CATCHUP_HOURS", "18")))
except ValueError:
    STARTUP_CATCHUP_HOURS = 18.0

# ------------------------------------------------------------------
# Future subscription support.
# Today: AUTH_ENABLED=0 -> everyone is treated as a subscriber.
# Later: flip to 1 and implement the TODOs in app/auth.py.
# ------------------------------------------------------------------
AUTH_ENABLED = cfg("MW_AUTH_ENABLED", "0") == "1"

# Shared secret for the manual-refresh endpoint (POST /api/update).
# Empty string disables the endpoint entirely.
ADMIN_TOKEN = cfg("MW_ADMIN_TOKEN", "")

HOST = cfg("MW_HOST", "0.0.0.0")
PORT = int(cfg("MW_PORT", "8000"))
