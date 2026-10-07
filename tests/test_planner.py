from datetime import date, datetime, time, timedelta, timezone

import pytest

from planner import (
    calculate_schedule,
    compute_plan,
    estimate_walking_time,
    format_offset,
    make_tz,
    offset_from_longitude,
    water_estimate_liters,
    water_per_person_liters,
)


def test_walking_time_uses_naismith_rule():
    # 10 km at 5 km/h = 2 h, plus 500 m of ascent = 50 min.
    assert estimate_walking_time(10.0, 500.0) == timedelta(hours=2, minutes=50)


def test_walking_time_ignores_negative_inputs():
    assert estimate_walking_time(-5, -100) == timedelta(0)


def test_water_rounds_up_to_half_litre():
    # 2.5 h * 0.5 L = 1.25 L -> 1.5 L per person -> 6 L for four people.
    duration = timedelta(hours=2, minutes=30)
    assert water_per_person_liters(duration) == 1.5
    assert water_estimate_liters(duration, group_size=4) == 6.0


def test_water_minimum_one_person():
    assert water_estimate_liters(timedelta(hours=2), group_size=0) == 1.0


def test_schedule_times():
    tz = timezone.utc
    start = datetime(2026, 6, 1, 8, 0, tzinfo=tz)
    sunset = datetime(2026, 6, 1, 18, 0, tzinfo=tz)
    s = calculate_schedule(start, timedelta(hours=3), sunset)

    assert s["target_finish"] == datetime(2026, 6, 1, 17, 0, tzinfo=tz)
    assert s["latest_safe_start"] == datetime(2026, 6, 1, 14, 0, tzinfo=tz)
    assert s["finish_time"] == datetime(2026, 6, 1, 11, 0, tzinfo=tz)
    assert s["midpoint_time"] == datetime(2026, 6, 1, 9, 30, tzinfo=tz)
    # Must be at the halfway point by 17:00 - 1.5 h = 15:30 to still finish by 17:00.
    assert s["hard_turnaround_time"] == datetime(2026, 6, 1, 15, 30, tzinfo=tz)
    assert s["daylight_margin_minutes"] == 7 * 60
    assert s["safe"] is True


def test_schedule_flags_late_start():
    tz = timezone.utc
    start = datetime(2026, 6, 1, 16, 0, tzinfo=tz)
    sunset = datetime(2026, 6, 1, 18, 0, tzinfo=tz)
    s = calculate_schedule(start, timedelta(hours=3), sunset)
    assert s["safe"] is False


def test_offset_helpers():
    assert format_offset(5.5) == "UTC+5:30"
    assert format_offset(-7) == "UTC-7"
    assert format_offset(0) == "UTC+0"
    assert offset_from_longitude(-122.3) == -8.0
    with pytest.raises(ValueError):
        make_tz(20)


def _plan(**overrides):
    args = dict(
        trail_name="Test Trail",
        on_date=date(2026, 10, 10),
        start_time=time(8, 0),
        distance_km=10,
        elevation_gain_m=300,
        group_size=2,
        latitude=47.6,
        longitude=-122.3,
        utc_offset_hours=-7,
    )
    args.update(overrides)
    return compute_plan(**args)


def test_compute_plan_is_consistent():
    plan = _plan()
    # 10 km = 2 h, 300 m = 30 min, breaks 30 min -> 3 h total.
    assert plan["walking_time_hours"] == 2.5
    assert plan["total_time_hours"] == 3.0
    assert plan["start_time"] == "08:00"
    assert plan["finish_time"] == "11:00"
    assert plan["utc_offset"] == "UTC-7"
    assert plan["safe"] is True
    assert plan["warnings"] == []
    assert plan["water_per_person_liters"] == 1.5  # 0.5 L/h for 3 h
    assert plan["water_liters"] == 3.0  # two people
    # Sunset in Seattle in mid-October is early evening.
    assert "17:00" <= plan["sunset"] <= "19:30"


def test_compute_plan_warns_when_late():
    plan = _plan(start_time=time(16, 0))
    assert plan["safe"] is False
    assert any("after sunset" in w for w in plan["warnings"])


def test_compute_plan_warns_before_sunrise():
    plan = _plan(start_time=time(4, 0))
    assert any("before sunrise" in w for w in plan["warnings"])


def test_india_sun_times_use_explicit_offset():
    plan = _plan(latitude=19.0, longitude=73.0, utc_offset_hours=5.5)
    assert plan["utc_offset"] == "UTC+5:30"
    assert "06:00" <= plan["sunrise"] <= "07:00"
    assert "17:30" <= plan["sunset"] <= "18:45"


def test_polar_night_raises_friendly_error():
    with pytest.raises(ValueError, match="polar"):
        _plan(latitude=80, longitude=0, utc_offset_hours=0, on_date=date(2026, 12, 21))


@pytest.mark.parametrize(
    "overrides",
    [
        {"distance_km": 0},
        {"latitude": 95},
        {"longitude": -200},
        {"route_type": "teleport"},
        {"utc_offset_hours": 30},
    ],
)
def test_compute_plan_validates_inputs(overrides):
    with pytest.raises(ValueError):
        _plan(**overrides)


def test_blank_trail_name_gets_default():
    assert _plan(trail_name="   ")["trail_name"] == "Unnamed trail"
