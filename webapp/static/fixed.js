/* All Weather Fixed tab.
 *
 * Two STATIC allocations (A = Golden Butterfly, B = equity-tilted), each shown
 * as its own section stacked top-to-bottom. Every section mirrors the dynamic
 * tab's read: the server ships one JSON blob a day with each portfolio's daily
 * equity curve plus SPY/QQQ buy-and-hold, indexed to 100 at that portfolio's
 * first shared bar. Slicing to a period, re-basing, and recomputing statistics
 * all happen in the browser, so the period control is instant.
 *
 * This module deliberately reuses the pure helpers defined in strategy.js
 * (stats, pct, num, esc, signed, isDark, cssVar, plotInto, dateTickStops,
 * heatColors, _rgb, MONTHS_KEY, the DCA math). Only the AW-specific pieces --
 * which read the dynamic payload's shape -- are reimplemented here against the
 * fixed payload. Both scripts share one global lexical scope, so those names
 * are visible without any export.
 */

const FX = {
  data: null,                 // the cached payload (both sections)
  sec: {                      // per-section view state
    A: { i0: 0, i1: 0, log: false, dca: false, rebal: "annual" },
    B: { i0: 0, i1: 0, log: false, dca: false, rebal: "annual" },
    C: { i0: 0, i1: 0, log: false, dca: false, rebal: "annual" },
  },
};

/* Series drawn in every section: the portfolio, then SPY and QQQ buy-and-hold.
 * Same hues as the dynamic tab so the two tabs read as one system. */
const FX_SERIES = [
  { key: "strategy", light: "#0e6e4f", dark: "#3fbf8f", width: 3.0, fill: true },
  { key: "SPY", light: "#c2903a", dark: "#e0b158", width: 1.4, fill: false },
  { key: "QQQ", light: "#4d6fa8", dark: "#7fa8e6", width: 1.4, fill: false },
];

/* Stable leg order for the pie, so a symbol keeps its colour across both
 * sections (GLD is the same slice in A and B). Indexes the shared PIE palette
 * from strategy.js. */
const FX_LEG = ["VTI", "IJS", "TLT", "SHY", "IEF", "GLD", "DBC", "BND"];
const fxLegColor = sym => {
  const pal = pieColors();
  const i = FX_LEG.indexOf(sym);
  const j = i >= 0 ? i : [...sym].reduce((a, c) => a + c.charCodeAt(0), 0);
  return pal[j % pal.length];
};

const fxSection = k => FX.data.sections[k];
/* The strategy curve depends on the section's selected rebalance schedule
 * (evaluation-only). Benchmarks never do. Falls back to the default `series`
 * if an older cache lacks the per-schedule curves. */
const fxSeries = (k, key) => {
  const sec = fxSection(k);
  if (key !== "strategy") return sec.benchmarks[key];
  const by = sec.series_by_rebal;
  return (by && by[FX.sec[k].rebal]) || sec.series;
};
const fxSeriesColor = s => (isDark() ? s.dark : s.light);
const fxSeriesLabel = (sec, key) =>
  key === "strategy" ? t("fx." + sec.key + ".name")
    : key === "SPY" ? t("series.spy") : t("series.qqq");

/* ---------- context bands (recessions / drawdowns / events) --------------
 * Same visual as the dynamic tab, but reading THIS section's own shades over
 * its own window rather than the global AW payload. */
