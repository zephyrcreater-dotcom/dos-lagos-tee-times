from datetime import time

from src.monitor import _now_in_window, _parse_hhmm_local


class TestParseHHMMLocal:
    def test_parses_basic_time(self):
        assert _parse_hhmm_local("23:30") == time(23, 30)

    def test_parses_midnight(self):
        assert _parse_hhmm_local("00:00") == time(0, 0)


class TestNowInWindow:
    def test_non_wrapping_window_inside(self):
        assert _now_in_window(time(9, 0), time(17, 0), now=time(12, 0)) is True

    def test_non_wrapping_window_outside(self):
        assert _now_in_window(time(9, 0), time(17, 0), now=time(20, 0)) is False

    def test_wrapping_window_inside_before_midnight(self):
        assert _now_in_window(time(23, 30), time(1, 30), now=time(23, 45)) is True

    def test_wrapping_window_inside_after_midnight(self):
        assert _now_in_window(time(23, 30), time(1, 30), now=time(0, 15)) is True

    def test_wrapping_window_outside(self):
        assert _now_in_window(time(23, 30), time(1, 30), now=time(12, 0)) is False

    def test_wrapping_window_boundary_inclusive(self):
        assert _now_in_window(time(23, 30), time(1, 30), now=time(23, 30)) is True
        assert _now_in_window(time(23, 30), time(1, 30), now=time(1, 30)) is True
