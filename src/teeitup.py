"""Client for the public TeeItUp / GolfNow (Kenna) tee-time availability API.

See RESEARCH.md for how this endpoint was discovered and documented. This module only
talks to the read-only `/v2/tee-times` endpoint; it never logs in, holds a cart, or
submits a reservation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import requests

logger = logging.getLogger(__name__)

API_BASE_URL = "https://phx-api-be-east-1b.kenna.io"
DEFAULT_ALIAS = "dos-lagos-golf-course"
DEFAULT_FACILITY_ID = "3510"
BOOKING_SITE_URL = "https://dos-lagos-golf-course.book.teeitup.com/teetimes"
COURSE_TIMEZONE = ZoneInfo("America/Los_Angeles")

REQUEST_TIMEOUT_SECONDS = 10
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


@dataclass(frozen=True)
class TeeTime:
    """A single bookable tee time slot, matching one rate on one tee time."""

    date: str  # "YYYY-MM-DD", course-local date
    time: str  # "HH:MM", course-local 24h time
    available_spots: int
    price: float | None
    booking_url: str
    unique_id: str
    rate_name: str

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "time": self.time,
            "available_spots": self.available_spots,
            "price": self.price,
            "booking_url": self.booking_url,
            "unique_id": self.unique_id,
            "rate_name": self.rate_name,
        }


class TeeItUpError(RuntimeError):
    """Raised when the availability API cannot be reached or returns something unexpected."""


def booking_url_for_date(iso_date: str, facility_id: str = DEFAULT_FACILITY_ID) -> str:
    return f"{BOOKING_SITE_URL}?course={facility_id}&date={iso_date}&max=999999"


def _parse_teetime_entry(entry: dict, iso_date: str, facility_id: str) -> list[TeeTime]:
    """Turn one raw `teetimes[]` entry into zero or more TeeTime records (one per rate)."""
    results: list[TeeTime] = []

    max_players = entry.get("maxPlayers")
    booked_players = entry.get("bookedPlayers", 0)
    if max_players is None:
        logger.warning("Skipping tee time entry with no maxPlayers: %r", entry)
        return results
    available_spots = max(0, max_players - booked_players)

    raw_teetime = entry.get("teetime")
    if not raw_teetime:
        logger.warning("Skipping tee time entry with no teetime timestamp: %r", entry)
        return results

    try:
        teetime_utc = datetime.fromisoformat(raw_teetime.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Could not parse teetime timestamp %r", raw_teetime)
        return results
    teetime_local = teetime_utc.astimezone(COURSE_TIMEZONE)
    local_time_str = teetime_local.strftime("%H:%M")

    rates = entry.get("rates") or []
    if not rates:
        logger.warning("Tee time at %s %s has no rates", iso_date, local_time_str)
        return results

    booking_url = booking_url_for_date(iso_date, facility_id)

    for rate in rates:
        rate_id = rate.get("_id") or rate.get("externalId")
        if rate_id is None:
            logger.warning("Rate with no id, skipping: %r", rate)
            continue
        price_cents = rate.get("greenFeeCart")
        price = round(price_cents / 100, 2) if isinstance(price_cents, (int, float)) else None
        unique_id = f"{iso_date}:{raw_teetime}:{rate_id}"
        results.append(
            TeeTime(
                date=iso_date,
                time=local_time_str,
                available_spots=available_spots,
                price=price,
                booking_url=booking_url,
                unique_id=unique_id,
                rate_name=rate.get("name", "Unknown"),
            )
        )
    return results


def parse_tee_times_response(payload: list, iso_date: str, facility_id: str) -> list[TeeTime]:
    """Parse the raw JSON body of a `/v2/tee-times` response into TeeTime records.

    Tolerant of malformed/missing fields: individual bad entries are logged and skipped
    rather than raising, so one bad record doesn't take down a whole monitoring run.
    """
    if not isinstance(payload, list):
        raise TeeItUpError(f"Expected a list response, got {type(payload).__name__}")

    all_tee_times: list[TeeTime] = []
    for day_block in payload:
        if not isinstance(day_block, dict):
            logger.warning("Skipping malformed day block: %r", day_block)
            continue
        entries = day_block.get("teetimes") or []
        for entry in entries:
            all_tee_times.extend(_parse_teetime_entry(entry, iso_date, facility_id))
    return all_tee_times


def get_tee_times(
    target_date: date | str,
    alias: str = DEFAULT_ALIAS,
    facility_id: str = DEFAULT_FACILITY_ID,
    session: requests.Session | None = None,
) -> list[TeeTime]:
    """Fetch available tee times for a single date.

    Args:
        target_date: a `date` object or an "YYYY-MM-DD" string.
        alias: the TeeItUp site alias (course-specific slug).
        facility_id: the GolfNow facility id.
        session: optional pre-built `requests.Session` (mainly for tests).

    Returns:
        A list of TeeTime records, possibly empty. An empty list can mean either
        "no availability that day" or "that day is outside the booking window" — the API
        does not distinguish between the two (see RESEARCH.md).

    Raises:
        TeeItUpError: if the request ultimately fails after retries, or the response
            cannot be parsed.
    """
    iso_date = target_date.isoformat() if isinstance(target_date, date) else target_date

    url = f"{API_BASE_URL}/v2/tee-times"
    params = {"date": iso_date, "facilityIds": facility_id}
    headers = {
        "Accept": "application/json",
        "x-be-alias": alias,
        "User-Agent": (
            "dos-lagos-tee-times-monitor/1.0 "
            "(+https://github.com/; personal, low-frequency availability check)"
        ),
    }

    http = session or requests.Session()
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = http.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            payload = response.json()
            return parse_tee_times_response(payload, iso_date, facility_id)
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.warning(
                "Attempt %d/%d to fetch tee times for %s failed: %s",
                attempt,
                MAX_RETRIES,
                iso_date,
                exc,
            )
            if attempt < MAX_RETRIES:
                import time

                time.sleep(RETRY_BACKOFF_SECONDS * attempt)

    raise TeeItUpError(f"Failed to fetch tee times for {iso_date} after {MAX_RETRIES} attempts") from last_error
