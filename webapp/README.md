# Market Big Picture and Long-term Strategies — web app

Interactive dashboard: FastAPI backend, daily data collection from FRED /
Yahoo Finance / multpl.com, five macro figure sets rendered client-side with
Plotly, plus an **All Weather Strategy** tab that reruns the ZP_AllWeather9
backtest every day and publishes the current allocation.

```
marketwatch/
├── run.py                THE launcher -- same command on Windows and Linux
├── config.ini            all settings, including the FRED API key
├── app/
│   ├── determinism.py    pins BLAS/SIMD dispatch; read this before numpy
│   ├── selftest.py       reproducibility check:  python run.py selftest
│   ├── main.py           FastAPI app, routes, twice-daily in-process scheduler
│   ├── update.py         the data job:  python run.py update
│   ├── data_pipeline.py  downloads (verified logic from the original script)
│   ├── figures.py        the five figure builders (verified vs matplotlib)
│   ├── strategy.py       All-Weather backtest engine (port of the Zorro .c)
│   ├── strategy_service.py  strategy download / cache / CSV export
│   ├── fixed_service.py  the Classical Fixed tab
│   ├── auth.py           access-control seam for future subscriptions
│   └── settings.py       config.ini + environment resolution
├── templates/ static/    dashboard UI (incl. the Einnia logo + favicons)
├── tools/vectorize_logo.py   regenerates the logo SVGs from the raster
├── docs/Server_runbook.md    Ubuntu + Cloudflare Tunnel production runbook
├── data/                 pickle, figure JSON, meta (created at runtime)
├── run_server.bat        Windows double-click shim; forwards to run.py
├── requirements.txt      EXACT pins -- see the note inside
└── Dockerfile            for hosting services
```

## Running it — identical on Windows and Linux

```
python run.py             set up if needed, then start the server
python run.py update      fetch data and rebuild now
python run.py selftest    reproducibility check (compare between machines)
python run.py doctor      show config, environment and cache state
```

That is the whole interface, and it is the same text on both operating
systems. `run.py` runs on the system Python, needs nothing installed, and its
first job is to build the project's own virtual environment with the pinned
dependencies and re-launch itself inside it.

Then open http://localhost:8000.

**Ubuntu first time:**

```bash
sudo apt install python3-venv python-is-python3
```

Python 3.11 or newer is required (numpy 2.3.x sets that floor).

`python3-venv` is required (on 24.04 the venv is not optional -- PEP 668 marks
the system Python externally-managed and pip refuses to install into it).
`python-is-python3` is what makes the command literally identical to Windows;
without it, use `python3 run.py`.

**Windows first time:** nothing. Install Python from python.org with "Add
python.exe to PATH" ticked.

Already have a `MarketBigPictureWatch.pkl` from the standalone scripts? Copy
it into `data/` and start the server -- it builds the figures from the pickle
automatically on first launch.

## Configuration

Everything lives in **`config.ini`** in this folder. It is a plain visible
file, read identically on both operating systems, and the only setting worth
filling in is the FRED API key:

```ini
[marketwatch]
fred_api_key = your_key_here
```

Without a key the app falls back to an unauthenticated scrape of
fredgraph.csv, which is throttled per IP and is the usual cause of a read
timeout partway through a long update. Keys are free from
https://fredaccount.stlouisfed.org/apikey

**The file wins.** A value written here beats an environment variable of the
same name (`MW_FRED_API_KEY`, `MW_PORT`, ...). That is the opposite of the
usual convention and is deliberate: what you can see in the file is what the
app uses, and a stale variable in a shell profile or in Windows user variables
cannot silently override the key you just pasted in. Environment variables
still fill in anything left empty. `python run.py doctor` prints where each
value came from and flags any setting where both exist.

## Data updates — nothing to set up

The server updates itself **twice a day**, at the times in `config.ini`
(default 06:20 and 19:20 local), from inside its own process. There is no
cron job and no Windows Task Scheduler entry, and there is nothing to
register.

Two mechanisms cover the two ways this can go wrong:

- **The schedule** fires while the server is running. Missed firings are
  coalesced into a single run, so a laptop waking after two days does not
  queue four updates.
- **The startup catch-up** covers the case the schedule cannot: a machine
  that was off, asleep or rebooting when the slot came round. If the cache is
  older than `startup_catchup_hours` (default 18) the server updates as soon
  as it starts, in the background, so the site is serving immediately.

If you would rather drive it yourself, set `enable_scheduler = 0` and run
`python run.py update`. There is also an HTTP trigger: set `admin_token` and
`POST /api/update` with an `X-Admin-Token` header.

The first update takes longer than you might expect -- roughly 10-25 minutes.
Most of that is the strategy tab, which runs 3 sleeves x 6 fractions x 2
brake settings = 36 full backtests. Setting `strategy_vt_ab = 0` halves it,
at the cost of hiding the dashboard's brake checkbox.

## Reproducibility

Two machines running this code on the same data are expected to produce
**bit-identical** results, and there is a command to prove it:

```
python run.py selftest
```

Run it on both machines and compare the `COMBINED` hash. Same hash means the
two compute identically and any remaining dashboard difference is coming from
the DATA, not the code. Different hash means the environment line printed
above it tells you which layer to look at.

This is not free, and it is not automatic in general. Getting here required
pinning three things that are normally left to chance:

1. **Dependency versions** (`requirements.txt`) -- pinned exactly. numpy and
   pandas are the two that must match; different versions of them do not
   compute the same numbers.
2. **The OpenBLAS kernel** (`OPENBLAS_CORETYPE`). numpy's `@` dispatches to a
   matmul microkernel chosen at runtime *from the detected CPU*, and
   different kernels sum in a different order.
3. **numpy's own SIMD dispatch** (`NPY_DISABLE_CPU_FEATURES`), for the same
   reason one layer down.

Points 2 and 3 sound like last-bit pedantry. They are not, because of the
optimizer. `optimize_weights` runs five gradient ascents from different
starting points and keeps the best by a strict float comparison
(`if cur_obj > best_obj`). When two restarts converge to near-equal
objectives -- common, since restart 0 anchors on the previous weights -- a
last-bit difference selects a *different local optimum*, not a nearby weight
vector. That happens at ~600 rebalances.

Measured, by running the identical backtest under two BLAS kernels and
ablating one mechanism at a time (relative difference in final equity):

