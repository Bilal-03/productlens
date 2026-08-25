from datetime import date

from app.analytics.time_ranges import default_comparison, resolve_period


def test_last_week_is_latest_complete_week() -> None:
    current = resolve_period("last_week")
    previous = default_comparison("last_week")
    assert current.start == date(2026, 8, 17)
    assert current.end == date(2026, 8, 24)
    assert previous is not None
    assert previous.start == date(2026, 8, 10)
    assert previous.end == date(2026, 8, 17)


def test_month_to_date_uses_equal_elapsed_comparison() -> None:
    current = resolve_period("this_month")
    previous = default_comparison("this_month")
    assert (current.end - current.start).days == 23
    assert previous is not None
    assert (previous.end - previous.start).days == 23

