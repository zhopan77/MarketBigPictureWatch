"""
The web application.

Routes
  GET  /                    dashboard page (tabs for each figure)
  GET  /api/meta            figure list + last-updated timestamp
  GET  /api/figures/{slug}  pre-rendered plotly figure JSON
  POST /api/update          manual refresh (requires X-Admin-Token header)
  GET  /healthz             liveness probe for hosting services

Run locally:      uvicorn app.main:app --host 0.0.0.0 --port 8000
Run in prod:      same command behind the hosting service's process manager.
"""

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings, strategy_service, fixed_service
from .auth import User, require_access
from .figures import FIGURES
from .update import FIG_DIR, META_PATH, run_update

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# A threading.Lock (not asyncio) because the update runs on a plain worker
# thread; .locked() is also read by the /api/update endpoint below.
_update_lock = threading.Lock()


def _settle(fut: "asyncio.Future", result, exc) -> None:
    """Resolve the awaiting future from the worker thread."""
    if fut.done():
        return
    if exc is not None:
        fut.set_exception(exc)
    else:
        fut.set_result(result)


async def _run_update_async(rebuild_only: bool = False) -> None:
    """Run the (blocking) daily update WITHOUT ever blocking a clean shutdown.

    The download + rebuild is long and does blocking network I/O. Running it on
    asyncio's default executor made Ctrl-C hang: those worker threads are
    non-daemon and get JOINED by the interpreter's atexit hook, so the process
    could not exit until an in-flight update finished -- which is exactly why it
    had to be force-closed after an auto-update kicked off.

    Instead we run it on a DAEMON thread and await the result through a future.
    On Ctrl-C the awaiting task is cancelled and the daemon thread is abandoned
    with the process, so shutdown is immediate. A non-blocking lock keeps two
    updates from overlapping: a trigger that fires while one is running is
    skipped rather than queued.
    """
    if not _update_lock.acquire(blocking=False):
        print("Update already running; skipping this trigger.")
        return
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    def worker() -> None:
        result, exc = None, None
        try:
            run_update(rebuild_only)
        except BaseException as e:                  # noqa: BLE001
            exc = e
        finally:
            _update_lock.release()
        try:
            loop.call_soon_threadsafe(_settle, fut, result, exc)
        except RuntimeError:
            pass          # loop already closing during shutdown -- nothing to do

    threading.Thread(target=worker, name="mw-update", daemon=True).start()
    try:
        await fut
    except asyncio.CancelledError:
        # Shutdown while updating: let the daemon thread die with the process
        # instead of joining it (which is what used to hang the exit).
        raise