| variant | divergence |
|---|---|
| production | 4.97e-04 |
| volatility brake disabled entirely | 4.62e-04 |
| continuous brake, no threshold jump | 5.07e-04 |
| continuous sleeve, no on/off flip | 5.77e-04 |
| `N_RESTARTS = 1` | **6.03e-08** |

The path-dependent volatility brake looks like the obvious culprit and is
not: removing it changes nothing. Nor does smoothing any of the discrete
branches -- a choice between distinct local optima is not a threshold that
can be smoothed. Pinning dispatch is what fixes it.

This was never about the operating system: two machines with different CPUs
would diverge the same way.

`app/determinism.py` has the full explanation and must stay imported before
numpy anywhere.

## Deploying to a hosting service later

The app is a standard ASGI service, so any Python-friendly host works
(Render, Railway, Fly.io, a small VPS):

- **Web service:** `python run.py`, or the included `Dockerfile`. The
  determinism settings are applied by `app/__init__.py` before numpy loads,
  whichever entry point is used.
- **Persistent disk:** mount a volume at `data/` so the cache survives
  restarts.
- **Nightly job:** none needed. The scheduler runs in-process, so the only
  requirement is an always-on instance. On a host that sleeps idle instances,
  the startup catch-up covers the gap.
- **Health check:** `GET /healthz`.

### systemd, for a Linux server

```ini
# /etc/systemd/system/marketwatch.service
[Unit]
Description=Market Big Picture Watch
After=network-online.target
Wants=network-online.target

[Service]
User=YOUR_USER
WorkingDirectory=/srv/marketwatch
ExecStart=/usr/bin/python3 /srv/marketwatch/run.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now marketwatch
journalctl -u marketwatch -f
```

`run.py` finds and re-enters its own virtual environment, so `ExecStart` can
point at the system Python. `WorkingDirectory` matters: `data_dir` in
`config.ini` is relative to the project folder.

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


## v5.0 -- conditional volatility brake (production)

Both strategies now scale the book down when the strategy's own trailing
60-day realised volatility exceeds 1.5x a 10% annualised target:
`k = clip(0.10 / realised_vol, 0.30, 1.0)`, with the freed weight parked in
BIL. `k <= 1` always -- the account is a cash IRA, so the brake de-risks but
never levers up. Relative proportions inside the risk book are preserved, and
the optimizer never sees the brake.

"Conditional" matters: plain volatility targeting rescales every bar and can
increase drawdowns, whereas acting only in the high-volatility extreme improves
risk-adjusted return with far less turnover. In practice the brake engages on
roughly 19% of order bars (mean k 0.92), and adjustment rows are tagged
`REBAL vt0.62` so you can see when and how hard it applied.

Evidence (project CSVs, phase-averaged over the 5 rebalance phases, QQQ sleeve
at 0.75, in-sample 2006-01..2026-05):

| variant | Sharpe | CAGR | MaxDD |
|---|---|---|---|
| v3.9.2 | 0.9339 | 12.42% | 19.90% |
| v5.0 | 1.0095 | 11.99% | 17.13% |

5/5 paired wins, paired sd 0.026; all four sub-periods improve; OOS
2000-10..2005-12 agrees. A ramped (smoothed) threshold was tested and is worse
at every width -- the discontinuity is load-bearing, not an oversight.

Constants: `VT_TARGET / VT_WIN / VT_HI / VT_FLOOR` in `app/strategy.py`.
The rate-tied objective is always on; `SIGD_CMAX = 0.0` reverts to plain
Sortino if it is ever needed for comparison.
Pass `vol_target=False` to `run_backtest` to reproduce v3.9.2 behaviour.

## v5.1 -- composition bands

Bands first appeared in v5.0 overlaid on the equity curve, which was too busy
to read. v5.1 restores the equity chart's original shading and gives the
composition its own chart.

The equity chart keeps its original two-tone gain/loss shading. Per-leg
composition lives in its own chart directly above the adjustment log, because
ten bands layered under three benchmark lines was unreadable.

* One band per leg, sized by that leg's weight at each bar. The strategy's own
  curve is the envelope; no SPY/QQQ benchmarks, which is the clutter the
  separate chart exists to avoid.
* The SLEEVE leg (QQQ, QLD or TQQQ depending on the kind) is drawn in a bright
  lime highlighter rather than a palette slot, in both the bands and the pie,
  since it is the part of the book the strategy is actually deciding about.
* Band order comes from the payload's own `legs`, sorted. It used to be
  `LEG_ORDER.filter(...)`, which silently dropped any leg missing from that
  list -- which is how TQQQ disappeared from the chart while still being in
  the book. Unknown symbols also get a stable colour slot rather than grey.
* Bands are SOLID and identical to the pie slice for the same symbol -- both
  index `LEG_ORDER` in `static/strategy.js`. Adjacent bands are separated by a
  hairline in the card colour, the same way the pie separates its slices.
* Bands read alphabetically top to bottom (BIL top, XLE bottom). They are
  stacked from the CURVE DOWNWARD, which makes trace insertion order
  alphabetical as well -- so the legend is alphabetical without depending on
  `legendrank`.
* Hovering gives one tooltip listing the whole book at that bar. It is drawn by
  a single invisible trace: per-band hovertemplates under "x unified" would
  stack ten rows.
* The chart carries its OWN period controls (`.awb-quick`, `#awb-from`,
  `#awb-to`), independent of the equity chart's, so you can scrub allocation
  history without moving the period the stats table reads from. Both open on
  the same default (5y). The classes are deliberately distinct: `.aw-quick` is
  selected globally and reusing it would drive both charts at once.
* Clicking a row in the adjustment log marks that date with a dotted vertical
  line; clicking it again clears it. If the date lies outside the chart's
  window, the window slides to centre it while KEEPING the current zoom width;
  y is never pinned, so it rescales to what is visible.
* Both charts set `hoverlabel` explicitly (card background, hairline border,
  ink text) rather than relying on Plotly's defaults, which differ by mode:
  `x` paints the label from the TRACE colour (`color0 = d.bgcolor || dColor`
  in `fx/hover.js`), while `x unified` composites from the plot background.
  That mismatch is why the composition tooltip came out green-tinted.
