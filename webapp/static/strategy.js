/* All Weather Strategy tab.
 *
 * The server ships one JSON blob per day: the daily equity curve of the
 * strategy plus SPY and QQQ buy-and-hold, all indexed to 100 at the first
 * bar.  Everything below - slicing to a period, re-basing to 0% at that
 * period's start, and recomputing the statistics - happens in the browser,
 * so dragging the period handles is instant and never hits the server.
 *
 * The statistics use the same conventions as the Python/Zorro side:
 * trading-day sampling, no risk-free rate, equity-to-equity drawdown.
 */

const AW = {
  kind: null,      // "base" | "leverage" -- which cached payload is loaded
  cache: {},       // kind -> payload, so switching tabs is instant
  markDate: null,  // adjustment date marked on the composition chart
  volBrake: true,  // false = read the brake-free variant set
  dca: false,      // true = contribute monthly instead of a lump sum
  b0: 0, b1: 0,    // composition chart's own window, independent of i0/i1
  data: null,      // the cached payload (all sleeve fractions)
  frac: null,      // selected SLEEVE_FRAC key, e.g. "0.50"
  i0: 0, i1: 0,    // selected [begin, end] indices into data.dates
  logScale: false,
};

/* The payload holds one precomputed variant per sleeve fraction. Benchmarks
 * and the calendar are shared, so only the strategy series, its statistics,
 * its allocation and its adjustment log change when the dropdown moves. */
/* Which precomputed set to read. The vol brake is PATH-DEPENDENT -- it reads
 * the strategy's own trailing realised vol -- so unlike a sleeve fraction its
 * alternative cannot be derived in the browser; both are backtested. Falls
 * back to the braked set when the other is absent (older payload, or the kind
 * has no brake, in which case the two would be identical anyway). */
/* The brake changes the BOOK, so its alternative is precomputed rather than
 * derived here. Falls back to the braked set when the other is absent. */
const variantSet = () =>
  (!AW.volBrake && AW.data.variants_nobrake) ? AW.data.variants_nobrake
                                             : AW.data.variants;
const variant = () => variantSet()[AW.frac];

/* Rebuild dense per-bar weights from the step encoding the payload ships.
 * `book` is [[rowIndex, w0..wN] ...] in per-mille, emitted only when the book
 * CHANGED, so we forward-fill between entries. Cached per (kind, frac) since
 * the slider re-renders constantly and this is the only O(bars x legs) work
 * in the panel. */
const _bookCache = {};
function bookMatrix() {
  const key = AW.kind + "|" + AW.frac + "|" + (AW.volBrake ? "b" : "n");
  if (_bookCache[key]) return _bookCache[key];
  const steps = variant().book, legs = AW.data.legs || [];
  const n = AW.data.dates.length;
  if (!steps || !steps.length || !legs.length) return null;
  const out = new Array(n);
  let si = 0, cur = new Array(legs.length).fill(0);
  for (let i = 0; i < n; i++) {
    while (si < steps.length && steps[si][0] === i) {
      cur = steps[si].slice(1).map(v => v / 1000);
      si++;
    }
    out[i] = cur;
  }
  _bookCache[key] = { legs, rows: out };
  return _bookCache[key];
}
/* ---------- fixed monthly investment (dollar-cost averaging) -------------
 * The strategy's RETURNS are unchanged by how the money arrives, so this is a
 * pure client-side re-simulation of the cash-flow schedule -- no rebuild.
 *
 * One unit is contributed on the first bar of each calendar month. The series
 * returned is VALUE / CONTRIBUTED, so it starts at 1.0 and reads as "profit
 * per dollar put in". With a single contribution at t0 it reduces exactly to
 * the existing series/series[0], which is what keeps the unchecked view
 * identical.
 *
 * WHICH METRICS CHANGE
 *   volatility / Sharpe / Sortino  -- identical, and provably so. The
 *     account evolves V_t = V_{t-1}*(1+r_t) + c_t, so its return with the
 *     contribution stripped out is (V_t - c_t)/V_{t-1} - 1 == r_t exactly.
 *     They describe the strategy, which the funding schedule cannot alter.
 *   return / CAGR                  -- money-weighted (see moneyWeightedCAGR).
 *   MaxDD / Ulcer / UPI            -- recomputed on the ACCOUNT BALANCE, which
 *     really is a different path: fresh contributions cushion a fall, so the
 *     balance drops less in percentage terms than the strategy does.
 */
function contributionBars(dates) {
  const out = [0];
  for (let i = 1; i < dates.length; i++) {
    if (dates[i].slice(0, 7) !== dates[i - 1].slice(0, 7)) out.push(i);
  }
  return out;
}

/* Account balance under the contribution schedule: what the brokerage
 * statement would show. Distinct from dcaPath(), which normalises by the
 * amount contributed. */
function dcaAccount(raw, dates) {
  const bars = new Set(contributionBars(dates));
  const out = new Array(raw.length);
  let value = 0;
  for (let i = 0; i < raw.length; i++) {
    if (i > 0) value *= raw[i] / raw[i - 1];
    if (bars.has(i)) value += 1;
    out[i] = value;
  }
  return out;
}

function dcaPath(raw, dates) {
  const bars = new Set(contributionBars(dates));
  const out = new Array(raw.length);
  let value = 0, contributed = 0;
  for (let i = 0; i < raw.length; i++) {
    if (i > 0) value *= raw[i] / raw[i - 1];      // market move
    if (bars.has(i)) { value += 1; contributed += 1; }
    out[i] = value / contributed;
  }
  return out;
}

/* Money-weighted (internal) rate of return: the annual rate at which the
 * contributions would have to compound to reach the final value. Bisection --
 * the future value is strictly increasing in the rate, so it cannot fail. */
