#!/usr/bin/env python3
"""
Market Big Picture Watch -- one launcher, same commands on Windows and Linux.

    python run.py               set up if needed, then start the server
    python run.py update        fetch data and rebuild now
    python run.py selftest      reproducibility check (compare across machines)
    python run.py doctor        show config, environment and cache state
    python run.py setup         create the venv and install, then stop

There is deliberately no run.bat / run.sh pair. Two launchers drift apart, and
the difference between them is exactly the kind of thing that makes one
machine behave unlike the other -- which is the problem this version exists to
fix. Everything platform-specific is a few lines of `if os.name == "nt"`
below, in one place, in a file you can read.

This script runs on the SYSTEM Python and needs nothing installed. Its first
job is to build the project's own virtual environment and re-launch itself
inside it, so the dependency versions are pinned and isolated no matter what
else is on the machine.

Python 3.11 or newer. On Ubuntu, `sudo apt install python3-venv` first; on
24.04 the venv is not optional, because PEP 668 marks the system Python
externally-managed and pip refuses to install into it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / ".venv"
IS_WIN = os.name == "nt"
# 3.11 since v6.2.6: numpy 2.3.x requires it, and numpy 2.3 is the first
# line publishing cp314 wheels, which one of the two machines needs.
MIN_PY = (3, 11)

# The two paths that differ between platforms, kept together so there is one
# place to look. Everything else in this file is identical on both.
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
VENV_MARKER = VENV / ("Scripts/activate" if IS_WIN else "bin/activate")


def _say(msg: str = "") -> None:
    print(msg, flush=True)


def _die(msg: str) -> "NoReturn":       # noqa: F821
    _say()
    for line in msg.strip().splitlines():
        _say("  " + line.strip())
    _say()
    raise SystemExit(1)


def in_venv() -> bool:
    """Are we already running inside the project's venv?

    Compares sys.prefix, NOT sys.executable. On Linux .venv/bin/python is a
    SYMLINK to the system interpreter, so resolving both paths makes them
    equal and this returns True from outside the venv -- which silently runs
    the whole app against whatever numpy the system happens to have, defeating
    the version pinning entirely. sys.prefix is the venv directory inside a
    venv and the installation prefix outside it, with no symlink to fall for.
    """
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


# ---------------------------------------------------------------------
# Environment setup
# ---------------------------------------------------------------------
def ensure_venv() -> None:
    """Create the venv, repair a broken pip, and install pinned dependencies.

    pip is upgraded ONLY when it is too old to read modern wheel tags, never
    as a matter of routine -- pip replacing itself mid-run is what corrupted
    an install here before, leaving a pip that could not import. When it does
    happen it is verified afterwards and the venv is rebuilt if it broke.
    """
    if sys.version_info < MIN_PY:
        _die(f"""
            This needs Python {MIN_PY[0]}.{MIN_PY[1]} or newer.
            You are running {sys.version.split()[0]} from {sys.executable}
            Install a newer Python and run this script with it.
        """)

    if not VENV_PY.exists():
        _say(f"Creating the virtual environment in {VENV.name} ...")
        r = subprocess.run([sys.executable, "-m", "venv", str(VENV)])
        # Check the RESULT, not the return code: `venv` can exit 0 having
        # produced an unusable tree when ensurepip is missing, which is the
        # normal state of a Debian/Ubuntu system without python3-venv.
        if r.returncode != 0 or not VENV_PY.exists():
            hint = ("On Ubuntu/Debian install the venv module first:\n"
                    "    sudo apt install python3-venv\n"
                    if not IS_WIN else
                    "Reinstall Python from python.org and tick "
                    '"Install launcher for all users".\n')
            _die(f"""
                Could not create the virtual environment in {VENV}
                {hint}
                Then run this again. To see the underlying error:
                    {sys.executable} -m venv {VENV}
            """)

    # A venv whose pip cannot run repairs itself, then is rebuilt if that is
    # not enough. Both steps are quiet no-ops on a healthy install.
    if not _pip_works():
        _say("Repairing pip in the virtual environment ...")
        subprocess.run([str(VENV_PY), "-m", "ensurepip", "--upgrade"],
                       capture_output=True)
    if not _pip_works():
        _say("Rebuilding the virtual environment ...")
        import shutil
        shutil.rmtree(VENV, ignore_errors=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)])
    if not _pip_works():
        _die(f"""
            The virtual environment exists but pip does not work inside it.
            Delete the {VENV.name} folder and run this again.
        """)

    # pip has to be new enough to RECOGNISE the wheel tags. An old pip does
    # not understand PEP 600 manylinux tags (manylinux_2_17_...), decides no
    # wheel matches, silently falls back to the source tarball, and then dies
    # in meson looking for a C compiler. Ubuntu's python3-venv can seed a
    # fairly old pip, and this launcher deliberately does not upgrade pip as a
    # matter of routine -- pip replacing itself mid-run is what corrupted an
    # install here before. So: upgrade only when it is actually too old, and
    # verify afterwards, with the existing rebuild path as the safety net.
    pv = _pip_version()
    if pv and pv < (23, 1):
        _say(f"pip {'.'.join(map(str, pv))} is too old to read modern wheel "
             f"tags - upgrading it ...")
        subprocess.run([str(VENV_PY), "-m", "pip", "install", "--upgrade",
                        "--disable-pip-version-check", "pip"])
        if not _pip_works():
            _say("The pip upgrade left it unusable - rebuilding the "
                 "virtual environment ...")
            import shutil
            shutil.rmtree(VENV, ignore_errors=True)
            subprocess.run([sys.executable, "-m", "venv", str(VENV)])
            if not _pip_works():
                _die(f"""
                    Could not get a working pip in {VENV.name}.
                    Delete that folder and run this again.
                """)

    if not _deps_ok():
        _say("Installing dependencies (a minute or two, once) ...")
        base = [str(VENV_PY), "-m", "pip", "install",
                "--disable-pip-version-check", "--no-warn-script-location",
                "-r", str(HERE / "requirements.txt")]
        # First pass refuses source builds. Without this, a missing wheel
        # turns into a compiler error twenty lines deep in meson, which says
        # nothing about the actual problem. With it, pip says plainly that no
        # distribution matches -- and no compiler is needed to find that out.
        first = subprocess.run(base + ["--only-binary=:all:"],
                               capture_output=True, text=True)
        r = first
        if first.returncode != 0:
            # A pure-python dependency that ships only an sdist is a legitimate
            # reason for pass one to fail, and building those needs no
            # compiler. Retry unrestricted; if THAT fails too, report pass
            # one's error, which is the readable one.
            _say("  (no wheel for one or more packages; retrying)")
            r = subprocess.run(base)
        if r.returncode != 0 or not _deps_ok():
            hint = ""
            for line in (first.stderr or "").splitlines():
                if "No matching distribution" in line or "from versions:" in line:
                    hint += "                " + line.strip() + "\n"
            _die(f"""
                Dependency installation failed.

