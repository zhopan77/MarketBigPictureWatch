"""
The daily update, packaged as a single command:

    python -m app.update                 # download fresh data + rebuild figures
    python -m app.update --rebuild-only  # rebuild figures from the existing pickle

This one command is what every scheduler calls:
  - Windows Task Scheduler (see update_data.bat / register_task.bat)
  - cron on a Linux host:  0 6 * * * cd /srv/marketwatch && .venv/bin/python -m app.update
  - hosting-service cron jobs (Render/Railway/Fly scheduled jobs) run it too
  - the in-process scheduler in app/main.py calls run_update() directly
"""

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone

from . import data_pipeline, figures, settings, strategy_service

FIG_DIR = settings.DATA_DIR / "figures"
META_PATH = settings.DATA_DIR / "meta.json"


def rebuild_figures(all_data: dict, log=print) -> None:
    """Build all figures and serialize them to JSON for the web app."""
    log("Building figures...")
    figs = figures.build_all_figures(all_data)
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    for slug, fig in figs.items():
        (FIG_DIR / f"{slug}.json").write_text(fig.to_json(), encoding="utf-8")
        log(f"  wrote figures/{slug}.json")
    META_PATH.write_text(json.dumps({
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "figures": [{"slug": s, "title": t} for s, t in figures.FIGURES.items()],
    }), encoding="utf-8")


def run_strategy(log=print) -> bool:
    """Rerun the All-Weather backtest and cache it.  Isolated in its own
    try/except so a Yahoo hiccup here can never take down the macro figures
    (and vice versa) -- each half of the dashboard fails independently."""
    log("Running All-Weather strategy backtest...")
    try:
        strategy_service.run_strategy_update(log_fn=log)
        return True
    except Exception:
        log("Strategy update FAILED (macro figures are unaffected):")
        traceback.print_exc()
        return False


def run_update(rebuild_only: bool = False, log=print,
               skip_strategy: bool = False) -> None:
    if rebuild_only:
        log("Rebuilding figures from existing pickle (no download)...")
        all_data = data_pipeline.load_data()
    else:
        all_data = data_pipeline.collect_all_data(log=log)
        data_pipeline.save_data(all_data)
        log(f"Saved data to {data_pipeline.PICKLE_PATH}")
    rebuild_figures(all_data, log=log)
    if not skip_strategy:
        run_strategy(log=log)
    log("Update complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description="MarketWatch daily update")
    parser.add_argument("--rebuild-only", action="store_true",
                        help="rebuild figures from the existing pickle "
                             "without downloading")
    parser.add_argument("--strategy-only", action="store_true",
                        help="rerun only the All-Weather backtest")
    parser.add_argument("--skip-strategy", action="store_true",
                        help="refresh the macro figures but not the strategy")
    args = parser.parse_args()
    try:
        if args.strategy_only:
            return 0 if run_strategy() else 1
        run_update(rebuild_only=args.rebuild_only,
                   skip_strategy=args.skip_strategy)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
