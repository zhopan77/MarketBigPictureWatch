# Market Big Picture and Long-term Strategies — web app

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
  Sortino, Ulcer, UPI, max drawdown) for all three, recomputed for that period.
  UPI is the Ulcer Performance Index (the Martin ratio, 马丁比率): CAGR divided
  by the Ulcer Index, i.e. return per unit of drawdown *pain* rather than per
  unit of volatility. Like the Sharpe and Sortino here it subtracts no
  risk-free rate, and CAGR is scaled to percent because the Ulcer Index is
  already in percentage points
- begin/end sliders plus 1y / 3y / 5y / 10y / 15y / Max shortcuts, opening
  on the last 5 years. Slicing,
  re-basing and the statistics all happen in the browser, so the controls are
  instant and never hit the server
- a facts strip at the top right: data through, sleeve state, and the **last
  adjustment** date in bold -- the day the book actually last changed, which
  is the date the exported allocation belongs to. Internals that describe HOW
  the strategy works (the Hurst reading, the rebalance count, the realised
  cash carry) are deliberately not shown
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

**Figure cache keys.** Cached figures are keyed by slug AND language, since
the two languages are separate files. Every lookup goes through one `figKey()`
helper: when the key gained a language component, one call site kept reading by
bare slug, which silently stopped the theme switch from repainting the macro
charts until a reload.

**Browser cache.** `style.css` and `strategy.js` are served with a
cache-busting stamp taken from their mtime, so a new build can never be run
against a previous release's script. That failure mode is silent and
confusing: the new markup loads, the old script runs, and the page looks
healthy while quietly doing the wrong thing — a new tab rendering the old
tab's data, for example.

**The download cache is pandas-version specific.** `data/MarketBigPictureWatch.pkl`
holds pickled pandas objects, and those are only readable by a compatible
pandas — pandas 3 stores date columns at second/microsecond resolution and
pandas 2 cannot restore a resolution it never produces. Running the app from a
different environment than the one that wrote the cache (a `.venv` versus
conda `base`, say) therefore fails inside the unpickler. A sidecar records the
writing versions so the error names both sides, and `--rebuild-only` falls
back to a full download rather than stopping: the pickle is only a download
cache, so re-fetching costs a couple of minutes rather than a diagnosis.

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

The header stamp shows both the last data update and the **next scheduled
one**, in the same format, each with a full date and the viewer's time zone.
Both follow the UI language rather than the browser's locale, so Chinese gives
`2026年7月29日 01:00 CDT` against English's `Jul 29, 2026, 01:00 AM CDT`. The
parts are composed by hand because asking zh-CN for a zone name wedges it into
the middle (`2026年7月29日 GMT-5 06:00`), and the zone abbreviation is always
read through en-US so it stays the familiar CDT rather than GMT-5. The configured hours are
SERVER-local, so the page is given the server's UTC offset and converts: on a
single-machine install that reduces to the obvious thing, and from a phone on
the LAN it still names the correct instant rather than confidently showing the
right numbers in the wrong zone. It recomputes each minute so an all-day window
does not go stale, and reads "manual" when the in-process scheduler is off.

The in-process scheduler is optional: if `apscheduler` is not installed the
site still serves and simply says so, since many installs drive
`python -m app.update` from cron or Task Scheduler instead. When enabled it
runs **twice a day, at 06:00 and 19:00 local time**,
refreshing both the macro figures and the All Weather backtest. Override with
`MW_UPDATE_HOURS` (comma separated, e.g. `7,13,21`); the older single-hour
`MW_UPDATE_HOUR` still works and is merged in.

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

## Language

English and Simplified Chinese, chosen with the radio buttons in the top bar
**Every page load starts in English.** The choice is deliberately NOT
persisted: a remembered language is indistinguishable from a wrong default once
you have forgotten you picked it. `navigator.language` is not sniffed either,
so a Chinese-locale browser also opens in English. To make it sticky, save
`LANG` in `applyLanguage()` and read it back in `initLanguage()`. `static/i18n.js` holds both tables; static
markup carries `data-i18n="key"` and is swapped in place, while strings built
in JS call `t("key")` and are re-rendered on switch.

The Chinese is a financial register rather than a literal gloss — "sleeve"
becomes 增强仓 rather than a word-for-word translation, and the ratios use
their standard names (夏普比率, 索提诺比率, 最大回撤). One typographic detail:
Latin needs a word space between the two halves of the title and CJK does not,
so the separator is inserted by CSS rather than baked into the markup.

