/* Translation layer.
 *
 * Two mechanisms, because the page has two kinds of text:
 *   - static markup carries data-i18n="key" and is swapped in place;
 *   - strings built in JS call t("key") at render time.
 * Changing language therefore means: set the flag, swap the markup, re-render.
 *
 * Chinese here is Simplified, in a financial register rather than a literal
 * gloss: "sleeve" becomes 增强仓 (enhancement position) rather than a
 * word-for-word translation, and the ratio names use their standard Chinese
 * finance terms (夏普比率, 索提诺比率, 最大回撤).
 *
 * NOT translated: the contents of the macro charts on tabs 01-05. Their
 * titles and axis labels are baked into the figure JSON at build time, so
 * translating them means rebuilding the figures per language.
 */

const I18N = {
  en: {
    "app.title_1": "Market Big Picture",
    "app.title_2": "and Long-term Strategies",
    "app.title_full": "Market Big Picture and Long-term Strategies",
    "app.tagline": "See the big picture. Weather the market. Build wealth steadily.",
    "app.updated": "data updated",
    "app.nodata": "no data yet",
    "app.dark": "Dark mode",
    "app.lang": "Language",

    "tab.markets": "Markets, Inflation & Money",
    "tab.rates-stress": "Rates & Financial Stress",
    "tab.economy": "Population, Labor & Housing",
    "tab.futures-long": "Futures \u2014 Long Term (8y)",
    "tab.futures-short": "Futures \u2014 Short Term (1y)",
    "tab.all-weather-fixed": "Classical Fixed",
    "tab.all-weather": "All Weather Dynamic",
    "tab.all-weather-lev": "All Weather Dynamic Leverage",
    "tab.all-weather-lev3": "All Weather Dynamic High Leverage",
    "panel.leverage3x": "All Weather Dynamic High Leverage",

    "fx.title": "Classical Fixed",
    "fx.lede": "Well-known static allocations you rebalance about once a year — included for comparison, not as our recommended approach (see the dynamic strategies). Same backtest engine and benchmarks.",
    "fx.since": "since",
    "fx.rebalance": "rebalance",
    "fx.annual": "annual",
    "fx.rebal.tip": "For performance evaluation only — changes the backtested curve and its statistics, not the target allocation or the CSV export.",
    "fx.rebal.none": "None (buy & hold)",
    "fx.rebal.annual": "Annually (Jan 1)",
    "fx.rebal.semi": "Semi-annually (Jan, Jul)",
    "fx.rebal.quarterly": "Quarterly (Jan, Apr, Jul, Oct)",
    "fx.monthly.caption": "portfolio, % — selected period; the first month is partial unless the period starts on a month boundary",
    "fx.foot": "Backtested with a long-history small-cap value proxy (IJS); your tradeable choice may differ (AVUV/VBR).",
    "fx.A.name": "60/40",
    "fx.B.name": "Golden Butterfly",
    "fx.C.name": "Equity-Tilted All-Weather",
    "fx.A.blurb": "The textbook 60% stocks / 40% bonds balanced portfolio — the most common benchmark in the industry. Included for reference, not a recommended strategy; rebalanced once a year.",
    "fx.B.ref": "A well-known “lazy” portfolio popular with the FIRE crowd, created by Portfolio Charts:",
    "fx.B.reflink": "Golden Butterfly on Portfolio Charts →",
    "fx.B.blurb": "Five equal fifths — total US market, small-cap value, long- and short-term Treasuries, and gold. The lowest-maintenance mix and the tightest historical drawdown; rebalanced once a year. Built for low drawdown and consistency, not maximum return.",
    "fx.C.blurb": "~55% US equity (with a small-cap value tilt), duration-balanced Treasuries, and a 20% gold anchor. Weights optimized on 2006–2026 history for a better risk-adjusted return (Sharpe) than a plain 60/40; rebalanced once a year.",
    "app.partial": "partial data",
    "crisis.Dot-com": "Dot-com",
    "crisis.GFC": "GFC",
    "crisis.bear": " bear",
    "crisis.COVID": "COVID",
    "crisis.Liberation Day": "Liberation Day",
    "crisis.Iran war": "Iran war",
    "brake.on": "vol brake",
    "brake.hint": "scales the whole book down when its own realised volatility runs hot",
    "dl.balancer": "Portfolio Balancer",
    "dl.balancer_tip": "Desktop app that turns a target allocation into broker orders",
    "bands.title": "Composition",
    "bands.caption": "share of the book held in each leg; click a row in the log below to mark that date",
    "panel.base": "All Weather Dynamic",
    "panel.leverage": "All Weather Dynamic Leverage",

    "fact.through": "through",
    "fact.sleeve": "sleeve",
    "fact.lastadj": "last adjustment",
    "fact.nextupdate": "next update",
    "sched.manual": "manual",
    "sleeve.on": "sleeve ON",
    "sleeve.off": "sleeve OFF",
    "sleeve.fraction": "sleeve fraction",
    "sleeve.hint_a": "share of the book tilted into",
    "sleeve.hint_b": "while the sleeve is on",

    "stats.name": "Name",
    "stats.return": "Return",
    "stats.cagr": "CAGR",
    "stats.vol": "Volatility",
    "stats.dvol": "Down Vol",
    "stats.sharpe": "Sharpe",
    "stats.sortino": "Sortino",
    "stats.ulcer": "Ulcer",
    "stats.upi": "UPI",
    "stats.maxdd": "MaxDD",

    "series.strategy": "All Weather Dynamic",
    "series.strategy_lev": "All Weather Dynamic Leverage",
    "series.strategy_lev3": "All Weather Dynamic High Leverage",
    "series.spy": "SPY buy & hold",
    "series.qqq": "QQQ buy & hold",
    "chart.cumret": "cumulative return",
    "chart.growth": "growth of 100 (log)",
    "chart.logscale": "log scale",
    "dca.label": "fixed monthly investment",
    "dca.tip": "Invest an equal amount on the first trading day of every month instead of a lump sum at the start. Return and CAGR become money-weighted; Ulcer and MaxDD are measured on the account balance. Expect them to look small: early in the period little has been invested yet, so monthly deposits outrun the losses and the balance barely dips. They describe the ACCOUNT, not the strategy. Volatility, Sharpe and Sortino are unchanged -- stripping the contribution from the account return recovers the strategy return exactly, so the funding schedule cannot alter them.",
    "range.begin": "begin",
    "range.end": "end",
    "range.max": "Max",

    "alloc.title": "Allocation",
    "alloc.asof": "as of",
    "alloc.invest": "invest",
    "alloc.export": "Export allocation CSV",
    "alloc.symbol": "Symbol",
    "alloc.holding": "Holding",
    "alloc.weight": "Weight",
    "alloc.amount": "Amount",
    "alloc.price": "Price",
    "alloc.shares": "Shares",

    "monthly.title": "Monthly returns",
    "monthly.caption": "strategy, % \u2014 selected period; the first month is partial unless the period starts on a month boundary",
    "monthly.year": "Year",
    "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],

    "log.title": "Adjustment log \u2014 every rebalance and sleeve flip",
    "log.entries": "entries",
    "log.to": "to",
    "log.none": "no entries",
    "log.rebal": "REBAL",
    "log.toport": "to PORT",
    "log.tosleeve": "to",

    "msg.loading": "Loading\u2026",
    "msg.unavailable": "Strategy not available.",
    "msg.build": "Build it with",
    "msg.reload": "then reload.",
    "msg.figunavailable": "Figure unavailable.",
    "msg.figbuild": "To build the figures, run",
    "msg.figreload": "and reload this page.",
    "msg.loadfail": "Could not load the figure.",
    "msg.stale_a": "This cache was built by an older version",
    "msg.stale_b": "so some of it may be incomplete. Rebuild with",
    "msg.noplotly": "Charts need plotly.js, which did not load. Everything else on this tab is unaffected.",
    "msg.figlang": "Charts for this language have not been built yet \u2014 showing English. Build them with",

    "foot.sources": "Sources: FRED \u00b7 Yahoo Finance \u00b7 multpl.com",
    "foot.disclaimer": "Not investment advice.",
    "foot.longdisclaimer": "The information provided is for educational and informational purposes only and does not constitute financial or investment advice. Always conduct your own due diligence or consult a professional before making any investment decisions. Past performance is no guarantee of future results. Investments are subject to risk, including possible loss of principal.",
    "disclaimer.backtest": "For simplicity, backtests do not account for tax, trading cost, or slippage.",
  },

  zh: {
    "app.title_1": "\u5e02\u573a\u603b\u89c8",
    "app.title_2": "\u548c\u957f\u671f\u7b56\u7565",
    "app.title_full": "\u5e02\u573a\u603b\u89c8\u548c\u957f\u671f\u7b56\u7565",
    "app.tagline": "\u6d1e\u5bdf\u5927\u5c40  \u7a7f\u8d8a\u725b\u718a  \u7a33\u5065\u79ef\u7d2f\u8d22\u5bcc",
    "app.updated": "\u6570\u636e\u66f4\u65b0",
    "app.nodata": "\u6682\u65e0\u6570\u636e",
    "app.dark": "\u6df1\u8272\u6a21\u5f0f",
    "app.lang": "\u8bed\u8a00",

    "tab.markets": "\u5e02\u573a\u3001\u901a\u80c0\u4e0e\u8d27\u5e01",
    "tab.rates-stress": "\u5229\u7387\u4e0e\u91d1\u878d\u538b\u529b",
    "tab.economy": "\u4eba\u53e3\u3001\u5c31\u4e1a\u4e0e\u4f4f\u623f",
    "tab.futures-long": "\u671f\u8d27 \u2014 \u957f\u671f\uff088\u5e74\uff09",
    "tab.futures-short": "\u671f\u8d27 \u2014 \u77ed\u671f\uff081\u5e74\uff09",
    "tab.all-weather-fixed": "\u7ecf\u5178\u56fa\u5b9a",
    "tab.all-weather": "\u5168\u5929\u5019\u52a8\u6001",
    "tab.all-weather-lev": "\u5168\u5929\u5019\u52a8\u6001\u6760\u6746",
    "tab.all-weather-lev3": "\u5168\u5929\u5019\u52a8\u6001\u9ad8\u6760\u6746",
    "panel.leverage3x": "\u5168\u5929\u5019\u52a8\u6001\u9ad8\u6760\u6746",

    "fx.title": "\u7ecf\u5178\u56fa\u5b9a",
    "fx.lede": "\u5e7f\u4e3a\u4eba\u77e5\u7684\u9759\u6001\u914d\u7f6e\uff0c\u5927\u7ea6\u6bcf\u5e74\u518d\u5e73\u8861\u4e00\u6b21\u2014\u2014\u4ec5\u4f9b\u6bd4\u8f83\uff0c\u5e76\u975e\u6211\u4eec\u63a8\u8350\u7684\u65b9\u6848\uff08\u8bf7\u53c2\u89c1\u52a8\u6001\u7b56\u7565\uff09\u3002\u4f7f\u7528\u76f8\u540c\u7684\u56de\u6d4b\u5f15\u64ce\u548c\u57fa\u51c6\u3002",
    "fx.since": "\u8d77\u59cb",
    "fx.rebalance": "\u518d\u5e73\u8861",
    "fx.annual": "\u6bcf\u5e74",
    "fx.rebal.tip": "\u4ec5\u7528\u4e8e\u7ee9\u6548\u8bc4\u4f30\u2014\u2014\u53ea\u6539\u53d8\u56de\u6d4b\u66f2\u7ebf\u53ca\u5176\u7edf\u8ba1\u6570\u636e\uff0c\u4e0d\u5f71\u54cd\u76ee\u6807\u914d\u7f6e\u6216 CSV \u5bfc\u51fa\u3002",
    "fx.rebal.none": "\u4e0d\u518d\u5e73\u8861\uff08\u4e70\u5165\u6301\u6709\uff09",
    "fx.rebal.annual": "\u6bcf\u5e74\uff081 \u6708 1 \u65e5\uff09",
    "fx.rebal.semi": "\u6bcf\u534a\u5e74\uff081 \u6708\u30017 \u6708\uff09",
    "fx.rebal.quarterly": "\u6bcf\u5b63\u5ea6\uff081 \u6708\u30014 \u6708\u30017 \u6708\u300110 \u6708\uff09",
    "fx.monthly.caption": "\u7ec4\u5408\uff0c%\u2014\u2014\u6240\u9009\u533a\u95f4\uff1b\u82e5\u533a\u95f4\u975e\u4ece\u6708\u521d\u5f00\u59cb\uff0c\u9996\u6708\u4e3a\u4e0d\u5b8c\u6574\u6708\u4efd",
    "fx.foot": "\u56de\u6d4b\u4f7f\u7528\u957f\u5386\u53f2\u7684\u5c0f\u76d8\u4ef7\u503c\u66ff\u4ee3\u6807\u7684\uff08IJS\uff09\uff1b\u60a8\u53ef\u4ea4\u6613\u7684\u9009\u62e9\u53ef\u80fd\u4e0d\u540c\uff08AVUV/VBR\uff09\u3002",
    "fx.A.name": "60/40",
    "fx.B.name": "黄金蝴蝶",
    "fx.C.name": "偏股全天候",
    "fx.A.blurb": "教科书式的 60% 股票 / 40% 债券平衡组合——业内最常见的基准。仅供参考，并非推荐策略；每年再平衡一次。",
    "fx.B.ref": "\u4e00\u4e2a\u5e7f\u4e3a\u4eba\u77e5\u7684\u201c\u61d2\u4eba\u201d\u7ec4\u5408\uff0c\u6df1\u53d7 FIRE\uff08\u8d22\u52a1\u72ec\u7acb\u63d0\u524d\u9000\u4f11\uff09\u4eba\u7fa4\u6b22\u8fce\uff0c\u7531 Portfolio Charts \u63d0\u51fa\uff1a",
    "fx.B.reflink": "\u5728 Portfolio Charts \u67e5\u770b\u9ec4\u91d1\u8774\u8776 \u2192",
    "fx.B.blurb": "五等分——全美股市、小盘价值、长期与短期国债、黄金。维护最简单、历史回撤最小；每年再平衡一次。追求低回撤与稳健，而非最高回报。",
    "fx.C.blurb": "约 55% 美国股票（含小盘价值倾斜），搭配久期均衡的国债和 20% 黄金压舱。权重基于 2006–2026 年历史优化，风险调整后回报（夏普比率）优于普通 60/40；每年再平衡一次。",
    "app.partial": "\u6570\u636e\u4e0d\u5b8c\u6574",
    "crisis.Dot-com": "\u4e92\u8054\u7f51\u6ce1\u6cab",
    "crisis.GFC": "2008\u91d1\u878d\u5371\u673a",
    "crisis.bear": "\u718a\u5e02",
    "crisis.COVID": "\u65b0\u51a0\u75ab\u60c5",
    "crisis.Liberation Day": "\u89e3\u653e\u65e5\u5173\u7a0e",
    "crisis.Iran war": "\u4f0a\u6717\u6218\u4e89",
    "brake.on": "\u6ce2\u52a8\u7387\u5239\u8f66",
    "brake.hint": "\u5f53\u7ec4\u5408\u81ea\u8eab\u5df2\u5b9e\u73b0\u6ce2\u52a8\u7387\u8fc7\u9ad8\u65f6\u6309\u6bd4\u4f8b\u964d\u4f4e\u6574\u4f53\u4ed3\u4f4d",
    "dl.balancer": "\u6295\u8d44\u7ec4\u5408\u518d\u5e73\u8861\u5de5\u5177",
    "dl.balancer_tip": "\u684c\u9762\u5e94\u7528\uff1a\u5c06\u76ee\u6807\u914d\u7f6e\u8f6c\u6362\u4e3a\u5238\u5546\u8ba2\u5355",
    "bands.title": "\u6301\u4ed3\u6784\u6210",
    "bands.caption": "\u5404\u6807\u7684\u5360\u6bd4\uff1b\u70b9\u51fb\u4e0b\u65b9\u8c03\u4ed3\u8bb0\u5f55\u53ef\u6807\u8bb0\u8be5\u65e5\u671f",
    "panel.base": "\u5168\u5929\u5019\u52a8\u6001",
    "panel.leverage": "\u5168\u5929\u5019\u52a8\u6001\u6760\u6746",

    "fact.through": "\u6570\u636e\u622a\u81f3",
    "fact.sleeve": "\u589e\u5f3a\u4ed3",
    "fact.lastadj": "\u6700\u8fd1\u8c03\u4ed3",
    "fact.nextupdate": "\u4e0b\u6b21\u66f4\u65b0",
    "sched.manual": "\u624b\u52a8",
    "sleeve.on": "\u589e\u5f3a\u4ed3 \u5f00\u542f",
    "sleeve.off": "\u589e\u5f3a\u4ed3 \u5173\u95ed",
    "sleeve.fraction": "\u589e\u5f3a\u4ed3\u6bd4\u4f8b",
    "sleeve.hint_a": "\u589e\u5f3a\u4ed3\u5f00\u542f\u65f6\u6295\u5165",
    "sleeve.hint_b": "\u7684\u8d44\u91d1\u6bd4\u4f8b",

    "stats.name": "\u540d\u79f0",
    "stats.return": "\u7d2f\u8ba1\u6536\u76ca",
    "stats.cagr": "\u5e74\u5316\u6536\u76ca",
    "stats.vol": "\u6ce2\u52a8\u7387",
    "stats.dvol": "\u4e0b\u884c\u6ce2\u52a8\u7387",
    "stats.sharpe": "\u590f\u666e\u6bd4\u7387",
    "stats.sortino": "\u7d22\u63d0\u8bfa\u6bd4\u7387",
    "stats.ulcer": "\u6e83\u75a1\u6307\u6570",
    "stats.upi": "\u9a6c\u4e01\u6bd4\u7387",
    "stats.maxdd": "\u6700\u5927\u56de\u64a4",

    "series.strategy": "\u5168\u5929\u5019\u52a8\u6001",
    "series.strategy_lev": "\u5168\u5929\u5019\u52a8\u6001\u6760\u6746",
    "series.strategy_lev3": "\u5168\u5929\u5019\u52a8\u6001\u9ad8\u6760\u6746",
    "series.spy": "SPY \u4e70\u5165\u6301\u6709",
    "series.qqq": "QQQ \u4e70\u5165\u6301\u6709",
    "chart.cumret": "\u7d2f\u8ba1\u6536\u76ca",
    "chart.growth": "\u51c0\u503c\u589e\u957f\uff08\u5bf9\u6570\uff0c\u8d77\u70b9100\uff09",
    "chart.logscale": "\u5bf9\u6570\u5750\u6807",
    "dca.label": "\u6bcf\u6708\u5b9a\u989d\u6295\u8d44",
    "dca.tip": "\u6bcf\u6708\u9996\u4e2a\u4ea4\u6613\u65e5\u6295\u5165\u7b49\u989d\u8d44\u91d1\uff0c\u800c\u975e\u671f\u521d\u4e00\u6b21\u6027\u6295\u5165\u3002\u6536\u76ca\u4e0e\u5e74\u5316\u6536\u76ca\u6539\u4e3a\u8d44\u91d1\u52a0\u6743\uff1b\u6e83\u75a1\u6307\u6570\u4e0e\u6700\u5927\u56de\u64a4\u6309\u8d26\u6237\u4f59\u989d\u8ba1\u7b97\uff08\u65b0\u6295\u5165\u7684\u8d44\u91d1\u4f1a\u7f13\u51b2\u4e0b\u8dcc\uff09\uff1b\u6ce2\u52a8\u7387\u3001\u590f\u666e\u3001\u7d22\u63d0\u8bfa\u4e0d\u53d8\u2014\u2014\u5254\u9664\u5f53\u671f\u6295\u5165\u540e\u5373\u4e3a\u7b56\u7565\u6536\u76ca\uff0c\u6545\u6295\u8d44\u65b9\u5f0f\u65e0\u6cd5\u6539\u53d8\u5b83\u4eec\u3002",
    "range.begin": "\u8d77\u59cb",
    "range.end": "\u7ed3\u675f",
    "range.max": "\u5168\u90e8",

    "alloc.title": "\u5f53\u524d\u914d\u7f6e",
    "alloc.asof": "\u622a\u81f3",
    "alloc.invest": "\u6295\u8d44\u91d1\u989d",
    "alloc.export": "\u5bfc\u51fa\u914d\u7f6e CSV",
    "alloc.symbol": "\u4ee3\u7801",
    "alloc.holding": "\u540d\u79f0",
    "alloc.weight": "\u6743\u91cd",
    "alloc.amount": "\u91d1\u989d",
    "alloc.price": "\u4ef7\u683c",
    "alloc.shares": "\u80a1\u6570",

    "monthly.title": "\u6708\u5ea6\u6536\u76ca",
    "monthly.caption": "\u7b56\u7565\uff0c%\uff08\u6309\u6240\u9009\u533a\u95f4\uff1b\u82e5\u533a\u95f4\u975e\u81ea\u7136\u6708\u8d77\u59cb\uff0c\u9996\u6708\u4e3a\u4e0d\u5b8c\u6574\u6708\u4efd\uff09",
    "monthly.year": "\u5168\u5e74",
    "months": ["1\u6708", "2\u6708", "3\u6708", "4\u6708", "5\u6708", "6\u6708",
               "7\u6708", "8\u6708", "9\u6708", "10\u6708", "11\u6708", "12\u6708"],

    "log.title": "\u8c03\u4ed3\u8bb0\u5f55 \u2014 \u6bcf\u6b21\u518d\u5e73\u8861\u4e0e\u589e\u5f3a\u4ed3\u5207\u6362",
    "log.entries": "\u6761\u8bb0\u5f55",
    "log.to": "\u81f3",
    "log.none": "\u6682\u65e0\u8bb0\u5f55",
    "log.rebal": "\u518d\u5e73\u8861",
    "log.toport": "\u8f6c\u56de\u7ec4\u5408",
    "log.tosleeve": "\u8f6c\u5165",

    "msg.loading": "\u52a0\u8f7d\u4e2d\u2026",
    "msg.unavailable": "\u7b56\u7565\u6570\u636e\u4e0d\u53ef\u7528\u3002",
    "msg.build": "\u8bf7\u8fd0\u884c",
    "msg.reload": "\u7136\u540e\u5237\u65b0\u9875\u9762\u3002",
    "msg.figunavailable": "\u56fe\u8868\u4e0d\u53ef\u7528\u3002",
    "msg.figbuild": "\u8bf7\u8fd0\u884c",
    "msg.figreload": "\u5e76\u5237\u65b0\u9875\u9762\u3002",
    "msg.loadfail": "\u56fe\u8868\u52a0\u8f7d\u5931\u8d25\u3002",
    "msg.stale_a": "\u7f13\u5b58\u7531\u65e7\u7248\u672c\u751f\u6210",
    "msg.stale_b": "\u90e8\u5206\u5185\u5bb9\u53ef\u80fd\u4e0d\u5b8c\u6574\u3002\u8bf7\u91cd\u5efa\uff1a",
    "msg.noplotly": "\u56fe\u8868\u9700\u8981 plotly.js\uff0c\u4f46\u672a\u80fd\u52a0\u8f7d\u3002\u672c\u9875\u5176\u4f59\u5185\u5bb9\u4e0d\u53d7\u5f71\u54cd\u3002",
    "msg.figlang": "\u672c\u8bed\u8a00\u7684\u56fe\u8868\u5c1a\u672a\u751f\u6210\uff0c\u5f53\u524d\u663e\u793a\u82f1\u6587\u3002\u8bf7\u8fd0\u884c\uff1a",

    "foot.sources": "\u6570\u636e\u6765\u6e90\uff1aFRED \u00b7 Yahoo Finance \u00b7 multpl.com",
    "foot.disclaimer": "\u4ee5\u4e0a\u5185\u5bb9\u4e0d\u6784\u6210\u6295\u8d44\u5efa\u8bae\u3002",
    "foot.longdisclaimer": "\u672c\u4fe1\u606f\u4ec5\u4f9b\u6559\u80b2\u548c\u53c2\u8003\u4e4b\u7528\uff0c\u4e0d\u6784\u6210\u4efb\u4f55\u8d22\u52a1\u6216\u6295\u8d44\u5efa\u8bae\u3002\u5728\u505a\u51fa\u4efb\u4f55\u6295\u8d44\u51b3\u7b56\u524d\uff0c\u8bf7\u52a1\u5fc5\u81ea\u884c\u8fdb\u884c\u5c3d\u804c\u8c03\u67e5\u6216\u54a8\u8be2\u4e13\u4e1a\u4eba\u58eb\u3002\u8fc7\u5f80\u4e1a\u7ee9\u4e0d\u4ee3\u8868\u672a\u6765\u8868\u73b0\u3002\u6295\u8d44\u6d89\u53ca\u98ce\u9669\uff0c\u5305\u62ec\u53ef\u80fd\u635f\u5931\u672c\u91d1\u3002",
    "disclaimer.backtest": "\u4e3a\u7b80\u5316\u8d77\u89c1\uff0c\u56de\u6d4b\u672a\u8ba1\u5165\u7a0e\u8d39\u3001\u4ea4\u6613\u6210\u672c\u6216\u6ed1\u70b9\u3002",
  },
};