function moneyWeightedCAGR(raw, dates) {
  const bars = contributionBars(dates);
  const n = raw.length;
  let value = 0;
  for (const i of bars) value += raw[n - 1] / raw[i];   // FV of each unit
  const fv = value, k = bars.length;
  const ages = bars.map(i => (n - 1 - i) / 252);
  let lo = -0.95, hi = 5.0;
  for (let it = 0; it < 200; it++) {
    const mid = (lo + hi) / 2;
    let acc = 0;
    for (const a of ages) acc += Math.pow(1 + mid, a);
    if (acc < fv) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

const seriesFor = key =>
  key === "strategy" ? variant().series : AW.data.benchmarks[key];

const SERIES = [
  { key: "strategy", label: "All Weather Strategy", i18n: "series.strategy",
    light: "#0e6e4f", dark: "#3fbf8f", width: 3.0, fill: true },
  { key: "SPY", label: "SPY buy & hold", i18n: "series.spy",
    light: "#c2903a", dark: "#e0b158", width: 1.4, fill: false },
  { key: "QQQ", label: "QQQ buy & hold", i18n: "series.qqq",
    light: "#4d6fa8", dark: "#7fa8e6", width: 1.4, fill: false },
];

// 11 entries: one per possible leg (9 ETFs + BIL + QLD). The 11th hue was
// added when the composition bands arrived -- the palette used to be 10.
const PIE_LIGHT = ["#0e6e4f", "#c2903a", "#4d6fa8", "#8c5a7a", "#6a8f3c",
                   "#b0603a", "#4f8f8a", "#7a6aa8", "#93794a", "#5b6472",
                   "#a34248", "#5a7d5a"];
const PIE_DARK  = ["#3fbf8f", "#e0b158", "#7fa8e6", "#c88bae", "#9ec95a",
                   "#e08a63", "#66c2bb", "#a99ae0", "#c4a86a", "#9aa3b0",
                   "#e8848c", "#8fbf8f"];

/* Canonical leg order: ALPHABETICAL, so a symbol always gets the same colour
 * no matter which kind is loaded or how the allocation happens to be sorted.
 * The pie and the composition bands both index this, which is what keeps
 * them in agreement. Bands are drawn with BIL at the top, XLE at the bottom
 * (see stackOrder below). */
const LEG_ORDER = ["BIL", "EEM", "EFA", "GLD", "IEF", "IWM",
                   "QLD", "QQQ", "SPY", "TLT", "TQQQ", "VBR", "XLE"];

/* The sleeve is the point of the strategy, so it gets a highlighter colour
 * rather than a palette slot -- bright lime, which stays legible on both the
 * white and the near-black card. Whichever symbol the sleeve buys (QQQ, QLD or
 * TQQQ) picks this up, in the bands and in the pie alike. */
const SLEEVE_HILITE = () => (isDark() ? "#ccff33" : "#7cb800");
/* Chinese date ticks.
 *
 * Plotly composes its automatic date ticks as month + year, and the zh-CN
 * locale's shortMonths are single characters, so a month-scale tick renders
 * "\u4e5d 2025". These stops override that to 2025\u5e749\u6708.
 *
 * %-m / %-d use d3-time-format's no-pad modifier (verified: "%Y\u5e74%-m\u6708"
 * formats 2025-09-15 as "2025\u5e749\u6708"). dtickrange is in ms.
 * Returning undefined for English leaves Plotly's own defaults alone. */
const DAY_MS = 86400000;
const ZH_DATE_STOPS = [
  { dtickrange: [null, 7 * DAY_MS], value: "%Y\u5e74%-m\u6708%-d\u65e5" },
  { dtickrange: [7 * DAY_MS, 30 * DAY_MS], value: "%-m\u6708%-d\u65e5" },
  { dtickrange: [30 * DAY_MS, 365 * DAY_MS], value: "%Y\u5e74%-m\u6708" },
  { dtickrange: [365 * DAY_MS, null], value: "%Y\u5e74" },
];
/* Context bands: NBER recessions and >=20% SPY drawdowns, drawn BENEATH every
 * trace (layer:"below") so they never obscure a curve.
 *
 * The two sets overlap -- the 2001 recession sits inside the dot-com bear --
 * and stacking two translucent rects would double the tint there. So the
 * spans are merged into a non-overlapping union first, giving one uniform
 * grey wash. */
function contextBands(lo, hi) {
  const sh = AW.data && AW.data.shades;
  if (!sh) return { shapes: [], annotations: [] };
  const spans = []
    .concat(sh.recession || [], sh.drawdown || [], sh.event || [])
    .filter(e => e.from && e.to)
    .map(e => [e.from, e.to, e.label || ""])
    .sort((a, b) => (a[0] < b[0] ? -1 : 1));

  // Merge overlapping spans, unioning their labels. The GFC appears twice --
  // once as an NBER recession, once as a >=20% drawdown -- and two translucent
  // rects would double the tint, so they become one band with one label.
  const merged = [];
  spans.forEach(([a, b, name]) => {
    const last = merged[merged.length - 1];
    if (last && a <= last[1]) {
      if (b > last[1]) last[1] = b;
      if (name) last[2].add(name);
    } else merged.push([a, b, new Set(name ? [name] : [])]);
  });

  // Shapes with xref:"x" take part in the axis autorange, so a band outside
  // the selected period would drag the chart back to cover it: drop those and
  // clamp partial overlaps to the window edges.
  // light mode needed more contrast: 0.055 on a white card was invisible
  const grey = isDark() ? "rgba(255,255,255,0.07)" : "rgba(17,17,17,0.13)";
  const shapes = [], annotations = [];
  merged
    .filter(([a, b]) => !(b < lo || a > hi))
    .forEach(([a, b, names]) => {
      const x0 = a < lo ? lo : a, x1 = b > hi ? hi : b;
      shapes.push({
        type: "rect", xref: "x", yref: "paper",
        x0, x1, y0: 0, y1: 1,
        fillcolor: grey, line: { width: 0 }, layer: "below",
      });
      const raw = [...names].join(" / ");
      if (!raw) return;
      // known crises get a translation; anything else (e.g. "2022 bear")
      // falls through to the server's own wording
      // "2022 bear" is generated server-side for unnamed episodes, so it is
      // composed rather than looked up -- a future "2031 bear" then works
      // with no new key.
      const bear = /^(\d{4}) bear$/.exec(raw);
      const key = "crisis." + raw;
      const text = bear ? bear[1] + t("crisis.bear")
                        : (t(key) === key ? raw : t(key));
      const mid = new Date((Date.parse(x0) + Date.parse(x1)) / 2)
        .toISOString().slice(0, 10);
      annotations.push({
        x: mid, y: 0.99, xref: "x", yref: "paper", text,
        showarrow: false, yanchor: "top",
        font: { size: 10, color: cssVar("--slate") },
      });
    });
  return { shapes, annotations };
}

const dateTickStops = () => currentLang() === "zh" ? ZH_DATE_STOPS : undefined;

const legColor = sym => {
  if (AW.data && sym === AW.data.sleeve_symbol) return SLEEVE_HILITE();
  const i = LEG_ORDER.indexOf(sym);
  const pal = pieColors();
  // unknown symbols fall back to a stable slot rather than a grey blob, so a
  // leg added server-side still gets a distinct colour
  const j = i >= 0 ? i : [...sym].reduce((a, c) => a + c.charCodeAt(0), 0);
  return pal[j % pal.length];
};

/* ---------- theme ----------
 * Chart colours are read from the CSS custom properties at draw time, so the
 * charts follow whatever the stylesheet says the theme is. One source of
 * truth: change a token in style.css and the plots move with it. */
// The strategy series is named for the tab it belongs to, so tab 07's legend
// reads "All Weather Leverage Strategy" rather than borrowing tab 06's name.
/* The strategy row is named per KIND. An earlier startsWith("leverage") test
 * matched leverage3x too, so the 3x tab reused the 2x label. Explicit map,
 * falling back to the series' own key for anything unlisted. */
const STRATEGY_LABEL = {
  base: "series.strategy",
  leverage: "series.strategy_lev",
  leverage3x: "series.strategy_lev3",
};
const seriesLabel = s =>
  (s.key === "strategy" && STRATEGY_LABEL[AW.kind])
    ? t(STRATEGY_LABEL[AW.kind]) : t(s.i18n);

const isDark = () => document.documentElement.dataset.theme === "dark";
const cssVar = n =>
  getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const seriesColor = s => (isDark() ? s.dark : s.light);
const pieColors = () => (isDark() ? PIE_DARK : PIE_LIGHT);

/* Repaint a PRE-RENDERED plotly figure for the current theme. The macro
 * figures are built server-side against a white template, so every surface,
 * axis, legend and subplot annotation has to be overridden by name. */
function themeLayoutPatch(layout) {
  const ink = cssVar("--ink"), grid = cssVar("--grid"),
        axis = cssVar("--axis"), card = cssVar("--card");
  const p = { paper_bgcolor: card, plot_bgcolor: card, "font.color": ink };
  Object.keys(layout || {}).forEach(k => {
    if (/^[xy]axis\d*$/.test(k)) {
      p[k + ".gridcolor"] = grid;
      p[k + ".linecolor"] = axis;
      p[k + ".zerolinecolor"] = grid;
      p[k + ".tickfont.color"] = ink;
      p[k + ".title.font.color"] = ink;
    } else if (/^legend\d*$/.test(k)) {
      p[k + ".bgcolor"] = card;
      p[k + ".bordercolor"] = grid;
      p[k + ".font.color"] = ink;
    }
  });
  (layout.annotations || []).forEach((a, i) => {
    p["annotations[" + i + "].font.color"] = ink;
  });
  return p;
}


/* ---------- trace colours in dark mode ----------
 * The macro figures are rendered server-side against a light palette, and a
 * lot of it vanishes on a dark background: darkblue sits at 1.09:1, black at
 * 1.26, blue at 1.94. relayout() only repaints the chrome, so the traces are
 * lifted here instead.
 *
 * Lightness is raised until the colour clears the threshold, then a slice of
 * the ORIGINAL lightness is added back. That second part matters: a plain
 * lift to a fixed target maps blue and darkblue onto the same value, and the
 * Case-Shiller chart uses both for different cities.
 */
const TRACE_MIN_CONTRAST = 4.5;

let _colorCtx = null;
function _cssToRgb(css) {
  if (typeof css !== "string") return null;
  if (!_colorCtx) _colorCtx = document.createElement("canvas").getContext("2d");
  _colorCtx.fillStyle = "#000";
  _colorCtx.fillStyle = css;                 // normalises names, hex, rgb()
  const v = _colorCtx.fillStyle;
  if (v[0] === "#") return [1, 3, 5].map(i => parseInt(v.substr(i, 2), 16));
  const m = v.match(/[\d.]+/g);
  return m && m.length >= 3 ? [+m[0], +m[1], +m[2]] : null;
}
function _rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2;
  if (mx === mn) return [0, 0, l];
  const d = mx - mn;
  const s = l > 0.5 ? d / (2 - mx - mn) : d / (mx + mn);
  let h;
  if (mx === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
  else if (mx === g) h = ((b - r) / d + 2) / 6;
  else h = ((r - g) / d + 4) / 6;
  return [h, s, l];
}
function _hslToRgb(h, s, l) {
  if (s === 0) { const v = Math.round(l * 255); return [v, v, v]; }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = t => {
    t = (t + 1) % 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [f(h + 1 / 3), f(h), f(h - 1 / 3)].map(v => Math.round(v * 255));
}
function _contrast(a, b) {
  const la = _relLum(a), lb = _relLum(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}
function liftForDark(css) {
  const rgb = _cssToRgb(css);
  if (!rgb) return css;
  const bg = _cssToRgb(cssVar("--card")) || [27, 30, 36];
  if (_contrast(rgb, bg) >= TRACE_MIN_CONTRAST) return css;
  const [h, sat, l] = _rgbToHsl(rgb);
  let lo = l, hi = 1;
  for (let i = 0; i < 24; i++) {
    const m = (lo + hi) / 2;
    if (_contrast(_hslToRgb(h, sat, m), bg) >= TRACE_MIN_CONTRAST) hi = m;
    else lo = m;
  }
  const out = _hslToRgb(h, sat, Math.min(0.86, hi + 0.28 * l));
  return `rgb(${out[0]},${out[1]},${out[2]})`;
}

function applyFigureTheme(div, fig) {
  if (typeof Plotly === "undefined" || !div || !div.data || !fig) return;
  try {
    // Record the untouched colours once. restyle() mutates the cached figure
    // in place, so without this the light palette would be lost on the first
    // switch to dark and never come back.
    if (!fig._origColors) {
      fig._origColors = (fig.data || []).map(t => ({
        line: t.line && typeof t.line.color === "string" ? t.line.color : null,
        marker: t.marker && typeof t.marker.color === "string" ? t.marker.color : null,
      }));
    }
    const dark = isDark();
    const li = [], lc = [], mi = [], mc = [];
    fig._origColors.forEach((o, i) => {
      if (o.line) { li.push(i); lc.push(dark ? liftForDark(o.line) : o.line); }
      if (o.marker) { mi.push(i); mc.push(dark ? liftForDark(o.marker) : o.marker); }
    });
    if (li.length) Plotly.restyle(div, { "line.color": lc }, li);
    if (mi.length) Plotly.restyle(div, { "marker.color": mc }, mi);
    Plotly.relayout(div, themeLayoutPatch(fig.layout));
  } catch (e) { /* noop */ }
}



/* ---------- statistics (mirrors compute_stats() in strategy_service.py) --- */
function stats(series) {
  const n = series.length;
  if (n < 3) return null;
  const r = [];
  for (let i = 1; i < n; i++) r.push(series[i] / series[i - 1] - 1);
  const m = r.length;
  const mean = r.reduce((a, b) => a + b, 0) / m;
  let ss = 0, dsq = 0;
  for (const x of r) {
    ss += (x - mean) * (x - mean);
    if (x < 0) dsq += x * x;
  }
  const sd = Math.sqrt(ss / (m - 1));            // sample stdev, ddof=1
  const sdDown = Math.sqrt(dsq / m);             // downside deviation
  const years = m / 252;
  const A = Math.sqrt(252);

  let peak = series[0], maxDD = 0, ddSq = 0;
  for (const e of series) {
    if (e > peak) peak = e;
    const dd = (peak - e) / peak;
    if (dd > maxDD) maxDD = dd;
    ddSq += (100 * dd) * (100 * dd);
  }
  const ulcer = Math.sqrt(ddSq / n);
  const cagr = Math.pow(series[n - 1] / series[0], 1 / years) - 1;
  return {
    total: series[n - 1] / series[0] - 1,
    cagr: cagr,
    vol: sd * A,
    dvol: sdDown * A,
    sharpe: sd > 0 ? (mean / sd) * A : 0,
    sortino: sdDown > 0 ? (mean * A) / sdDown : 0,
    ulcer: ulcer,
    // Ulcer Performance Index / Martin ratio. Mirrors compute_stats() in
    // strategy_service.py: no risk-free rate, CAGR in percent to match the
    // Ulcer Index's units.
    upi: ulcer > 0 ? (cagr * 100) / ulcer : 0,
    maxDD: maxDD,
  };
}

// Symbols and tags come from our own backend, but they are interpolated into
// innerHTML, so escape them rather than trusting the shape of the payload.
const esc = s => String(s).replace(/[&<>"]/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const pct = (x, d = 1) => (x * 100).toFixed(d) + "%";
const num = (x, d = 2) => x.toFixed(d);
// a signed cell: green when positive, alarming bold red when negative
const signed = (v, txt) => `<td class="${v < 0 ? "neg" : "gain"}">${txt}</td>`;



/* Draw into a container, degrading gracefully if plotly.js is unavailable.
 * Without this, one failed CDN fetch throws inside renderChart() and takes
 * the whole panel down with it - no statistics, no monthly table, no
 * allocation, no log. The tables need no charting library, so they should
 * survive a missing one. */
function plotInto(id, traces, layout) {
  const el = document.getElementById(id);
  if (typeof Plotly === "undefined") {
    el.innerHTML = '<p class="plot-missing">' + esc(t("msg.noplotly")) + '</p>';
    return;
  }
  // Locale is read at draw time, so switching language and re-rendering is
  // enough to relabel every axis -- no separate tick-format handling.
  Plotly.react(el, traces, layout, {
    responsive: true, displaylogo: false,
    locale: currentLang() === "zh" ? "zh-CN" : "en",
  });
}

/* ---------- monthly + yearly returns ------------------------------------
 * Month-end equity chained from the first bar of the SELECTED period, so the
 * table always agrees with the statistics ledger and the chart above it.
 * The first month is therefore a partial month whenever the period does not
 * begin on a month boundary - flagged in the caption rather than hidden.
 * ---------------------------------------------------------------------- */
const MONTHS_KEY = "months";

function monthlyReturns() {
  const dates = AW.data.dates.slice(AW.i0, AW.i1 + 1);
  const eq = variant().series.slice(AW.i0, AW.i1 + 1);
  const order = [], lastOfMonth = new Map();
  for (let i = 0; i < dates.length; i++) {
    const k = dates[i].slice(0, 7);            // YYYY-MM
    if (!lastOfMonth.has(k)) order.push(k);
    lastOfMonth.set(k, eq[i]);                 // ends as the month's last value
  }
  const byYear = new Map();
  let prev = eq[0];
  for (const k of order) {
    const v = lastOfMonth.get(k);
    const r = v / prev - 1;
    prev = v;
    const y = k.slice(0, 4), m = parseInt(k.slice(5, 7), 10) - 1;
    if (!byYear.has(y)) byYear.set(y, new Array(12).fill(null));
    byYear.get(y)[m] = r;
  }
  return byYear;
}

/* ---------- monthly heat map ----------
 * Each month is a block whose fill runs from the neutral (white in light
 * mode, the card in dark) at 0% out to a deep green at +10% and a deep red
 * at -10%, clamped beyond.
 *
 * The label colour is chosen per block rather than fixed: whichever of pure
 * black or pure white contrasts better with that fill. Pure endpoints matter
 * -- the two contrast curves cross at a background luminance of 0.179, where
 * both give 4.58:1, so this choice can never fall below AA anywhere on the
 * scale. Anything softer than pure black dips under 4.5 near the crossover.
 */
const HEAT_CAP = 0.10;                     // return that saturates the scale

function _rgb(hex) {
  const h = hex.replace("#", "").trim();
  return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
}
function _relLum(c) {
  const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92
                                                 : Math.pow((v + 0.055) / 1.055, 2.4); };
  return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
}
function heatColors(r, zero, pos, neg) {
  const t = Math.max(-1, Math.min(1, r / HEAT_CAP));
  const end = t >= 0 ? pos : neg;
  const k = Math.abs(t);
  const bg = zero.map((c, i) => Math.round(c + (end[i] - c) * k));
  const L = _relLum(bg);
  return { bg: `rgb(${bg.join(",")})`,
           fg: (1.05 / (L + 0.05)) >= ((L + 0.05) / 0.05) ? "#fff" : "#000" };
}

function renderMonthly() {
  const byYear = monthlyReturns();
  // resolve the palette once per render, not once per cell
  const zero = _rgb(cssVar("--heat-zero"));
  const pos  = _rgb(cssVar("--heat-pos"));
  const neg  = _rgb(cssVar("--heat-neg"));

  const head = `<tr><th class="yr"></th>` +
    t(MONTHS_KEY).map(m => `<th>${m}</th>`).join("") +
    `<th class="tot">${t("monthly.year")}</th></tr>`;
  const rows = [...byYear.entries()].map(([y, months]) => {
    let growth = 1, any = false;
    const cells = months.map(r => {
      if (r === null) return `<td class="na">\u2013</td>`;
      growth *= 1 + r; any = true;
      const { bg, fg } = heatColors(r, zero, pos, neg);
      return `<td class="cell" style="background:${bg};color:${fg}">` +
             `${(r * 100).toFixed(1)}</td>`;
    }).join("");
    const yr = growth - 1;
    const tot = any
      ? `<td class="tot ${yr < 0 ? "neg" : "gain"}">${(yr * 100).toFixed(1)}</td>`
      : `<td class="tot na">\u2013</td>`;
    return `<tr><th class="yr">${y}</th>${cells}${tot}</tr>`;
  }).join("");
  document.getElementById("aw-monthly").innerHTML = head + rows;
}

/* ---------- rendering ---------------------------------------------------- */
/* Payload-level warnings, e.g. the rate-tied Sortino term switched off because
 * DGS10 could not be downloaded. Without this the strategy silently changes
 * behaviour and the only trace is a line in the update log. */
function renderWarnings() {
  const el = document.getElementById("aw-warn");
  if (!el) return;
  const w = (AW.data && AW.data.warnings) || [];
  el.hidden = w.length === 0;
  el.textContent = w.join("; ");
  el.title = w.join("\n");
}

function renderStats() {
  const dts = AW.data.dates.slice(AW.i0, AW.i1 + 1);
  const rows = SERIES.map(s => {
    const slice = seriesFor(s.key).slice(AW.i0, AW.i1 + 1);
    const st = stats(slice);
    if (st && AW.dca) {
      // Return figures -> money-weighted. Drawdown figures -> recomputed on
      // the account balance. Volatility, Sharpe and Sortino are left alone
      // because they are mathematically unchanged, not because they are hard
      // to compute (see the note above dcaAccount).
      const path = dcaPath(slice, dts);
      st.total = path[path.length - 1] - 1;
      st.cagr = moneyWeightedCAGR(slice, dts);
      const acct = dcaAccount(slice, dts);
      let peak = 0, maxDD = 0, ddSq = 0, cnt = 0;
      for (const v of acct) {
        if (v <= 0) continue;               // before the first contribution
        if (v > peak) peak = v;
        const dd = (peak - v) / peak;
        if (dd > maxDD) maxDD = dd;
        ddSq += (100 * dd) * (100 * dd);
        cnt++;
      }
      st.maxDD = maxDD;
      st.ulcer = cnt ? Math.sqrt(ddSq / cnt) : 0;
      st.upi = st.ulcer > 0 ? (st.cagr * 100) / st.ulcer : 0;
    }
    return { s, st };
  }).filter(x => x.st);

  const head = `<tr><th class="lbl">${t("stats.name")}</th>
      <th>${t("stats.return")}</th><th>${t("stats.cagr")}</th>
      <th>${t("stats.vol")}</th><th>${t("stats.dvol")}</th>
      <th>${t("stats.sharpe")}</th><th>${t("stats.sortino")}</th>
      <th>${t("stats.ulcer")}</th><th>${t("stats.upi")}</th>
      <th>${t("stats.maxdd")}</th></tr>`;
  const body = rows.map(({ s, st }, i) => `
    <tr class="${i === 0 ? "hero" : ""}">
      <td class="lbl"><span class="swatch" style="background:${seriesColor(s)}"></span>${esc(seriesLabel(s))}</td>
      ${signed(st.total, pct(st.total, 1))}${signed(st.cagr, pct(st.cagr, 2))}
      <td>${pct(st.vol, 1)}</td><td>${pct(st.dvol, 1)}</td>
      <td>${num(st.sharpe)}</td><td>${num(st.sortino)}</td>
      <td>${num(st.ulcer)}</td><td>${num(st.upi)}</td>
      <td class="neg">-${pct(st.maxDD, 1)}</td>
    </tr>`).join("");
  document.getElementById("aw-stats").innerHTML = head + body;
}

function renderChart() {
  const d = AW.data;
  const x = d.dates.slice(AW.i0, AW.i1 + 1);

  // Linear view shows cumulative return re-based to 0% at the period start.
  // A log axis cannot render negative values, so the log view switches to
  // growth of 100 instead - same shape, always positive. The neutral line is
  // 0% in one case and 100 in the other; everything below keys off that.
  const log = AW.logScale;
  const baseline = log ? 100 : 0;

  const lines = SERIES.map(s => {
    let raw = seriesFor(s.key).slice(AW.i0, AW.i1 + 1);
    if (AW.dca) raw = dcaPath(raw, x);     // value per dollar contributed
    const b0 = raw[0];
    return { s, y: raw.map(v => (log ? 100 * v / b0 : (v / b0 - 1) * 100)) };
  });

  // Shade the strategy's area against the neutral line: green where it is
  // ahead, red where it is behind. Plotly has no two-tone fill, so this is
  // the standard split -- clamp the series above and below the baseline and
  // fill each half separately. `tozeroy` is not usable here because on a log
  // axis zero is minus infinity, so both halves fill `tonexty` against an
  // invisible flat trace pinned at the baseline. That works identically on
  // linear and log, which is why the log view keeps its shading.
  // Shade the strategy's area against the neutral line: green where it is
  // ahead, red where it is behind. Plotly has no two-tone fill, so this is
  // the standard split -- clamp the series above and below the baseline and
  // fill each half separately. `tozeroy` is not usable here because on a log
  // axis zero is minus infinity, so both halves fill `tonexty` against an
  // invisible flat trace pinned at the baseline. That works identically on
  // linear and log, which is why the log view keeps its shading.
  //
  // Per-leg composition moved to its own chart (drawBands) in v5.0: overlaying
  // ten bands on top of three lines here was unreadable.
  const area = [];
  const strat = lines.find(l => l.s.fill);
  if (strat) {
    const flat = x.map(() => baseline);
    const hidden = {
      x, type: "scatter", mode: "lines", line: { width: 0 },
      hoverinfo: "skip", showlegend: false,
    };
    area.push({ ...hidden, y: flat });
    area.push({ ...hidden, y: strat.y.map(v => Math.max(v, baseline)),
                fill: "tonexty", fillcolor: cssVar("--fill") });
    area.push({ ...hidden, y: flat });
    area.push({ ...hidden, y: strat.y.map(v => Math.min(v, baseline)),
                fill: "tonexty", fillcolor: cssVar("--fill-loss") });
  }

  // fills first so the lines draw on top of them
  const traces = area.concat(lines.map(({ s, y }) => ({
    x, y, name: seriesLabel(s), type: "scatter", mode: "lines",
    line: { color: seriesColor(s), width: s.width },
    hovertemplate: (log ? "%{y:.0f}" : "%{y:.1f}%") +
                   "<extra>" + seriesLabel(s) + "</extra>",
  })));

  const bands = contextBands(x[0], x[x.length - 1]);
  const ink = cssVar("--ink"), grid = cssVar("--grid"),
        axis = cssVar("--axis"), card = cssVar("--card");
  const layout = {
    template: "plotly_white",
    autosize: true, height: 480,
    margin: { l: 64, r: 20, t: 18, b: 40 },
    paper_bgcolor: card, plot_bgcolor: card,
    hovermode: "x unified",
    shapes: bands.shapes, annotations: bands.annotations,
    // Explicit on BOTH charts so they match in either theme. Left to its
    // defaults, "x" mode paints the label from the TRACE colour
    // (color0 = d.bgcolor || dColor in fx/hover.js), which tinted the
    // composition tooltip green, while "x unified" composites from the plot
    // background and came out card-coloured.
    hoverlabel: { bgcolor: card, bordercolor: cssVar("--hairline"),
                  font: { color: ink, size: 13,
                          family: "Libre Franklin, system-ui, sans-serif" } },
    font: { size: 14, color: ink, family: "Libre Franklin, system-ui, sans-serif" },
    legend: { orientation: "h", x: 0, y: 1.08,
              font: { size: 13, color: ink }, bgcolor: card },
    xaxis: { showgrid: true, griddash: "dot", gridcolor: grid,
             linecolor: axis, mirror: true, ticks: "outside",
             automargin: true, tickfont: { color: ink },
             tickformatstops: dateTickStops(),
             // ISO in the hover box. Plotly would otherwise render the axis
             // default ("Nov 2023"), which is both coarser than the data and
             // untranslated -- its month names need a separate locale bundle,
             // so an ISO date sidesteps localisation altogether.
             hoverformat: "%Y-%m-%d" },
    yaxis: { title: { text: log ? t("chart.growth") : t("chart.cumret"),
                      standoff: 12 },
             automargin: true,
             ticksuffix: log ? "" : "%",
             showgrid: true, griddash: "dot", gridcolor: grid,
             linecolor: axis, mirror: true, ticks: "outside",
             tickfont: { color: ink }, title_font: { color: ink },
             zeroline: !log, zerolinecolor: grid,
             type: log ? "log" : "linear" },
  };
  plotInto("aw-chart", traces, layout);
}

/* ---------- composition bands -------------------------------------------
 * A dedicated chart: the strategy's own curve with the area beneath it split
 * into one band per leg, sized by that leg's weight at each bar.
 *
 * Stacking runs from the CURVE DOWNWARD in alphabetical order, so trace
 * insertion order is alphabetical too -- the legend comes out alphabetical
 * without depending on `legendrank`, and the bands read A..Z top to bottom.
 * (Stacking upward from the baseline would need reverse order and leave the
 * legend reversed.)
 *
 * No benchmark lines: this chart answers "what was held", and SPY/QQQ would
 * re-introduce exactly the clutter it exists to remove.
 */
/* Faint vertical rules marking every logged adjustment: rebalances and sleeve
 * flips. Drawn with layer:"above" -- unlike the recession bands, which sit
 * below the traces -- because the composition bands are SOLID fills and would
 * otherwise hide them completely.
 *
 * Density guard: the full window holds ~800 adjustments, which at 15y is a
 * line every few days and reads as a solid wash rather than as marks. Past
 * REBAL_MAX in view, only the sleeve flips are drawn: they are far rarer
 * (~135) and are the ones worth seeing at that zoom. The threshold is set so
 * the 1y/3y/5y presets still show every adjustment.
 */
const REBAL_MAX = 300;   // 1y/3y/5y show every adjustment; 10y+ thins to flips
function adjustmentShapes(lo, hi) {
  const v = variant();
  const adj = (v && v.adjustments) || [];
  const win = adj.filter(a => a.date >= lo && a.date <= hi);
  const flipsOnly = win.length > REBAL_MAX;
  const dark = isDark();
  // Rebalances are frequent, so they stay neutral grey and recede; sleeve
  // flips are rare and consequential, so they keep the pink. Solid rather
  // than dotted -- at this density dotted lines shimmer.
  //
  // Both kinds are now grey; flips are told apart by being DARKER and THICKER
  // rather than by hue. Pink read as an alarm colour and dominated the
  // composition it was meant to annotate.
  const nFlip = win.filter(a => a.tag !== "REBAL").length;
  const fade = Math.max(0.45, Math.min(1, 1 - (nFlip - 25) / 140));
  const cReb = dark ? "rgba(160,168,176,0.32)" : "rgba(55,62,70,0.42)";
  const cFlip = dark ? `rgba(224,230,238,${(0.62 * fade).toFixed(2)})`
                     : `rgba(18,24,32,${(0.66 * fade).toFixed(2)})`;
  const out = [];
  win.forEach(a => {
    const flip = a.tag !== "REBAL";      // "to <sleeve>" / "to PORT"
    if (flipsOnly && !flip) return;
    out.push({
      type: "line", xref: "x", yref: "paper",
      x0: a.date, x1: a.date, y0: 0, y1: 1, layer: "above",
      line: { color: flip ? cFlip : cReb,
              width: flip ? (fade > 0.7 ? 1.6 : 1.3) : 0.8 },
    });
  });
  return out;
}

function renderBands() {
  const el = document.getElementById("aw-bands");
  if (!el) return;
  const d = AW.data, book = bookMatrix();
  if (!book) { el.innerHTML = ""; return; }

  const x = d.dates.slice(AW.b0, AW.b1 + 1);
  const log = AW.logScale;
  const baseline = log ? 100 : 0;
  const rawEq = variant().series.slice(AW.b0, AW.b1 + 1);
  const b0 = rawEq[0];
  const curve = rawEq.map(v => (log ? 100 * v / b0 : (v / b0 - 1) * 100));

  const rows = book.rows.slice(AW.b0, AW.b1 + 1);
  const col = {};
  book.legs.forEach((sy, j) => { col[sy] = j; });
  // Sorted from the payload's legs rather than filtered through LEG_ORDER --
  // filtering dropped any leg missing from that list (TQQQ did not vanish from
  // the book, it vanished from the chart).
  const order = [...book.legs].sort();
  const total = rows.map(r => order.reduce(
    (a, sy) => a + Math.max(0, r[col[sy]] || 0), 0));
  const seen = {};
  rows.forEach(r => order.forEach(sy => {
    if ((r[col[sy]] || 0) > 0.0005) seen[sy] = true;
  }));

  // line_shape "hv" holds each value until the next point instead of
  // interpolating to it. The book only changes on adjustment bars, so a
  // straight line between them implies a gradual reallocation that never
  // happened -- and it reads worst across weekends, where one segment spans
  // three calendar days on a date axis (a Friday->Monday flip looked like it
  // began on the Friday).
  const hidden = {
    x, type: "scatter", mode: "lines", line: { width: 0, shape: "hv" },
    hoverinfo: "skip", showlegend: false,
  };
  const traces = [{ ...hidden, y: curve }];
  const cum = new Array(rows.length).fill(0);
  order.forEach(sy => {
    const j = col[sy];
    const y = rows.map((r, i) => {
      cum[i] += Math.max(0, r[j] || 0);
      const f = total[i] > 0 ? cum[i] / total[i] : 0;
      return baseline + (curve[i] - baseline) * (1 - f);
    });
    traces.push({
      ...hidden, y, name: sy, fill: "tonexty",
      // Solid, identical to the pie slice for the same symbol. Bands are
      // separated by a hairline in the card colour rather than by opacity,
      // which is exactly how the pie separates its slices.
      fillcolor: legColor(sy),
      line: { width: 0.8, color: cssVar("--card"), shape: "hv" },
      showlegend: !!seen[sy],
    });
  });

  // One tooltip listing the whole book at that bar. A single invisible trace
  // keeps the hover to ONE box; per-band hovertemplates under "x unified"
  // would stack ten rows and be unreadable.
  // Plotly's SVG text renderer supports <span style="..."> (TAG_STYLES/
  // STYLEMATCH in svg_text_utils), so each row can carry a filled square in
  // the leg's own colour -- the same read as the equity chart's unified hover,
  // but kept to ONE box instead of ten stacked rows.
  const label = rows.map((r, i) => order
    .filter(sy => (r[col[sy]] || 0) > 0.0005)
    .map(sy => '<span style="color:' + legColor(sy) + '">\u25a0</span> ' +
               sy + " " + (100 * r[col[sy]] / (total[i] || 1)).toFixed(1) + "%")
    .join("<br>") || "cash only");
  traces.push({
    x, y: curve, type: "scatter", mode: "lines", showlegend: false,
    line: { color: isDark() ? "#3fbf8f" : "#0e6e4f", width: 2, shape: "hv" },
    // customdata rather than %{x}: Plotly formats a parsed date axis to
    // whatever the zoom suggests ("Jan 2026"), and we want the same full
    // YYYY-MM-DD the marker annotation shows.
    text: label, customdata: x,
    hovertemplate: "<b>%{customdata}</b><br>%{text}<extra></extra>",
  });

  const bands = contextBands(x[0], x[x.length - 1]);
  const ink = cssVar("--ink"), grid = cssVar("--grid"),
        axis = cssVar("--axis"), card = cssVar("--card");
  const layout = {
    template: "plotly_white", autosize: true, height: 360,
    margin: { l: 64, r: 20, t: 18, b: 40 },
    paper_bgcolor: card, plot_bgcolor: card,
    hovermode: "x",
    // Explicit on BOTH charts so they match in either theme. Left to its
    // defaults, "x" mode paints the label from the TRACE colour
    // (color0 = d.bgcolor || dColor in fx/hover.js), which tinted the
    // composition tooltip green, while "x unified" composites from the plot
    // background and came out card-coloured.
    hoverlabel: { bgcolor: card, bordercolor: cssVar("--hairline"),
                  font: { color: ink, size: 13,
                          family: "Libre Franklin, system-ui, sans-serif" } },
    font: { size: 13, color: ink,
            family: "Libre Franklin, system-ui, sans-serif" },
    legend: { orientation: "h", x: 0, y: 1.10,
              font: { size: 12, color: ink }, bgcolor: card,
              // Plotly defaults traceorder to "reversed" when a chart
              // holds filled area traces, which displayed the
              // alphabetical stack backwards (XLE..BIL). Pin it.
              traceorder: "normal" },
    xaxis: { showgrid: false,   // the adjustment rules are the vertical reference here;
             // a calendar grid on top of them is just noise
             griddash: "dot", gridcolor: grid,
             linecolor: axis, mirror: true, ticks: "outside",
             automargin: true, tickfont: { color: ink },
             tickformatstops: dateTickStops(),
             // ISO in the hover box. Plotly would otherwise render the axis
             // default ("Nov 2023"), which is both coarser than the data and
             // untranslated -- its month names need a separate locale bundle,
             // so an ISO date sidesteps localisation altogether.
             hoverformat: "%Y-%m-%d" },
    yaxis: { showgrid: true, griddash: "dot", gridcolor: grid,
             linecolor: axis, mirror: true, ticks: "outside",
             automargin: true, tickfont: { color: ink },
             type: log ? "log" : "linear", ticksuffix: log ? "" : "%" },
    // context bands first (they sit below the traces), then the adjustment
    // rules on top of the solid fills
    shapes: bands.shapes.concat(adjustmentShapes(x[0], x[x.length - 1])),
    annotations: bands.annotations.slice(),
  };

  // Marker for a clicked adjustment row. Only drawn when that date is inside
  // the visible window; otherwise it would pin to the axis edge and read as
  // a bug rather than as "outside the range you are looking at".
  if (AW.markDate && x.indexOf(AW.markDate) >= 0) {
    layout.shapes.push({
      type: "line", xref: "x", yref: "paper",
      x0: AW.markDate, x1: AW.markDate, y0: 0, y1: 1,
      line: { color: ink, width: 1.5, dash: "dot" },
    });
    layout.annotations.push({
      x: AW.markDate, y: 1, xref: "x", yref: "paper", text: AW.markDate,
      showarrow: false, yanchor: "bottom", font: { size: 11, color: ink },
      bgcolor: card,
    });
  }
  plotInto("aw-bands", traces, layout);
}

function renderAllocation() {
  const alloc = variant().allocation || [];
  const amt = currentAmount();

  document.getElementById("aw-alloc-body").innerHTML = alloc.map(a => {
    const dollars = Math.round(amt * a.weight);
    const shares = a.price > 0 ? Math.floor(dollars / a.price) : 0;
    return `<tr>
      <td class="sym">${a.symbol}</td><td class="name">${a.name}</td>
      <td class="r">${pct(a.weight, 1)}</td>
      <td class="r">$${dollars.toLocaleString()}</td>
      <td class="r">$${a.price.toFixed(2)}</td>
      <td class="r">${shares.toLocaleString()}</td></tr>`;
  }).join("");

  plotInto("aw-pie", [{
    type: "pie", hole: 0.55, sort: false,
    labels: alloc.map(a => a.symbol),
    values: alloc.map(a => a.weight),
    marker: { colors: alloc.map(a => legColor(a.symbol)),
              line: { color: cssVar("--card"), width: 1.5 } },
    textinfo: "label+percent", textposition: "outside",
    // automargin lets plotly reserve whatever room the outside labels need,
    // so long labels near the top can no longer be clipped by the container.
    automargin: true,
    hovertemplate: "%{label}  %{percent}<extra></extra>",
  }], {
    height: 380, margin: { l: 34, r: 34, t: 38, b: 38 },
    showlegend: false,
    paper_bgcolor: cssVar("--card"), plot_bgcolor: cssVar("--card"),
    font: { size: 13, color: cssVar("--ink"),
            family: "IBM Plex Mono, monospace" },
  }, { responsive: true, displaylogo: false });
}

function renderLog() {
  const all = variant().adjustments || [];
  // State the extent explicitly. The whole point is that a short log should
  // look wrong at a glance rather than just looking like a short history.
  const ext = document.getElementById("aw-log-extent");
  if (ext) {
    ext.textContent = all.length
      ? `${all.length} ${t("log.entries")}, ${all[0].date} ${t("log.to")} `
        + `${all[all.length - 1].date}`
      : t("log.none");
  }
  const items = all.slice().reverse();
  document.getElementById("aw-log").innerHTML = items.map(a => {
    // esc() on the symbol: the whole string can no longer be escaped at the
    // end because it now carries markup for the arrow.
    const fmt = w => Object.entries(w)
      .map(([k, v]) => `${esc(k)}=${(v * 100).toFixed(1)}%`).join(" ");
    // Rows where cash was spent to swap leveraged exposure for plain QQQ show
    // the book on both sides of the swap.
    const legs = a.weights_pre
      ? `${fmt(a.weights_pre)} <span class="arrow">&#8594;</span> ${fmt(a.weights)}`
      : fmt(a.weights);
    // Tags arrive as "REBAL" / "to PORT" / "to <SYM>"; render them in the
    // current language, and key the colour on meaning rather than wording.
    const isRebal = a.tag === "REBAL";
    const isOff = a.tag === "to PORT";
    const cls = isRebal ? "t-rebal" : (isOff ? "t-off" : "t-on");
    const label = isRebal ? t("log.rebal")
                : isOff ? t("log.toport")
                : `${t("log.tosleeve")} ${a.tag.replace(/^to\s+/, "")}`;
    // vt < 1 means the volatility brake throttled the book that day.
    const vt = (a.vt !== undefined && a.vt < 1)
      ? `<span class="vt" title="volatility brake">x${a.vt.toFixed(2)}</span>` : "";
    const on = AW.markDate === a.date ? " is-marked" : "";
    return `<div class="logline${on}" data-date="${a.date}" role="button" tabindex="0">` +
           `<span class="d">${a.date}</span>` +
           `<span class="t ${cls}">${esc(label)}</span>${vt}` +
           `<span class="w">${legs}</span></div>`;
  }).join("");
}

/* ---------- period control ----------------------------------------------- */
function currentAmount() {
  const v = parseFloat(document.getElementById("aw-amount").value);
  return isFinite(v) && v > 0 ? v : 100000;
}

/* The composition chart carries its own window so you can scrub through
 * allocation history without disturbing the equity chart's period (and the
 * stats table that reads from it). Same 252-bars-per-year convention. */
function syncBandLabels() {
  document.getElementById("awb-from-label").textContent = AW.data.dates[AW.b0];
  document.getElementById("awb-to-label").textContent = AW.data.dates[AW.b1];
}

function setBandRange(i0, i1) {
  const n = AW.data.dates.length;
  AW.b0 = Math.max(0, Math.min(i0, n - 2));
  AW.b1 = Math.max(AW.b0 + 1, Math.min(i1, n - 1));
  document.getElementById("awb-from").value = AW.b0;
  document.getElementById("awb-to").value = AW.b1;
  syncBandLabels();
  renderBands();
}

function setBandYears(y) {
  const n = AW.data.dates.length;
  if (y === null) { setBandRange(0, n - 1); return; }
  setBandRange(Math.max(0, n - 1 - Math.round(y * 252)), n - 1);
}

function syncRangeLabels() {
  document.getElementById("aw-from-label").textContent = AW.data.dates[AW.i0];
  document.getElementById("aw-to-label").textContent = AW.data.dates[AW.i1];
}

function setRange(i0, i1) {
  const n = AW.data.dates.length;
  AW.i0 = Math.max(0, Math.min(i0, n - 2));
  AW.i1 = Math.max(AW.i0 + 1, Math.min(i1, n - 1));
  document.getElementById("aw-from").value = AW.i0;
  document.getElementById("aw-to").value = AW.i1;
  syncRangeLabels();
  renderStats();
  renderMonthly();
  renderChart();
}

function setYears(y) {
  const n = AW.data.dates.length;
  if (y === null) { setRange(0, n - 1); return; }
  // 252 trading bars per year, clamped to the data we actually have.
  setRange(Math.max(0, n - 1 - Math.round(y * 252)), n - 1);
}


/* Switch sleeve fraction. All three are already computed and in memory, so
 * this is a pure re-render - no fetch, no recomputation. The selected period
 * is deliberately preserved so the fractions stay directly comparable. */
function setFrac(key) {
  if (!AW.data.variants[key]) return;
  AW.frac = key;
  document.getElementById("aw-frac").value = key;
  const adj = variant().allocation_date || AW.data.as_of;
  document.getElementById("aw-alloc-date").textContent = adj;
  document.getElementById("aw-lastadj").textContent = adj;
  renderThemed({ withLog: true });
}

/* Redraw everything whose colours are baked in at render time rather than
 * inherited from CSS. That is: the heat-map blocks and the statistics
 * swatches (inline style attributes) and both plotly surfaces (plotly copies
 * colours into its own state). Text colours driven by CSS classes -- the
 * gain/loss figures, the adjustment log tags -- follow the theme on their
 * own and are not the reason this function exists.
 *
 * Routed through one function on purpose: when this was a hand-written list
 * of calls at each site, a theme flip redrew the chart and the donut but not
 * the heat map or the swatches, which then kept the previous theme's colours
 * until a reload. */
/* Text built in JS rather than carried by data-i18n. Split out of bootPanel
 * because switching language must refresh it: leaving it there meant the
 * sleeve pill kept the previous language's wording after a switch. */
function renderLabels() {
  const d = AW.data;
  if (!d) return;
  // Heading follows the translation table, not the payload, so it matches the
  // tab that opened it.
  document.getElementById("aw-title").textContent =
    t("panel." + (AW.kind || "base")) || d.title || "All Weather Dynamic";
  // Every place the sleeve instrument is named follows the payload, so the
  // leveraged tab never claims to be holding QQQ.
  const sym = d.sleeve_symbol || "QQQ";
  for (const id of ["aw-frac-label", "aw-frac-hint"]) {
    const el = document.getElementById(id);
    if (el) el.textContent = sym;
  }
  const pill = document.getElementById("aw-sleeve");
  if (pill) pill.textContent = sym + " " +
    (d.sleeve_on ? t("sleeve.on") : t("sleeve.off"));
}

/* When the next scheduled refresh is due. Hours come from the server (the
 * scheduler runs in the server's local time, which for a desktop install is
 * this machine), and the next occurrence is worked out against the local
 * clock so it stays right without the page reloading. */
/* Short zone name ("CDT", "GMT+8"). Always read through en-US: zh-CN renders
 * the same zone as "GMT-5", and the familiar abbreviation is the point. */
function tzShort(when) {
  try {
    const parts = new Intl.DateTimeFormat("en-US", { timeZoneName: "short" })
      .formatToParts(when);
    const p = parts.find(x => x.type === "timeZoneName");
    return p ? p.value : "";
  } catch (e) {
    return "";
  }
}

/* One stamp format for both the last update and the next one.
 *
 * Composed from parts rather than one toLocaleString call: asking zh-CN for a
 * zone name yields "2026年7月29日 GMT-5 06:00", with the zone wedged into the
 * middle. Built this way it reads
 *     Jul 29, 2026, 06:00 AM CDT
 *     2026年7月29日 06:00 CDT
 * and follows the UI language rather than the browser's own locale, so
 * switching to Chinese restyles the date too. */
function fmtStamp(when) {
  const zh = currentLang() === "zh";
  const loc = zh ? "zh-CN" : undefined;
  const date = when.toLocaleDateString(loc,
    { year: "numeric", month: "short", day: "numeric" });
  const time = when.toLocaleTimeString(loc,
    { hour: "2-digit", minute: "2-digit" });
  const zone = tzShort(when);
  return date + (zh ? " " : ", ") + time + (zone ? " " + zone : "");
}

function nextUpdateAt() {
  let hours = [];
  try { hours = JSON.parse(document.body.dataset.updateHours || "[]"); }
  catch (e) { hours = []; }
  if (!hours.length) return null;
  hours = hours.slice().sort((a, b) => a - b);

  // The configured hours belong to the SCHEDULE's zone -- update_timezone if
  // one is set, otherwise the server's own local time. serverOffset carries
  // that zone's current UTC offset. Work in it to pick the next slot, then
  // hand back a real instant so it displays in the viewer's zone. On a
  // single-machine install the offsets match and this reduces to the obvious
  // thing; across a UTC server and a local desktop it is what keeps the two
  // stamps describing the same moment.
  // The MINUTE matters. This used to be hardcoded to 0 while the schedule
  // actually runs at :20, so every "next update" stamp was 20 minutes early.
  const mParsed = parseInt(document.body.dataset.updateMinute || "", 10);
  const minute = Number.isNaN(mParsed) ? 0 : Math.min(59, Math.max(0, mParsed));

  const parsed = parseInt(document.body.dataset.serverOffset || "", 10);
  const nowMs = Date.now();
  const serverOff = Number.isNaN(parsed)
    ? -new Date(nowMs).getTimezoneOffset() : parsed;
  const shift = serverOff * 60000;

  // A Date shifted by the offset, read through its UTC getters, behaves as
  // the server's wall clock.
  const sNow = new Date(nowMs + shift);
  for (let day = 0; day < 2; day++) {
    for (const h of hours) {
      const sWhen = Date.UTC(sNow.getUTCFullYear(), sNow.getUTCMonth(),
                             sNow.getUTCDate() + day, h, minute, 0, 0);
      const when = new Date(sWhen - shift);      // back to a true instant
      if (when.getTime() > nowMs) return when;
    }
  }
  return null;
}

/* The next refresh, formatted like the update stamp above it. */
function nextUpdateText() {
  const when = nextUpdateAt();
  return when ? fmtStamp(when) : t("sched.manual");
}

function renderThemed({ withLog = false } = {}) {
  if (!AW.data) return;
  renderLabels();      // language-dependent wording
  renderStats();       // legend swatches are inline-coloured
  renderWarnings();    // e.g. rate-tied Sortino disabled
  renderMonthly();     // heat-map blocks are inline-coloured
  renderChart();
  renderBands();
  renderAllocation();
  if (withLog) renderLog();
}

/* ---------- boot --------------------------------------------------------- */
async function loadStrategy(kind = "base") {
  const host = document.getElementById("aw-panel");
  const msg = document.getElementById("aw-message");
  // Switching tabs re-renders from a payload already in memory if we have it.
  if (kind !== AW.kind) {
    AW.kind = kind;
    AW.data = AW.cache[kind] || null;
    if (AW.data) { bootPanel(); return; }
  }
  if (AW.data) {
    renderChart(); renderAllocation();
    if (typeof Plotly !== "undefined") {
      Plotly.Plots.resize("aw-chart"); Plotly.Plots.resize("aw-pie");
    }
    return;
  }

  msg.hidden = false;
  msg.innerHTML = "Loading the strategy\u2026";
  try {
    const resp = await fetch("/api/strategy?kind=" + encodeURIComponent(AW.kind));
    if (!resp.ok) {
      const detail = (await resp.json().catch(() => ({}))).detail || resp.statusText;
      msg.innerHTML = "<strong>Strategy not available.</strong> " + detail +
        "<br>Build it with <code>python -m app.update --strategy-only</code>, " +
        "then reload.";
      host.hidden = true;
      return;
    }
    AW.data = await resp.json();
  } catch (err) {
    msg.innerHTML = "<strong>Could not load the strategy.</strong> " + err;
    host.hidden = true;
    return;
  }

  bootPanel();
  wireOnce();
}

/* Paint the panel from AW.data. Safe to call repeatedly -- a tab switch does
 * exactly this, with a different payload. */
function bootPanel() {
  const d = AW.data, n = d.dates.length;
  document.getElementById("aw-message").hidden = true;
  document.getElementById("aw-panel").hidden = false;

  // A cached payload built by older code can look perfectly healthy while
  // missing data (this is how a lifted 250-entry log cap stayed invisible).
  // Compare the cache's stamp with the running code's and say so.
  const want = parseInt(document.body.dataset.payloadVersion || "0", 10);
  const got = parseInt(d.payload_version || 0, 10);
  const stale = document.getElementById("aw-stale");
  if (stale && want && got < want) {
    stale.hidden = false;
    stale.innerHTML = "<strong>This cache was built by an older version</strong> " +
      "(v" + got + ", current is v" + want + "), so some of it may be " +
      "incomplete. Rebuild with <code>python -m app.update --strategy-only</code>.";
  } else if (stale) {
    stale.hidden = true;
  }

  renderLabels();
  document.getElementById("aw-asof").textContent = d.as_of;

  const sel = document.getElementById("aw-frac");
  // Label as a percentage; the option VALUE stays the payload's key ("0.60")
  // so nothing downstream has to know about the friendlier label.
  sel.innerHTML = d.fracs.map(f =>
    `<option value="${f}">${Math.round(parseFloat(f) * 100)}%</option>`).join("");
  // Per-kind first, then the single legacy value, then the payload's own.
  let perKind = {};
  try { perKind = JSON.parse(document.body.dataset.defaultFracs || "{}"); }
  catch (e) { perKind = {}; }
  const wantFrac = perKind[AW.kind]
                   || document.body.dataset.defaultFrac
                   || d.default_frac;
  AW.frac = d.fracs.includes(wantFrac) ? wantFrac : d.fracs[0];
  sel.value = AW.frac;
  sel.onchange = () => setFrac(sel.value);
  const firstAdj = variant().allocation_date || d.as_of;
  document.getElementById("aw-alloc-date").textContent = firstAdj;
  document.getElementById("aw-lastadj").textContent = firstAdj;
  document.getElementById("aw-sleeve").className =
    "pill " + (d.sleeve_on ? "pill-on" : "pill-off");



  document.getElementById("aw-from").max = n - 1;
  document.getElementById("aw-to").max = n - 1;

  const bf = document.getElementById("awb-from");
  const bt = document.getElementById("awb-to");
  if (bf && bt) { bf.max = n - 1; bt.max = n - 1; }

  const defYears = parseFloat(document.body.dataset.defaultYears)
                   || d.default_years || 5;
  document.querySelectorAll(".aw-quick").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.years === String(defYears))));
  document.querySelectorAll(".awb-quick").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.years === String(defYears))));
  AW.markDate = null;                 // a new payload invalidates the marker
  AW.dca = false;
  const dbox = document.getElementById("aw-dca");
  if (dbox) dbox.checked = false;
  const bwrap = document.getElementById("aw-brake-wrap");
  const bbox = document.getElementById("aw-brake");
  if (bwrap && bbox) {
    bwrap.hidden = !d.variants_nobrake;   // nothing to compare against
    AW.volBrake = true;
    bbox.checked = true;
  }
  setYears(defYears);
  setBandYears(defYears);             // same default window as the equity chart
  renderAllocation();
  renderLog();
}

