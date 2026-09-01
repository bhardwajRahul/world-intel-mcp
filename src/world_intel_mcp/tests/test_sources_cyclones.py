"""Tests for sources/cyclones.py — respx-mocked NHC CurrentStorms.json.

Gaps / not covered: the real quiet-season payload shape (assumed
``{"activeStorms": []}`` from the populated shape — four storms were
active when this was written, so the quiet shape is mocked, not
observed); Central Pacific (cp) storm ids, mocked only.
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.cyclones import _safe_int, fetch_cyclones

# Field shapes mirror the live feed observed 2026-09-01: intensity and
# pressure are strings, positions are the *Numeric floats.
_NHC = {
    "activeStorms": [
        {
            "id": "al052026",
            "binNumber": "AT5",
            "name": "Edouard",
            "classification": "TS",
            "intensity": "45",
            "pressure": "1000",
            "latitudeNumeric": 29.6,
            "longitudeNumeric": -93.5,
            "movementDir": 305,
            "movementSpeed": 8,
            "lastUpdate": "2026-09-01T17:00:00.000Z",
            "publicAdvisory": {
                "advNum": "005",
                "url": "https://www.nhc.noaa.gov/text/MIATCPAT5.shtml",
            },
        },
        {
            "id": "ep112026",
            "name": "Karina",
            "classification": "HU",
            "intensity": "120",
            "pressure": "945",
            "latitudeNumeric": 18.1,
            "longitudeNumeric": -129.0,
            "movementDir": 270,
            "movementSpeed": 12,
            "lastUpdate": "2026-09-01T15:00:00.000Z",
        },
        {
            "id": "cp032026",
            "name": "Unnamed",
            "classification": "ZZ",  # unknown code passes through raw
            "intensity": "not-a-number",
            "latitudeNumeric": 15.0,
            "longitudeNumeric": 179.9,
        },
    ]
}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_cyclones_extracts_storms(fetcher: Fetcher) -> None:
    respx.get(url__regex=r".*nhc\.noaa\.gov.*").mock(
        return_value=httpx.Response(200, json=_NHC)
    )

    result = await fetch_cyclones(fetcher)

    assert result["source"] == "nhc"
    assert result["count"] == 3
    assert "degraded" not in result
    assert result["by_basin"] == {
        "atlantic": 1,
        "eastern_pacific": 1,
        "central_pacific": 1,
    }

    edouard = result["storms"][0]
    assert edouard["id"] == "al052026"
    assert edouard["name"] == "Edouard"
    assert edouard["basin"] == "atlantic"
    assert edouard["classification"] == "TS"
    assert edouard["classification_name"] == "Tropical Storm"
    assert edouard["intensity_kt"] == 45  # string "45" coerced
    assert edouard["pressure_mb"] == 1000
    assert edouard["latitude"] == pytest.approx(29.6)
    assert edouard["longitude"] == pytest.approx(-93.5)
    assert edouard["movement_dir_deg"] == 305
    assert edouard["movement_speed_kt"] == 8
    assert edouard["last_update"] == "2026-09-01T17:00:00.000Z"
    assert edouard["advisory_url"] == "https://www.nhc.noaa.gov/text/MIATCPAT5.shtml"

    karina = result["storms"][1]
    assert karina["basin"] == "eastern_pacific"
    assert karina["classification_name"] == "Hurricane"
    assert karina["intensity_kt"] == 120
    assert karina["advisory_url"] is None  # no publicAdvisory block

    unnamed = result["storms"][2]
    assert unnamed["basin"] == "central_pacific"
    assert unnamed["classification"] == "ZZ"
    assert unnamed["classification_name"] == "ZZ"  # unknown code kept raw
    assert unnamed["intensity_kt"] is None  # unparseable
    assert unnamed["pressure_mb"] is None  # absent


@respx.mock
@pytest.mark.asyncio
async def test_fetch_cyclones_quiet_season_is_valid_not_degraded(
    fetcher: Fetcher,
) -> None:
    """Zero active storms is a real state of the world, not an outage."""
    respx.get(url__regex=r".*nhc\.noaa\.gov.*").mock(
        return_value=httpx.Response(200, json={"activeStorms": []})
    )

    result = await fetch_cyclones(fetcher)

    assert result["count"] == 0
    assert result["storms"] == []
    assert result["by_basin"] == {}
    assert "degraded" not in result
    assert "error" not in result


@respx.mock
@pytest.mark.asyncio
async def test_fetch_cyclones_feed_down_is_marked_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch failure must never be shape-identical to a quiet tropics."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*nhc\.noaa\.gov.*").mock(return_value=httpx.Response(500))

    result = await fetch_cyclones(fetcher)

    assert result["degraded"] is True
    assert result["reason"] == "nhc_fetch_failed"
    assert "unavailable" in result["error"].lower()
    assert result["storms"] == []
    assert result["count"] == 0


def test_safe_int() -> None:
    assert _safe_int(None) is None
    assert _safe_int("45") == 45
    assert _safe_int(45) == 45
    assert _safe_int("nope") is None
