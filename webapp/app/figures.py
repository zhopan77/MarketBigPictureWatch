"""
Figure builders.  This is the plotting code verified trace-by-trace against
the original matplotlib script, adapted for the web:

  - figures autosize to the browser instead of a fixed 1920x1080
  - each figure is serialized to JSON once at update time, so page loads
    never pay the figure-building cost

Requires plotly >= 5.15 (multiple legends).
"""

from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

macro_yrs_ultralong = 30
future_yrs_long = 8
future_yrs_short = 1
legend_fontsize = 12

# A solid hairline grid at low opacity reads cleaner at high DPI than a dotted
# one, which goes fuzzy once the browser scales it.
GRID = dict(showgrid=True, griddash="solid",
            gridcolor="rgba(120,130,145,0.22)", gridwidth=1)
NOGRID = dict(showgrid=False)
AXIS_LINE = "rgba(120,130,145,0.55)"
FONT_FAMILY = ("Libre Franklin, system-ui, -apple-system, 'Segoe UI', "
               "Roboto, sans-serif")

# ---------------------------------------------------------------------
# Palette
#
# The builders name their colours ("blue", "red", ...) which historically
# resolved to the CSS primaries: pure #0000FF, #FFFF00, #FF00FF and so on.
# Those are what made the charts look like 1990s gnuplot output, and yellow
# on white was close to invisible. Resolving the same names through this
# table restyles every call site at once, without touching a single builder.
#
# Chosen for even perceived weight (no colour shouts louder than its
# neighbours), separation in hue rather than just lightness, and enough
# darkness to stay legible on white.
# ---------------------------------------------------------------------
PALETTE = {
    "blue":      "#3b7dd8",
    "red":       "#d1495b",
    "green":     "#2a9d5c",
    "orange":    "#d06a26",
    "magenta":   "#a05195",
    "purple":    "#7c5cbf",
    "cyan":      "#2ba0a8",
    "aqua":      "#2ba0a8",
    "yellow":    "#b38c14",   # dark enough to read on white, unlike #FFFF00
    "gold":      "#b3820f",
    "pink":      "#c4658d",
    "brown":     "#8c6d4f",
    "black":     "#2b3038",   # soft near-black rather than pure
    "darkblue":  "#1f4e8c",
    "darkgreen": "#1c6b45",
}


def _col(c):
    """Resolve a palette name; pass hex and None straight through."""
    if isinstance(c, str):
        return PALETTE.get(c, c)
    return c


MPL_C0 = PALETTE["blue"]     # GDP line
MPL_M = PALETTE["magenta"]
MPL_C = PALETTE["cyan"]

cities_of_interest = [
    "National", "Chicago", "SanFrancisco", "LosAngeles", "SanDiego",
    "Portland", "Seattle", "Phoenix", "Dallas",
]
# Case-Shiller city cycle. Ordered for MAXIMUM hue separation rather than
# following the old sequence: nine lines share one subplot, and the previous
# order put magenta, red and pink together, which are hard to tell apart once
# dark mode lifts them toward each other.
colors = [
    PALETTE["black"], PALETTE["blue"], PALETTE["green"], PALETTE["orange"],
    PALETTE["magenta"], PALETTE["cyan"], PALETTE["red"], PALETTE["darkblue"],
    PALETTE["brown"], PALETTE["purple"], PALETTE["gold"], PALETTE["pink"],
]


def _dates_to_str(x):
    """Serialize dates as plain 'YYYY-MM-DD' strings.

    Different plotly/pandas/numpy version combinations serialize datetime64
    arrays differently (ns-precision strings, tz offsets, epoch integers,
    binary typed arrays), and not all of them are parsed identically by all
    plotly.js versions.  Plain date strings are parsed the same everywhere,
    and the data is daily so nothing is lost.
    """
    if hasattr(x, "dt"):
        if getattr(x.dt, "tz", None) is not None:
            x = x.dt.tz_localize(None)
        return x.dt.strftime("%Y-%m-%d")
    return x


def _range_str(v):
    """Axis range endpoint as a plain 'YYYY-MM-DD' string."""
    return pd.Timestamp(v).strftime("%Y-%m-%d")


def line(df, name, color=None, width=1.5, dash=None, legend=None,
         showlegend=True):
    return go.Scatter(
        x=_dates_to_str(df["date"]), y=df["value"], name=name, mode="lines",
        showlegend=showlegend, legend=legend,
        line=dict(color=_col(color), width=width, dash=dash),
    )


