"""Tests for sources/fleet.py — component aggregation is monkeypatched at
the sibling-module boundary (fleet imports them inside the function, so
patching the module attributes intercepts the real calls).

Gaps / not covered: the real intelligence/military component functions are
not exercised here (they have their own tests); naval-base static data is
asserted only as non-empty, not for content.
"""

import pytest

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources import intelligence, military
from world_intel_mcp.sources.fleet import _fleet_readiness, fetch_fleet_report


def test_fleet_readiness_low_activity() -> None:
    level, score = _fleet_readiness({}, [], [])
    assert level == "LOW_ACTIVITY"
    assert score == 0


def test_fleet_readiness_high_activity() -> None:
    # aircraft 60 -> capped 30; one critical waterway -> 30; one surge -> 15.
    theaters = {"european": {"count": 60}}
    waterways = [{"status": "critical"}]
    surges = [{"region": "baltic_sea"}]
    level, score = _fleet_readiness(theaters, waterways, surges)
    assert score == 75
    assert level == "HIGH_ACTIVITY"


def test_fleet_readiness_normal_operations() -> None:
    # aircraft 20 -> 10; one advisory waterway -> 10; no surges. Total 20.
    theaters = {"a": {"count": 20}}
    waterways = [{"status": "advisory"}]
    level, score = _fleet_readiness(theaters, waterways, [])
    assert score == 20
    assert level == "NORMAL_OPERATIONS"


def test_fleet_readiness_ignores_non_dict_theaters() -> None:
    level, score = _fleet_readiness({"bad": "not-a-dict"}, [], [])
    assert score == 0
    assert level == "LOW_ACTIVITY"


@pytest.mark.asyncio
async def test_fetch_fleet_report(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _posture(f) -> dict:
        return {
            "theaters": {
                "european": {
                    "count": 4,
                    "top_types": ["C-17", "KC-135", "F-16", "P-8"],
                },
            }
        }

    async def _vessels(f) -> dict:
        return {
            "waterways": [
                {"name": "Suez Canal", "status": "elevated", "warning_count": 2},
            ]
        }

    async def _surges(f) -> dict:
        return {
            "surges": [
                {
                    "region": "black_sea",
                    "aircraft_count": 12,
                    "baseline": 5,
                    "ratio": 2.4,
                },
            ]
        }

    monkeypatch.setattr(military, "fetch_theater_posture", _posture)
    monkeypatch.setattr(intelligence, "fetch_vessel_snapshot", _vessels)
    monkeypatch.setattr(intelligence, "fetch_military_surge", _surges)

    result = await fetch_fleet_report(fetcher)

    assert result["source"] == "fleet-activity-report"
    assert result["theater_count"] == 1
    assert result["theater_summary"] == [
        {
            "name": "european",
            "aircraft_count": 4,
            "top_types": ["C-17", "KC-135", "F-16"],  # truncated to 3
        }
    ]
    assert result["waterway_summary"] == [
        {"name": "Suez Canal", "status": "elevated", "warning_count": 2}
    ]
    assert result["active_surges"] == [
        {"region": "black_sea", "aircraft_count": 12, "baseline": 5, "ratio": 2.4}
    ]
    assert result["surge_count"] == 1
    assert result["total_tracked_aircraft"] == 4
    # Static dataset ships naval bases; the report must see a non-zero count.
    assert result["naval_base_count"] > 0

    # Readiness: 4 aircraft -> 2; elevated waterway -> 20; 1 surge -> 15 = 37.
    assert result["readiness_score"] == 37
    assert result["readiness_level"] == "NORMAL_OPERATIONS"


@pytest.mark.asyncio
async def test_fetch_fleet_report_survives_component_failures(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every dynamic component raising still yields a well-formed report.
    Observation (flagged in review, not fixed): the report carries no
    degraded marker, so three dead components read as a quiet fleet."""

    async def _boom(f) -> dict:
        raise RuntimeError("component down")

    monkeypatch.setattr(military, "fetch_theater_posture", _boom)
    monkeypatch.setattr(intelligence, "fetch_vessel_snapshot", _boom)
    monkeypatch.setattr(intelligence, "fetch_military_surge", _boom)

    result = await fetch_fleet_report(fetcher)

    assert result["readiness_level"] == "LOW_ACTIVITY"
    assert result["readiness_score"] == 0
    assert result["theater_summary"] == []
    assert result["waterway_summary"] == []
    assert result["active_surges"] == []
    assert result["total_tracked_aircraft"] == 0
    assert "error" not in result  # current (dishonest-quiet) behavior


@pytest.mark.asyncio
async def test_waterway_warning_count_from_real_vessel_snapshot_shape(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: fetch_vessel_snapshot emits the count as
    "naval_warnings", and the fleet report read only "warning_count",
    so per-waterway warning counts were 0 in every real report (the
    silent-zero class). The report must propagate the count from the
    shape the snapshot actually emits."""
    from world_intel_mcp.sources import intelligence, military

    async def _snapshot_real_shape(f, **kwargs):
        return {
            "waterways": [
                {"name": "Strait of Hormuz", "status": "critical", "naval_warnings": 3}
            ]
        }

    async def _empty(f, **kwargs):
        return {}

    monkeypatch.setattr(intelligence, "fetch_vessel_snapshot", _snapshot_real_shape)
    monkeypatch.setattr(military, "fetch_theater_posture", _empty)
    monkeypatch.setattr(intelligence, "fetch_military_surge", _empty)

    from world_intel_mcp.sources.fleet import fetch_fleet_report

    result = await fetch_fleet_report(fetcher)
    ww = result["waterway_summary"][0]
    assert ww["name"] == "Strait of Hormuz"
    assert ww["warning_count"] == 3