/* Listeners are bound once for the life of the page, not per payload. */
let _wired = false;
function wireOnce() {
  // Delegated so it survives every re-render of the log. Clicking a row marks
  // that date on the composition chart; clicking the marked row clears it.
  const logHost = document.getElementById("aw-log");
  if (logHost && !logHost.dataset.wired) {
    logHost.dataset.wired = "1";
    const pick = ev => {
      const row = ev.target.closest(".logline");
      if (!row) return;
      const date = row.dataset.date;
      AW.markDate = (AW.markDate === date) ? null : date;
      // If the marked date sits outside the composition chart's window, slide
      // the window to centre it while KEEPING the current zoom width, so the
      // level of detail you were looking at is preserved. y is never pinned,
      // so it rescales to whatever is now visible.
      if (AW.markDate) {
        const di = AW.data.dates.indexOf(AW.markDate);
        if (di >= 0 && (di < AW.b0 || di > AW.b1)) {
          const n = AW.data.dates.length;
          const w = AW.b1 - AW.b0;
          let b0 = Math.round(di - w / 2);
          b0 = Math.max(0, Math.min(b0, n - 1 - w));
          setBandRange(b0, b0 + w);          // re-renders
        } else {
          renderBands();
        }
      } else {
        renderBands();
      }
      renderLog();
      const el = document.getElementById("aw-bands");
      if (AW.markDate && el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };
    logHost.addEventListener("click", pick);
    logHost.addEventListener("keydown", ev => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); pick(ev); }
    });
  }

  if (_wired) return;
  _wired = true;
  const from = document.getElementById("aw-from");
  const to = document.getElementById("aw-to");
  from.addEventListener("input", () => setRange(+from.value, AW.i1));
  to.addEventListener("input", () => setRange(AW.i0, +to.value));
  document.querySelectorAll(".aw-quick").forEach(b => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".aw-quick").forEach(x =>
        x.setAttribute("aria-pressed", String(x === b)));
      setYears(b.dataset.years === "max" ? null : +b.dataset.years);
    });
  });
  // Composition chart's own controls. Distinct classes/ids from the equity
  // chart's: `.aw-quick` is selected globally, so reusing it would drive both.
  const bfrom = document.getElementById("awb-from");
  const bto = document.getElementById("awb-to");
  if (bfrom && bto) {
    bfrom.addEventListener("input", () => setBandRange(+bfrom.value, AW.b1));
    bto.addEventListener("input", () => setBandRange(AW.b0, +bto.value));
  }
  document.querySelectorAll(".awb-quick").forEach(b => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".awb-quick").forEach(x =>
        x.setAttribute("aria-pressed", String(x === b)));
      setBandYears(b.dataset.years === "max" ? null : +b.dataset.years);
    });
  });
  const brakeBox = document.getElementById("aw-brake");
  if (brakeBox) {
    brakeBox.addEventListener("change", e => {
      AW.volBrake = e.target.checked;
      renderThemed({ withLog: true });
    });
  }
  const dcaBox = document.getElementById("aw-dca");
  if (dcaBox) {
    dcaBox.addEventListener("change", e => {
      AW.dca = e.target.checked;
      renderThemed();          // chart + stats only; the log is unaffected
    });
  }
  document.getElementById("aw-log-scale").addEventListener("change", e => {
    AW.logScale = e.target.checked;
    renderChart();
    renderBands();
  });
  document.getElementById("aw-amount").addEventListener("input", renderAllocation);
  document.getElementById("aw-export").addEventListener("click", () => {
    window.location = "/api/strategy/allocations.csv?amount=" +
                      currentAmount() + "&frac=" + encodeURIComponent(AW.frac) +
                      "&kind=" + encodeURIComponent(AW.kind);
  });
}