class LegendManager:
    LOCS = {
        "upper left":   (0.01, 0.99, "left",   "top"),
        "upper center": (0.50, 0.99, "center", "top"),
        "upper right":  (0.99, 0.99, "right",  "top"),
        "lower left":   (0.01, 0.01, "left",   "bottom"),
        "lower center": (0.50, 0.01, "center", "bottom"),
        "lower right":  (0.99, 0.01, "right",  "bottom"),
    }

    def __init__(self, fig):
        self.fig = fig
        self.count = 0

    def new(self, row, col, loc="upper left"):
        self.count += 1
        name = "legend" if self.count == 1 else f"legend{self.count}"
        sp = self.fig.get_subplot(row, col)
        xd, yd = sp.xaxis.domain, sp.yaxis.domain
        fx, fy, xanchor, yanchor = self.LOCS[loc]
        self.fig.update_layout({name: dict(
            x=xd[0] + fx * (xd[1] - xd[0]),
            y=yd[0] + fy * (yd[1] - yd[0]),
            xanchor=xanchor, yanchor=yanchor,
            font=dict(size=legend_fontsize),
            bgcolor="rgba(255,255,255,0.82)",
            bordercolor="rgba(120,130,145,0.35)", borderwidth=1,
        )})
        return name


def style_figure(fig, xlim=None, height=1000):
    fig.update_layout(
        template="plotly_white",
        plot_bgcolor="white", paper_bgcolor="white",
        autosize=True, height=height,
        margin=dict(l=60, r=60, t=60, b=40),
        font=dict(size=14, family=FONT_FAMILY, color="#2b3038"),
    )
    # A hairline frame instead of the old heavy black box: still a crisp
    # boundary, but it no longer competes with the data inside it.
    fig.update_xaxes(**GRID, ticks="outside", ticklen=4,
                     tickcolor=AXIS_LINE,
                     linecolor=AXIS_LINE, linewidth=1, mirror=True,
                     zeroline=False)
    fig.update_yaxes(**GRID, ticks="outside", ticklen=4,
                     tickcolor=AXIS_LINE,
                     linecolor=AXIS_LINE, linewidth=1, mirror=True,
                     zeroline=False, secondary_y=False)
    fig.update_yaxes(**NOGRID, secondary_y=True)
    if xlim is not None:
        fig.update_xaxes(range=[_range_str(v) for v in xlim])


