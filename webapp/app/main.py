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
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import settings
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
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            _run_update_async,
            CronTrigger(hour=settings.UPDATE_HOUR, minute=0),
            id="daily_update", coalesce=True, misfire_grace_time=3600,
        )
        scheduler.start()
        print(f"In-process scheduler on: daily update at "
              f"{settings.UPDATE_HOUR:02d}:00 local time.")
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


@app.get("/")
async def index(request: Request, user: User = Depends(require_access)):
    meta = _load_meta()
    return templates.TemplateResponse(request, "index.html", {
        "figures": [{"slug": s, "title": t} for s, t in FIGURES.items()],
        "meta": meta,
    })


@app.get("/api/meta")
async def api_meta(user: User = Depends(require_access)):
    meta = _load_meta()
    if meta is None:
        raise HTTPException(404, "No data yet - run `python -m app.update`")
    return meta


@app.get("/api/figures/{slug}")
async def api_figure(slug: str, user: User = Depends(require_access)):
    if slug not in FIGURES:
        raise HTTPException(404, f"Unknown figure '{slug}'")
    path = FIG_DIR / f"{slug}.json"
    if not path.is_file():
        raise HTTPException(404, "Figure not built yet - run "
                                 "`python -m app.update`")
    return FileResponse(path, media_type="application/json")


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
