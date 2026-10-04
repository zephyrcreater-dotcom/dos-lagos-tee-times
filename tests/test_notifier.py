import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import requests

from src.notifier import (
    EmailConfig,
    _with_shortened_urls,
    build_consolidated_body,
    build_consolidated_subject,
    build_sms_body,
    ntfy_server_from_env,
    ntfy_topic_from_env,
    send_ntfy_alert,
    shorten_url,
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
        assert "Sat 10/10" in body
        assert "7:30 AM" in body
        assert "https://example.test/book?date=2026-10-10" in body

    def test_multiple_matches_on_different_dates_each_get_their_url(self):
        tee_times = [
            make_tee_time("2026-10-11", "08:00"),
            make_tee_time("2026-10-10", "07:30"),
        ]
        body = build_sms_body(tee_times)
        assert "2 matching tee times" in body
        assert "Sat 10/10 7:30 AM: https://example.test/book?date=2026-10-10" in body
        assert "Sun 10/11 8:00 AM: https://example.test/book?date=2026-10-11" in body

    def test_same_hour_matches_share_one_url_line(self):
        # Two times in the same date/hour share a booking_url (it brackets the whole hour)
        # — the text should list both times once, with the link only once.
        tee_times = [
            make_tee_time("2026-10-10", "07:30"),
            make_tee_time("2026-10-10", "07:40"),
        ]
        body = build_sms_body(tee_times)
        assert body.count("example.test") == 1
        assert "7:30 AM, 7:40 AM" in body


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class TestShortenUrl:
    def test_returns_shortened_url_on_success(self, monkeypatch):
        monkeypatch.setattr(
            "src.notifier.requests.get",
            lambda *a, **k: _FakeResponse("https://tinyurl.com/abc123"),
        )
        assert shorten_url("https://example.test/long/path") == "https://tinyurl.com/abc123"

    def test_falls_back_to_original_on_network_error(self, monkeypatch):
        def raise_error(*a, **k):
            raise requests.ConnectionError("boom")

        monkeypatch.setattr("src.notifier.requests.get", raise_error)
        original = "https://example.test/long/path"
        assert shorten_url(original) == original

    def test_falls_back_to_original_on_unexpected_response_body(self, monkeypatch):
        monkeypatch.setattr(
            "src.notifier.requests.get",
            lambda *a, **k: _FakeResponse("Error, database insert failed"),
        )
        original = "https://example.test/long/path"
        assert shorten_url(original) == original

    def test_falls_back_to_original_on_http_error_status(self, monkeypatch):
        monkeypatch.setattr(
            "src.notifier.requests.get",
            lambda *a, **k: _FakeResponse("server error", status_code=500),
        )
        original = "https://example.test/long/path"
        assert shorten_url(original) == original


class TestWithShortenedUrls:
    def test_replaces_booking_url(self, monkeypatch):
        monkeypatch.setattr("src.notifier.shorten_url", lambda url: f"short://{url}")
        tee_times = [make_tee_time("2026-10-10", "07:30")]
        result = _with_shortened_urls(tee_times)
        assert result[0].booking_url == "short://https://example.test/book?date=2026-10-10"
        # Original list/objects are untouched (TeeTime is frozen).
        assert tee_times[0].booking_url == "https://example.test/book?date=2026-10-10"

    def test_shortens_each_distinct_url_only_once(self, monkeypatch):
        calls = []

        def fake_shorten(url):
            calls.append(url)
            return f"short-{len(calls)}"

        monkeypatch.setattr("src.notifier.shorten_url", fake_shorten)
        tee_times = [
            make_tee_time("2026-10-10", "07:30"),  # shares a URL with the next one
            make_tee_time("2026-10-10", "07:40"),
            make_tee_time("2026-10-11", "08:00"),  # different date -> different URL
        ]
        result = _with_shortened_urls(tee_times)
        assert len(calls) == 2  # only 2 distinct booking_urls across the 3 tee times
        assert result[0].booking_url == result[1].booking_url == "short-1"
        assert result[2].booking_url == "short-2"


class TestNtfyTopicFromEnv:
    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("NTFY_TOPIC", raising=False)
        assert ntfy_topic_from_env() is None

    def test_returns_topic_when_set(self, monkeypatch):
        monkeypatch.setenv("NTFY_TOPIC", "my-secret-topic-abc123")
        assert ntfy_topic_from_env() == "my-secret-topic-abc123"


class TestNtfyServerFromEnv:
    def test_defaults_to_public_server(self, monkeypatch):
        monkeypatch.delenv("NTFY_SERVER", raising=False)
        assert ntfy_server_from_env() == "https://ntfy.sh"

    def test_uses_override_when_set(self, monkeypatch):
        monkeypatch.setenv("NTFY_SERVER", "https://ntfy.example.com")
        assert ntfy_server_from_env() == "https://ntfy.example.com"


class TestSendNtfyAlert:
    def test_posts_to_topic_url_with_title_and_click_headers(self, monkeypatch):
        captured = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["headers"] = headers
            return _FakeResponse("ok")

        monkeypatch.setattr("src.notifier.requests.post", fake_post)
        tee_times = [make_tee_time("2026-10-10", "07:30"), make_tee_time("2026-10-11", "08:00")]
        send_ntfy_alert(tee_times, topic="my-secret-topic", server="https://ntfy.sh")

        assert captured["url"] == "https://ntfy.sh/my-secret-topic"
        assert captured["headers"]["Click"] == "https://example.test/book?date=2026-10-10"
        assert b"2 matching Dos Lagos tee time" in captured["data"]

    def test_strips_trailing_slash_from_server(self, monkeypatch):
        captured = {}

        def fake_post(url, **k):
            captured["url"] = url
            return _FakeResponse("ok")

        monkeypatch.setattr("src.notifier.requests.post", fake_post)
        send_ntfy_alert([make_tee_time("2026-10-10", "07:30")], topic="t", server="https://ntfy.sh/")
        assert captured["url"] == "https://ntfy.sh/t"

    def test_raises_on_http_error(self, monkeypatch):
        monkeypatch.setattr(
            "src.notifier.requests.post",
            lambda *a, **k: _FakeResponse("server error", status_code=500),
        )
        with pytest.raises(requests.HTTPError):
            send_ntfy_alert([make_tee_time("2026-10-10", "07:30")], topic="t")
