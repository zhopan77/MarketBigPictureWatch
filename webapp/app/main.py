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
from datetime import datetime, timedelta
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings, strategy_service
from .auth import User, require_access
from .figures import FIGURES
from .update import FIG_DIR, META_PATH, run_update

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_update_lock = asyncio.Lock()


async def _run_update_async(rebuild_only: bool = False) -> None:
    """Run the (blocking) update in a worker thread, one at a time."""
    async with _update_lock:
        await asyncio.to_thread(run_update, rebuild_only)


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
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            # The in-process scheduler is optional -- plenty of installs drive
            # `python -m app.update` from cron or Task Scheduler instead. A
            # missing dependency should not stop the site from serving.
            print("apscheduler not installed; in-process scheduling is off. "
                  "Run `python -m app.update` externally, or "
                  "`pip install apscheduler`.")
            AsyncIOScheduler = None
    if settings.ENABLE_SCHEDULER and AsyncIOScheduler is not None:
        scheduler = AsyncIOScheduler()
        # One job per configured hour. coalesce collapses a backlog into a
        # single run, so a laptop waking from sleep does not fire both.
        for hour in settings.UPDATE_HOURS:
            scheduler.add_job(
                _run_update_async,
                CronTrigger(hour=hour, minute=0),
                id=f"update_{hour:02d}", coalesce=True,
                misfire_grace_time=3600, max_instances=1,
            )
        scheduler.start()
        times = ", ".join(f"{h:02d}:00" for h in settings.UPDATE_HOURS)
        print(f"In-process scheduler on: updates at {times} local time "
              f"(macro figures + All Weather strategy).")
    yield
    if scheduler:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Market Big Picture Watch", lifespan=lifespan)
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
            {"slug": "all-weather", "kind": "base",
             "title": "All Weather Strategy"},
            {"slug": "all-weather-lev", "kind": "leverage",
             "title": "All Weather Leverage Strategy"},
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
        "scheduler_on": settings.ENABLE_SCHEDULER,
        # Minutes east of UTC for the server right now (DST-aware). The hours
        # above are server-local, so a viewer in another zone needs this to
        # convert them.
        "server_utc_offset": int(
            (datetime.now().astimezone().utcoffset() or timedelta()).total_seconds() // 60),
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
