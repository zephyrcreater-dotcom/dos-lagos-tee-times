"""Main orchestration: fetch -> filter -> diff against state -> notify.

Usage:
    python -m src.monitor                          # normal run: check configured days, email on new matches
    python -m src.monitor --dry-run                # check configured days, print matches, send no email
    python -m src.monitor --date 2026-10-10 --dry-run   # check one specific date, print matches, no email
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time as time_module
from datetime import datetime, time as dt_time
from pathlib import Path

from . import filters, state as state_module
from .notifier import EmailConfig, send_tee_time_alerts
from .teeitup import COURSE_TIMEZONE, TeeItUpError, TeeTime, get_tee_times

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_STATE_PATH = "state.json"


def load_config(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}. Copy config.example.json to {path} and edit it."
        )
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_candidate_dates(config: dict) -> list[str]:
    days = config.get("days", ["Saturday", "Sunday"])
    days_ahead = config.get("days_ahead", 12)
    return filters.upcoming_dates_for_days(days, days_ahead)


def fetch_all_tee_times(dates: list[str], config: dict) -> list[TeeTime]:
    """Fetch tee times for every candidate date, logging (not raising) per-date failures."""
    alias = config.get("alias", "dos-lagos-golf-course")
    facility_id = config.get("facility_id", "3510")

    all_tee_times: list[TeeTime] = []
    for iso_date in dates:
        try:
            tee_times = get_tee_times(iso_date, alias=alias, facility_id=facility_id)
            logger.info("Fetched %d tee time(s) for %s", len(tee_times), iso_date)
            all_tee_times.extend(tee_times)
        except TeeItUpError as exc:
            logger.error("Failed to fetch tee times for %s: %s", iso_date, exc)
    return all_tee_times


def print_tee_times(tee_times: list[TeeTime]) -> None:
    if not tee_times:
        print("No matching tee times found.")
        return
    for t in sorted(tee_times, key=lambda x: (x.date, x.time)):
        price_str = f"${t.price:.2f}" if t.price is not None else "price n/a"
        print(f"{t.date} {t.time}  {t.available_spots} spot(s)  {price_str}  {t.booking_url}")


def run_one_cycle(config: dict, state_path: str, dry_run: bool, single_date: str | None) -> int:
    """Run exactly one fetch -> filter -> diff -> notify -> save cycle. Returns an exit code."""
    dates = [single_date] if single_date else fetch_candidate_dates(config)
    if not dates:
        logger.info("No candidate dates match the configured days/days_ahead; nothing to do.")
        return 0

    logger.info("Checking dates: %s", ", ".join(dates))
    all_tee_times = fetch_all_tee_times(dates, config)
    matching = filters.filter_tee_times(all_tee_times, config)
    logger.info("%d tee time(s) matched preferences out of %d fetched", len(matching), len(all_tee_times))

    state = state_module.load_state(state_path)
    newly_available = state_module.find_newly_available(matching, state)

    if dry_run:
        print(f"-- Dry run: {len(newly_available)} newly-available matching tee time(s) --")
        print_tee_times(newly_available)
        print(f"\n-- All {len(matching)} matching tee time(s) (including already-notified) --")
        print_tee_times(matching)
        return 0

    if newly_available:
        logger.info("Sending email alert(s) for %d newly-available tee time(s)", len(newly_available))
        try:
            email_config = EmailConfig.from_env()
            send_tee_time_alerts(newly_available, email_config)
        except ValueError as exc:
            logger.error("Cannot send email: %s", exc)
            return 1
        except Exception:
            logger.exception("Failed to send one or more email alerts")
            return 1
    else:
        logger.info("No newly-available matching tee times; no email sent.")

    # Update state for every matching tee time we saw this run (not just the new ones),
    # so availability that drops and comes back later is detected as "new" again.
    updated_state = state_module.update_state(matching, state)
    state_module.save_state(state_path, updated_state)

    return 0


def run(config_path: str, state_path: str, dry_run: bool, single_date: str | None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1

    return run_one_cycle(config, state_path, dry_run, single_date)


def _parse_hhmm_local(value: str) -> dt_time:
    hours, minutes = value.split(":")
    return dt_time(int(hours), int(minutes))


def _now_in_window(window_start: dt_time, window_end: dt_time, now: dt_time | None = None) -> bool:
    """Check if `now` (Pacific local time) falls in [window_start, window_end].

    Handles windows that wrap past midnight (e.g. 23:30 -> 01:30).
    """
    now = now or datetime.now(COURSE_TIMEZONE).time()
    if window_start <= window_end:
        return window_start <= now <= window_end
    return now >= window_start or now <= window_end


def run_burst(
    config_path: str,
    state_path: str,
    burst_minutes: int,
    poll_interval_seconds: int,
    window_start: str,
    window_end: str,
) -> int:
    """Poll repeatedly for up to `burst_minutes`, but only if currently within the release window.

    Intended for a GitHub Actions cron that fires once or twice a day near the suspected
    midnight-Pacific inventory rollover (see RESEARCH.md). If the workflow happens to run
    outside the configured window (e.g. the "wrong" one of the two DST-covering cron
    triggers fired), this exits almost immediately instead of burning Actions minutes.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config(config_path)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        return 1

    start_t = _parse_hhmm_local(window_start)
    end_t = _parse_hhmm_local(window_end)

    if not _now_in_window(start_t, end_t):
        logger.info(
            "Current Pacific time is outside the burst window (%s-%s); exiting without polling.",
            window_start,
            window_end,
        )
        return 0

    deadline = time_module.monotonic() + burst_minutes * 60
    iteration = 0
    while True:
        iteration += 1
        logger.info("Burst poll iteration %d", iteration)
        exit_code = run_one_cycle(config, state_path, dry_run=False, single_date=None)
        if exit_code != 0:
            logger.warning("Burst iteration %d returned non-zero exit code %d", iteration, exit_code)

        if time_module.monotonic() >= deadline:
            logger.info("Burst window elapsed (%d iterations); exiting.", iteration)
            return 0
        if not _now_in_window(start_t, end_t):
            logger.info("Walked past the configured time window; exiting early.")
            return 0

        time_module.sleep(poll_interval_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor Dos Lagos tee time availability.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH, help="Path to state.json")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matching tee times instead of sending email or updating state",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Check a single specific date (YYYY-MM-DD) instead of the configured days/days_ahead window",
    )
    parser.add_argument(
        "--burst",
        action="store_true",
        help="Poll repeatedly for a bounded window instead of checking once (see README for why)",
    )
    parser.add_argument("--burst-minutes", type=int, default=20, help="Max minutes to poll during --burst")
    parser.add_argument("--poll-interval", type=int, default=30, help="Seconds between polls during --burst")
    parser.add_argument(
        "--window-start",
        default="23:30",
        help="Pacific local HH:MM burst window start (--burst exits immediately outside this window)",
    )
    parser.add_argument(
        "--window-end",
        default="01:30",
        help="Pacific local HH:MM burst window end (may be earlier than --window-start to wrap past midnight)",
    )
    args = parser.parse_args(argv)

    if args.burst:
        return run_burst(
            config_path=args.config,
            state_path=args.state,
            burst_minutes=args.burst_minutes,
            poll_interval_seconds=args.poll_interval,
            window_start=args.window_start,
            window_end=args.window_end,
        )

    return run(
        config_path=args.config,
        state_path=args.state,
        dry_run=args.dry_run,
        single_date=args.date,
    )


if __name__ == "__main__":
    sys.exit(main())
