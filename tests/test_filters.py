from datetime import date

import pytest

from src import filters
from src.teeitup import TeeTime


def make_tee_time(date_str="2026-10-10", time_str="07:30", spots=4, price=47.0):
    return TeeTime(
        date=date_str,
        time=time_str,
        available_spots=spots,
        price=price,
        booking_url="https://example.test/book",
        unique_id=f"{date_str}:{time_str}:1",
        rate_name="18 Holes",
    )


class TestUpcomingDatesForDays:
    def test_finds_next_saturday_and_sunday(self):
        # 2026-10-04 is a Sunday (confirmed against the real calendar used in RESEARCH.md)
        today = date(2026, 10, 4)
        result = filters.upcoming_dates_for_days(["Saturday", "Sunday"], days_ahead=12, today=today)
        assert result == ["2026-10-04", "2026-10-10", "2026-10-11"]

    def test_days_ahead_is_inclusive_boundary(self):
        today = date(2026, 10, 4)
        # Oct 10 is exactly 6 days out; with days_ahead=6 it must still be included.
        result = filters.upcoming_dates_for_days(["Saturday"], days_ahead=6, today=today)
        assert result == ["2026-10-10"]

    def test_days_ahead_excludes_just_past_boundary(self):
        today = date(2026, 10, 4)
        result = filters.upcoming_dates_for_days(["Saturday"], days_ahead=5, today=today)
        assert result == []

    def test_weekday_only_filter(self):
        today = date(2026, 10, 4)
        result = filters.upcoming_dates_for_days(["Monday"], days_ahead=12, today=today)
        assert result == ["2026-10-05", "2026-10-12"]

    def test_unknown_day_name_raises(self):
        with pytest.raises(ValueError):
            filters.upcoming_dates_for_days(["Someday"], days_ahead=7)

    def test_empty_days_list_returns_empty(self):
        today = date(2026, 10, 4)
        assert filters.upcoming_dates_for_days([], days_ahead=12, today=today) == []


class TestTimeInRange:
    def test_within_range(self):
        assert filters.time_in_range("07:30", "06:00", "11:00") is True

    def test_before_range(self):
        assert filters.time_in_range("05:59", "06:00", "11:00") is False

    def test_after_range(self):
        assert filters.time_in_range("11:01", "06:00", "11:00") is False

    def test_inclusive_boundaries(self):
        assert filters.time_in_range("06:00", "06:00", "11:00") is True
        assert filters.time_in_range("11:00", "06:00", "11:00") is True


class TestMatchesPreferences:
    def test_matches_all_criteria(self):
        config = {"earliest_time": "06:00", "latest_time": "11:00", "minimum_open_spots": 2}
        tee_time = make_tee_time(time_str="07:30", spots=4)
        assert filters.matches_preferences(tee_time, config) is True

    def test_fails_on_too_few_spots(self):
        config = {"earliest_time": "06:00", "latest_time": "11:00", "minimum_open_spots": 2}
        tee_time = make_tee_time(time_str="07:30", spots=1)
        assert filters.matches_preferences(tee_time, config) is False

    def test_fails_on_time_out_of_range(self):
        config = {"earliest_time": "06:00", "latest_time": "11:00", "minimum_open_spots": 1}
        tee_time = make_tee_time(time_str="13:00", spots=4)
        assert filters.matches_preferences(tee_time, config) is False

    def test_defaults_when_config_sparse(self):
        tee_time = make_tee_time(time_str="23:00", spots=1)
        assert filters.matches_preferences(tee_time, {}) is True


class TestFilterTeeTimes:
    def test_filters_a_mixed_list(self):
        config = {"earliest_time": "06:00", "latest_time": "11:00", "minimum_open_spots": 2}
        good = make_tee_time(time_str="07:00", spots=4)
        bad_time = make_tee_time(time_str="18:00", spots=4)
        bad_spots = make_tee_time(time_str="07:30", spots=1)
        result = filters.filter_tee_times([good, bad_time, bad_spots], config)
        assert result == [good]
