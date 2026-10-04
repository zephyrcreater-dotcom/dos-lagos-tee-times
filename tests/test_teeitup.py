import pytest

from src.teeitup import TeeItUpError, booking_url_for_date, booking_url_for_slot, parse_tee_times_response

SAMPLE_RESPONSE = [
    {
        "dayInfo": {"dawn": "2026-10-10T13:27:00.000Z"},
        "courseId": "54f14c830c8ad60378b02750",
        "totalAvailableTeetimes": 1,
        "teetimes": [
            {
                "courseId": "54f14c830c8ad60378b02750",
                "teetime": "2026-10-10T14:32:00.000Z",
                "maxPlayers": 4,
                "bookedPlayers": 0,
                "players": [],
                "rates": [
                    {
                        "_id": 311324260,
                        "externalId": "311324260",
                        "name": "18 Holes",
                        "greenFeeCart": 4700,
                    }
                ],
            }
        ],
    }
]


class TestParseTeeTimesResponse:
    def test_parses_valid_response(self):
        result = parse_tee_times_response(SAMPLE_RESPONSE, "2026-10-10", "3510")
        assert len(result) == 1
        t = result[0]
        assert t.date == "2026-10-10"
        assert t.available_spots == 4
        assert t.price == 47.0
        assert t.rate_name == "18 Holes"
        assert t.unique_id == "2026-10-10:2026-10-10T14:32:00.000Z:311324260"
        # 14:32 UTC on 2026-10-10 is 07:32 Pacific Daylight Time.
        assert t.time == "07:32"
        # The booking URL should be scoped to the 07:00 hour, not the whole day.
        assert "start=7&end=8" in t.booking_url

    def test_available_spots_accounts_for_booked_players(self):
        payload = [
            {
                "teetimes": [
                    {
                        "teetime": "2026-10-10T14:32:00.000Z",
                        "maxPlayers": 4,
                        "bookedPlayers": 3,
                        "rates": [{"_id": 1, "name": "18 Holes", "greenFeeCart": 4700}],
                    }
                ]
            }
        ]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result[0].available_spots == 1

    def test_fully_booked_slot_has_zero_spots_not_negative(self):
        payload = [
            {
                "teetimes": [
                    {
                        "teetime": "2026-10-10T14:32:00.000Z",
                        "maxPlayers": 2,
                        "bookedPlayers": 2,
                        "rates": [{"_id": 1, "name": "18 Holes", "greenFeeCart": 4700}],
                    }
                ]
            }
        ]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result[0].available_spots == 0

    def test_empty_teetimes_list_returns_empty(self):
        payload = [{"dayInfo": {}, "totalAvailableTeetimes": 0, "teetimes": []}]
        result = parse_tee_times_response(payload, "2026-10-17", "3510")
        assert result == []

    def test_missing_teetimes_key_returns_empty(self):
        payload = [{"dayInfo": {}, "totalAvailableTeetimes": 0}]
        result = parse_tee_times_response(payload, "2026-10-17", "3510")
        assert result == []

    def test_entry_missing_max_players_is_skipped_not_raised(self):
        payload = [{"teetimes": [{"teetime": "2026-10-10T14:32:00.000Z", "rates": []}]}]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result == []

    def test_entry_missing_teetime_timestamp_is_skipped(self):
        payload = [{"teetimes": [{"maxPlayers": 4, "bookedPlayers": 0, "rates": []}]}]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result == []

    def test_entry_with_unparseable_timestamp_is_skipped(self):
        payload = [
            {
                "teetimes": [
                    {
                        "teetime": "not-a-timestamp",
                        "maxPlayers": 4,
                        "bookedPlayers": 0,
                        "rates": [{"_id": 1, "name": "18 Holes", "greenFeeCart": 4700}],
                    }
                ]
            }
        ]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result == []

    def test_entry_with_no_rates_is_skipped(self):
        payload = [
            {
                "teetimes": [
                    {"teetime": "2026-10-10T14:32:00.000Z", "maxPlayers": 4, "bookedPlayers": 0, "rates": []}
                ]
            }
        ]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result == []

    def test_rate_missing_price_gets_none_not_crash(self):
        payload = [
            {
                "teetimes": [
                    {
                        "teetime": "2026-10-10T14:32:00.000Z",
                        "maxPlayers": 4,
                        "bookedPlayers": 0,
                        "rates": [{"_id": 1, "name": "18 Holes"}],
                    }
                ]
            }
        ]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result[0].price is None

    def test_malformed_day_block_is_skipped(self):
        payload = ["not-a-dict", {"teetimes": []}]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert result == []

    def test_non_list_top_level_raises(self):
        with pytest.raises(TeeItUpError):
            parse_tee_times_response({"not": "a list"}, "2026-10-10", "3510")

    def test_multiple_rates_produce_multiple_tee_times(self):
        payload = [
            {
                "teetimes": [
                    {
                        "teetime": "2026-10-10T14:32:00.000Z",
                        "maxPlayers": 4,
                        "bookedPlayers": 0,
                        "rates": [
                            {"_id": 1, "name": "18 Holes", "greenFeeCart": 4700},
                            {"_id": 2, "name": "9 Holes", "greenFeeCart": 2500},
                        ],
                    }
                ]
            }
        ]
        result = parse_tee_times_response(payload, "2026-10-10", "3510")
        assert len(result) == 2
        assert {t.rate_name for t in result} == {"18 Holes", "9 Holes"}


class TestBookingUrlForDate:
    def test_builds_expected_url(self):
        url = booking_url_for_date("2026-10-10", "3510")
        assert url == "https://dos-lagos-golf-course.book.teeitup.com/teetimes?course=3510&date=2026-10-10&max=999999"


class TestBookingUrlForSlot:
    def test_brackets_the_containing_hour(self):
        url = booking_url_for_slot("2026-10-10", "07:32", "3510")
        assert url == (
            "https://dos-lagos-golf-course.book.teeitup.com/teetimes"
            "?course=3510&date=2026-10-10&start=7&end=8&max=999999"
        )

    def test_on_the_hour_still_brackets_correctly(self):
        url = booking_url_for_slot("2026-10-10", "14:00", "3510")
        assert "start=14&end=15" in url

    def test_11pm_hour_does_not_overflow_past_23(self):
        url = booking_url_for_slot("2026-10-10", "23:30", "3510")
        assert "start=23&end=23" in url
