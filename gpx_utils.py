"""GPX helpers: distance and elevation gain, computed locally with gpxpy."""

from __future__ import annotations

from typing import Iterable

import gpxpy

# Ignore elevation wiggles smaller than this (metres). GPS altitude is noisy,
# and summing every tiny up-tick would greatly overstate the climb.
ELEVATION_NOISE_THRESHOLD_M = 3.0


def elevation_gain(elevations: Iterable[float | None], threshold: float = ELEVATION_NOISE_THRESHOLD_M) -> float:
    """Total ascent in metres, ignoring changes smaller than ``threshold``.

    Uses a simple hysteresis filter: the reference elevation only moves once
    the track has climbed or dropped by at least ``threshold`` metres.
    """
    gain = 0.0
    reference: float | None = None

    for value in elevations:
        if value is None:
            continue
        if reference is None:
            reference = float(value)
            continue
        delta = float(value) - reference
        if abs(delta) >= threshold:
            if delta > 0:
                gain += delta
            reference = float(value)

    return gain


def parse_gpx(data: bytes | str) -> dict[str, float]:
    """Parse GPX content and return ``distance_km`` and ``elevation_gain_m``.

    Both tracks and routes are supported. Raises ``ValueError`` if the file is
    not valid GPX or contains no usable path.
    """
    try:
        gpx = gpxpy.parse(data)
    except Exception as exc:  # gpxpy raises several different exception types
        raise ValueError(f"Not a valid GPX file: {exc}") from exc

    distance_m = 0.0
    gain_m = 0.0
    point_count = 0

    for track in gpx.tracks:
        for segment in track.segments:
            points = segment.points
            point_count += len(points)
            distance_m += segment.length_2d()
            gain_m += elevation_gain(p.elevation for p in points)

    for route in gpx.routes:
        points = route.points
        point_count += len(points)
        distance_m += route.length()
        gain_m += elevation_gain(p.elevation for p in points)

    if point_count < 2 or distance_m <= 0:
        raise ValueError("The GPX file does not contain a path with at least two points.")

    return {
        "distance_km": distance_m / 1000.0,
        "elevation_gain_m": gain_m,
    }