* Hover rows carry a filled square in the leg's colour. Plotly's SVG text
  renderer supports `<span style="...">` (see `TAG_STYLES` / `STYLEMATCH` in
  `svg_text_utils`), so the colour key lives inside the single tooltip rather
  than needing ten stacked "x unified" rows.
* Chinese date ticks are formatted explicitly via `tickformatstops`
  (`ZH_DATE_STOPS`). Plotly composes automatic date ticks as month + year, and
  the zh-CN locale's `shortMonths` are single characters, so a month-scale tick
  came out as "\u4e5d 2025"; the stops render 2025\u5e749\u6708 instead. `%-m` is
  d3-time-format's no-pad modifier. English keeps Plotly's defaults.
* Axis labels follow the language toggle. `static/plotly-locale-zh-cn.js` is
  vendored from the plotly.js 3.1.0 package (not the CDN, so it cannot drift
  from the pinned build); it self-registers, and `plotInto` picks it via
  `config.locale` at draw time, so re-rendering after a language switch is all
  that is needed.
* Both charts' period buttons share one style rule (`.aw-quick, .awb-quick`)
  while keeping separate classes for behaviour -- `.aw-quick` is selected
  globally by the equity chart's handler.
* Hover shows the full YYYY-MM-DD. Both charts set `xaxis.hoverformat` to
  `%Y-%m-%d`; the composition chart additionally passes the date through
  `customdata` so its single tooltip is built from the raw string. The axis
  default ("Jan 2026") is both coarser than the data and untranslated --
  Plotly's month names need a separate locale bundle, so ISO avoids the
  localisation problem entirely.
* Rows where the volatility brake engaged carry an `x0.62` chip. The brake
  factor is its own `vt` field on each adjustment -- folding it into `tag`
  broke the log's exact-match label logic.
* Weights ship step-encoded as `variants[frac].book` -- `[rowIndex, w0..wN]` in
  per-mille, emitted only on change -- since `held_hist` is a step function and
  a dense matrix would be ~99% repeated rows. ~83 KB instead of ~350 KB. Leg
  order is in the payload's `legs`.
* `PAYLOAD_VERSION` is 4. An older cached payload has no `book`; the chart
  renders empty rather than breaking, and the stale banner tells you to rebuild.


## v5.2 -- rate-tied Sortino constant + context shading

### Rate-tied Sortino constant

The Sortino denominator carries an additive constant that scales with how far
the 10-year yield sits below 4%:

    c_t = SIGD_CMAX * clip((SIGD_RATE_REF - y_t) / SIGD_RATE_REF, 0, 1)

with `y_t` the 504-day average of DGS10. Rationale: a bond's forward expected
return is roughly its starting yield, so trailing Sortino over-credits bonds
near the zero bound with capital gains that cannot repeat. `mu / (sigD + c)`
interpolates between risk-adjusted and absolute return, and dilutes a small
sigD far more than a large one.

Smoothing and the choice of the LONG yield both matter: measured on bills, or
unsmoothed, the penalty spikes during a flight to quality and strips ballast
mid-crash. As configured the 2008 multiplier is ~0.04.

Effect (project CSVs, phase-averaged, sleeve 0.75, vs plain Sortino):

v5.3 runs `SIGD_SMOOTH = 252`, the strongest of the seven dose-matched
variants tested:

| window | CAGR | Sharpe | MaxDD |
|---|---|---|---|
| 2008-2019 | 6.41% -> 7.82% | 0.630 -> 0.711 | 15.72% -> 16.60% |
| full 2006-2026 | 12.31% -> 13.19% | 1.032 -> 1.061 | 17.08% -> 17.57% |

v5.2 shipped `SIGD_SMOOTH = 504`, which gives 7.28% / 12.80% and a slightly
lower drawdown. Switching between them is one constant.

Caveat on the stronger setting: 252 is the variant that was TUNED, so its edge
carries more fitting risk than the sweep's other six. Full-sample Sharpe across
all seven ranged +0.029 down to -0.017 against a noise floor of 0.013, and only
this one sat clearly above it. The 2008-2019 CAGR gain is robust in a way the
Sharpe gain is not -- all seven variants improved that window.

**Caveat, deliberately loud:** ZIRP occurs once in the sample. Every bit of
this evidence comes from one regime, and the 2000-2005 OOS window cannot test
it -- yields were 4-6% there, leaving the term inactive. Set `SIGD_CMAX = 0.0`
to disable. Note `SIGD_CMAX` is a FRACTION: 0.151 is 15.1% annualised.

Data: `DGS10` via `fetch_long_yield()`, same FRED route as VIXCLS, fetched once
per update run. If FRED is unreachable the function returns None and the
backtest falls back to plain Sortino rather than failing. The macro pipeline
already downloaded DGS10 and DGS3MO twice daily; v5.2 also persists the raw
`t3m`, which previously survived only inside the `SOFR_t3m` spread.

### Context shading

Both charts shade NBER recessions and >=20% SPY drawdowns in light grey,
drawn with `layer:"below"` so they never obscure a curve. Drawdown spans are
computed from SPY peak-to-TROUGH (not to recovery -- 2007 did not recover
until 2012, and shading that would tint most of the chart), so future bear
markets appear with no code change. Recessions are NBER-dated and listed in `strategy_service.py`, alongside an
`EVENTS` list for named episodes that fall UNDER the 20% detector threshold:
Liberation Day (2025-04-02..04-08, tariffs announced 04-02, S&P -12% over four
sessions, trough 04-08) and the Iran war (2026-02-27..03-30, joint US-Israeli
strikes 02-28, Hormuz closed 03-04, SPY trough 03-30 at -8.9% from its 01-27
peak). Both fall under the 20% threshold, which is why the automatic detector
never sees them. The two sets overlap, so spans are merged into a
non-overlapping union before drawing; otherwise the tint would double where a
recession sits inside a bear market. Bands are then clipped to each chart's
own visible window -- shapes drawn with `xref:"x"` take part in the axis
autorange, so an out-of-period band would drag the chart back to cover it.
Each band carries a label ("GFC", "COVID", "2022 bear") drawn just inside the
top of the plot; overlapping spans union their labels, so the GFC's recession
and drawdown records produce one band with one name. Named crises are
translated via `crisis.*` i18n keys, and anything unnamed falls through to the
server's generic "<year> bear".

`PAYLOAD_VERSION` is 5.

### Kinds

