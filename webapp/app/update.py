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

from . import data_pipeline, figures, settings

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


def run_update(rebuild_only: bool = False, log=print) -> None:
    if rebuild_only:
        log("Rebuilding figures from existing pickle (no download)...")
        all_data = data_pipeline.load_data()
    else:
        all_data = data_pipeline.collect_all_data(log=log)
        data_pipeline.save_data(all_data)
        log(f"Saved data to {data_pipeline.PICKLE_PATH}")
    rebuild_figures(all_data, log=log)
    log("Update complete.")


def main() -> int:
    parser = argparse.ArgumentParser(description="MarketWatch daily update")
    parser.add_argument("--rebuild-only", action="store_true",
                        help="rebuild figures from the existing pickle "
                             "without downloading")
    args = parser.parse_args()
    try:
        run_update(rebuild_only=args.rebuild_only)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
