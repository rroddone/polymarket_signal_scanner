"""
main.py — Polymarket Signal Scanner CLI entrypoint.

Usage:
    venv/bin/python main.py --harvest              # full ingest + analyze cycle
    venv/bin/python main.py --harvest --limit 5    # dry-run: first 5 markets only
    venv/bin/python main.py --backtest             # intraday backtest
    venv/bin/python main.py --backtest --limit 20  # quick smoke-test on 20 signals
    venv/bin/python main.py --serve                # launch Streamlit dashboard
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Polymarket Signal Scanner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--harvest",  action="store_true", help="Run ingest + analyze pipeline")
    group.add_argument("--backtest", action="store_true", help="Run intraday backtest")
    group.add_argument("--serve",    action="store_true", help="Launch Streamlit dashboard")

    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Restrict to first N items (dry-run mode for --harvest and --backtest)",
    )
    # Backward-compat flag from old analyze.py; silently ignored
    p.add_argument("--no-search", action="store_true", default=False, help=argparse.SUPPRESS)
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    if args.harvest:
        from src.jobs.harvester import Harvester
        Harvester().run(limit=args.limit)

    elif args.backtest:
        from src.jobs.backtester import Backtester
        Backtester().run(limit=args.limit)

    elif args.serve:
        dashboard = PROJECT_ROOT / "dashboard" / "app.py"
        try:
            result = subprocess.run(
                [str(PROJECT_ROOT / "venv" / "bin" / "streamlit"), "run", str(dashboard)],
                cwd=str(PROJECT_ROOT),
            )
            sys.exit(result.returncode)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
