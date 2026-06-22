"""Tests for synthetic demo freshness helpers."""

from __future__ import annotations

from datetime import date

from dialin.demo_freshness import (
    context_dates_to_ensure,
    is_demo_location,
    observed_dates_to_append,
    recommendation_refresh_dates,
)


def test_demo_location_detection_is_explicit() -> None:
    """Only seeded demo tenant/location pairs should auto-refresh."""

    assert is_demo_location("acct_fadri", "loc_fadri_main")
    assert not is_demo_location("acct_fadri", "loc_other")
    assert not is_demo_location("acct_live", "loc_fadri_main")


def test_observed_dates_append_only_missing_calendar_days() -> None:
    """Synthetic closeout rows should be appended only after the latest date."""

    assert observed_dates_to_append(date(2026, 6, 4), date(2026, 6, 6)) == (
        date(2026, 6, 5),
        date(2026, 6, 6),
    )
    assert observed_dates_to_append(date(2026, 6, 6), date(2026, 6, 6)) == ()


def test_context_dates_include_tomorrow_for_predictions() -> None:
    """Weather and event context should be available for tomorrow's prep row."""

    assert context_dates_to_ensure(date(2026, 6, 4), date(2026, 6, 6)) == (
        date(2026, 6, 5),
        date(2026, 6, 6),
        date(2026, 6, 7),
    )
    assert context_dates_to_ensure(date(2026, 6, 6), date(2026, 6, 6)) == (
        date(2026, 6, 6),
        date(2026, 6, 7),
    )


def test_recommendation_refresh_covers_stale_tail_and_tomorrow() -> None:
    """Opening on June 6 after June 4 data should refresh June 4-7 targets."""

    assert recommendation_refresh_dates(date(2026, 6, 4), date(2026, 6, 6)) == (
        date(2026, 6, 4),
        date(2026, 6, 5),
        date(2026, 6, 6),
        date(2026, 6, 7),
    )
    assert recommendation_refresh_dates(date(2026, 6, 6), date(2026, 6, 6)) == (
        date(2026, 6, 6),
        date(2026, 6, 7),
    )


def test_horizon_extends_to_nearest_open_prep_day() -> None:
    """A closed next day should pull weather and recommendation coverage forward."""

    # Today is Sunday June 21; Monday is closed, so the nearest open prep day is
    # Tuesday June 23. Both context and recommendation horizons must reach it.
    tuesday = date(2026, 6, 23)

    assert context_dates_to_ensure(date(2026, 6, 21), date(2026, 6, 21), tuesday) == (
        date(2026, 6, 21),
        date(2026, 6, 22),
        date(2026, 6, 23),
    )
    assert recommendation_refresh_dates(date(2026, 6, 21), date(2026, 6, 21), tuesday) == (
        date(2026, 6, 21),
        date(2026, 6, 22),
        date(2026, 6, 23),
    )


def test_horizon_never_shrinks_below_default_lookahead() -> None:
    """An already-open next day keeps the standard one-day lookahead."""

    # The nearest open day is tomorrow, so the explicit end must not shorten it.
    assert recommendation_refresh_dates(
        date(2026, 6, 6), date(2026, 6, 6), date(2026, 6, 6)
    ) == (date(2026, 6, 6), date(2026, 6, 7))