| kind | sleeve | tab |
|---|---|---|
| `base` | QQQ | All Weather Strategy |
| `leverage` | QLD (2x) | All Weather Leverage Strategy |
| `leverage3x` | TQQQ (3x) | All Weather More Leverage Strategy |

### Sizing the brake target

`VT_TARGET` is now per-kind (`"vt_target"` in `KINDS`). The target must match
the risk the book is MEANT to run, not be a constant:

| kind | vt_target | why |
|---|---|---|
| base, leverage | 0.10 | book runs 15-20% vol; 10% engages meaningfully |
| leverage3x | 0.20 | TQQQ runs far above 10%, which pins the brake on |

The target is a per-(kind, sleeve_frac) TABLE (`vt_table` in `KINDS`), not a
formula:

| kind | 0% | 20% | 40% | 60% | 80% | 100% |
|---|---|---|---|---|---|---|
| base (QQQ 1x) | 10 | 10 | 10 | 10 | 10 | 10 |
| leverage (QLD 2x) | 10 | 10 | 10 | 12 | 18 | 18 |
| leverage3x (TQQQ 3x) | 10 | 10 | 15 | 20 | 25 | 35 |

Chosen by sweeping every (kind, frac, target) cell -- 16 targets x 6 fractions
x 3 kinds, phase-averaged -- and taking the monotone, round-valued table that
maximises total UPI subject to MaxDD not exceeding the no-brake baseline.
18/18 cells came out at least as good as the previous linear rule, mean UPI
+0.046.

Two things that pass went wrong first, and are worth not repeating:

* **Sharpe is the wrong objective.** It is maximised by pinning the brake at
  its 0.30 floor -- 70% cash forever -- which costs 3-11pp of CAGR. UPI
  (CAGR/Ulcer) penalises over- AND under-braking.
* **The linear rule had the wrong shape.** It applied the same `frac/0.60`
  scaling to every kind, but book volatility rises with the fraction only as
  fast as the sleeve is levered:

  | no-brake book vol | 0% | 20% | 40% | 60% | 80% | 100% |
  |---|---|---|---|---|---|---|
  | base | 11.9% | 12.1% | 12.4% | 12.9% | 13.5% | 14.2% |
  | leverage | 11.9% | 12.9% | 14.6% | 16.7% | 19.0% | 21.4% |
  | leverage3x | 11.9% | 14.0% | 17.2% | 21.0% | 24.8% | 28.5% |

  A 1x sleeve barely moves it, so the base kind's target should stay flat; the
  old rule loosened it to 17% at frac 1.00, which just switched the brake off.

The values are deliberately COARSE. Adjacent grid targets differ by ~0.05 UPI
(p90 0.23), the same size as the gains, so finer per-cell tuning would be
fitting noise. `scaled_vt_target()` remains as the fallback for a fraction
absent from a table.

### FRED access

`app/fred.py` is the single entry point for FRED, shared by the macro pipeline
and the strategy service (which previously had separate, unequal retry logic).

Set `MW_FRED_API_KEY` (or `FRED_API_KEY`) in `.env` to use the official
api.stlouisfed.org endpoint. Without a key it falls back to
`pandas_datareader`, which fetches `fredgraph.csv` -- unauthenticated,
throttled per IP, and the cause of the read timeouts seen on long runs: a full
update pulls ~35 series back to back, exactly the burst that endpoint refuses.
A free key is available at https://fredaccount.stlouisfed.org/apikey

Either transport retries with a 5/20/60s backoff and then raises; callers
decide whether that is fatal. The macro pipeline records the failure and
continues with an empty frame; the strategy service falls back to Yahoo ^VIX
for VIX, and for DGS10 disables the rate-tied Sortino term and says so in the
payload.

### Update robustness

`get_daily_data_from_fred()` retries with a widening backoff (5s, 20s, 60s;
four attempts total). A run pulls ~35 FRED series back to back and FRED
throttles bursts, so pandas_datareader's own short retry could give up and
abort the whole update on one slow response. The strategy's own
`fetch_long_yield()` already degraded gracefully; the macro pipeline did not.

Individual series are also allowed to fail. After the retries are exhausted a
series is recorded in `DOWNLOAD_FAILURES`, returned as an EMPTY frame, and the
run continues; derived series use an inner merge so they come out empty rather
than raising. The names land in `meta.json` under `failures` and the header
shows an orange "partial data (n)" badge listing them on hover, so a partial
update is visible instead of silently stale. Both the FRED and Yahoo helpers
behave this way.

Note this trades a loud failure for a quiet one: the update now SUCCEEDS with
gaps. The badge is the only signal, so it should not be ignored.

If an update still fails partway, `python -m app.update --rebuild-only`
rebuilds the figures from the cached pickle without re-downloading. A
rebuild-only run keeps the previous run's `failures`, since the data is still
partial.


## Vol-brake toggle

Each strategy panel carries a `vol brake` checkbox beside the sleeve-fraction
picker. Unchecked it reads a second precomputed set of variants built with the
brake off.

The brake is PATH-DEPENDENT -- it reads the strategy's own trailing realised
volatility -- so unlike a sleeve fraction its alternative cannot be derived in
the browser; it has to be backtested. Cost: 2 sets x 6 fractions x 3 kinds =
**36 backtests per update**. `MW_STRATEGY_VT_AB=0` skips the second set and
hides the checkbox, halving that.

Because the payload roughly quadrupled when the second set arrived,
`GZipMiddleware` was added -- this JSON compresses about 5x and nothing was
compressed before.

## v6.1.1 -- leverage consolidation

A book holding `D` of an L-times fund alongside `(L-1)*D` of cash carries
exactly the same `L*D` of QQQ exposure as `L*D` of plain QQQ, so the swap is
free of any exposure change:

    D = min(w_sleeve, w_cash / (L - 1))
    sleeve -= D;  QQQ += L*D;  cash -= (L-1)*D        weights still sum to 1

What it removes is daily-reset volatility decay on that slice plus the expense
gap (QLD 0.95% / TQQQ 0.86% against QQQ 0.20%); what it costs is the BIL yield
on the cash spent. Measured at a 60% sleeve, phase-averaged, 8/8 window-kind
cells improved on CAGR, Sharpe and MaxDD together:

