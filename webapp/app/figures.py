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
legend_fontsize = 10

GRID = dict(showgrid=True, griddash="dot", gridcolor="rgba(150,150,150,0.55)")
NOGRID = dict(showgrid=False)
MPL_C0 = "#1f77b4"          # matplotlib default-cycle blue (GDP line)
MPL_M = "#bf00bf"           # matplotlib letter-code "m" (muted magenta)
MPL_C = "#00bfbf"           # matplotlib letter-code "c" (muted cyan)

cities_of_interest = [
    "National", "Chicago", "SanFrancisco", "LosAngeles", "SanDiego",
    "Portland", "Seattle", "Phoenix", "Dallas",
]
colors = [
    "black", "green", "blue", "cyan", "magenta", "red",
    "yellow", "darkblue", "pink", "purple", "orange", "brown",
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
        line=dict(color=color, width=width, dash=dash),
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
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor="rgba(150,150,150,0.9)", borderwidth=1,
        )})
        return name


def style_figure(fig, xlim=None, height=1000):
    fig.update_layout(
        template="plotly_white",
        plot_bgcolor="white", paper_bgcolor="white",
        autosize=True, height=height,
        margin=dict(l=60, r=60, t=60, b=40),
        font=dict(size=12),
    )
    fig.update_xaxes(**GRID, ticks="outside",
                     linecolor="black", mirror=True, zeroline=False)
    fig.update_yaxes(**GRID, ticks="outside",
                     linecolor="black", mirror=True, zeroline=False,
                     secondary_y=False)
    fig.update_yaxes(**NOGRID, secondary_y=True)
    if xlim is not None:
        fig.update_xaxes(range=[_range_str(v) for v in xlim])


def build_fig_markets(d, todaystr, xlim):
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            f"Stock and Gold as of {todaystr}",
            f"S&P500 / Gold as of {todaystr}",
            f"Inflation Index (10 years ago = 100) as of {todaystr}",
            f"S&P500 vs. GDP and M2 as of {todaystr}",
            f"Money Supply and GDP as of {todaystr}",
            f"Stock Market Valuation - Ratios as of {todaystr}",
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
    baseline_date = pd.Timestamp(date(date.today().year - baseline_yearsago,
                                      date.today().month, date.today().day))
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

    fig.add_trace(line(d["ShillerPE10"], "Shiller P/E 10", "blue",
                       legend=lm.new(3, 2, "upper left")), row=3, col=2)
    fig.add_trace(line(d["TobinQ"], "Tobin's Q", "red",
                       legend=lm.new(3, 2, "upper right")),
                  row=3, col=2, secondary_y=True)

    style_figure(fig, xlim=xlim)
    return fig


def build_fig_rates_stress(d, todaystr, xlim):
    fig = make_subplots(
        rows=3, cols=2,
        subplot_titles=(
            f"Treasury Zero-Coupon Yield as of {todaystr}",
            f"Stock Market and Interest Rate Structure as of {todaystr}",
            f"Financial Stress Indicators (1) as of {todaystr}",
            f"Financial Stress Indicators (2) as of {todaystr}",
            f"Financial Stress Indicators (3) as of {todaystr}",
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
                             line=dict(color="red", width=1.5),
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
            f"Population as of {todaystr}",
            f"Labor Market Condition as of {todaystr}",
            f"S&P/Case-Shiller Home Price Indices as of {todaystr}",
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
                               font=dict(size=11, color="#999"),
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
                   font=dict(size=14)),
    )
    fig.update_xaxes(**GRID, tickfont=dict(size=7), ticks="outside",
                     linecolor="black", mirror=True, zeroline=False)
    fig.update_yaxes(**GRID, tickfont=dict(size=7), ticks="outside",
                     linecolor="black", mirror=True, zeroline=False)
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
            f"Futures - Long Term ({future_yrs_long}-year) as of {todaystr}",
            fixed_xlim=True),
        "futures-short": build_fig_futures(
            all_data, todaystr, start_short, xlim_end,
            f"Futures - Short Term ({future_yrs_short}-year) as of {todaystr}",
            fixed_xlim=False),
    }
