"""Pure planning maths for TrailCard.

Everything in this module is deterministic and works offline: no LLM calls and
no network access. The numbers produced here are the source of truth for the
printed card. The language model only wraps plain-language advice around them.

Safety model (deliberately simple and conservative):

* Walking time uses Naismith's rule: 5 km/h plus 1 minute per 10 m of ascent.
* Planned breaks are added on top of walking time.
* You should be finished at least ``SAFETY_BUFFER_HOURS`` before sunset.
* The *hard turnaround time* is the latest clock time at which you may reach
  the halfway point (far end of an out-and-back, midpoint of a loop) and still
  finish inside that buffer.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone

SPEED_KM_PER_HOUR = 5.0
MINUTES_PER_10M_ASCENT = 1.0
SAFETY_BUFFER_HOURS = 1.0
WATER_LITERS_PER_HOUR_PER_PERSON = 0.5
DEFAULT_BREAK_MINUTES = 30
DEFAULT_EMERGENCY_NUMBER = "112"
ROUTE_TYPES = ("out-and-back", "loop")

# Keys in the plan dictionary that hold clock times ("HH:MM").
TIME_KEYS = (
    "sunrise",
    "sunset",
    "start_time",
    "finish_time",
    "target_finish",
    "latest_safe_start",
    "midpoint_time",
    "hard_turnaround_time",
)


# --------------------------------------------------------------------------- #
# Time zone helpers
# --------------------------------------------------------------------------- #
def offset_from_longitude(longitude: float) -> float:
    """Rough UTC offset (whole hours) from longitude.

    Only used when the caller does not supply an explicit UTC offset. Real
    time zones follow borders and daylight saving, so the app always asks the
    user for the offset instead of relying on this.
    """
    return float(max(-12, min(14, round(longitude / 15.0))))


def make_tz(utc_offset_hours: float) -> timezone:
    """Build a fixed-offset timezone from a number of hours (e.g. 5.5)."""
    if not -12 <= utc_offset_hours <= 14:
        raise ValueError("UTC offset must be between -12 and +14 hours.")
    return timezone(timedelta(hours=utc_offset_hours))


def format_offset(utc_offset_hours: float) -> str:
    """Format an offset like ``UTC+5:30``, ``UTC-7`` or ``UTC+0``."""
    total_minutes = round(utc_offset_hours * 60)
    sign = "-" if total_minutes < 0 else "+"
    hours, minutes = divmod(abs(total_minutes), 60)
    text = f"UTC{sign}{hours}"
    if minutes:
        text += f":{minutes:02d}"
    return text


# --------------------------------------------------------------------------- #
# Core maths
# --------------------------------------------------------------------------- #
def estimate_walking_time(distance_km: float, elevation_gain_m: float) -> timedelta:
    """Naismith's rule: 5 km/h plus 1 minute per 10 m of ascent."""
    distance_km = max(0.0, float(distance_km))
    elevation_gain_m = max(0.0, float(elevation_gain_m))

    hours = distance_km / SPEED_KM_PER_HOUR
    minutes = (elevation_gain_m / 10.0) * MINUTES_PER_10M_ASCENT
    return timedelta(hours=hours, minutes=minutes)


def water_per_person_liters(duration: timedelta) -> float:
    """Water per person, rounded *up* to the nearest 0.5 L."""
    hours = max(0.0, duration.total_seconds() / 3600.0)
    raw = WATER_LITERS_PER_HOUR_PER_PERSON * hours
    return math.ceil(raw * 2) / 2


def water_estimate_liters(duration: timedelta, group_size: int) -> float:
    """Total water for the group (per-person amount times group size)."""
    people = max(1, int(group_size))
    return water_per_person_liters(duration) * people


def get_sun_times(
    latitude: float, longitude: float, on_date: date, tz: timezone
) -> dict[str, datetime]:
    """Sunrise and sunset for a location and date, in the given timezone."""
    from astral import Observer
    from astral.sun import sun

    try:
        result = sun(Observer(latitude, longitude), date=on_date, tzinfo=tz)
    except ValueError as exc:  # polar day / polar night
        raise ValueError(
            "There is no normal sunrise/sunset on this date at this latitude "
            "(polar day or night), so TrailCard cannot plan around daylight."
        ) from exc

    return {"sunrise": result["sunrise"], "sunset": result["sunset"]}


