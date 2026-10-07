from pathlib import Path

import pytest

from gpx_utils import elevation_gain, parse_gpx

SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "sample.gpx"


def test_elevation_gain_ignores_small_noise():
    # Wiggles under 3 m are ignored; real climbs of 10 m, 10 m and 10 m count.
    assert elevation_gain([0, 1, 0, 1, 0, 10, 20, 15, 25]) == 30.0


def test_elevation_gain_handles_missing_values():
    assert elevation_gain([None, 0, None, 10]) == 10.0
    assert elevation_gain([]) == 0.0


def test_parse_sample_gpx():
    result = parse_gpx(SAMPLE.read_bytes())
    assert 3.0 < result["distance_km"] < 6.0
    assert 400 < result["elevation_gain_m"] < 500


def test_parse_gpx_accepts_text():
    result = parse_gpx(SAMPLE.read_text(encoding="utf-8"))
    assert result["distance_km"] > 0


def test_parse_gpx_rejects_garbage():
    with pytest.raises(ValueError):
        parse_gpx(b"this is not gpx")


def test_parse_gpx_rejects_empty_track():
    empty = (
        b'<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        b"<trk><trkseg></trkseg></trk></gpx>"
    )
    with pytest.raises(ValueError):
        parse_gpx(empty)
