# Market Big Picture Watch — web app

Interactive dashboard for the MarketBigPictureWatch figures: FastAPI backend,
daily data collection from FRED / Yahoo Finance / multpl.com, and the five
figure sets rendered client-side with Plotly.

```
marketwatch/
├── app/
│   ├── main.py           FastAPI app, routes, in-process daily scheduler
│   ├── update.py         the daily job:  python -m app.update
│   ├── data_pipeline.py  downloads (verified logic from the original script)
│   ├── figures.py        the five figure builders (verified vs matplotlib)
│   ├── auth.py           access-control seam for future subscriptions
│   └── settings.py       env-var configuration
├── templates/ static/    dashboard UI
├── data/                 pickle, figure JSON, meta (created at runtime)
├── run_server.bat        Windows: start the server
├── update_data.bat       Windows: manual / Task Scheduler update
├── register_task.bat     Windows: one-time Task Scheduler registration
└── Dockerfile            for hosting services later
```

## Run it on Windows

```bat
cd marketwatch
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app.update      REM first data download (~2-5 min)
run_server.bat
```

Open http://localhost:8000. To reach it from other devices on your network,
allow port 8000 through Windows Firewall.

Already have a `MarketBigPictureWatch.pkl` from the standalone scripts?
Copy it into `data\` and start the server — it builds the figures from the
pickle automatically on first launch (or run
`python -m app.update --rebuild-only`).

## Daily data collection — pick one

1. **In-process (default, zero setup).** The server schedules its own update
   at `MW_UPDATE_HOUR` (06:00). Just keep `run_server.bat` running. If the
   machine was asleep at 06:00, the job runs when it wakes (1-hour grace).
2. **Windows Task Scheduler.** Set `MW_ENABLE_SCHEDULER=0` in `.env`, then run
   `register_task.bat` once as Administrator. Logs land in `data\update.log`.
3. **cron / hosting-service scheduled job.** Same command everywhere:
   `python -m app.update`.
4. **HTTP trigger.** Set `MW_ADMIN_TOKEN` in `.env`, then
   `curl -X POST -H "X-Admin-Token: <token>" http://host:8000/api/update`
   — handy for cron-over-HTTP services.

## Deploying to a hosting service later

The app is a standard ASGI service, so any Python-friendly host works
(Render, Railway, Fly.io, a small VPS):

- **Web service:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
  (or the included `Dockerfile`).
- **Persistent disk:** mount a volume at `data/` so figures and the pickle
  survive restarts.
- **Nightly job:** either leave the in-process scheduler on (simplest,
  requires an always-on instance), or set `MW_ENABLE_SCHEDULER=0` and add the
  host's cron job running `python -m app.update` in the same environment.
- **Health check:** `GET /healthz`.

## Making it subscription-based later

The seam is already in place — every content route depends on
`require_access` in `app/auth.py`, which today lets everyone in because
`MW_AUTH_ENABLED=0`. When you're ready:

1. Add accounts: the `fastapi-users` package gives you registration, login,
   sessions, and password reset with a small amount of glue code. Implement
   `get_current_user` in `app/auth.py` to read its session.
2. Add billing: create a Stripe subscription product, store each user's
   Stripe customer id, and update `has_active_subscription` from Stripe
   webhooks (`checkout.session.completed`, `customer.subscription.updated`
   / `.deleted`).
3. Set `MW_AUTH_ENABLED=1`. The figure routes now return 401/402 for
   non-subscribers; add your login and pricing pages.

No changes to the pipeline, figures, or routes are needed — only `auth.py`
plus the new pages.

## Configuration

All via environment variables or `.env` (see `.env.example`):
`MW_DATA_DIR`, `MW_ENABLE_SCHEDULER`, `MW_UPDATE_HOUR`, `MW_AUTH_ENABLED`,
`MW_ADMIN_TOKEN`, `MW_PORT`.