| | 5y | 10y | 15y | max |
|---|---|---|---|---|
| QLD CAGR | +0.10pp | +0.12pp | +0.08pp | +0.06pp |
| QLD MaxDD | -0.02pp | -0.10pp | -0.10pp | -0.06pp |
| TQQQ CAGR | +0.09pp | +0.11pp | +0.07pp | +0.05pp |
| TQQQ MaxDD | -0.01pp | -0.41pp | -0.41pp | -0.41pp |

The gains are small because CASH is the binding constraint: only ~23% of a QLD
sleeve and ~8% of a TQQQ one can be converted. A 3x fund needs two units of
cash per unit converted against one for a 2x, which is why the 3x tab
consolidates less despite having more decay to remove.

Runs AFTER the volatility brake on purpose: the brake parks weight in cash and
this step is exposure-neutral, so the brake's risk reduction survives and the
freed cash is used to de-lever rather than sitting idle. Adjustment rows carry a `cons` field (share of the sleeve converted), and
rows where the swap changed the printed book show it on both sides:

    2007-04-24  to QLD   SPY=4.9% EFA=8.0% IEF=26.2% BIL=0.6% QLD=60.0%
                      ->  SPY=4.9% QQQ=1.2% EFA=8.0% IEF=26.2% QLD=59.4%

The pair is emitted only when the two books differ AT DISPLAY PRECISION,
which the log renders to one decimal; a swap of a few basis points would
otherwise render an identical pair. `_log_shape()` in `strategy.py` must
track the renderer's precision, so change both together.

ALWAYS ON, with no toggle. A rate-scaled variant was built and tested first --
the swap gives up cash yield, so in principle it is worth less when cash pays
well, and the break-even is `sigma > sqrt(2r/L)`, satisfied on 100% of days in
the ZIRP years but only 26-56% in 2024-2026. Measurement did not support it:
the ordering was `always-on > rate-scaled > off` in all six window/kind cells,
and a binary gate on the same condition changed nothing measurable. Since the
step is exposure-neutral and never lost in testing, it is simply part of the
strategy.

The base kind's sleeve already IS QQQ, so consolidation is a no-op there.

## v6.1.2 -- fixed monthly investment (dollar-cost averaging)

A checkbox above the equity chart switches the comparison from a lump sum at
the start of the period to an equal contribution on the first trading day of
every month. It changes only HOW THE MONEY ARRIVES -- allocation, rebalancing,
the sleeve and the brake are all untouched.

Entirely client-side. The strategy's returns are a property of the strategy,
not of the funding schedule, so the DCA path is re-simulated in the browser
from the series already in the payload: no extra backtests, no payload change,
no rebuild.

The plotted series becomes VALUE / CONTRIBUTED, so it still starts at zero and
reads as profit per dollar invested. With a single contribution it reduces
exactly to the existing curve (verified: max error 1.4e-14), which is what
keeps the unchecked view identical.

**Which metrics change, and why not all of them.**

*Return and CAGR* become money-weighted. CAGR is the internal rate of return,
solved by bisection on the contribution schedule -- verified exact, recovering
10.000% from a constant 10%/yr path.

*Volatility, Sharpe and Sortino are mathematically IDENTICAL* and are left
alone. The account evolves `V_t = V_{t-1}*(1+r_t) + c_t`, so its own return
with the contribution stripped out is `(V_t - c_t)/V_{t-1} - 1 == r_t`
exactly (verified to 1.6e-16). They describe the strategy, and the funding
schedule cannot alter it. This is a fact, not a display convention.

*MaxDD and Ulcer ARE different* and are recomputed on the ACCOUNT BALANCE.
Expect them to look small -- on a -50%-then-recovery path, lump-sum MaxDD 50.0%
against account MaxDD 2.9%. That is arithmetically right: early in the period
little has been invested, so monthly deposits outrun the losses and the balance
barely dips. It measures the ACCOUNT, not the strategy, and the tooltip says
so. Uncheck the box to see the strategy's own drawdown.

Behaviour is the textbook one, which is the point of offering the comparison:

| path | lump sum | monthly |
|---|---|---|
| steady +10%/yr | +61.0% | +28.6% |
| -50% then full recovery | -0.1% | **+38.5%** |
| +80% then back | +0.1% | -26.4% |

## Portfolio Balancer download

`static/downloads/PortfolioBalancerDesktop.zip` is served by the existing
`/static` mount and linked from under the title on every strategy tab.
`__pycache__` was stripped before bundling (139 KB -> 88 KB). The archive was
scanned for credentials before being added -- it contains none, and no `.env`
-- which matters because this host is internet-facing. Re-check that before
replacing it with a newer build.

## v6.1.4 -- All Weather Fixed (static allocations A & B)

A new tab, placed BEFORE the dynamic All-Weather strategies, for accounts you
rebalance about once a YEAR rather than once a day -- a 401(k), an IRA, or a
"Trump account". It holds two fixed, buy-and-hold books, stacked A over B:

  * **Fixed A -- Golden Butterfly**: 20% each VTI, IJS, TLT, SHY, GLD.
  * **Fixed B -- Equity-tilted All-Weather**: 40% VTI, 15% IJS, 20% TLT,
    10% IEF, 10% GLD, 5% DBC (~55% equity).

Each section carries the same features as the dynamic tab -- equity curve vs
SPY/QQQ, the statistics ledger (CAGR, vol, Sharpe/Sortino, Ulcer, UPI, MaxDD),
the monthly-returns heat map, the allocation donut + holdings table sized to an
invested amount, the CSV export, the period slider/quick-buttons, the log-scale
and fixed-monthly-investment toggles -- but for a STATIC book.

A **Rebalance schedule** dropdown (evaluation-only) switches the backtested curve
between None (buy & hold), Annually (Jan 1), Semi-annually (Jan/Jul) and
Quarterly (Jan/Apr/Jul/Oct). All four curves are precomputed per section and
shipped in the payload, so the dropdown switches instantly with no re-fetch. It
changes only the curve, its statistics and the monthly heat map -- never the
target allocation or the CSV export, which are always the current book.

Backtest: fixed weights held in shares so the book drifts between rebalances,
snapped back to target on the first trading bar of each calendar year (annual
rebalance). Each portfolio uses its OWN calendar -- the intersection of only the
funds it holds plus the benchmarks -- so Fixed A (gold-bound, ~2004) is not
truncated to Fixed B's start (DBC-bound, ~2006). Long-history proxies are used
where a modern fund is too young: IJS (2000) for small-cap value rather than
AVUV (2019), DBC (2006) for commodities. The UI names the tradeable
alternatives (AVUV/VBR, GLDM, SCHP).

