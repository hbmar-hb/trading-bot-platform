"""Monitor shadow-mode keys and alert on regressions.

Intended to run from cron or a Celery beat task every few minutes.  Exits with
non-zero status if any of the following is detected:

- A prediction with signal_id == "None" in the recent window.
- No new predictions in the configured staleness window.
- The candidate shadow evaluation window is unhealthy.

Examples
--------
    # Run once and print a report
    python backend/scripts/monitor_shadow_mode.py

    # Only return the exit code, no output
    python backend/scripts/monitor_shadow_mode.py --quiet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running the script directly from the scripts/ directory.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.shadow_monitor_service import run_shadow_monitor_check


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor shadow mode health")
    parser.add_argument(
        "--candidate-window-hours",
        type=int,
        default=48,
        help="Hours to look back for candidate shadow predictions",
    )
    parser.add_argument(
        "--live-window-hours",
        type=int,
        default=168,
        help="Hours to look back for live-vs-shadow predictions",
    )
    parser.add_argument(
        "--max-age-minutes",
        type=int,
        default=60,
        help="Alert if no prediction was recorded in this many minutes",
    )
    parser.add_argument(
        "--max-none-lookback-hours",
        type=int,
        default=24,
        help="Alert if a 'None' signal_id appears within this many hours",
    )
    parser.add_argument("--quiet", action="store_true", help="Only emit exit code")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument(
        "--no-save-history",
        action="store_true",
        help="Do not persist the report to Redis history",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    report = run_shadow_monitor_check(
        candidate_window_hours=args.candidate_window_hours,
        live_window_hours=args.live_window_hours,
        max_age_minutes=args.max_age_minutes,
        max_none_lookback_hours=args.max_none_lookback_hours,
        save_history=not args.no_save_history,
    )

    if args.json:
        if not args.quiet:
            print(json.dumps(report, indent=2, default=str))
    elif not args.quiet:
        print("Shadow mode health check")
        print("=" * 50)
        print(
            f"{report['candidate']['key']}: "
            f"total={report['candidate']['total_in_window']} "
            f"resolved={report['candidate']['resolved']} "
            f"none_recent={report['candidate']['none_recent']} "
            f"recent={report['candidate']['recent_predictions']}"
        )
        print(
            f"{report['live']['key']}: "
            f"total={report['live']['total_in_window']} "
            f"resolved={report['live']['resolved']} "
            f"none_recent={report['live']['none_recent']} "
            f"recent={report['live']['recent_predictions']}"
        )
        print(f"Candidate eval: {report['candidate_eval']}")
        print(f"Healthy: {report['healthy']}")

    return 0 if report["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