{hint or "                (see the output above)"}
                {_interpreter_report()}

                The usual cause is that no prebuilt wheel exists for this
                exact Python version, so pip tried to compile from source.
                Either install a Python that the pinned versions publish
                wheels for (3.11 - 3.14 are verified), or adjust the pins in
                requirements.txt -- but change them on BOTH machines and
                re-run `python run.py selftest` on each to confirm the
                hashes still agree.

                Full output:
                    {VENV_PY} -m pip install -r requirements.txt
            """)

    ok, why = _imports_ok()
    if not ok:
        _die(f"""
            The dependencies installed, but the application does not import:

                {why}

            Python here is {sys.version.split()[0]}. If that error mentions a
            missing standard-library module, a pinned package is too old for
            this interpreter. To see the whole traceback:
                {VENV_PY} -c "import app.main"
        """)


def _pip_version() -> tuple | None:
    """(major, minor) of the venv's pip, or None if it cannot be read."""
    if not VENV_PY.exists():
        return None
    r = subprocess.run([str(VENV_PY), "-m", "pip", "--version"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        parts = r.stdout.split()[1].split(".")
        return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
    except (IndexError, ValueError):
        return None


def _interpreter_report() -> str:
    """The three facts that explain a missing wheel, on one line each."""
    import platform as _pl
    pv = _pip_version()
    py = sys.version.split()[0]
    if VENV_PY.exists():
        r = subprocess.run([str(VENV_PY), "-c",
                            "import sys, sysconfig;"
                            "print(sys.version.split()[0], sysconfig.get_platform())"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.split():
            py, plat = r.stdout.split()[0], r.stdout.split()[-1]
        else:
            plat = _pl.machine()
    else:
        plat = _pl.machine()
    return (f"Python {py}   pip {'.'.join(map(str, pv)) if pv else '?'}   "
            f"platform {plat}")


def _pip_works() -> bool:
    if not VENV_PY.exists():
        return False
    return subprocess.run([str(VENV_PY), "-m", "pip", "--version"],
                          capture_output=True).returncode == 0


# Parses a requirements line into (name, version, marker-applies?). Markers
# are needed because pandas-datareader is pinned per interpreter -- see the
# note in requirements.txt. Only `python_version <op> "X.Y"` is supported,
# which is the only marker this project uses; anything else is treated as
# "applies", so an unknown marker can never silently skip a version check.
_REQ_RE = r'^([A-Za-z0-9_.\-]+)(?:\[[^\]]+\])?==([^;]+)(?:;(.*))?$'

_DEPS_CODE = r"""
import re, sys, pathlib
from importlib.metadata import version, PackageNotFoundError

def marker_applies(marker):
    if not marker:
        return True
    m = re.search(r'python_version\s*(==|>=|<=|!=|>|<)\s*["\']([\d.]+)["\']', marker)
    if not m:
        return True                      # unknown marker -> check anyway
    op, want = m.group(1), tuple(int(x) for x in m.group(2).split('.'))
    cur = sys.version_info[:len(want)]
    return {'==': cur == want, '!=': cur != want, '>=': cur >= want,
            '<=': cur <= want, '>': cur > want, '<': cur < want}[op]

bad = []
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    line = line.split('#')[0].strip()
    m = re.match(REQ_RE, line)
    if not m or not marker_applies(m.group(3)):
        continue
    try:
        if version(m.group(1)) != m.group(2).strip():
            bad.append(m.group(1))
    except PackageNotFoundError:
        bad.append(m.group(1))
sys.exit(1 if bad else 0)
"""


def _deps_ok() -> bool:
    """Are the pinned versions actually the ones installed?

    Checks the VERSIONS, not just importability. An environment that merely
    has 'some pandas' is the thing this release exists to rule out: two
    machines on different pandas produce different numbers, and nothing else
    in the app would notice.
    """
    if not VENV_PY.exists():
        return False
    code = f"REQ_RE = {_REQ_RE!r}\n" + _DEPS_CODE
    return subprocess.run([str(VENV_PY), "-c", code, str(HERE / "requirements.txt")],
                          capture_output=True).returncode == 0


def _imports_ok() -> tuple[bool, str]:
    """Do the installed packages actually IMPORT?

    Resolving and installing a wheel is not the same as being able to import
    it. pandas-datareader 0.10.0 installs cleanly on Python 3.12 and then
    fails at import, because it reaches for distutils -- removed from the
    stdlib in 3.12. That shipped, and it surfaced as a traceback at server
    start rather than at setup. Checking here turns it into one clear
    sentence at the moment the environment is built.
    """
    if not VENV_PY.exists():
        return False, "no virtual environment"
    code = ("import sys; sys.path.insert(0, %r);"
            "import app; from app import main; print('ok')" % str(HERE))
    r = subprocess.run([str(VENV_PY), "-c", code], capture_output=True, text=True)
    if r.returncode == 0:
        return True, ""
    tail = [l for l in (r.stderr or "").strip().splitlines() if l.strip()]
    return False, (tail[-1] if tail else "unknown import error")


def relaunch(args: list[str]) -> "NoReturn":     # noqa: F821
    """Re-run this script inside the venv and exit with its status.

    subprocess rather than os.execv: execv on Windows makes the parent
    process return to the shell immediately while the child keeps running,
    which means Ctrl-C stops reaching the server and the prompt comes back
    over live output. A subprocess behaves the same way on both systems.
    """
    try:
        r = subprocess.run([str(VENV_PY), str(HERE / "run.py"), *args])
        raise SystemExit(r.returncode)
    except KeyboardInterrupt:
        raise SystemExit(130)


# ---------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------
def cmd_serve(args: list[str]) -> int:
    from app import settings          # noqa: E402  (needs the venv)
    import uvicorn                    # noqa: E402

    host, port = _resolve_host(settings.HOST), settings.PORT
    _say()
    _say(f"  Market Big Picture Watch  {_version()}")
    for url in _urls(host, port):
        _say(f"  {url}")
    _say(f"  automatic update at {_hours_text(settings)}")
    _say(f"  Ctrl-C to stop")
    _say()
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
    return 0


def _ipv6_available() -> bool:
    """Can we actually bind a dual-stack IPv6 socket on this machine?"""
    import socket
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        return False
    try:
        s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        s.bind(("::", 0))
        return True
    except (OSError, AttributeError):
        return False
    finally:
        s.close()


def _resolve_host(configured: str) -> str:
    """Turn the configured host into what uvicorn should bind.

    `auto` (the default) binds "::" when the machine has usable IPv6 and
    "0.0.0.0" when it does not.

    This exists because "0.0.0.0" is IPv4-ONLY. A browser reaching the server
    over IPv6 gets a connection refused -- the same error as nothing
    listening, which is a confusing way to find out.

    NOT dual-stack, despite what an earlier version of this comment claimed.
    A raw Linux "::" socket with IPV6_V6ONLY cleared does serve IPv4 clients,
    but asyncio does not leave it cleared: asyncio.base_events.create_server
    calls setsockopt(IPPROTO_IPV6, IPV6_V6ONLY, True) on every AF_INET6
    listener, so uvicorn's "::" bind is genuinely IPv6-only and an IPv4 client
    gets exactly the refusal this was meant to prevent. Verified against the
    CPython source, and observed in production. Set host = 0.0.0.0 explicitly
    when IPv4 clients have to reach the app.

    Falling back still matters: on a host with IPv6 disabled, binding "::"
    fails outright and the server would not start at all.

    An explicit value in config.ini is always honoured as-is.
    """
    if (configured or "").strip().lower() not in ("auto", ""):
        return configured
    return "::" if _ipv6_available() else "0.0.0.0"


def _urls(host: str, port: int) -> list:
    """The URLs that actually work, printed at startup.

    Spelling out the port is the point. An IPv6 address ends in a hextet that
    looks like a port, so `http://[....:8280]` reads as "port 8280" and is
    really port 80 -- which is exactly how this was first hit.
    """
    import socket
    out = [f"http://localhost:{port}"]
    if host in ("0.0.0.0", "::"):
        try:
            ip4 = socket.gethostbyname(socket.gethostname())
            if not ip4.startswith("127."):
                out.append(f"http://{ip4}:{port}")
        except OSError:
            pass
        if host == "::":
            out.append(f"http://[<this machine's IPv6 address>]:{port}"
                       f"   <- note the :{port}, the address itself ends in a "
                       f"hextet that looks like a port")
            out.append("  bound IPv6-only (asyncio forces IPV6_V6ONLY); "
                       "set host = 0.0.0.0 if IPv4 clients need to reach it")
        out.append("  (reachable from other machines on this network)")
    return out


def cmd_update(args: list[str]) -> int:
    from app import update
    return update.main(args) or 0


def cmd_selftest(args: list[str]) -> int:
    from app import selftest
    return selftest.main(args)


def cmd_setup(args: list[str]) -> int:
    _say("Environment ready.")
    _say(f"  interpreter  {sys.executable}")
    return 0


def cmd_doctor(args: list[str]) -> int:
    """Everything needed to explain 'why is this machine different'."""
    from app import determinism, settings
    import json

    _say()
    _say(f"  Market Big Picture Watch {_version()} -- doctor")
    _say("  " + "-" * 66)
    _say(f"  project      {HERE}")
    _say(f"  interpreter  {sys.executable}")
    _say(f"  {determinism.summary_line()}")
    fp = determinism.fingerprint()
    if fp.get("overridden"):
        _say(f"  NOTE: overridden from the environment: "
             f"{', '.join(fp['overridden'])}")
    if fp.get("simd_pin_fallback"):
        _say(f"  NOTE: SIMD probe fell back ({fp['simd_pin_fallback']}); "
             f"reproducibility may be reduced")
    _say()
    _say("  configuration (value <- where it came from)")
    for name, val in [
        ("MW_FRED_API_KEY", "set" if settings.FRED_API_KEY else "(empty)"),
        ("MW_UPDATE_HOURS", ",".join(f"{h:02d}:{settings.UPDATE_MINUTE:02d}"
                                     for h in settings.UPDATE_HOURS)),
        ("MW_UPDATE_TIMEZONE", settings.UPDATE_TIMEZONE or
         f"(local: {settings.schedule_tz_name()})"),
        ("MW_ENABLE_SCHEDULER", str(settings.ENABLE_SCHEDULER)),
        ("MW_HOST", f"{settings.HOST} -> binds "
                    f"{_resolve_host(settings.HOST)}"),
        ("MW_PORT", str(settings.PORT)),
        ("MW_DATA_DIR", str(settings.DATA_DIR)),
        ("MW_STRATEGY_VT_AB", str(settings.STRATEGY_VT_AB)),
        ("MW_ADMIN_TOKEN", "set" if settings.ADMIN_TOKEN else "(empty)"),
    ]:
        _say(f"    {name:<22} {val:<28} <- {settings.config_source(name)}")
    cfg_file = settings.CONFIG_PATH
    _say(f"    config file            {cfg_file.name:<28} "
         f"<- {'found' if cfg_file.is_file() else 'MISSING'}")
    _say()
    _say("  data cache")
    d = settings.DATA_DIR
    if not d.is_dir():
        _say(f"    {d} does not exist yet -- run: python run.py update")
    else:
        meta = d / "meta.json"
        if meta.is_file():
            try:
                m = json.loads(meta.read_text(encoding="utf-8"))
                _say(f"    last update  {m.get('generated', '?')}")
            except Exception:
                _say("    meta.json present but unreadable")
        else:
            _say("    no meta.json -- run: python run.py update")
        n = len(list(d.glob("*.json")))
        _say(f"    {n} cached json file(s) in {d}")
    _say()
    return 0


def _version() -> str:
    try:
        from app import fixed_service
        return fixed_service.VERSION
    except Exception:
        return ""


def _hours_text(settings) -> str:
    if not settings.ENABLE_SCHEDULER:
        return "DISABLED"
    hh = settings.UPDATE_HOURS
    mm = settings.UPDATE_MINUTE
    return (", ".join(f"{h:02d}:{mm:02d}" for h in hh)
            + f" {settings.schedule_tz_name()}")


COMMANDS = {
    "serve": cmd_serve,
    "update": cmd_update,
    "selftest": cmd_selftest,
    "setup": cmd_setup,
    "doctor": cmd_doctor,
}


def main(argv: list[str]) -> int:
    cmd = "serve"
    rest = argv
    if argv and argv[0] in COMMANDS:
        cmd, rest = argv[0], argv[1:]
    elif argv and argv[0] in ("-h", "--help", "help"):
        _say(__doc__.strip())
        return 0
    elif argv and not argv[0].startswith("-"):
        _say(f"Unknown command {argv[0]!r}. "
             f"Try one of: {', '.join(COMMANDS)}")
        return 2

    if not in_venv():
        ensure_venv()
        if cmd == "setup":
            _say("Environment ready.")
            _say(f"  interpreter  {VENV_PY}")
            _say("  next:  python run.py")
            return 0
        relaunch([cmd, *rest])

    os.chdir(HERE)                     # so relative data_dir resolves the same
    sys.path.insert(0, str(HERE))
    return COMMANDS[cmd](rest)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        raise SystemExit(130)