Implementation mirrors the dynamic tab: `app/fixed_service.py` builds and caches
`data/strategy_fixed.json` in the same daily job (isolated in its own
try/except so it cannot take down the optimizer backtest, or vice versa);
`GET /api/strategy/fixed` and `GET /api/strategy/fixed/allocations.csv` serve
it; `static/fixed.js` renders the two sections into `#fx-root`, reusing the pure
helpers from `strategy.js`. Not investment advice.

**Refinements.** The fixed tab dropped the fixed-monthly-investment (DCA) toggle
-- money-weighted returns on a static book read as confusing rather than
informative. Its period quick-buttons (1y/3y/5y/...) now share the dynamic tab's
button styling, including the highlighted current selection. And a quiet
one-line caveat -- "For simplicity, backtests do not account for tax, trading
cost, or slippage." -- now sits under the header of each strategy panel and in
the footer of every tab (translated).

## v6.1.5 -- graceful shutdown fix

Ctrl-C could hang after an auto-update had fired, forcing a hard kill. Cause:
the scheduled update ran on asyncio's default executor, whose worker threads are
non-daemon and get joined by the interpreter's atexit hook -- so the process
could not exit until an in-flight download finished. The update now runs on a
DAEMON thread (`mw-update`) awaited through a future: on Ctrl-C the awaiting task
is cancelled and the thread is abandoned with the process, so shutdown is
immediate. Overlap is still prevented -- a trigger that fires while an update is
running is skipped rather than queued -- and the scheduler is stopped with
`wait=False` on shutdown.

## v6.2.0 -- reproducible across machines, one launcher, self-contained updates

The same code on the same data produced different numbers on Linux and on
Windows. The cause was not the operating system: numpy's `@` dispatches to an
OpenBLAS matmul kernel selected at runtime from the detected CPU, different
kernels sum in a different order, and the optimizer's argmax over five
restarts turns that 1e-15 difference into a different local optimum.
Reproduced on a single machine by changing only `OPENBLAS_CORETYPE`: final
equity 1,564,873.7356 vs 1,565,333.7623.

Fixed by pinning what was previously left to chance -- dependency versions
exactly, the BLAS kernel, and numpy's SIMD dispatch (`app/determinism.py`,
imported before numpy everywhere) -- and by making the claim checkable rather
than asserted: `python run.py selftest` runs the engine over a seeded
synthetic market that provably exercises the Hurst gate, the brake and the
weight cap, and prints a hash to compare between machines.

Four smaller determinism bugs went with it. `date.today()` fed FRED's
observation_end, so a UTC server and a US-Pacific desktop requested different
data. `yf.download(threads=True)` could drop one bar from the shared
calendar, and since the rebalance cadence counts bars rather than dates, one
dropped bar re-phases every rebalance for nineteen years. `.env` was read
without an explicit encoding. And the Sortino constant was passed through a
module global rather than an argument, which was safe only while the 36
backtests happened to run serially.

Everything else in the release follows from wanting one behaviour on both
systems: a single `run.py` replacing the .bat/.sh pair, a visible `config.ini`
replacing the hidden `.env`, and a twice-daily update that runs inside the
server -- with a startup catch-up for the case a schedule cannot cover -- so
no cron job or Task Scheduler entry is needed at all.

Also fixed: the ten-year baseline in the inflation figure crashed on 29
February (next occurrence 2028) by rebuilding the date rather than offsetting
it.

## v6.2.1 -- corrected the cause, no behaviour change

v6.2.0 shipped the right fix with the wrong explanation. It attributed the
cross-machine divergence to the path-dependent volatility brake. Ablation
says otherwise: disabling the brake entirely leaves the divergence unchanged
(4.62e-04 vs 4.97e-04), while dropping the optimizer to a single restart
collapses it to 6.03e-08. The amplifier is `if cur_obj > best_obj` choosing
among five local optima, not the brake's threshold.

Tested at the same time, and the reason the question came up: making the
sleeve a continuous 0-100% ramp instead of an on/off gate does NOT reduce the
numerical sensitivity (5.77e-04, no better than production), because a choice
between distinct local optima is not a threshold that smoothing can remove.
On the 1x sleeve it also costs performance -- CAGR 13.26 -> 12.00, Sharpe
1.072 -> 0.988, MaxDD 15.14% -> 19.38% -- consistent with the earlier ramp
study, which found the same and recommended the binary gate for 1x.

Documentation only. `app/determinism.py`, the README and the version string
changed; no executable line did, and `run.py selftest` returns the same hash.

## v6.2.2 -- optimizer tie-break, config file is authoritative

**Optimizer stability tie-break.** `optimize_weights` kept the best of its
five restarts with `if cur_obj > best_obj`. Near-ties are common (restart 0
anchors on the previous weights), and a near-tie between local optima selects
a materially different weight vector -- so that one comparison was resolving
real allocation decisions on whichever last bit the CPU produced. A restart
now wins outright only by a relative margin (`RESTART_TIE_REL`, 1e-6); inside
it, candidates are ranked by closeness to the book already held, then by
SPY+QQQ weight. Cross-machine divergence 4.97e-04 -> 6.42e-05, an 8x
improvement, for +0.01 pp CAGR and +0.001 Sharpe -- i.e. free.

Two things it does not do. It does not reduce turnover: adjustment counts and
turnover are unchanged, because genuine near-ties at 1e-6 are rarer than that
would need. And the margin must stay narrow -- at 1e-4 divergence is 1.72e-03,
3.5x WORSE than production, because "inside the margin" is itself a threshold
on a noisy quantity. Inside this app the tie-break is redundant anyway
(dispatch pinning already gives exact reproducibility); it earns its place in
the QuantConnect and Zorro ports, where BLAS cannot be pinned.

**Not shipped: a continuous volatility brake.** The 33% jump in gross exposure
at the trigger is real, and removing it buys nothing material. Tested as four
shapes across three sleeves and three rebalance phases: at a matched risk
target continuity does help (+0.018 to +0.033 Sharpe, 1.1-2.6 pp better
drawdown on 3/3 sleeves), but against production the best continuous form is
worth +0.004 Sharpe on base and -0.007 on TQQQ with 1/5 CAGR and 2/5 Sharpe
sub-period consistency. See `research/Brake_shape_and_optimizer_stability.md`.

