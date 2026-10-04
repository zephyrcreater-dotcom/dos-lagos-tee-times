"""Date-window calculation and preference filtering for tee times."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .teeitup import TeeTime

DAY_NAME_TO_WEEKDAY = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}


def upcoming_dates_for_days(days: list[str], days_ahead: int, today: date | None = None) -> list[str]:
    """Return ISO date strings, within [today, today + days_ahead], whose weekday is in `days`.

    `days_ahead` is inclusive: a value of 12 means today through today+12 (13 calendar days),
    matching Dos Lagos's confirmed 12-day booking window (see RESEARCH.md). `today` is
    injectable for testing; defaults to the real current date.
    """
    if today is None:
        today = date.today()

    wanted_weekdays = {DAY_NAME_TO_WEEKDAY[d] for d in days if d in DAY_NAME_TO_WEEKDAY}
    unknown = [d for d in days if d not in DAY_NAME_TO_WEEKDAY]
    if unknown:
        raise ValueError(f"Unknown day name(s): {unknown}")

    results = []
    for offset in range(0, days_ahead + 1):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() in wanted_weekdays:
            results.append(candidate.isoformat())
    return results


def _parse_hhmm(value: str) -> tuple[int, int]:
    hours, minutes = value.split(":")
    return int(hours), int(minutes)


def time_in_range(time_str: str, earliest: str, latest: str) -> bool:
    """Inclusive check that `time_str` ("HH:MM") falls within [earliest, latest]."""
    t = _parse_hhmm(time_str)
    lo = _parse_hhmm(earliest)
    hi = _parse_hhmm(latest)
    return lo <= t <= hi


def matches_preferences(tee_time: TeeTime, config: dict) -> bool:
    """Check a single TeeTime against the user's config preferences."""
    earliest = config.get("earliest_time", "00:00")
    latest = config.get("latest_time", "23:59")
    min_spots = config.get("minimum_open_spots", 1)

    if not time_in_range(tee_time.time, earliest, latest):
        return False
    if tee_time.available_spots < min_spots:
        return False
    return True


def filter_tee_times(tee_times: list[TeeTime], config: dict) -> list[TeeTime]:
    return [t for t in tee_times if matches_preferences(t, config)]