def _cache_age_hours() -> float | None:
    """How old the cached data is, in hours. None if there is none yet.

    Reads the UTC stamp written by update.rebuild_figures rather than the
    file mtime: copying the data folder between machines, or restoring a
    backup, resets mtimes and would make stale data look fresh.
    """
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(meta["updated_at"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0


def _start_scheduler():
    """The in-process twice-daily update. No cron, no Task Scheduler."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        # apscheduler is a pinned requirement, so this means a broken or
        # partial install rather than a configuration choice. Say so plainly:
        # silently not updating is the worst possible failure for this app.
        print("ERROR: apscheduler is missing, so automatic updates are OFF. "
              "Reinstall with `python run.py setup`. Until then the data "
              "will only refresh when you run `python run.py update`.")
        return None

    tz = settings.update_tzinfo()
    sched = AsyncIOScheduler(timezone=tz) if tz else AsyncIOScheduler()
    for hour in settings.UPDATE_HOURS:
        sched.add_job(
            _run_update_async,
            CronTrigger(hour=hour, minute=settings.UPDATE_MINUTE, timezone=tz),
            id=f"update_{hour:02d}",
            # coalesce: a backlog of missed firings collapses into ONE run,
            # so a laptop waking after two days does not queue four updates.
            coalesce=True,
            # a firing up to an hour late still counts; past that the startup
            # catch-up above is the safety net
            misfire_grace_time=3600,
            max_instances=1,
        )
    sched.start()
    times = ", ".join(f"{h:02d}:{settings.UPDATE_MINUTE:02d}"
                      for h in settings.UPDATE_HOURS)
    print(f"Automatic updates ON: {times} {settings.schedule_tz_name()}, "
          f"in this process. No cron or Task Scheduler needed.")
    return sched


def _next_run_text(scheduler) -> str:
    if scheduler is None:
        return "never (scheduler off)"
    try:
        times = [j.next_run_time for j in scheduler.get_jobs()
                 if getattr(j, "next_run_time", None)]
        return min(times).strftime("%Y-%m-%d %H:%M") if times else "unknown"
    except Exception:
        return "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # First run convenience: if a pickle exists but figures were never
    # built (e.g. you copied over your existing pkl), build them now.
    from .data_pipeline import PICKLE_PATH
    if PICKLE_PATH.is_file() and not META_PATH.is_file():
        print("Pickle found but no figures yet - building from pickle...")
        await _run_update_async(rebuild_only=True)

    scheduler = None
    if settings.ENABLE_SCHEDULER:
        scheduler = _start_scheduler()
        # Catch-up. The scheduler alone only covers a process that is RUNNING
        # when a slot comes round; a machine that was off, asleep or rebooting
        # at 06:20 would otherwise serve stale data until 19:20. This is the
        # piece that makes an external cron job unnecessary rather than merely
        # optional. It runs in the background so the site starts serving
        # immediately -- the update takes minutes, and stale data on screen
        # beats no site at all.
        age = _cache_age_hours()
        limit = settings.STARTUP_CATCHUP_HOURS
        if limit > 0 and (age is None or age > limit):
            why = "no cache yet" if age is None else f"cache is {age:.1f}h old"
            print(f"Startup catch-up: {why} (limit {limit:g}h) - "
                  f"updating in the background.")
            asyncio.get_running_loop().create_task(_run_update_async())
        elif age is not None:
            print(f"Cache is {age:.1f}h old; next update at "
                  f"{_next_run_text(scheduler)}.")
    else:
        print("Scheduler disabled (MW_ENABLE_SCHEDULER=0). Data will only "
              "refresh when you run `python run.py update`.")
    yield
    # Stop firing new jobs immediately and do NOT wait on any in-flight one --
    # the update runs on a daemon thread that dies with the process, so waiting
    # here would only reintroduce the Ctrl-C hang this is meant to avoid.
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass


app = FastAPI(title="Market Big Picture Watch", lifespan=lifespan)
# The strategy payloads are large and highly repetitive JSON -- 12 variants per
# kind, each with a daily series and a step-encoded book -- and compress about
# 5x. Nothing was compressed before, which was fine at 0.6 MB and is not at 2.4.
app.add_middleware(GZipMiddleware, minimum_size=1024)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")),
          name="static")


def _load_meta() -> dict | None:
    if META_PATH.is_file():
        return json.loads(META_PATH.read_text(encoding="utf-8"))
    return None


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Browsers request /favicon.ico at the site root regardless of the <link>
    tags, and static files are mounted under /static -- without this route that
    request 404s and some browsers then show no icon at all."""
    return FileResponse(BASE_DIR / "static" / "favicon.ico",
                        media_type="image/x-icon")


def _asset_version() -> str:
    """Cache-busting stamp from the newest static asset's mtime.

    Without this the browser can keep serving a previous release's
    strategy.js against a freshly rendered page. That failure is nasty
    because it is SILENT: the new markup loads, the old script runs, and the
    page looks fine while quietly doing the wrong thing (a new tab rendering
    the old tab's data, for instance). Appending the stamp to the URL means a
    changed file is always a different URL.
    """
    latest = 0
    for rel in ("static/strategy.js", "static/style.css", "static/i18n.js"):
        f = settings.BASE_DIR / rel
        if f.is_file():
            latest = max(latest, int(f.stat().st_mtime))
    return str(latest)


@app.get("/")
async def index(request: Request, user: User = Depends(require_access)):
    meta = _load_meta()
    return templates.TemplateResponse(request, "index.html", {
        "figures": [{"slug": s, "title": t} for s, t in FIGURES.items()],
        "strategy_tabs": [
            # Static allocations first, so the tab sits BEFORE the dynamic
            # All-Weather strategies. Its "fixed" kind routes the front end to
            # its own panel (#fx-root) rather than the optimizer panel.
            {"slug": "all-weather-fixed", "kind": "fixed",
             "title": "Classical Fixed"},
            {"slug": "all-weather", "kind": "base",
             "title": "All Weather Dynamic"},
            {"slug": "all-weather-lev", "kind": "leverage",
             "title": "All Weather Dynamic Leverage"},
            {"slug": "all-weather-lev3", "kind": "leverage3x",
             "title": "All Weather Dynamic High Leverage"},
        ],
        # Rendered into the page so the opening view follows the CURRENT
        # settings. These used to be read from the cached JSON, which meant a
        # changed default did not take effect until the next nightly rebuild.
        "strategy_defaults": {"frac": strategy_service.DEFAULT_FRAC,
                              "years": strategy_service.DEFAULT_YEARS},
        # Per-kind opening fraction, rendered rather than read from the cached
        # payload so editing the constant takes effect on the next reload.
        "strategy_default_fracs": {
            k: strategy_service.default_frac(k) for k in strategy_service.KINDS},
        "strategy_payload_version": strategy_service.PAYLOAD_VERSION,
        "asset_v": _asset_version(),
        # Rendered so the strategy tabs can show when the next refresh is due.
        "update_hours": settings.UPDATE_HOURS if settings.ENABLE_SCHEDULER else [],
        # The MINUTE was missing here, and the browser assumed :00 -- so the
        # "next update" stamp has been 20 minutes early on every machine.
        "update_minute": settings.UPDATE_MINUTE,
        "scheduler_on": settings.ENABLE_SCHEDULER,
        # Minutes east of UTC for the server right now (DST-aware). The hours
        # above are server-local, so a viewer in another zone needs this to
        # convert them.
        # Offset of the zone the SCHEDULE runs in -- which is the configured
        # timezone when one is set, otherwise the machine's own. Using the
        # machine's offset unconditionally would mis-place the next-update
        # stamp whenever the two differ.
        "server_utc_offset": int(
            ((datetime.now(settings.update_tzinfo()).utcoffset()
              if settings.update_tzinfo() is not None
              else datetime.now().astimezone().utcoffset())
             or timedelta()).total_seconds() // 60),
        "meta": meta,
    })


# ---------------------------------------------------------------------
# All-Weather strategy tab.  Both routes read the day's cached JSON -- the
# backtest itself only ever runs in the daily update job.
# ---------------------------------------------------------------------
@app.get("/api/strategy")
async def api_strategy(kind: str = "base",
                       user: User = Depends(require_access)):
    if kind not in strategy_service.KINDS:
        raise HTTPException(400, f"unknown strategy kind {kind!r}")
    path = strategy_service.cache_path(kind)
    if not path.is_file():
        raise HTTPException(404, "Strategy not built yet - run "
                                 "`python -m app.update --strategy-only`")
    return FileResponse(path, media_type="application/json")


@app.get("/api/strategy/allocations.csv")
async def api_strategy_csv(amount: float = 100_000.0, frac: str | None = None,
                           kind: str = "base",
                           user: User = Depends(require_access)):
    """Current allocation in the Logical Invest CSV layout.

    `frac` picks the sleeve-fraction variant (e.g. "0.50"); omitting it uses
    the dashboard default, so existing bookmarks keep working."""
    if kind not in strategy_service.KINDS:
        raise HTTPException(400, f"unknown strategy kind {kind!r}")
    payload = strategy_service.load_cached(kind)
    if payload is None:
        raise HTTPException(404, "Strategy not built yet")
    if not (0 < amount <= 1e12):
        raise HTTPException(400, "amount out of range")
    try:
        body = strategy_service.allocations_csv(payload, amount, frac)
    except KeyError:
        raise HTTPException(400, f"unknown sleeve fraction {frac!r}; "
                                 f"expected one of {payload.get('fracs')}")
    key = frac or payload.get("default_frac", "")
    variant = payload.get("variants", {}).get(key, {})
    stamp = variant.get("allocation_date") or payload.get("as_of", "")
    tag = key.replace(".", "")
    kindtag = "" if kind == "base" else f"_{kind}"
    return Response(
        content=body, media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename='
                 f'"Allocations_AllWeather{kindtag}_sleeve{tag}_{stamp}.csv"'},
    )


# ---------------------------------------------------------------------
# All-Weather Fixed tab (static allocations A & B). Same read-the-cache
# pattern as the dynamic strategy above.
# ---------------------------------------------------------------------
@app.get("/api/strategy/fixed")
async def api_strategy_fixed(user: User = Depends(require_access)):
    path = fixed_service.CACHE_PATH
    if not path.is_file():
        raise HTTPException(404, "Fixed allocations not built yet - run "
                                 "`python -m app.update --strategy-only`")
    return FileResponse(path, media_type="application/json")


@app.get("/api/strategy/fixed/allocations.csv")
async def api_strategy_fixed_csv(section: str = "A", amount: float = 100_000.0,
                                 user: User = Depends(require_access)):
    payload = fixed_service.load_cached()
    if payload is None:
        raise HTTPException(404, "Fixed allocations not built yet")
    if not (0 < amount <= 1e12):
        raise HTTPException(400, "amount out of range")
    try:
        body = fixed_service.allocations_csv(payload, section, amount)
    except KeyError:
        raise HTTPException(400, f"unknown fixed section {section!r}; "
                                 f"expected one of {payload.get('section_order')}")
    sec = payload.get("sections", {}).get(section, {})
    stamp = sec.get("allocation_date") or ""
    return Response(
        content=body, media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename='
                 f'"Allocations_AllWeatherFixed_{section}_{stamp}.csv"'},
    )


@app.get("/api/meta")
async def api_meta(user: User = Depends(require_access)):
    meta = _load_meta()
    if meta is None:
        raise HTTPException(404, "No data yet - run `python -m app.update`")
    return meta


@app.get("/api/figures/{slug}")
async def api_figure(slug: str, lang: str = "en",
                     user: User = Depends(require_access)):
    if slug not in FIGURES:
        raise HTTPException(404, f"Unknown figure '{slug}'")
    # Fall back to English rather than 404ing if a locale was never built --
    # but SAY SO in a header. A silent fallback is indistinguishable from a
    # broken translation, and the fix (rebuild the figures) is not guessable.
    served = lang
    path = FIG_DIR / (f"{slug}.json" if lang == "en" else f"{slug}.{lang}.json")
    if not path.is_file() and lang != "en":
        path = FIG_DIR / f"{slug}.json"
        served = "en"
    if not path.is_file():
        raise HTTPException(404, "Figure not built yet - run "
                                 "`python -m app.update`")
    return FileResponse(path, media_type="application/json",
                        headers={"X-Figure-Lang": served})


@app.post("/api/update")
async def api_update(request: Request):
    """Manual refresh, protected by a shared secret so it can be exposed
    publicly (or triggered by an external cron-over-HTTP service)."""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(404)
    token = request.headers.get("X-Admin-Token", "")
    if not secrets.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(403, "Bad admin token")
    if _update_lock.locked():
        return JSONResponse({"status": "already running"}, status_code=409)
    asyncio.create_task(_run_update_async())
    return {"status": "started"}