**config.ini is now authoritative.** It beats environment variables rather
than the other way round, so the key you paste into the file is the key that
gets used. Also fixed: the file is read as `utf-8-sig`, because Windows
Notepad writes a UTF-8 BOM and reading that as plain utf-8 made configparser
fail with MissingSectionHeaderError -- silently reverting EVERY setting,
including the FRED key, to its default.

**run_server.bat** now probes for an interpreter (`py -3`, then `python`,
then `python3`) instead of assuming `python` resolves. On Windows it can be
absent from PATH, or be the Microsoft Store stub that opens the Store instead
of running anything.

## v6.2.3 -- fixes a startup crash on Python 3.12+

`pandas-datareader==0.10.0` does `from distutils.version import LooseVersion`
at module scope. distutils was REMOVED from the standard library in Python
3.12, so that pin installs cleanly and then fails to import -- taking the
whole server down at startup on any 3.12+ interpreter, including a stock
Anaconda base:

    ModuleNotFoundError: No module named 'distutils'

Three changes, because one was not enough.

**The pin is now per interpreter.** 0.11.1 has no distutils reference but is
published only for Python 3.11+, so pinning it alone would have dropped
Ubuntu 22.04's stock 3.10. Environment markers select 0.11.1 on 3.11+ and
0.10.0 below. This is the only dependency allowed to vary, and it is safe to:
it is used solely for the un-keyed FRED fallback and touches no strategy
arithmetic. numpy and pandas stay exactly pinned.

**`data_pipeline.py` no longer imports it at top level.** It imported
pandas_datareader and never used it, which turned an optional fallback
dependency into a hard requirement for starting the server at all. The real
use in `fred.py` is a lazy import inside the fallback function.

**`run.py` now verifies the app IMPORTS after installing**, not just that the
versions resolve. Resolving a wheel and being able to import it are different
things, and that difference is the whole bug. A failure is now one sentence
at setup time instead of a traceback at server start.

Verified by installing and importing the full app on CPython 3.10, 3.11, 3.12
and 3.13, and by confirming `run.py selftest` returns the SAME hash on all
four -- `b625b7d8ed15b3042e9763d9a97eb9e3c7ac42053a421212fe635c12d417fd70`.
The two machines therefore do not need matching Python versions, only the
pinned numpy and pandas.

## v6.2.4 -- FRED API key shipped in config.ini

`config.ini` now carries the account's FRED key, so a fresh extract is already
configured: no environment variable, no shell profile, nothing to paste,
identical on Windows and Linux. Confirm with `python run.py doctor`, which
should show `MW_FRED_API_KEY  set  <- config.ini`.

With a key the app uses FRED's authenticated JSON API. Without one it falls
back to scraping fredgraph.csv, which is throttled per IP and is the usual
cause of a read timeout partway through a long update.

No code changed in this version.

## v6.2.5 -- install failures now say what is actually wrong

On Linux, `pip` fell back to numpy's SOURCE tarball and died twenty lines
deep in meson with `ERROR: Unknown compiler(s): [['cc'], ['gcc'], ...]`. That
message is about a missing C compiler, which is not the problem. The problem
is that no prebuilt wheel matched the interpreter, so pip tried to build one.

Two causes produce that, and this release handles both.

**pip too old to read the wheel tags.** A pip that predates PEP 600 does not
recognise `manylinux_2_17_...`, concludes no wheel matches, and reaches for
the sdist. Ubuntu's `python3-venv` can seed exactly such a pip. The launcher
now upgrades pip *only* when it is below 23.1, verifies it afterwards, and
rebuilds the venv if the upgrade breaks it -- pip replacing itself mid-run is
what corrupted an install here once, so it is still never done routinely.

**No wheel published for that Python version.** The first install pass now
runs with `--only-binary=:all:`, so pip refuses to build from source and says
plainly which versions DO exist. A second unrestricted pass follows, because
a pure-python dependency shipping only an sdist is legitimate and needs no
compiler; if that fails too, the readable error from the first pass is what
gets reported, together with the Python version, the pip version and the
platform. The failure now looks like:

    ERROR: Could not find a version that satisfies the requirement
      numpy==X.Y.Z (from versions: ...)
    Python 3.12.3   pip 24.0   platform linux-x86_64

If the pinned numpy has no wheel for your Python, change the pin on **both**
machines and re-run `python run.py selftest` on each -- numpy and pandas must
be identical across machines or the numbers diverge. Pins verified against
CPython 3.10-3.13.

## v6.2.6 -- supports Python 3.14

The Linux box runs Python 3.14.4. numpy 2.2.6 publishes no cp314 wheel, so
pip fell back to the source tarball and died looking for a C compiler; the
v6.2.5 diagnostics identified it in one run.

Pins moved to the first versions that cover 3.14: **numpy 2.3.5** (was
2.2.6), **pandas 2.3.3** (was 2.3.2) and **lxml 6.0.4** (6.0.0 has no cp314
wheel either). The whole dependency tree, transitively, now resolves as
wheels on CPython **3.11, 3.12, 3.13 and 3.14**, on manylinux x86-64 and
Windows amd64 -- checked with a pip new enough to know cp314 tags, which is
what the earlier check was missing.

**The minimum Python is now 3.11**, up from 3.10: numpy 2.3.x requires it,
and numpy 2.3 is the first line shipping cp314 wheels. Both machines are
above that.

**The selftest hash did not move.** It is still

    b625b7d8ed15b3042e9763d9a97eb9e3c7ac42053a421212fe635c12d417fd70

verified on CPython 3.11, 3.12 and 3.13 under the new numpy and pandas. The
dispatch pinning from v6.2.0 is doing its job: the arithmetic survived a
numpy minor bump and a pandas patch bump unchanged. On real data the whole
change is worth -0.004 pp of CAGR with identical adjustment counts and an
identical live allocation.

**Both machines need this version.** numpy and pandas must match across
machines; delete `.venv` on each and re-run, then compare selftest hashes.

## v6.2.7 -- reachable over IPv6

Browsing to the Linux box over IPv6 gave `ERR_CONNECTION_REFUSED`. Two causes,
both now handled.