function fxContextBands(shades, lo, hi) {
  if (!shades) return { shapes: [], annotations: [] };
  const spans = []
    .concat(shades.recession || [], shades.drawdown || [], shades.event || [])
    .filter(e => e.from && e.to)
    .map(e => [e.from, e.to, e.label || ""])
    .sort((a, b) => (a[0] < b[0] ? -1 : 1));

  const merged = [];
  spans.forEach(([a, b, name]) => {
    const last = merged[merged.length - 1];
    if (last && a <= last[1]) {
      if (b > last[1]) last[1] = b;
      if (name) last[2].add(name);
    } else merged.push([a, b, new Set(name ? [name] : [])]);
  });

  const grey = isDark() ? "rgba(255,255,255,0.07)" : "rgba(17,17,17,0.13)";
  const shapes = [], annotations = [];
  merged
    .filter(([a, b]) => !(b < lo || a > hi))
    .forEach(([a, b, names]) => {
      const x0 = a < lo ? lo : a, x1 = b > hi ? hi : b;
      shapes.push({
        type: "rect", xref: "x", yref: "paper", x0, x1, y0: 0, y1: 1,
        fillcolor: grey, line: { width: 0 }, layer: "below",
      });
      const raw = [...names].join(" / ");
      if (!raw) return;
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

/* ---------- statistics table ---------- */
function fxRenderStats(k) {
  const sec = fxSection(k), st8 = FX.sec[k];
  const dts = sec.dates.slice(st8.i0, st8.i1 + 1);
  const rows = FX_SERIES.map(s => {
    const slice = fxSeries(k, s.key).slice(st8.i0, st8.i1 + 1);
    const stx = stats(slice);
    if (stx && st8.dca) {
      const path = dcaPath(slice, dts);
      stx.total = path[path.length - 1] - 1;
      stx.cagr = moneyWeightedCAGR(slice, dts);
      const acct = dcaAccount(slice, dts);
      let peak = 0, maxDD = 0, ddSq = 0, cnt = 0;
      for (const v of acct) {
        if (v <= 0) continue;
        if (v > peak) peak = v;
        const dd = (peak - v) / peak;
        if (dd > maxDD) maxDD = dd;
        ddSq += (100 * dd) * (100 * dd);
        cnt++;
      }
      stx.maxDD = maxDD;
      stx.ulcer = cnt ? Math.sqrt(ddSq / cnt) : 0;
      stx.upi = stx.ulcer > 0 ? (stx.cagr * 100) / stx.ulcer : 0;
    }
    return { s, st: stx };
  }).filter(x => x.st);

  const head = `<tr><th class="lbl">${t("stats.name")}</th>
      <th>${t("stats.return")}</th><th>${t("stats.cagr")}</th>
      <th>${t("stats.vol")}</th><th>${t("stats.dvol")}</th>
      <th>${t("stats.sharpe")}</th><th>${t("stats.sortino")}</th>
      <th>${t("stats.ulcer")}</th><th>${t("stats.upi")}</th>
      <th>${t("stats.maxdd")}</th></tr>`;
  const body = rows.map(({ s, st }, i) => `
    <tr class="${i === 0 ? "hero" : ""}">
      <td class="lbl"><span class="swatch" style="background:${fxSeriesColor(s)}"></span>${esc(fxSeriesLabel(sec, s.key))}</td>
      ${signed(st.total, pct(st.total, 1))}${signed(st.cagr, pct(st.cagr, 2))}
      <td>${pct(st.vol, 1)}</td><td>${pct(st.dvol, 1)}</td>
      <td>${num(st.sharpe)}</td><td>${num(st.sortino)}</td>
      <td>${num(st.ulcer)}</td><td>${num(st.upi)}</td>
      <td class="neg">-${pct(st.maxDD, 1)}</td>
    </tr>`).join("");
  document.getElementById(`fx${k}-stats`).innerHTML = head + body;
}

/* ---------- equity chart ---------- */
function fxRenderChart(k) {
  const sec = fxSection(k), st8 = FX.sec[k];
  const x = sec.dates.slice(st8.i0, st8.i1 + 1);
  const log = st8.log;
  const baseline = log ? 100 : 0;

  const lines = FX_SERIES.map(s => {
    let raw = fxSeries(k, s.key).slice(st8.i0, st8.i1 + 1);
    if (st8.dca) raw = dcaPath(raw, x);
    const b0 = raw[0];
    return { s, y: raw.map(v => (log ? 100 * v / b0 : (v / b0 - 1) * 100)) };
  });

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

  const traces = area.concat(lines.map(({ s, y }) => ({
    x, y, name: fxSeriesLabel(sec, s.key), type: "scatter", mode: "lines",
    line: { color: fxSeriesColor(s), width: s.width },
    hovertemplate: (log ? "%{y:.0f}" : "%{y:.1f}%") +
                   "<extra>" + fxSeriesLabel(sec, s.key) + "</extra>",
  })));

  const bands = fxContextBands(sec.shades, x[0], x[x.length - 1]);
  const ink = cssVar("--ink"), grid = cssVar("--grid"),
        axis = cssVar("--axis"), card = cssVar("--card");
  const layout = {
    template: "plotly_white", autosize: true, height: 480,
    margin: { l: 64, r: 20, t: 18, b: 40 },
    paper_bgcolor: card, plot_bgcolor: card,
    hovermode: "x unified",
    shapes: bands.shapes, annotations: bands.annotations,
    hoverlabel: { bgcolor: card, bordercolor: cssVar("--hairline"),
                  font: { color: ink, size: 13,
                          family: "Libre Franklin, system-ui, sans-serif" } },
    font: { size: 14, color: ink, family: "Libre Franklin, system-ui, sans-serif" },
    legend: { orientation: "h", x: 0, y: 1.08,
              font: { size: 13, color: ink }, bgcolor: card },
    xaxis: { showgrid: true, griddash: "dot", gridcolor: grid,
             linecolor: axis, mirror: true, ticks: "outside",
             automargin: true, tickfont: { color: ink },
             tickformatstops: dateTickStops(), hoverformat: "%Y-%m-%d" },
    yaxis: { title: { text: log ? t("chart.growth") : t("chart.cumret"),
                      standoff: 12 },
             automargin: true, ticksuffix: log ? "" : "%",
             showgrid: true, griddash: "dot", gridcolor: grid,
             linecolor: axis, mirror: true, ticks: "outside",
             tickfont: { color: ink }, title_font: { color: ink },
             zeroline: !log, zerolinecolor: grid,
             type: log ? "log" : "linear" },
  };
  plotInto(`fx${k}-chart`, traces, layout);
}

/* ---------- monthly returns heat map ---------- */
function fxMonthlyReturns(k) {
  const sec = fxSection(k), st8 = FX.sec[k];
  const dates = sec.dates.slice(st8.i0, st8.i1 + 1);
  const eq = fxSeries(k, "strategy").slice(st8.i0, st8.i1 + 1);
  const order = [], lastOfMonth = new Map();
  for (let i = 0; i < dates.length; i++) {
    const key = dates[i].slice(0, 7);
    if (!lastOfMonth.has(key)) order.push(key);
    lastOfMonth.set(key, eq[i]);
  }
  const byYear = new Map();
  let prev = eq[0];
  for (const key of order) {
    const v = lastOfMonth.get(key);
    const r = v / prev - 1;
    prev = v;
    const y = key.slice(0, 4), m = parseInt(key.slice(5, 7), 10) - 1;
    if (!byYear.has(y)) byYear.set(y, new Array(12).fill(null));
    byYear.get(y)[m] = r;
  }
  return byYear;
}

function fxRenderMonthly(k) {
  const byYear = fxMonthlyReturns(k);
  const zero = _rgb(cssVar("--heat-zero"));
  const pos = _rgb(cssVar("--heat-pos"));
  const neg = _rgb(cssVar("--heat-neg"));
  const head = `<tr><th class="yr"></th>` +
    t(MONTHS_KEY).map(m => `<th>${m}</th>`).join("") +
    `<th class="tot">${t("monthly.year")}</th></tr>`;
  const rows = [...byYear.entries()].map(([y, months]) => {
    let growth = 1, any = false;
    const cells = months.map(r => {
      if (r === null) return `<td class="na">–</td>`;
      growth *= 1 + r; any = true;
      const { bg, fg } = heatColors(r, zero, pos, neg);
      return `<td class="cell" style="background:${bg};color:${fg}">` +
             `${(r * 100).toFixed(1)}</td>`;
    }).join("");
    const yr = growth - 1;
    const tot = any
      ? `<td class="tot ${yr < 0 ? "neg" : "gain"}">${(yr * 100).toFixed(1)}</td>`
      : `<td class="tot na">–</td>`;
    return `<tr><th class="yr">${y}</th>${cells}${tot}</tr>`;
  }).join("");
  document.getElementById(`fx${k}-monthly`).innerHTML = head + rows;
}

/* ---------- allocation table + donut ---------- */
function fxCurrentAmount(k) {
  const v = parseFloat(document.getElementById(`fx${k}-amount`).value);
  return isFinite(v) && v > 0 ? v : 100000;
}

function fxRenderAllocation(k) {
  const sec = fxSection(k);
  const alloc = sec.allocation || [];
  const amt = fxCurrentAmount(k);
  document.getElementById(`fx${k}-alloc-body`).innerHTML = alloc.map(a => {
    const dollars = Math.round(amt * a.weight);
    const shares = a.price > 0 ? Math.floor(dollars / a.price) : 0;
    return `<tr>
      <td class="sym">${esc(a.symbol)}</td><td class="name">${esc(a.name)}</td>
      <td class="r">${pct(a.weight, 1)}</td>
      <td class="r">$${dollars.toLocaleString()}</td>
      <td class="r">$${a.price.toFixed(2)}</td>
      <td class="r">${shares.toLocaleString()}</td></tr>`;
  }).join("");

  plotInto(`fx${k}-pie`, [{
    type: "pie", hole: 0.55, sort: false,
    labels: alloc.map(a => a.symbol),
    values: alloc.map(a => a.weight),
    marker: { colors: alloc.map(a => fxLegColor(a.symbol)),
              line: { color: cssVar("--card"), width: 1.5 } },
    textinfo: "label+percent", textposition: "outside", automargin: true,
    hovertemplate: "%{label}  %{percent}<extra></extra>",
  }], {
    height: 380, margin: { l: 34, r: 34, t: 38, b: 38 }, showlegend: false,
    paper_bgcolor: cssVar("--card"), plot_bgcolor: cssVar("--card"),
    font: { size: 13, color: cssVar("--ink"),
            family: "IBM Plex Mono, monospace" },
  });
}

/* ---------- period control (per section) ---------- */
function fxSyncLabels(k) {
  const sec = fxSection(k), st8 = FX.sec[k];
  document.getElementById(`fx${k}-from-label`).textContent = sec.dates[st8.i0];
  document.getElementById(`fx${k}-to-label`).textContent = sec.dates[st8.i1];
}

function fxSetRange(k, i0, i1) {
  const sec = fxSection(k), st8 = FX.sec[k], n = sec.dates.length;
  st8.i0 = Math.max(0, Math.min(i0, n - 2));
  st8.i1 = Math.max(st8.i0 + 1, Math.min(i1, n - 1));
  document.getElementById(`fx${k}-from`).value = st8.i0;
  document.getElementById(`fx${k}-to`).value = st8.i1;
  fxSyncLabels(k);
  fxRenderStats(k);
  fxRenderMonthly(k);
  fxRenderChart(k);
}

function fxSetYears(k, y) {
  const n = fxSection(k).dates.length;
  if (y === null) { fxSetRange(k, 0, n - 1); return; }
  fxSetRange(k, Math.max(0, n - 1 - Math.round(y * 252)), n - 1);
}

/* Full repaint of one section (theme/language change bake colours in). */
function fxRenderSection(k) {
  fxRenderStats(k);
  fxRenderMonthly(k);
  fxRenderChart(k);
  fxRenderAllocation(k);
}

function fxRenderAll() {
  if (!FX.data) return;
  FX.data.section_order.forEach(fxRenderSection);
}

/* ---------- boot ---------- */
async function loadFixed() {
  const host = document.getElementById("fx-panel");
  const msg = document.getElementById("fx-message");
  if (FX.data) {
    // Already loaded: just make sure the charts size to the now-visible panel.
    if (typeof Plotly !== "undefined") {
      FX.data.section_order.forEach(k => {
        Plotly.Plots.resize(`fx${k}-chart`);
        Plotly.Plots.resize(`fx${k}-pie`);
      });
    }
    return;
  }
  msg.hidden = false;
  msg.innerHTML = "Loading the fixed allocations…";
  try {
    const resp = await fetch("/api/strategy/fixed");
    if (!resp.ok) {
      const detail = (await resp.json().catch(() => ({}))).detail || resp.statusText;
      msg.innerHTML = "<strong>Fixed allocations not available.</strong> " +
        detail + "<br>Build them with " +
        "<code>python -m app.update --strategy-only</code>, then reload.";
      host.hidden = true;
      return;
    }
    FX.data = await resp.json();
  } catch (err) {
    msg.innerHTML = "<strong>Could not load the fixed allocations.</strong> " + err;
    host.hidden = true;
    return;
  }
  bootFixed();
  fxWireOnce();
}

function bootFixed() {
  const d = FX.data;
  document.getElementById("fx-message").hidden = true;
  document.getElementById("fx-panel").hidden = false;

  const want = parseInt(document.body.dataset.payloadVersion || "0", 10);
  const stale = document.getElementById("fx-stale");
  // The fixed payload carries its OWN version line; only warn when it is behind
  // the code, mirroring the dynamic panel's staleness note.
  const got = parseInt(d.payload_version || 0, 10);
  if (stale && got < 1) {
    stale.hidden = false;
    stale.innerHTML = "<strong>This cache looks incomplete.</strong> " +
      "Rebuild with <code>python -m app.update --strategy-only</code>.";
  } else if (stale) {
    stale.hidden = true;
  }

  const defYears = parseFloat(document.body.dataset.defaultYears)
                   || d.default_years || 5;
  d.section_order.forEach(k => {
    const sec = d.sections[k], n = sec.dates.length;
    document.getElementById(`fx${k}-asof`).textContent = sec.as_of;
    document.getElementById(`fx${k}-start`).textContent = sec.start;
    document.getElementById(`fx${k}-alloc-date`).textContent =
      sec.allocation_date || sec.as_of;
    document.getElementById(`fx${k}-from`).max = n - 1;
    document.getElementById(`fx${k}-to`).max = n - 1;
    FX.sec[k].log = false;
    FX.sec[k].rebal = d.default_rebal || "annual";
    const lbox = document.getElementById(`fx${k}-log`);
    if (lbox) lbox.checked = false;
    const rbox = document.getElementById(`fx${k}-rebal`);
    if (rbox) rbox.value = FX.sec[k].rebal;
    document.querySelectorAll(`.fx-quick[data-section="${k}"]`).forEach(b =>
      b.setAttribute("aria-pressed", String(b.dataset.years === String(defYears))));
    fxSetYears(k, defYears);
    fxRenderAllocation(k);
  });
}

let _fxWired = false;
function fxWireOnce() {
  if (_fxWired) return;
  _fxWired = true;
  FX.data.section_order.forEach(k => {
    const from = document.getElementById(`fx${k}-from`);
    const to = document.getElementById(`fx${k}-to`);
    from.addEventListener("input", () => fxSetRange(k, +from.value, FX.sec[k].i1));
    to.addEventListener("input", () => fxSetRange(k, FX.sec[k].i0, +to.value));
    document.querySelectorAll(`.fx-quick[data-section="${k}"]`).forEach(b => {
      b.addEventListener("click", () => {
        document.querySelectorAll(`.fx-quick[data-section="${k}"]`).forEach(x =>
          x.setAttribute("aria-pressed", String(x === b)));
        fxSetYears(k, b.dataset.years === "max" ? null : +b.dataset.years);
      });
    });
    document.getElementById(`fx${k}-log`).addEventListener("change", e => {
      FX.sec[k].log = e.target.checked;
      fxRenderChart(k);
    });
    // Rebalance schedule: evaluation-only, so it repaints the curve, the stats
    // and the monthly heat map, but never the allocation or the CSV export.
    const rbox = document.getElementById(`fx${k}-rebal`);
    if (rbox) rbox.addEventListener("change", e => {
      FX.sec[k].rebal = e.target.value;
      fxRenderStats(k);
      fxRenderMonthly(k);
      fxRenderChart(k);
    });
    document.getElementById(`fx${k}-amount`)
      .addEventListener("input", () => fxRenderAllocation(k));
    document.getElementById(`fx${k}-export`).addEventListener("click", () => {
      window.location = "/api/strategy/fixed/allocations.csv?section=" +
        encodeURIComponent(k) + "&amount=" + fxCurrentAmount(k);
    });
  });
}
