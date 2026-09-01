"""Tests for sources/climate.py — respx-mocked Open-Meteo anomaly math.

Gaps / not covered: real Open-Meteo response schemas; leap-year baseline
window edge (the module uses a fixed 365-day offset); the composite-cache
read path (only the write is asserted).
"""

import asyncio as asyncio_mod
from datetime import datetime, timezone, timedelta

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.climate import (
    CLIMATE_ZONES,
    _compute_anomalies,
    _safe_avg,
    _safe_sum,
    fetch_climate_anomalies,
)

# Current period: max/min pairs (10,0)->5 and (12,2)->7, third pair dropped
# because max is None. Avg temp 6.0. Precip 5+3 (None ignored) = 8.0.
_CURRENT = {
    "daily": {
        "temperature_2m_max": [10.0, 12.0, None],
        "temperature_2m_min": [0.0, 2.0, 5.0],
        "precipitation_sum": [5.0, 3.0, None],
    }
}
# Baseline: avg temp 4.0, precip 40.0.
_BASELINE = {
    "daily": {
        "temperature_2m_max": [8.0, 8.0],
        "temperature_2m_min": [0.0, 0.0],
        "precipitation_sum": [20.0, 20.0],
    }
}


def _mock_archive() -> None:
    """Route current vs baseline payloads by the start_date query param,
    mirroring how the module derives its two windows."""
    now = datetime.now(timezone.utc)
    current_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("start_date") == current_start:
            return httpx.Response(200, json=_CURRENT)
        return httpx.Response(200, json=_BASELINE)

    respx.get(url__regex=r".*archive-api\.open-meteo\.com.*").mock(side_effect=_handler)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_climate_anomalies_single_zone(fetcher: Fetcher) -> None:
    _mock_archive()

    result = await fetch_climate_anomalies(fetcher, zones=["sahel"])

    assert result["source"] == "open-meteo"
    assert list(result["zones"].keys()) == ["sahel"]
    zone = result["zones"]["sahel"]
    assert zone["name"] == "Sahel Region"
    assert zone["lat"] == 14.0
    assert zone["lon"] == 0.0
    # Derived from the mocked payloads, not from whatever the code emits.
    assert zone["current_avg_temp_c"] == 6.0
    assert zone["baseline_avg_temp_c"] == 4.0
    assert zone["temp_anomaly_c"] == 2.0
    assert zone["current_precip_mm"] == 8.0
    assert zone["baseline_precip_mm"] == 40.0
    assert zone["precip_anomaly_pct"] == -80.0
    # |2.0| <= 3 C and |-80| <= 100% — not significant.
    assert zone["is_significant"] is False
    assert result["significant_anomalies"] == []

    # Composite result cached under the "selected" label.
    assert fetcher.cache.get("climate:anomalies:selected") is not None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_climate_anomalies_all_zones(fetcher: Fetcher) -> None:
    _mock_archive()

    result = await fetch_climate_anomalies(fetcher)
    assert set(result["zones"].keys()) == set(CLIMATE_ZONES.keys())
    assert len(result["zones"]) == 15
    assert fetcher.cache.get("climate:anomalies:all") is not None


@pytest.mark.asyncio
async def test_fetch_climate_anomalies_unknown_zone(fetcher: Fetcher) -> None:
    # No HTTP mocked: an unknown zone key must short-circuit without a fetch.
    result = await fetch_climate_anomalies(fetcher, zones=["atlantis"])
    assert result["zones"] == {}
    assert result["significant_anomalies"] == []
    assert result["source"] == "open-meteo"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_climate_anomalies_api_failure_omits_zone(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suspected bug (documented, not fixed): a zone whose fetch fails is
    silently omitted — the response carries no error/data_gaps marker, so a
    full Open-Meteo outage returns {"zones": {}} indistinguishable in shape
    from a valid run over zero requested zones."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*archive-api\.open-meteo\.com.*").mock(
        return_value=httpx.Response(500)
    )

    result = await fetch_climate_anomalies(fetcher, zones=["sahel"])
    assert result["zones"] == {}
    assert result["significant_anomalies"] == []
    assert "error" not in result  # current (dishonest-quiet) behavior


def test_compute_anomalies_significant_temp() -> None:
    current = {
        "daily": {
            "temperature_2m_max": [12.0],
            "temperature_2m_min": [8.0],
            "precipitation_sum": [0.0],
        }
    }
    baseline = {
        "daily": {
            "temperature_2m_max": [4.0],
            "temperature_2m_min": [4.0],
            "precipitation_sum": [0.0],
        }
    }
    out = _compute_anomalies(current, baseline)
    assert out["temp_anomaly_c"] == 6.0
    assert out["is_significant"] is True


def test_compute_anomalies_zero_baseline_precip_guard() -> None:
    current = {"daily": {"precipitation_sum": [5.0]}}
    baseline = {"daily": {"precipitation_sum": [0.0]}}
    out = _compute_anomalies(current, baseline)
    # Guard divides by max(baseline, 0.1): (5 - 0) / 0.1 * 100 = 5000%.
    assert out["precip_anomaly_pct"] == 5000.0
    assert out["is_significant"] is True  # >100% precip anomaly


def test_compute_anomalies_empty_inputs() -> None:
    out = _compute_anomalies({}, {})
    assert out["current_avg_temp_c"] == 0.0
    assert out["baseline_avg_temp_c"] == 0.0
    assert out["temp_anomaly_c"] == 0.0
    assert out["precip_anomaly_pct"] == 0.0
    assert out["is_significant"] is False


def test_safe_avg_and_sum() -> None:
    assert _safe_avg([]) == 0.0
    assert _safe_avg([None, None]) == 0.0
    assert _safe_avg([1.0, None, 3.0]) == 2.0
    assert _safe_sum([]) == 0.0
    assert _safe_sum([1.5, None, 2.5]) == 4.0