def build_fig_markets(d, todaystr, xlim):
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Stock and Gold",
            "S&P500 / Gold",
            "Inflation Index (10 years ago = 100)",
            "S&P500 vs. GDP and M2",
            "Money Supply and GDP",
            "Stock Market Valuation - Ratios",
        ),
        specs=[[{"secondary_y": True},  {"secondary_y": False}],
               [{"secondary_y": False}, {"secondary_y": True}],
               [{"secondary_y": True},  {"secondary_y": True}]],
        vertical_spacing=0.09, horizontal_spacing=0.07,
    )
    lm = LegendManager(fig)

    fig.add_trace(line(d["SP500"], "S&P500", "blue",
                       legend=lm.new(1, 1, "upper left")), row=1, col=1)
    fig.add_trace(line(d["gold"], "Gold", "red",
                       legend=lm.new(1, 1, "lower right")),
                  row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="USD/OZ", row=1, col=1, secondary_y=True)

    fig.add_trace(line(d["SP500_gold"], "S&P500 / Gold", "blue",
                       showlegend=False), row=1, col=2)

    baseline_yearsago = 10
    # Subtracting years by rebuilding the date crashes on 29 February -- there
    # is no 29 Feb ten years earlier, so date() raises "day is out of range for
    # month" and the whole figure build fails. Next occurrence: 2028-02-29.
    # Offsetting the Timestamp instead clamps to the 28th like every other
    # date library does.
    baseline_date = pd.Timestamp(date.today()) - pd.DateOffset(
        years=baseline_yearsago)
    leg_infl = lm.new(2, 1, "upper left")
    infl_series = [
        ("cpi",           "CPI",           "blue",    "dot", 4),
        ("cpi_food",      "CPI:Food",      "green",   None,  1.5),
        ("cpi_housing",   "CPI:Housing",   "aqua",    None,  1.5),
        ("cpi_medical",   "CPI:Medical",   "magenta", None,  1.5),
        ("cpi_education", "CPI:Education", "gold",    None,  1.5),
        ("gdpdef",        "GDP Deflator",  "red",     "dot", 4),
    ]
    for key, name, color, dash, width in infl_series:
        df_s = d[key]
        baseline = df_s.loc[df_s["date"] >= baseline_date, "value"].iloc[0]
        df_norm = df_s.copy()
        df_norm["value"] = df_norm["value"] / baseline * 100.0
        fig.add_trace(line(df_norm, name, color, width=width, dash=dash,
                           legend=leg_infl), row=2, col=1)
    fig.update_yaxes(title_text="Index", row=2, col=1)

    fig.add_trace(line(d["SP500_gdp"], "S&P500 / GDP", "blue",
                       legend=lm.new(2, 2, "upper left")), row=2, col=2)
    fig.add_trace(line(d["SP500_M2"], "S&P500 / M2", "red",
                       legend=lm.new(2, 2, "upper right")),
                  row=2, col=2, secondary_y=True)

    leg_ms = lm.new(3, 1, "upper left")
    fig.add_trace(line(d["MB"], "MB", "blue", legend=leg_ms), row=3, col=1)
    fig.add_trace(line(d["M2"], "M2", "red", legend=leg_ms), row=3, col=1)
    fig.add_trace(line(d["GDP"], "GDP", MPL_C0, legend=leg_ms), row=3, col=1)
    fig.add_trace(line(d["RealGDP"], "Real GDP (2009 USD)", "darkgreen",
                       legend=leg_ms), row=3, col=1)
    leg_ms2 = lm.new(3, 1, "upper center")
    fig.add_trace(line(d["MB_GDP"], "MB/GDP", MPL_M, dash="dash",
                       legend=leg_ms2), row=3, col=1, secondary_y=True)
    fig.add_trace(line(d["M2_GDP"], "M2/GDP", MPL_C, dash="dash",
                       legend=leg_ms2), row=3, col=1, secondary_y=True)
    fig.update_yaxes(title_text="USD Bln", row=3, col=1, secondary_y=False)

    # Both series run high and to the right in the recent data, so top-anchored
    # legends sat on top of the curves. Anchored low instead: the lower left of
    # this panel is empty for the whole modern era.
    fig.add_trace(line(d["ShillerPE10"], "Shiller P/E 10", "blue",
                       legend=lm.new(3, 2, "lower left")), row=3, col=2)
    fig.add_trace(line(d["BuffettIndicator"], "Buffett Indicator", "red",
                       legend=lm.new(3, 2, "lower right")),
                  row=3, col=2, secondary_y=True)

    style_figure(fig, xlim=xlim)
    return fig


def build_fig_rates_stress(d, todaystr, xlim):
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            "Treasury Zero-Coupon Yield",
            "Stock Market and Interest Rate Structure",
            "Financial Stress Indicators (1)",
            "Financial Stress Indicators (2)",
            "Financial Stress Indicators (3)",
            "",
        ),
        specs=[[{"secondary_y": False}, {"secondary_y": True}],
               [{"secondary_y": True},  {"secondary_y": True}],
               [{"secondary_y": True},  None]],
        vertical_spacing=0.09, horizontal_spacing=0.07,
    )
    lm = LegendManager(fig)

    leg_ty = lm.new(1, 1, "upper left")
    for key, name, color in [
        ("treasury_yield20", "20 Yr", "blue"),
        ("treasury_yield10", "10 Yr", "green"),
        ("treasury_yield5",  "5 Yr",  "yellow"),
        ("treasury_yield2",  "2 Yr",  "orange"),
        ("treasury_yield1",  "1 Yr",  "red"),
    ]:
        fig.add_trace(line(d[key], name, color, width=0.5, legend=leg_ty),
                      row=1, col=1)
    fig.update_yaxes(title_text="%", row=1, col=1)

    fig.add_trace(line(d["SP500"], "S&P500", "blue",
                       legend=lm.new(1, 2, "upper left")), row=1, col=2)
    leg_sp = lm.new(1, 2, "upper center")
    fig.add_trace(line(d["treasury_yield_spread"], "1Yr/15Yr", "magenta",
                       width=1, legend=leg_sp), row=1, col=2, secondary_y=True)
    fig.add_trace(line(d["treasury_yield_spread_adj"], "1Yr/15Yr_MBAdj",
                       "cyan", width=1, legend=leg_sp),
                  row=1, col=2, secondary_y=True)
    first_date = d["treasury_yield_spread"]["date"].iloc[0]
    last_date = d["treasury_yield_spread"]["date"].iloc[-1]
    fig.add_trace(go.Scatter(x=[first_date, last_date], y=[1, 1], mode="lines",
                             line=dict(color=_col("red"), width=1.5,
                                       dash="dash"),
                             showlegend=False, hoverinfo="skip"),
                  row=1, col=2, secondary_y=True)

    fig.add_trace(line(d["vix"], "VIX", "blue",
                       legend=lm.new(2, 1, "upper left")), row=2, col=1)
    leg_fs1 = lm.new(2, 1, "upper right")
    fig.add_trace(line(d["tedspread"], "TED Spread (discontinued)", "magenta",
                       width=1, legend=leg_fs1), row=2, col=1, secondary_y=True)
    fig.add_trace(line(d["SOFR_t3m"], "SOFR-T-bill Spread", "purple",
                       width=1, legend=leg_fs1), row=2, col=1, secondary_y=True)
    fig.update_yaxes(title_text="%", row=2, col=1, secondary_y=True)

    fig.add_trace(line(d["SP500"], "S&P500", "blue",
                       legend=lm.new(2, 2, "upper left")), row=2, col=2)
    leg_fs2 = lm.new(2, 2, "upper center")
    fig.add_trace(line(d["stl_fsi"], "St. Louis Fed FSI", "red", width=1,
                       legend=leg_fs2), row=2, col=2, secondary_y=True)
    fig.add_trace(line(d["kc_fsi"], "Kansas City FSI", "green", width=1,
                       legend=leg_fs2), row=2, col=2, secondary_y=True)

    fig.add_trace(line(d["SP500"], "S&P500", "blue",
                       legend=lm.new(3, 1, "upper left")), row=3, col=1)
    leg_fs3 = lm.new(3, 1, "upper center")
    fig.add_trace(line(d["c_fsi"], "Cleveland FSI (discontinued)", "red",
                       width=1, legend=leg_fs3), row=3, col=1, secondary_y=True)
    fig.add_trace(line(d["anfci"], "Chicago Fed Adjusted National FCI",
                       "green", width=1, legend=leg_fs3),
                  row=3, col=1, secondary_y=True)

    style_figure(fig, xlim=xlim)
    return fig


