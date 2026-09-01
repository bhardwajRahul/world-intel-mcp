"""Tests for sources/launches.py — respx-mocked Launch Library 2.

Gaps / not covered: LL2 pagination (next/previous are ignored by
design); the free-tier 429 throttle response path (exercised only as a
generic failure via the 500 test).
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.launches import _safe_float, fetch_launch_schedule

_LL2 = {
    "count": 2,
    "next": None,
    "previous": None,
    "results": [
        {
            "id": "ll2-launch-demo-1",
            "name": "Pallas-1 | Demo Flight",
            "net": "2026-09-01T02:00:00Z",
            "window_start": "2026-09-01T01:52:00Z",
            "window_end": "2026-09-01T04:09:00Z",
            "status": {"id": 3, "name": "Launch Successful", "abbrev": "Success"},
            "launch_service_provider": {
                "name": "Galactic Energy",
                "type": "Commercial",
            },
            "rocket": {
                "configuration": {"name": "Pallas-1", "full_name": "Pallas-1 Block A"}
            },
            "pad": {
                "name": "Pallas-1 Launch Pad",
                # LL2 serializes pad coordinates as strings.
                "latitude": "40.7759",
                "longitude": "99.8102",
                "location": {
                    "name": "Jiuquan Satellite Launch Center",
                    "country_code": "CHN",
                },
            },
            "mission": {
                "name": "Demo Flight",
                "type": "Test Flight",
                "orbit": {"name": "Sun-Synchronous Orbit", "abbrev": "SSO"},
                "description": "First test launch with a dummy payload. " + "x" * 600,
            },
        },
        {
            "id": "ll2-launch-mystery-2",
            "name": "Mystery Rocket | Classified",
            "net": "2026-09-03T00:00:00Z",
            "status": {"name": "To Be Confirmed", "abbrev": "TBC"},
            "launch_service_provider": None,
            "rocket": {"configuration": {"name": "Mystery", "full_name": ""}},
            "pad": {"name": "Unknown Pad", "latitude": None, "longitude": "bogus"},
            "mission": None,
        },
    ],
}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_launch_schedule_extracts_fields(fetcher: Fetcher) -> None:
    route = respx.get(url__regex=r".*ll\.thespacedevs\.com.*").mock(
        return_value=httpx.Response(200, json=_LL2)
    )

    result = await fetch_launch_schedule(fetcher, limit=10)

    assert result["source"] == "launch-library"
    assert result["count"] == 2
    assert "degraded" not in result
    assert route.calls.last.request.url.params["limit"] == "10"

    first = result["launches"][0]
    assert first["name"] == "Pallas-1 | Demo Flight"
    assert first["provider"] == "Galactic Energy"
    assert first["provider_type"] == "Commercial"
    assert first["vehicle"] == "Pallas-1 Block A"
    assert first["pad"] == "Pallas-1 Launch Pad"
    assert first["pad_location"] == "Jiuquan Satellite Launch Center"
    assert first["country_code"] == "CHN"
    # String coordinates converted to floats.
    assert first["latitude"] == pytest.approx(40.7759)
    assert first["longitude"] == pytest.approx(99.8102)
    assert first["net"] == "2026-09-01T02:00:00Z"
    assert first["window_start"] == "2026-09-01T01:52:00Z"
    assert first["status"] == "Launch Successful"
    assert first["status_abbrev"] == "Success"
    assert first["mission"] == "Demo Flight"
    assert first["mission_type"] == "Test Flight"
    assert first["orbit"] == "SSO"
    # Long descriptions are truncated to 500 chars.
    assert len(first["mission_description"]) == 500
    assert first["mission_description"].startswith(
        "First test launch with a dummy payload."
    )

    second = result["launches"][1]
    assert second["provider"] is None  # null launch_service_provider
    assert second["vehicle"] == "Mystery"  # empty full_name falls back to name
    assert second["latitude"] is None
    assert second["longitude"] is None  # unparseable string
    assert second["mission"] is None
    assert second["orbit"] is None
    assert second["status"] == "To Be Confirmed"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_launch_schedule_limit_truncates_client_side(
    fetcher: Fetcher,
) -> None:
    """Even if the API returns more rows than asked, limit caps output."""
    respx.get(url__regex=r".*ll\.thespacedevs\.com.*").mock(
        return_value=httpx.Response(200, json=_LL2)
    )

    result = await fetch_launch_schedule(fetcher, limit=1)

    assert result["count"] == 1
    assert result["launches"][0]["name"] == "Pallas-1 | Demo Flight"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_launch_schedule_api_down_is_marked_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*ll\.thespacedevs\.com.*").mock(
        return_value=httpx.Response(500)
    )

    result = await fetch_launch_schedule(fetcher)

    assert result["degraded"] is True
    assert result["reason"] == "launch_library_fetch_failed"
    assert "unavailable" in result["error"].lower()
    assert result["launches"] == []
    assert result["count"] == 0


def test_safe_float() -> None:
    assert _safe_float(None) is None
    assert _safe_float("40.5") == 40.5
    assert _safe_float(40.5) == 40.5
    assert _safe_float("bogus") is None
