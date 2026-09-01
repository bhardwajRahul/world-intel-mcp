"""Tests for analysis/exposure.py — population exposure near active events.

Composition tests mock the three event sources at the source-function
boundary and run against the real config/population.py city dataset
(Tokyo 35.68/139.69, Cairo 30.04/31.24, Seoul 37.57/126.98).
"""

import pytest

from world_intel_mcp.analysis.exposure import (
    _find_exposed_cities,
    _format_pop,
    fetch_population_exposure,
)
from world_intel_mcp.sources import conflict, seismology, wildfire


def test_format_pop_tiers() -> None:
    assert _format_pop(500) == "500"
    assert _format_pop(45_000) == "45K"
    assert _format_pop(2_500_000) == "2.5M"


def test_find_exposed_cities_keeps_nearest_event_and_sorts() -> None:
    cities = [
        {"name": "Nearville", "country": "TST", "lat": 0.0, "lon": 0.0, "pop": 1000},
        {"name": "Edgeton", "country": "TST", "lat": 0.6, "lon": 0.0, "pop": 2000},
        {"name": "Farport", "country": "TST", "lat": 50.0, "lon": 50.0, "pop": 3000},
    ]
    events = [
        {"lat": 0.5, "lon": 0.0, "type": "flood"},  # ~55.6 km from Nearville
        {"lat": 0.1, "lon": 0.0, "type": "quake"},  # ~11.1 km from Nearville
        {"lat": None, "lon": 0.0, "type": "broken"},  # skipped
    ]
    exposed = _find_exposed_cities(events, cities, radius_km=100.0)

    names = [c["city"] for c in exposed]
    assert "Farport" not in names  # outside every radius
    near = next(c for c in exposed if c["city"] == "Nearville")
    # Both events are in range; the record must keep the CLOSER one.
    assert near["nearest_event"] == "quake"
    assert near["distance_km"] == pytest.approx(11.1, abs=0.2)
    # Result sorted by distance ascending.
    distances = [c["distance_km"] for c in exposed]
    assert distances == sorted(distances)


def _make_fake(payload: dict):
    async def _fake(fetcher, *args, **kwargs):
        return payload

    return _fake


async def test_population_exposure_across_three_domains(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        seismology,
        "fetch_earthquakes",
        _make_fake(
            {
                "earthquakes": [
                    {
                        "latitude": 35.68,
                        "longitude": 139.69,
                        "magnitude": 6.1,
                        "place": "near Tokyo",
                    }
                ]
            }
        ),
    )
    monkeypatch.setattr(
        wildfire,
        "fetch_wildfires",
        _make_fake(
            {
                "fires_by_region": {
                    "north_africa": {
                        "top_clusters": [
                            {
                                "lat": 30.04,
                                "lon": 31.24,
                                "max_frp": 500,
                                "fire_count": 12,
                            }
                        ]
                    }
                }
            }
        ),
    )
    monkeypatch.setattr(
        conflict,
        "fetch_acled_events",
        _make_fake(
            {
                "events": [
                    {
                        "latitude": 37.57,
                        "longitude": 126.98,
                        "event_type": "Battles",
                        "location": "Seoul",
                    }
                ]
            }
        ),
    )

    result = await fetch_population_exposure(fetcher, radius_km=200.0)

    assert result["events_analyzed"] == 3
    assert result["radius_km"] == 200.0
    assert result["event_types"] == ["conflict", "earthquake", "wildfire"]

    by_city = {c["city"]: c for c in result["exposed_cities"]}
    assert by_city["Tokyo"]["nearest_event"] == "earthquake"
    assert by_city["Tokyo"]["distance_km"] == 0.0
    assert by_city["Cairo"]["nearest_event"] == "wildfire"
    assert by_city["Seoul"]["nearest_event"] == "conflict"

    assert "JPN" in result["by_country"]
    assert set(result["by_event_type"]) == {"earthquake", "wildfire", "conflict"}
    # Tokyo alone is 37.4M, so the formatted total must be in millions.
    assert result["total_exposed_population"] >= 37_400_000
    assert result["total_exposed_population_formatted"].endswith("M")


async def test_remote_event_exposes_no_cities(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing negative: an event in the empty South Atlantic
    must expose nobody."""
    monkeypatch.setattr(
        seismology,
        "fetch_earthquakes",
        _make_fake(
            {"earthquakes": [{"latitude": -40.0, "longitude": -20.0, "magnitude": 5.5}]}
        ),
    )
    monkeypatch.setattr(wildfire, "fetch_wildfires", _make_fake({}))
    monkeypatch.setattr(conflict, "fetch_acled_events", _make_fake({}))

    result = await fetch_population_exposure(fetcher, radius_km=200.0)
    assert result["events_analyzed"] == 1
    assert result["exposed_city_count"] == 0
    assert result["total_exposed_population"] == 0
    assert result["by_country"] == {}


async def test_event_type_filter_skips_unrequested_sources(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _recording(name: str):
        async def _fake(fetcher, *args, **kwargs):
            calls.append(name)
            return {}

        return _fake

    monkeypatch.setattr(seismology, "fetch_earthquakes", await _recording("quake"))
    monkeypatch.setattr(wildfire, "fetch_wildfires", await _recording("fire"))
    monkeypatch.setattr(conflict, "fetch_acled_events", await _recording("conflict"))

    result = await fetch_population_exposure(fetcher, event_types=["earthquake"])
    assert result["event_types"] == ["earthquake"]
    assert calls == ["quake"]  # wildfire and conflict never fetched


async def test_source_failure_degrades_to_empty(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken(fetcher, *args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(seismology, "fetch_earthquakes", _broken)
    monkeypatch.setattr(wildfire, "fetch_wildfires", _make_fake({}))
    monkeypatch.setattr(conflict, "fetch_acled_events", _make_fake({}))

    result = await fetch_population_exposure(fetcher)
    assert result["events_analyzed"] == 0
    assert result["exposed_city_count"] == 0
