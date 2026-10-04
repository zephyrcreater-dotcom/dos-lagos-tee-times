from datetime import datetime
from zoneinfo import ZoneInfo

from src.notifier import build_consolidated_body, build_consolidated_subject
from src.teeitup import TeeTime

PACIFIC = ZoneInfo("America/Los_Angeles")


def make_tee_time(date_str, time_str, spots=4, price=47.0, unique_id=None):
    return TeeTime(
        date=date_str,
        time=time_str,
        available_spots=spots,
        price=price,
        booking_url=f"https://example.test/book?date={date_str}",
        unique_id=unique_id or f"{date_str}:{time_str}",
        rate_name="18 Holes",
    )


class TestBuildConsolidatedSubject:
    def test_singular(self):
        subject = build_consolidated_subject([make_tee_time("2026-10-10", "07:30")])
        assert subject == "Dos Lagos: 1 matching tee time available"

    def test_plural(self):
        subject = build_consolidated_subject(
            [make_tee_time("2026-10-10", "07:30"), make_tee_time("2026-10-11", "08:00")]
        )
        assert subject == "Dos Lagos: 2 matching tee times available"


class TestBuildConsolidatedBody:
    def test_numbers_entries_in_date_time_order(self):
        checked_at = datetime(2026, 10, 4, 10, 0, tzinfo=PACIFIC)
        unordered = [
            make_tee_time("2026-10-11", "08:00"),
            make_tee_time("2026-10-10", "07:30"),
            make_tee_time("2026-10-10", "06:45"),
        ]
        body = build_consolidated_body(unordered, checked_at=checked_at)
        lines = [l for l in body.splitlines() if l.startswith(("1)", "2)", "3)"))]
        assert lines[0].startswith("1) Saturday, October 10 — 6:45 AM")
        assert lines[1].startswith("2) Saturday, October 10 — 7:30 AM")
        assert lines[2].startswith("3) Sunday, October 11 — 8:00 AM")

    def test_includes_booking_url_and_spots_and_price(self):
        body = build_consolidated_body([make_tee_time("2026-10-10", "07:30", spots=2, price=47.0)])
        assert "2 spots" in body
        assert "$47/player" in body
        assert "https://example.test/book?date=2026-10-10" in body

    def test_singular_spot_wording(self):
        body = build_consolidated_body([make_tee_time("2026-10-10", "07:30", spots=1)])
        assert "1 spot —" in body

    def test_missing_price_handled(self):
        body = build_consolidated_body([make_tee_time("2026-10-10", "07:30", price=None)])
        assert "price unavailable" in body

    def test_includes_checked_at_timestamp(self):
        checked_at = datetime(2026, 10, 4, 10, 0, tzinfo=PACIFIC)
        body = build_consolidated_body([make_tee_time("2026-10-10", "07:30")], checked_at=checked_at)
        assert "Checked at:" in body
