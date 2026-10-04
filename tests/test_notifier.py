import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.notifier import (
    EmailConfig,
    build_consolidated_body,
    build_consolidated_subject,
    build_sms_body,
    sms_config_from_env,
    sms_gateway_address,
)
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


class TestSmsGatewayAddress:
    def test_builds_expected_address(self):
        assert sms_gateway_address("555-123-4567", "verizon") == "5551234567@vtext.com"

    def test_strips_formatting_characters(self):
        assert sms_gateway_address("(555) 123-4567", "att") == "5551234567@txt.att.net"

    def test_strips_leading_us_country_code(self):
        assert sms_gateway_address("15551234567", "t-mobile") == "5551234567@tmomail.net"

    def test_carrier_name_is_case_insensitive(self):
        assert sms_gateway_address("5551234567", "Verizon") == "5551234567@vtext.com"

    def test_unknown_carrier_raises(self):
        with pytest.raises(ValueError):
            sms_gateway_address("5551234567", "not-a-real-carrier")

    def test_wrong_digit_count_raises(self):
        with pytest.raises(ValueError):
            sms_gateway_address("12345", "verizon")


class TestSmsConfigFromEnv:
    BASE = EmailConfig(sender_address="me@gmail.com", app_password="pw", recipient_address="me@gmail.com")

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("PHONE_NUMBER", raising=False)
        monkeypatch.delenv("CARRIER", raising=False)
        assert sms_config_from_env(self.BASE) is None

    def test_returns_none_when_only_phone_set(self, monkeypatch):
        monkeypatch.setenv("PHONE_NUMBER", "5551234567")
        monkeypatch.delenv("CARRIER", raising=False)
        assert sms_config_from_env(self.BASE) is None

    def test_builds_config_when_both_set(self, monkeypatch):
        monkeypatch.setenv("PHONE_NUMBER", "5551234567")
        monkeypatch.setenv("CARRIER", "verizon")
        result = sms_config_from_env(self.BASE)
        assert result is not None
        assert result.recipient_address == "5551234567@vtext.com"
        # Sender credentials are reused from the base (email) config.
        assert result.sender_address == self.BASE.sender_address
        assert result.app_password == self.BASE.app_password


class TestBuildSmsBody:
    def test_single_match_includes_booking_url(self):
        body = build_sms_body([make_tee_time("2026-10-10", "07:30", spots=2)])
        assert "Saturday, October 10" in body
        assert "7:30 AM" in body
        assert "https://example.test/book?date=2026-10-10" in body

    def test_multiple_matches_gives_count_and_earliest_only(self):
        tee_times = [
            make_tee_time("2026-10-11", "08:00"),
            make_tee_time("2026-10-10", "07:30"),
        ]
        body = build_sms_body(tee_times)
        assert "2 matching tee times" in body
        assert "Earliest: Saturday, October 10 7:30 AM" in body
        assert "Check email for the full list" in body
        # Should not dump every booking URL into the text.
        assert body.count("example.test") == 0