let LANG = "en";

function t(key) {
  const table = I18N[LANG] || I18N.en;
  const v = table[key];
  return v === undefined ? (I18N.en[key] !== undefined ? I18N.en[key] : key) : v;
}

function currentLang() { return LANG; }

/** Swap every data-i18n element, then let the caller re-render generated text. */
function applyLanguage(lang, rerender) {
  LANG = I18N[lang] ? lang : "en";
  document.documentElement.lang = LANG === "zh" ? "zh-Hans" : "en";
  document.querySelectorAll("[data-i18n]").forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-title]").forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.title = t("app.title_full");
  if (typeof rerender === "function") rerender();
}

const DEFAULT_LANG = "en";

/* Every page load starts in English.
 *
 * The choice is deliberately NOT persisted: a remembered language is
 * indistinguishable from a wrong default once you have forgotten you picked
 * it, which is precisely the confusion it caused. The radio buttons still
 * switch freely within a session. To make it sticky instead, save LANG to
 * localStorage in applyLanguage() and read it back here.
 *
 * navigator.language is also deliberately not sniffed, so a Chinese-locale
 * browser still opens in English. */
function initLanguage() {
  // Clear any preference left by an earlier build that did persist it.
  try { localStorage.removeItem("mw-lang"); } catch (e) { /* noop */ }
  return DEFAULT_LANG;
}
