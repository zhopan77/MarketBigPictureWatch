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
  data: null,      // the cached payload (all sleeve fractions)
  frac: null,      // selected SLEEVE_FRAC key, e.g. "0.50"
  i0: 0, i1: 0,    // selected [begin, end] indices into data.dates
  logScale: false,
};

/* The payload holds one precomputed variant per sleeve fraction. Benchmarks
 * and the calendar are shared, so only the strategy series, its statistics,
 * its allocation and its adjustment log change when the dropdown moves. */
const variant = () => AW.data.variants[AW.frac];
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

const PIE_LIGHT = ["#0e6e4f", "#c2903a", "#4d6fa8", "#8c5a7a", "#6a8f3c",
                   "#b0603a", "#4f8f8a", "#7a6aa8", "#93794a", "#5b6472"];
const PIE_DARK  = ["#3fbf8f", "#e0b158", "#7fa8e6", "#c88bae", "#9ec95a",
                   "#e08a63", "#66c2bb", "#a99ae0", "#c4a86a", "#9aa3b0"];

/* ---------- theme ----------
 * Chart colours are read from the CSS custom properties at draw time, so the
 * charts follow whatever the stylesheet says the theme is. One source of
 * truth: change a token in style.css and the plots move with it. */
// The strategy series is named for the tab it belongs to, so tab 07's legend
// reads "All Weather Leverage Strategy" rather than borrowing tab 06's name.
const seriesLabel = s => (s.key === "strategy" && AW.kind === "leverage")
  ? t("series.strategy_lev") : t(s.i18n);

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
  Plotly.react(el, traces, layout, { responsive: true, displaylogo: false });
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
function renderStats() {
  const rows = SERIES.map(s => {
    const slice = seriesFor(s.key).slice(AW.i0, AW.i1 + 1);
    return { s, st: stats(slice) };
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
    const raw = seriesFor(s.key).slice(AW.i0, AW.i1 + 1);
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

  const ink = cssVar("--ink"), grid = cssVar("--grid"),
        axis = cssVar("--axis"), card = cssVar("--card");
  const layout = {
    template: "plotly_white",
    autosize: true, height: 480,
    margin: { l: 64, r: 20, t: 18, b: 40 },
    paper_bgcolor: card, plot_bgcolor: card,
    hovermode: "x unified",
    font: { size: 14, color: ink, family: "Libre Franklin, system-ui, sans-serif" },
    legend: { orientation: "h", x: 0, y: 1.08,
              font: { size: 13, color: ink }, bgcolor: card },
    xaxis: { showgrid: true, griddash: "dot", gridcolor: grid,
             linecolor: axis, mirror: true, ticks: "outside",
             automargin: true, tickfont: { color: ink } },
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
    marker: { colors: pieColors(),
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
    const legs = Object.entries(a.weights)
      .map(([k, v]) => `${k}=${Math.round(v * 100)}%`).join(" ");
    // Tags arrive as "REBAL" / "to PORT" / "to <SYM>"; render them in the
    // current language, and key the colour on meaning rather than wording.
    const isRebal = a.tag === "REBAL";
    const isOff = a.tag === "to PORT";
    const cls = isRebal ? "t-rebal" : (isOff ? "t-off" : "t-on");
    const label = isRebal ? t("log.rebal")
                : isOff ? t("log.toport")
                : `${t("log.tosleeve")} ${a.tag.replace(/^to\s+/, "")}`;
    return `<div class="logline"><span class="d">${a.date}</span>` +
           `<span class="t ${cls}">${esc(label)}</span>` +
           `<span class="w">${esc(legs)}</span></div>`;
  }).join("");
}

/* ---------- period control ----------------------------------------------- */
function currentAmount() {
  const v = parseFloat(document.getElementById("aw-amount").value);
  return isFinite(v) && v > 0 ? v : 100000;
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
    t("panel." + (AW.kind || "base")) || d.title || "All Weather 9";
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

  // The configured hours are SERVER-local. Work in server-local time to pick
  // the next one, then hand back a real instant so it displays in the
  // viewer's own zone. On a single-machine install the two offsets match and
  // this reduces to the obvious thing.
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
                             sNow.getUTCDate() + day, h, 0, 0, 0);
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
  renderMonthly();     // heat-map blocks are inline-coloured
  renderChart();
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
  // Show 50% / 75% / 100%; the option VALUE stays the payload's key ("0.50")
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

  const defYears = parseFloat(document.body.dataset.defaultYears)
                   || d.default_years || 5;
  document.querySelectorAll(".aw-quick").forEach(b =>
    b.setAttribute("aria-pressed", String(b.dataset.years === String(defYears))));
  setYears(defYears);
  renderAllocation();
  renderLog();
}

/* Listeners are bound once for the life of the page, not per payload. */
let _wired = false;
function wireOnce() {
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
  document.getElementById("aw-log-scale").addEventListener("change", e => {
    AW.logScale = e.target.checked;
    renderChart();
  });
  document.getElementById("aw-amount").addEventListener("input", renderAllocation);
  document.getElementById("aw-export").addEventListener("click", () => {
    window.location = "/api/strategy/allocations.csv?amount=" +
                      currentAmount() + "&frac=" + encodeURIComponent(AW.frac) +
                      "&kind=" + encodeURIComponent(AW.kind);
  });
}