def calculate_schedule(
    start_dt: datetime,
    total_duration: timedelta,
    sunset_dt: datetime,
    buffer_hours: float = SAFETY_BUFFER_HOURS,
) -> dict:
    """Work out finish, latest safe start and turnaround times.

    ``total_duration`` is the full time out (walking plus breaks).
    """
    buffer = timedelta(hours=buffer_hours)
    target_finish = sunset_dt - buffer
    finish_time = start_dt + total_duration

    return {
        "start_time": start_dt,
        "finish_time": finish_time,
        "target_finish": target_finish,
        "latest_safe_start": target_finish - total_duration,
        "midpoint_time": start_dt + total_duration / 2,
        "hard_turnaround_time": target_finish - total_duration / 2,
        "daylight_margin_minutes": round((sunset_dt - finish_time).total_seconds() / 60),
        "safe": finish_time <= target_finish,
    }


def format_time(dt: datetime | None) -> str:
    """Format a datetime as ``HH:MM`` (empty string if missing)."""
    return dt.strftime("%H:%M") if dt else ""


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def compute_plan(
    trail_name: str,
    on_date: date,
    start_time: time,
    distance_km: float,
    elevation_gain_m: float,
    group_size: int,
    latitude: float,
    longitude: float,
    utc_offset_hours: float | None = None,
    break_minutes: int = DEFAULT_BREAK_MINUTES,
    route_type: str = "out-and-back",
    emergency_number: str = DEFAULT_EMERGENCY_NUMBER,
) -> dict:
    """Build the JSON-friendly plan used by the UI, template and language model."""
    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    if float(distance_km) <= 0:
        raise ValueError("Distance must be greater than 0 km.")
    if route_type not in ROUTE_TYPES:
        raise ValueError(f"Route type must be one of {ROUTE_TYPES}.")

    offset = (
        offset_from_longitude(longitude) if utc_offset_hours is None else float(utc_offset_hours)
    )
    tz = make_tz(offset)

    start_dt = datetime.combine(on_date, start_time, tzinfo=tz)
    walking_time = estimate_walking_time(distance_km, elevation_gain_m)
    total_duration = walking_time + timedelta(minutes=max(0, int(break_minutes)))
    sun_times = get_sun_times(latitude, longitude, on_date, tz)
    schedule = calculate_schedule(start_dt, total_duration, sun_times["sunset"])

    warnings: list[str] = []
    if schedule["finish_time"] > sun_times["sunset"]:
        warnings.append(
            f"At this pace you would finish after sunset ({format_time(sun_times['sunset'])}). "
            f"Start by {format_time(schedule['latest_safe_start'])} or choose a shorter route."
        )
    elif not schedule["safe"]:
        warnings.append(
            f"This plan finishes less than {SAFETY_BUFFER_HOURS:g} hour before sunset "
            f"({format_time(sun_times['sunset'])}). "
            f"Start by {format_time(schedule['latest_safe_start'])} or choose a shorter route."
        )
    if schedule["latest_safe_start"] < sun_times["sunrise"]:
        warnings.append(
            "Even starting at first light, this route is long for the daylight available. "
            "Consider a shorter route or carry a headlamp and a backup light."
        )
    if start_dt < sun_times["sunrise"]:
        warnings.append("Your start time is before sunrise. Carry a headlamp.")

    return {
        "trail_name": (trail_name or "").strip() or "Unnamed trail",
        "date": on_date.isoformat(),
        "route_type": route_type,
        "group_size": max(1, int(group_size)),
        "latitude": round(float(latitude), 5),
        "longitude": round(float(longitude), 5),
        "utc_offset": format_offset(offset),
        "distance_km": round(float(distance_km), 2),
        "elevation_gain_m": int(round(max(0.0, float(elevation_gain_m)))),
        "walking_time_hours": round(walking_time.total_seconds() / 3600.0, 2),
        "break_minutes": max(0, int(break_minutes)),
        "total_time_hours": round(total_duration.total_seconds() / 3600.0, 2),
        "water_per_person_liters": water_per_person_liters(total_duration),
        "water_liters": water_estimate_liters(total_duration, group_size),
        "sunrise": format_time(sun_times["sunrise"]),
        "sunset": format_time(sun_times["sunset"]),
        "start_time": format_time(schedule["start_time"]),
        "finish_time": format_time(schedule["finish_time"]),
        "target_finish": format_time(schedule["target_finish"]),
        "latest_safe_start": format_time(schedule["latest_safe_start"]),
        "midpoint_time": format_time(schedule["midpoint_time"]),
        "hard_turnaround_time": format_time(schedule["hard_turnaround_time"]),
        "daylight_margin_minutes": schedule["daylight_margin_minutes"],
        "safety_buffer_hours": SAFETY_BUFFER_HOURS,
        "emergency_number": (emergency_number or "").strip() or DEFAULT_EMERGENCY_NUMBER,
        "safe": bool(schedule["safe"]),
        "warnings": warnings,
    }
