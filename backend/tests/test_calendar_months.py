from __future__ import annotations

from datetime import date

from app.api.routes.reviews import _add_calendar_months


def test_add_months_simple() -> None:
    assert _add_calendar_months(date(2026, 1, 15), 6) == date(2026, 7, 15)


def test_add_months_cross_year() -> None:
    assert _add_calendar_months(date(2026, 11, 10), 3) == date(2027, 2, 10)


def test_add_months_end_of_month_jan_to_feb() -> None:
    assert _add_calendar_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_add_months_end_of_month_leap_year() -> None:
    assert _add_calendar_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_add_months_end_of_month_jan_to_feb_non_leap() -> None:
    assert _add_calendar_months(date(2025, 1, 31), 1) == date(2025, 2, 28)


def test_add_months_end_of_month_mar_to_apr() -> None:
    assert _add_calendar_months(date(2026, 3, 31), 1) == date(2026, 4, 30)


def test_add_months_twelve() -> None:
    assert _add_calendar_months(date(2026, 6, 15), 12) == date(2027, 6, 15)


def test_add_months_zero() -> None:
    assert _add_calendar_months(date(2026, 3, 15), 0) == date(2026, 3, 15)


def test_add_months_feb_29_leap_year() -> None:
    assert _add_calendar_months(date(2028, 2, 29), 12) == date(2029, 2, 28)


def test_add_months_large_value() -> None:
    assert _add_calendar_months(date(2026, 1, 15), 24) == date(2028, 1, 15)
