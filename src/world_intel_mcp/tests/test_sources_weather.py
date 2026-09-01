"""Tests for sources/weather.py — respx-mocked NWS active alerts.

Gaps / not covered: real NWS zone-URL resolution (the module never
resolves affectedZones, by design); marine area codes; the severity
parameter's full value set against the live API.
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.weather import _representative_point, fetch_weather_alerts

# Square ring around (-100.5, 30.5); closing vertex repeats the first.
_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-100.0, 30.0],
            [-101.0, 30.0],
            [-101.0, 31.0],
            [-100.0, 31.0],
            [-100.0, 30.0],
        ]
    ],
}

_NWS = {
    "features": [
        {
            "id": "urn:oid:2.49.0.1.840.0.aaa",
            "geometry": _POLYGON,
            "properties": {
                "event": "Tornado Warning",
                "severity": "Extreme",
                "urgency": "Immediate",
                "certainty": "Observed",
                "headline": "Tornado Warning issued for Kerr County",
                "areaDesc": "Kerr, TX",
                "effective": "2026-09-01T11:46:00-05:00",
                "expires": "2026-09-01T12:30:00-05:00",
                "onset": "2026-09-01T11:46:00-05:00",
                "ends": "2026-09-01T12:30:00-05:00",
                "senderName": "NWS San Antonio TX",
            },
        },
        {
            "id": "urn:oid:2.49.0.1.840.0.bbb",
            # Zone-based alert: null geometry, must yield None coords.
            "geometry": None,
            "properties": {
                "event": "Extreme Heat Warning",
                "severity": "Severe",
                "urgency": "Expected",
                "certainty": "Likely",
                "headline": "Extreme Heat Warning until September 5",
                "areaDesc": "Jefferson; Wayne; Edwards",
                "effective": "2026-09-01T11:46:00-05:00",
                "expires": "2026-09-02T06:00:00-05:00",
                "senderName": "NWS Paducah KY",
            },
        },
        {
            "id": "urn:oid:2.49.0.1.840.0.ccc",
            "geometry": None,
            "properties": {
                "event": "Red Flag Warning",
                "severity": "Severe",
                "urgency": "Expected",
                "certainty": "Likely",
                "areaDesc": "Eastern Beaverhead National Forest",
                "senderName": "NWS Missoula MT",
            },
        },
    ]
}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_weather_alerts_extracts_fields_and_centroid(
    fetcher: Fetcher,
) -> None:
    route = respx.get(url__regex=r".*api\.weather\.gov.*").mock(
        return_value=httpx.Response(200, json=_NWS)
    )

    result = await fetch_weather_alerts(fetcher, area="tx", severity="severe")

    assert result["source"] == "nws"
    assert result["coverage"] == "US"
    assert result["count"] == 3
    assert "degraded" not in result
    assert result["by_severity"] == {"Extreme": 1, "Severe": 2}

    tornado = result["alerts"][0]
    assert tornado["event"] == "Tornado Warning"
    assert tornado["severity"] == "Extreme"
    assert tornado["urgency"] == "Immediate"
    assert tornado["headline"] == "Tornado Warning issued for Kerr County"
    assert tornado["area"] == "Kerr, TX"
    assert tornado["effective"] == "2026-09-01T11:46:00-05:00"
    assert tornado["expires"] == "2026-09-01T12:30:00-05:00"
    assert tornado["sender"] == "NWS San Antonio TX"
    # Mean of the square's 4 distinct vertices.
    assert tornado["latitude"] == 30.5
    assert tornado["longitude"] == -100.5

    heat = result["alerts"][1]
    assert heat["latitude"] is None
    assert heat["longitude"] is None

    # Input normalization: area upper-cased, severity capitalized.
    request = route.calls.last.request
    assert request.url.params["area"] == "TX"
    assert request.url.params["severity"] == "Severe"
    assert result["query"] == {"area": "TX", "severity": "Severe"}
    # NWS policy: a descriptive User-Agent must be sent.
    assert "world-intel-mcp" in request.headers["User-Agent"]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_weather_alerts_limit_is_client_side(
    fetcher: Fetcher,
) -> None:
    """The live endpoint rejects a limit query param with HTTP 400
    (verified 2026-09-01), so limit must never reach the request."""
    route = respx.get(url__regex=r".*api\.weather\.gov.*").mock(
        return_value=httpx.Response(200, json=_NWS)
    )

    result = await fetch_weather_alerts(fetcher, limit=2)

    assert result["count"] == 2
    assert len(result["alerts"]) == 2
    assert "limit" not in route.calls.last.request.url.params


@respx.mock
@pytest.mark.asyncio
async def test_fetch_weather_alerts_empty_is_valid_not_degraded(
    fetcher: Fetcher,
) -> None:
    respx.get(url__regex=r".*api\.weather\.gov.*").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    result = await fetch_weather_alerts(fetcher, area="RI")

    assert result["count"] == 0
    assert result["alerts"] == []
    assert result["by_severity"] == {}
    assert "degraded" not in result
    assert "error" not in result


@respx.mock
@pytest.mark.asyncio
async def test_fetch_weather_alerts_api_down_is_marked_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*api\.weather\.gov.*").mock(
        return_value=httpx.Response(500)
    )

    result = await fetch_weather_alerts(fetcher)

    assert result["degraded"] is True
    assert result["reason"] == "nws_fetch_failed"
    assert "unavailable" in result["error"].lower()
    assert result["alerts"] == []
    assert result["count"] == 0
    assert result["coverage"] == "US"


def test_representative_point_variants() -> None:
    assert _representative_point(None) == (None, None)
    assert _representative_point({}) == (None, None)
    assert _representative_point({"type": "Point", "coordinates": [1, 2]}) == (
        None,
        None,
    )
    assert _representative_point({"type": "Polygon", "coordinates": []}) == (
        None,
        None,
    )
    assert _representative_point({"type": "Polygon", "coordinates": [[]]}) == (
        None,
        None,
    )

    lat, lon = _representative_point(_POLYGON)
    assert (lat, lon) == (30.5, -100.5)

    multi = {"type": "MultiPolygon", "coordinates": [_POLYGON["coordinates"]]}
    assert _representative_point(multi) == (30.5, -100.5)

    malformed = {"type": "Polygon", "coordinates": [[["x", "y"], ["x", "y"]]]}
    assert _representative_point(malformed) == (None, None)