def build_fig_economy(d, todaystr, xlim):
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Population",
            "Labor Market Condition",
            "S&P/Case-Shiller Home Price Indices",
            "",
        ),
        specs=[[{"secondary_y": True}, {"secondary_y": True}],
               [{"secondary_y": False}, None]],
        vertical_spacing=0.12, horizontal_spacing=0.07,
    )
    lm = LegendManager(fig)

    leg_pop = lm.new(1, 1, "upper left")
    fig.add_trace(line(d["population"].assign(value=d["population"]["value"] / 1e6),
                       "Population", "blue", width=1, dash="dash",
                       legend=leg_pop), row=1, col=1)
    fig.add_trace(line(d["wa_population"].assign(value=d["wa_population"]["value"] / 1e6),
                       "Working Age (15-64) Population", "magenta", width=1,
                       dash="dash", legend=leg_pop), row=1, col=1)
    leg_gpc = lm.new(1, 1, "lower right")
    fig.add_trace(line(d["gdp_per_capita"], "GDP Per Capita", "red", width=1,
                       legend=leg_gpc), row=1, col=1, secondary_y=True)
    fig.add_trace(line(d["realgdp_per_capita"],
                       "Real GDP Per Capita (2009 USD)", "green", width=1,
                       legend=leg_gpc), row=1, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Bln Persons", row=1, col=1, secondary_y=False)
    fig.update_yaxes(title_text="K USD", row=1, col=1, secondary_y=True)

    leg_lab = lm.new(1, 2, "lower left")
    fig.add_trace(line(d["epr"], "Employment-Population Ratio", "green",
                       width=1, legend=leg_lab), row=1, col=2)
    fig.add_trace(line(d["lfpr"], "Labor Force Participation Rate", "blue",
                       width=1, legend=leg_lab), row=1, col=2)
    fig.add_trace(line(d["uer"], "Unemployment Rate", "red", width=1,
                       legend=lm.new(1, 2, "upper center")),
                  row=1, col=2, secondary_y=True)
    fig.update_yaxes(title_text="%", row=1, col=2, secondary_y=False)
    fig.update_yaxes(title_text="%", row=1, col=2, secondary_y=True)

    leg_cs = lm.new(2, 1, "upper left")
    for n, city in enumerate(cities_of_interest):
        lw = 3 if city in ["National", "Chicago", "SanFrancisco"] else 1
        fig.add_trace(line(d["caseshiller"][city], city, colors[n], width=lw,
                           legend=leg_cs), row=2, col=1)

    style_figure(fig, xlim=xlim)
    return fig


def build_fig_futures(d, todaystr, start_date, xlim_end, suptitle,
                      fixed_xlim):
    fig = make_subplots(rows=4, cols=5,
                        vertical_spacing=0.06, horizontal_spacing=0.04)
    lm = LegendManager(fig)
    start_ts = pd.Timestamp(start_date)

    for i, comdty in enumerate(d["futures_underlying"]):
        r, c = (i // 5) + 1, (i % 5) + 1
        df_fut = d["futures_prices"][comdty]
        if not df_fut.empty and getattr(df_fut["date"].dt, "tz", None) is not None:
            df_fut = df_fut.assign(date=df_fut["date"].dt.tz_localize(None))
        
        # FIX: Always filter to the target window before adding the trace.
        # This ensures the Y-axis scales only to the data visible in the window.
        df_fut = df_fut[(df_fut["date"] >= start_ts) & (df_fut["date"] <= xlim_end)]

        if not df_fut.empty:
            fig.add_trace(line(df_fut, comdty, "blue", width=1,
                               legend=lm.new(r, c, "upper left")),
                          row=r, col=c)
        else:
            # make the failed download visible instead of leaving a hole:
            # an empty named trace keeps the panel axes and legend alive,
            # and the annotation says what's missing
            fig.add_trace(line(pd.DataFrame({"date": [], "value": []}),
                               comdty, "blue", width=1,
                               legend=lm.new(r, c, "upper left")),
                          row=r, col=c)
            fig.add_annotation(text=comdty + "<br>(no data)", showarrow=False,
                               font=dict(size=13, color="#999"),
                               x=0.5, y=0.5, xref="x domain", yref="y domain",
                               row=r, col=c)
        if fixed_xlim:
            fig.update_xaxes(range=[_range_str(start_ts), _range_str(xlim_end)],
                             row=r, col=c)

    fig.update_layout(
        template="plotly_white",
        plot_bgcolor="white", paper_bgcolor="white",
        autosize=True, height=1000,
        margin=dict(l=50, r=30, t=70, b=30),
        title=dict(text=suptitle, x=0.5, xanchor="center",
                   font=dict(size=16)),
        font=dict(family=FONT_FAMILY, color="#2b3038"),
    )
    # These panels style their own axes rather than going through
    # style_figure(), so the modernised frame has to be applied here too.
    fig.update_xaxes(**GRID, tickfont=dict(size=9), ticks="outside", ticklen=4,
                     tickcolor=AXIS_LINE, linecolor=AXIS_LINE, linewidth=1,
                     mirror=True, zeroline=False)
    fig.update_yaxes(**GRID, tickfont=dict(size=9), ticks="outside", ticklen=4,
                     tickcolor=AXIS_LINE, linecolor=AXIS_LINE, linewidth=1,
                     mirror=True, zeroline=False)
    return fig


# Registry: slug -> human title.  Order defines the nav order.
FIGURES = {
    "markets":       "Markets, Inflation & Money",
    "rates-stress":  "Rates & Financial Stress",
    "economy":       "Population, Labor & Housing",
    "futures-long":  f"Futures — Long Term ({future_yrs_long}y)",
    "futures-short": f"Futures — Short Term ({future_yrs_short}y)",
}


def build_all_figures(all_data: dict) -> dict[str, go.Figure]:
    """Build every figure.  Returns {slug: plotly Figure}."""
    todaystr = date.today().strftime("%Y-%m-%d")
    date_plotend = date.today()
    date_plotstart = date_plotend - timedelta(
        days=int(round(macro_yrs_ultralong * 365.25)))
    xlim = (pd.Timestamp(date_plotstart), pd.Timestamp(date_plotend))
    xlim_end = xlim[1]
    start_long = date_plotend - timedelta(days=int(round(future_yrs_long * 365.25)))
    start_short = date_plotend - timedelta(days=int(round(future_yrs_short * 365.25)))

    return {
        "markets": build_fig_markets(all_data, todaystr, xlim),
        "rates-stress": build_fig_rates_stress(all_data, todaystr, xlim),
        "economy": build_fig_economy(all_data, todaystr, xlim),
        "futures-long": build_fig_futures(
            all_data, todaystr, start_long, xlim_end,
            f"Futures - Long Term ({future_yrs_long}-year)",
            fixed_xlim=True),
        "futures-short": build_fig_futures(
            all_data, todaystr, start_short, xlim_end,
            f"Futures - Short Term ({future_yrs_short}-year)",
            fixed_xlim=False),
    }
