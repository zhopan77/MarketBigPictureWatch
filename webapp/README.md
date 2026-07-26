# Market Big Picture Watch — web app

Interactive dashboard: FastAPI backend, daily data collection from FRED /
Yahoo Finance / multpl.com, five macro figure sets rendered client-side with
Plotly, plus an **All Weather Strategy** tab that reruns the ZP_AllWeather9
backtest every day and publishes the current allocation.

```
marketwatch/
├── app/
│   ├── main.py           FastAPI app, routes, in-process daily scheduler
│   ├── update.py         the daily job:  python -m app.update
│   ├── data_pipeline.py  downloads (verified logic from the original script)
│   ├── figures.py        the five figure builders (verified vs matplotlib)
│   ├── strategy.py       All-Weather backtest engine (port of the Zorro .c)
│   ├── strategy_service.py  strategy download / cache / CSV export
│   ├── auth.py           access-control seam for future subscriptions
│   └── settings.py       env-var configuration
├── templates/ static/    dashboard UI (incl. the Einnia logo + favicons)
├── tools/vectorize_logo.py   regenerates the logo SVGs from the raster
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

## All Weather Strategy tab

A Python port of `ZP_AllWeather9_v3_9_2_Cap_LiveETF.c` runs as part of the
daily job and caches its result, so page loads never pay the backtest cost.

**What the tab shows**

- equity curve of the strategy with SPY and QQQ buy-and-hold overlaid,
  re-based to 0% at the start of whatever period you select
- a statistics ledger (return, CAGR, volatility, downside volatility, Sharpe,
  Sortino, Ulcer, max drawdown) for all three, recomputed for that period
- begin/end sliders plus 1y / 3y / 5y / 10y / 15y / Max shortcuts, opening
  on the last 5 years. Slicing,
  re-basing and the statistics all happen in the browser, so the controls are
  instant and never hit the server
- a facts strip at the top right: data through, current Hurst, rebalance
  count, realised BIL carry, sleeve state, and the **last adjustment** date
  in bold -- the day the book actually last changed, which is the date the
  exported allocation belongs to
- a **QQQ sleeve fraction** dropdown (0.50 / 0.75 / 1.00, defaulting to
  0.75). All three are
  backtested in the daily job and shipped together, so switching is an
  instant re-render with no recomputation, and the selected period is kept
  so the fractions stay directly comparable
- the current allocation as a table and a donut chart, with an **Export
  allocation CSV** button
- monthly and yearly returns for the strategy, computed over the same
  selected period as everything else on the page (so the first month is a
  partial month unless the period starts on a month boundary)
- the full adjustment log: every rebalance and every QQQ-sleeve flip since
  2008, independent of the selected period

**Sleeve fractions.** `SLEEVE_FRAC` sets how much of the book tilts into QQQ
while the sleeve is on. It affects ONLY the effective book: the optimizer
reads returns, momentum and VIX, and the sleeve ON/OFF state comes from the
Hurst band and the HA trend candle -- neither depends on the fraction, and
equity never feeds back into sizing. So the optimizer weights and the sleeve
timeline are identical across all three variants, which is asserted by the
backtest and is why they are directly comparable.

**Exported CSV.** `GET /api/strategy/allocations.csv?amount=100000&frac=0.50`
returns
the Logical Invest layout byte for byte — leading `""` row, every field
quoted, CRLF line endings, one-decimal weights, whole-dollar amounts with
thousands separators, floored share counts, and the trailing
`"Total Allocation","","(adjust leverage here)"` row. Existing automation
that reads Logical Invest allocation files needs no changes. Omitting `frac`
exports the default fraction, so older bookmarks keep working; the filename
carries the fraction (`Allocations_AllWeather_sleeve075_2026-05-07.csv`).

**Cache staleness.** Anything that lives in `data/strategy.json` -- the equity
series, the allocations, the adjustment log -- only changes when the backtest
is rerun. Code changes to `build_payload` therefore have no visible effect
until the next update. To stop that being silent, the payload carries a
`PAYLOAD_VERSION`; the page compares it against the running code's and shows a
notice with the exact command if the cache is older. The adjustment log also
states its own extent ("595 entries, 2008-06-10 to 2026-05-07"), so a
truncated or short log is obvious rather than looking like a short history.
Presentation-only settings (the opening sleeve fraction and period) are
rendered by the server instead, so those take effect immediately.

**Running it**

```bat
python -m app.update                    REM macro figures + strategy (daily job)
python -m app.update --strategy-only    REM just the backtest (~15 s)
python -m app.update --skip-strategy    REM just the macro figures
```

The strategy step is wrapped in its own try/except: a Yahoo outage on one
side never takes down the other half of the dashboard. Output lands in
`data/strategy.json` (served by `/api/strategy`) and `data/strategy_adjustments.log`.

**Parity with the Zorro build — read before trusting the numbers.** Every
constant, the objective, the weight cap, the DFA-Hurst, the rolling
Heikin-Ashi trend test, the hysteresis and the bar-counted cadence are
transcribed 1:1. Four things deliberately differ and cannot be made
identical:

1. **Random restarts.** Restarts 1-4 draw from numpy's generator, not
   Zorro's `random()`, so the optimizer can settle on a different local
   optimum. Restart 0 is deterministic and dominates in practice.
2. **Fills.** A target set at the close of day *t* is applied at day *t+1*'s
   open, matching Zorro's next-bar market order — but with fractional
   shares, so Zorro's lot-rounding cash drag is absent.
3. **Data.** Yahoo (`auto_adjust=True`) rather than the local `.t6` files.
   Both are split- and dividend-adjusted, but the vendors differ slightly.
4. **Floating point.** Different summation order in the vectorised
   objective; irrelevant except that a gradient optimizer can amplify
   last-bit differences into slightly different weights.

Treat this as independent double-proofing and as the source of the live
allocation — not as a bit-exact replica of the Zorro backtest.

**Cash carry.** `auto_adjust=True` back-adjusts for distributions, so BIL's
series is a total-return series and the residual cash weight genuinely earns
the bill rate. The header strip and the update log both report BIL's realised
annualised return over the window; it should track the average 1-3 month
T-bill yield. A reading near 0% would mean distributions are not being
adjusted in and the cash leg is silently earning nothing.

Cash is carried in **BIL**, which only lists from 2007-05-30. That is what
binds the start of the backtest: the aligned history begins there and
trading starts at 2008-06-10, giving roughly 18 years. The tab opens on the
most recent 15.

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

## Dark mode

A **Dark mode** switch sits in the top bar. The whole stylesheet runs on CSS
custom properties, so the theme is a token swap on `<html data-theme="dark">`;
the preference is stored in `localStorage` and applied by a tiny inline script
before first paint, so there is no white flash on load. The Einnia mark ships
as **SVG**, traced from the raster by `tools/vectorize_logo.py`. The source art
was drawn on a white plate, so every edge pixel was a blend of ink and white;
knocking the plate out left those blends opaque and whitish, which is invisible
on a light page and shows as a white fringe on a dark one. Vector has no
baked-in anti-aliasing to fringe, and stays sharp at any size. Two files ship:
the brand blue and red sit at 2.8:1 and 3.8:1 against the dark paper, so dark
mode loads `einnia-dark.svg`, whose failing hues are lifted just far enough to
clear AA while yellow and green pass through untouched. CSS picks the file, so
the right logo is correct on first paint. The favicons are re-rendered from the
same vector onto transparency, so they do not fringe either. Plotly figures carry
baked-in colours rather than CSS, so they are repainted separately -- every
subplot axis, legend and annotation is overridden by name, and the TRACE
colours are lifted too. That last part matters: the macro figures use a light
palette in which `darkblue` sits at 1.09:1 against the dark card, `black` at
1.26 and `blue` at 1.94. Each failing colour has its lightness raised until it
clears 4.5:1, plus a slice of its original lightness added back -- without that
second term `blue` and `darkblue` map onto the same value, and the Case-Shiller
chart uses both for different cities. Originals are recorded before the first
restyle, so switching back to light restores the palette exactly. All foreground /
background pairs in both themes meet WCAG AA or better.

Anything whose colour is baked in at render time -- the heat-map blocks and
statistics swatches (inline `style` attributes) and both plotly surfaces
(plotly copies colours into its own state) -- has to be redrawn on a theme
change, so all of it is routed through a single `renderThemed()` rather than
a hand-written list of calls at each site. Text colours that come from CSS
classes follow the theme on their own.

## Signed figures

Two channels, two jobs. **Colour carries the sign**: a vivid green for gains,
an alarming red for losses, on Return, CAGR, MaxDD, monthly cells and yearly
totals. Volatility, downside volatility, Sharpe, Sortino and Ulcer are not
signed, so they stay ink. Individual monthly cells stay ink when positive --
only the yearly totals go green -- so the grid does not become a wall of
colour.

The monthly grid is a **heat map**: each month is a block running from the
neutral (white in light mode, the card in dark) at 0% out to a deep green at
+10% and a deep red at -10%, clamped beyond. The number sits inside the block
in whichever of pure black or pure white contrasts better with that fill --
pure endpoints are deliberate, because the two contrast curves cross at a
background luminance of 0.179 where both give 4.58:1, so no step of the scale
can fall below AA. Yearly totals get no block fill, only bold plus the
gain/loss text colour, so they read as a summary of the row rather than
another cell in the matrix.

**Weight carries the headline**: the strategy row of the statistics ledger and
the Year column of the monthly grid are bold; benchmark rows and individual
months are not. Weight is deliberately NOT tied to the sign, so bold means
"this is the number that matters" rather than "this one is bad".

All colour/background pairs clear WCAG AA, including on the tinted strategy
row (which qualifies as WCAG large text once bold).

The equity chart shades the strategy's area against its neutral line -- 0% on
the linear scale, 100 on the log scale -- green above it and red below.
Plotly has no two-tone fill, so the series is clamped above and below the
baseline and each half is filled separately against an invisible flat trace.
Filling `tonexty` rather than `tozeroy` is what makes this work on a log axis,
where zero is minus infinity.

## A note on the opening view

`DEFAULT_FRAC` and `DEFAULT_YEARS` in `app/strategy_service.py` set what the
tab opens on. They are rendered into the page by the server on every request,
NOT read from the cached JSON -- otherwise changing one would have no effect
until the next nightly rebuild.

## Configuration

All via environment variables or `.env` (see `.env.example`):
`MW_DATA_DIR`, `MW_ENABLE_SCHEDULER`, `MW_UPDATE_HOUR`, `MW_AUTH_ENABLED`,
`MW_ADMIN_TOKEN`, `MW_PORT`.