**`0.0.0.0` is IPv4-only.** A socket bound there does not accept IPv6
connections at all -- the kernel answers with a RST, which the browser reports
as "refused", indistinguishable from nothing listening. The default is now
`host = auto`: bind `::` when the machine has usable IPv6 (dual-stack, so IPv4
clients still work), and fall back to `0.0.0.0` when it does not. The fallback
is not cosmetic -- on a host with IPv6 disabled, binding `::` fails and the
server would not start at all.

**The URL needs the port, and an IPv6 address hides that.** The last hextet
looks like one: `http://[2606:...:8280]` is port 80, not 8280. The startup
banner now prints every working URL with the port spelled out, and says so.

`python run.py doctor` shows both the configured value and what it resolves
to, e.g. `MW_HOST  auto -> binds ::`.

## v6.2.8 -- the schedule can be pinned to a timezone

The Linux server "didn't update" while Windows did. It had: at 06:20 **UTC**,
because that box's clock is UTC and `update_hours` was interpreted in the
machine's own local time. The browser rendered the stamp in the viewer's zone,
so it read as 01:20 AM CDT -- five hours from the desktop's 06:20 AM. Same
rule, different clocks, nothing broken.

**New setting `update_timezone`.** Leave it empty for the old behaviour
(machine local). Name an IANA zone -- `America/Chicago` -- and both machines
fire at the same real moment whatever their host clocks say. An unusable name
warns and falls back to local rather than stopping the server. Verified by
scheduling a run in `America/Chicago` on a host whose clock is UTC and
watching it fire five hours off the host's wall time.

**Bug fixed: the NEXT UPDATE stamp was 20 minutes early**, on every machine
since `update_minute` was added. The browser-side calculation built the next
slot with `Date.UTC(..., h, 0, 0, 0)` -- minute hardcoded to zero -- while the
schedule actually runs at `:20`. The minute is now passed to the page and used.

The startup banner and `run.py doctor` both name the zone the schedule is
anchored to, so "why did it run then" is answerable without arithmetic.

## v6.2.9 -- 5-year yield chart was three weeks long

`5YrYield` comes from Yahoo's `^FVX` with FRED's `DGS5` as a fallback, but the
fallback only fired on an EXCEPTION. Yahoo returned about fifteen trading days
for an eight-year request -- a success, as far as the code was concerned. The
row-count guard in `get_daily_data_from_yahoo` (`len(df) < 10`) let it through,
because fifteen is more than ten. The chart drew a flat line across 2018-2026
with a spike of real data at the right-hand edge.

The guard now asks the right question: not "how many rows" but "does this
cover the window I asked for". A frame spanning less than half the requested
range is treated as a failed download and FRED is used instead.

Two deliberate limits on the rule:

- **It only applies to the two series that have a FRED equivalent.** Those are
  Treasury yields, so a full history is known to exist and a short answer is
  unambiguously wrong. The commodity and currency futures are exempt: a
  contract can legitimately begin part-way through the window, and there would
  be nothing better to switch to anyway. (The first draft flagged a contract
  starting in 2023 as broken -- caught in testing.)
- **It never trades data for nothing.** FRED is coverage-checked too, so a bad
  FRED day cannot replace a short-but-real Yahoo series with an empty one.

Either way the substitution is logged and added to the header's failure badge,
so a short series is visible rather than silently charted.

## v6.3.0 -- the selftest checks INPUTS before blaming the arithmetic

The closing advice said a differing COMBINED hash meant "compare the
environment line". That points at the wrong suspect when the two machines are
running different versions of the app: the generated fixture depends on the
universe, so a version mismatch changes the INPUT hash too, and the machines
never tested the same thing at all. The environment was innocent.

The summary now numbers the two hashes, marks INPUT as the gate, and gives an
ordered procedure. Note the second branch, which is subtler than "inputs are
fine, so it must be the environment": an engine change moves COMBINED while
leaving INPUT untouched, so the **app version is worth checking first in both
cases**, not just when inputs differ. The app version is printed alongside the
environment for exactly that reason.

The comparison can also be done for you:

    python run.py selftest --expect <combined> --expect-input <input>

Exit codes: **0** match, **1** inputs match but the arithmetic differs,
**2** inputs differ so the comparison is invalid. Passing `--expect` without
`--expect-input` says so, rather than quietly assuming the inputs agreed.
Abbreviated hashes copied from the printed summary compare correctly.

Production deployment (Ubuntu, systemd, Cloudflare Tunnel + Access) is
documented in `docs/Server_runbook.md`: everyday commands, how the server and
tunnel were built, what is still outstanding, how to deploy a new version, and
a troubleshooting table.

One correction it prompted, applied in v6.3.0: `host = ::` is **IPv6-only**,
not dual-stack. A raw Linux `::` socket with `IPV6_V6ONLY` cleared does serve
IPv4 clients, but `asyncio.base_events.create_server` sets that option to True
on every AF_INET6 listener, so uvicorn's `::` bind refuses IPv4 -- exactly the
confusion `auto` was added to prevent, inverted. Verified against the CPython
source. Set `host = 0.0.0.0` when IPv4 clients need to reach the app; on a
`::` bind use `http://[::1]:8000`, not `127.0.0.1`.

## v6.3.1 -- upgrade procedure written into the runbook

`docs/Server_runbook.md` section 6 is now a full upgrade runbook rather than a
sketch: stage the new version beside the live one, do the dependency install
and verification while the old one is still serving, then cut over with a
rename. Downtime is seconds and rollback is the same rename backwards.

It covers what the obvious stop-copy-start approach gets wrong (`config.ini`
is in the zip and gets overwritten; copying over does not delete files removed
in a newer version; nothing installs dependencies), the ownership rule that
decides whether permissions ever need fixing (`mv` and `cp -a` preserve,
`sudo unzip` and `sudo cp -r` create root-owned files), what systemd does and
does not notice about changed application files, and how to close the gap
between a Windows/3.12 dev box and a Linux/3.14 server before any downtime.

Also corrected: the Cloudflare route targets `http://[::]:8000`, not
`[::1]:8000`. Section 5's bind-lockdown item now says both the config and the
route must change together, since a `[::]` route cannot reach an IPv4-only
listener.

Documentation only -- no executable line changed and the selftest hash is
unchanged.