The macro charts on tabs 01-05 are translated too. Their text is baked into
the figure JSON, so `app/figures_i18n.py` post-processes the finished figure
rather than threading a language through every builder: the plotting code
stays single-language and readable, and adding a locale means adding a
dictionary. `python -m app.update` therefore writes `{slug}.json` and
`{slug}.zh.json`, and the API serves whichever the page asks for. If a locale was never built it
falls back to English and says so in an `X-Figure-Lang` header, which the page
turns into a visible notice naming the command to run -- a silent fallback is
indistinguishable from a broken translation.

Date tick labels are a separate problem: plotly renders those itself, so no
dictionary can reach them. The Chinese build attaches `tickformatstops` to
every x axis, which swaps the pattern by zoom level -- an 8-year chart wants
`2026年` where a one-year chart wants `2026年7月` and a one-month view wants
`2026年7月28日`. The `-` pad modifier drops the leading zero, so it reads 7月
rather than 07月.

Strings absent from the table pass through unchanged, which keeps tickers and
index names (CPI, M2, VIX) correct without enumerating them; a `KEEP` set
marks those as deliberate so `untranslated()` only reports genuine gaps, which
the build prints. Futures contract names ARE translated (CrudeOil becomes WTI原油) since the
legend is the only label identifying each of the twenty small panels, and the
"(no data)" placeholder drawn on a failed panel is translated with it. Note
these keys are the descriptive names in `data_pipeline.futures_underlying`,
NOT the Yahoo symbols -- writing them against the symbols produces a table that
silently matches nothing.

## Dark mode

**Dark is the default**; a **Dark mode** switch sits in the top bar and an
explicit choice of light is remembered. The whole stylesheet runs on CSS
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

## Macro figure styling

The builders name their line colours ("blue", "red", ...), which used to
resolve to the CSS primaries — pure `#0000FF`, `#FFFF00`, `#FF00FF`. That is
what made the charts look like old gnuplot output, and yellow on white was
nearly invisible. Those names now resolve through a `PALETTE` table in
`figures.py`, so one edit restyles every call site while the names stay
readable where they are used.

The palette is chosen for even perceived weight, separation by hue rather than
lightness, and enough darkness to stay legible on white — the binding
constraint, since light mode gets no automatic lifting (worst is 3.14:1, above
the 3.0 non-text threshold). The Case-Shiller city cycle is ordered for maximum
hue separation: nine lines share one subplot, and the old order put magenta,
red and pink together, which become hard to separate once dark mode lifts them.

Also: a solid hairline grid instead of a dotted one (dots go fuzzy when the
browser scales them), a hairline axis frame instead of the old solid black box,
and the UI's own font.

**Palette changes are baked into the figure JSON**, so they need
`python -m app.update --rebuild-only` to appear.

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

## All Weather Leverage Strategy

A second tab runs the identical strategy with one change: while the sleeve is
ON it buys **QLD** (ProShares Ultra QQQ, 2x daily) instead of QQQ. Everything
else — the optimizer, the universe, the VIX regimes, the Hurst/Heikin-Ashi
gate, the cadence — is untouched, and the base strategy's numbers are
bit-identical to before the change.

Two deliberate design points:

* **The signal still comes from QQQ.** QLD is 2x QQQ's daily return, so it
  carries no extra information about trend or persistence — only extra noise
  and decay. Reading the gate off QQQ keeps the timing identical between the
  two tabs, which is what makes them comparable.
* **QQQ keeps its own optimizer weight.** The sleeve becomes a separate QLD
  leg rather than replacing QQQ, so the optimizer's solution is untouched.

`QLD` is downloaded alongside but deliberately excluded from the calendar
intersection: if it ever started later than BIL it would silently truncate the
plain strategy's history too. If its history does not cover the window, the
leveraged tab is skipped and the plain one is unaffected.

**Account leverage is still 1x** — weights sum to 1.0 and nothing is bought on
margin. But holding a 2x fund means the BOOK's economic exposure exceeds 100%
whenever the sleeve is on, and the drawdowns reflect that. Read the MaxDD
column before drawing conclusions from the CAGR column.

## A note on the opening view

`DEFAULT_YEARS` in `app/strategy_service.py` sets the opening period, and each
entry in `KINDS` carries its own `default_frac`: **0.75** for the plain sleeve,
**0.50** for the leveraged one, where drawdown grows fast enough past 0.50 that
opening higher would put the most flattering curve in front of you by default. They are rendered into the page by the server on every request,
NOT read from the cached JSON -- otherwise changing one would have no effect
until the next nightly rebuild.

## Configuration

All via environment variables or `.env` (see `.env.example`):
`MW_DATA_DIR`, `MW_ENABLE_SCHEDULER`, `MW_UPDATE_HOUR`, `MW_AUTH_ENABLED`,
`MW_ADMIN_TOKEN`, `MW_PORT`.
