"""Tests for sources/military.py parsing/filtering helpers and bbox plumbing.

Deliberately scoped to what test_sources.py does NOT already cover
(fetch_aircraft_details_batch lives there): _is_military_icao,
_is_military_callsign, _extract_aircraft, _icao_to_country, and the bbox
parameter path through both the adsb.lol client-side filter and the
OpenSky query-parameter fallback.

Gaps / not covered: fetch_theater_posture aggregation (exercised
indirectly by intelligence tests via monkeypatch, not live here);
OpenSky auth-header construction with real credentials.
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.military import (
    _extract_aircraft,
    _icao_to_country,
    _is_military_callsign,
    _is_military_icao,
    fetch_military_flights,
)

# OpenSky state vector: index 0 icao24, 1 callsign, 2 origin_country,
# 5 lon, 6 lat, 7 baro alt, 8 on_ground, 9 velocity, 10 heading, 14 squawk.
_MIL_STATE = [
    "ae1234",
    "RCH285  ",
    "United States",
    None,
    None,
    -70.0,
    40.0,
    10000.0,
    False,
    250.0,
    90.0,
    None,
    None,
    None,
    "7700",
    None,
    None,
]
_CIV_STATE = [
    "4ca123",
    "UAL123  ",
    "Ireland",
    None,
    None,
    -71.0,
    41.0,
    11000.0,
    False,
    240.0,
    91.0,
    None,
    None,
    None,
    "1200",
    None,
    None,
]


def test_is_military_icao() -> None:
    assert _is_military_icao("AE1234") is True
    assert _is_military_icao("ae1234") is True  # case-insensitive
    assert _is_military_icao("43C001") is True  # UK military
    assert _is_military_icao("ABC123") is True  # "AB" US extended range
    assert _is_military_icao("700111") is True  # Pakistan
    assert _is_military_icao("4CA123") is False  # civilian Ireland
    assert _is_military_icao("A00001") is False


def test_is_military_callsign() -> None:
    assert _is_military_callsign("RCH285") is True
    assert _is_military_callsign(" duke01 ") is True  # stripped + upper
    assert _is_military_callsign("SAM946") is True
    assert _is_military_callsign("UAL123") is False
    assert _is_military_callsign("") is False
    assert _is_military_callsign(None) is False


def test_extract_aircraft_state_vector_mapping() -> None:
    ac = _extract_aircraft(_MIL_STATE)
    assert ac == {
        "icao24": "ae1234",
        "callsign": "RCH285",  # stripped
        "origin_country": "United States",
        "latitude": 40.0,
        "longitude": -70.0,
        "altitude_m": 10000.0,
        "velocity_ms": 250.0,
        "heading": 90.0,
        "on_ground": False,
        "squawk": "7700",
    }

    # Empty callsign maps to None, not "".
    no_callsign = list(_MIL_STATE)
    no_callsign[1] = ""
    assert _extract_aircraft(no_callsign)["callsign"] is None


def test_icao_to_country_longest_prefix_wins() -> None:
    assert _icao_to_country("ae9999") == "United States"
    assert _icao_to_country("43C001") == "United Kingdom"
    assert _icao_to_country("3AA111") == "France"
    assert _icao_to_country("3F0000") == "Germany"
    assert _icao_to_country("FFFFFF") == ""


@respx.mock
@pytest.mark.asyncio
async def test_fetch_military_flights_adsblol_bbox_client_side_filter(
    fetcher: Fetcher,
) -> None:
    respx.get(url__regex=r".*api\.adsb\.lol/v2/mil.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "ac": [
                    {
                        "hex": "ae1234",
                        "flight": "RCH285 ",
                        "lat": 40.0,
                        "lon": -70.0,
                        "alt_baro": 30000,
                        "gs": 450,
                        "track": 90,
                        "squawk": "1200",
                        "t": "C17",
                        "r": "02-1099",
                    },
                    {
                        "hex": "3f8abc",
                        "flight": "GAF123",
                        "lat": 10.0,
                        "lon": 10.0,
                        "alt_baro": 25000,
                    },
                    # No position — dropped during normalization.
                    {"hex": "aaa000", "lat": None, "lon": 5.0},
                ]
            },
        )
    )

    # Without bbox: both positioned aircraft survive.
    result = await fetch_military_flights(fetcher)
    assert result["source"] == "adsb.lol"
    assert result["military_filter"] == "adsblol_mil_endpoint"
    assert result["count"] == 2
    us_bird = next(a for a in result["aircraft"] if a["icao24"] == "ae1234")
    assert us_bird["callsign"] == "RCH285"
    assert us_bird["origin_country"] == "United States"  # derived from prefix
    assert us_bird["aircraft_type"] == "C17"
    assert us_bird["registration"] == "02-1099"
    assert us_bird["on_ground"] is False

    # With bbox: only the aircraft inside 35..45 lat / -80..-60 lon remains
    # (second call is served from cache, so no rate-limit stall).
    result = await fetch_military_flights(fetcher, bbox="35,-80,45,-60")
    assert result["count"] == 1
    assert result["aircraft"][0]["icao24"] == "ae1234"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_military_flights_opensky_fallback_bbox_params(
    fetcher: Fetcher,
) -> None:
    # adsb.lol answers but with zero aircraft -> falls through to OpenSky.
    respx.get(url__regex=r".*api\.adsb\.lol/v2/mil.*").mock(
        return_value=httpx.Response(200, json={"ac": []})
    )
    opensky_route = respx.get(url__regex=r".*opensky-network\.org.*").mock(
        return_value=httpx.Response(200, json={"states": [_MIL_STATE, _CIV_STATE]})
    )

    result = await fetch_military_flights(fetcher, bbox="10,20,30,40")

    assert result["source"] == "opensky"
    assert result["military_filter"] == "icao_prefix+callsign"
    # Civilian state (non-military icao AND non-military callsign) filtered.
    assert result["count"] == 1
    assert result["aircraft"][0]["icao24"] == "ae1234"

    # bbox must be plumbed into OpenSky query params, in OpenSky's naming.
    params = opensky_route.calls.last.request.url.params
    assert params["lamin"] == "10"
    assert params["lomin"] == "20"
    assert params["lamax"] == "30"
    assert params["lomax"] == "40"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_military_flights_both_sources_down(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*api\.adsb\.lol.*").mock(return_value=httpx.Response(500))
    respx.get(url__regex=r".*opensky-network\.org.*").mock(
        return_value=httpx.Response(500)
    )

    result = await fetch_military_flights(fetcher)
    # Honest degradation: source says "none" rather than claiming a feed.
    assert result["source"] == "none"
    assert result["aircraft"] == []
    assert result["count"] == 0
