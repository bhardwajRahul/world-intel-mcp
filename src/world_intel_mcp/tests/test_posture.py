"""Tests for analysis/posture.py — strategic posture composite.

fetch_strategic_posture composes 11 source functions, so composition tests
mock at the source-function boundary (pattern from test_aoi.py). The
composite expectation is hand-computed from DOMAIN_WEIGHTS:
0.18*32 + 0.16*80 + 0.16*80 + 0.10*30 + 0.10*40 + 0.08*20 + 0.07*40
+ 0.08*21 + 0.07*55 = 48.29 -> 48.3.
"""

import pytest

from world_intel_mcp.analysis.posture import (
    _risk_level,
    fetch_strategic_posture,
)
from world_intel_mcp.sources import (
    climate,
    cyber,
    health,
    infrastructure,
    intelligence,
    military,
    shipping,
    space_weather,
)


@pytest.mark.parametrize(
    "score,level",
    [
        (80.0, "CRITICAL"),
        (60.0, "HIGH"),
        (40.0, "ELEVATED"),
        (25.0, "GUARDED"),
        (10.0, "LOW"),
    ],
)
def test_risk_level_tiers(score: float, level: str) -> None:
    assert _risk_level(score) == level


def _make_fake(payload: dict):
    async def _fake(fetcher, *args, **kwargs):
        return payload

    return _fake


def _patch_all_sources(monkeypatch: pytest.MonkeyPatch, payloads: dict) -> None:
    monkeypatch.setattr(
        intelligence, "fetch_military_surge", _make_fake(payloads["surge"])
    )
    monkeypatch.setattr(
        military, "fetch_theater_posture", _make_fake(payloads["theaters"])
    )
    monkeypatch.setattr(
        intelligence, "fetch_instability_index", _make_fake(payloads["instability"])
    )
    monkeypatch.setattr(
        intelligence, "fetch_hotspot_escalation", _make_fake(payloads["hotspots"])
    )
    monkeypatch.setattr(
        infrastructure, "fetch_cable_health", _make_fake(payloads["cables"])
    )
    monkeypatch.setattr(
        infrastructure, "fetch_internet_outages", _make_fake(payloads["outages"])
    )
    monkeypatch.setattr(
        shipping, "fetch_shipping_index", _make_fake(payloads["shipping"])
    )
    monkeypatch.setattr(cyber, "fetch_cyber_threats", _make_fake(payloads["cyber"]))
    monkeypatch.setattr(
        health, "fetch_disease_outbreaks", _make_fake(payloads["health"])
    )
    monkeypatch.setattr(
        climate, "fetch_climate_anomalies", _make_fake(payloads["climate"])
    )
    monkeypatch.setattr(
        space_weather, "fetch_space_weather", _make_fake(payloads["space"])
    )


_ACTIVE_WORLD = {
    # military: surge 20 + one active theater (>10 aircraft) 12 = 32
    "surge": {
        "surge_count": 1,
        "surges": [{"region": "red_sea", "aircraft_count": 12}],
    },
    "theaters": {"theaters": {"middle_east": {"count": 20}, "arctic": {"count": 2}}},
    # political: single country CII 80 -> avg 80
    "instability": {
        "countries": [
            {"country_code": "SDN", "country_name": "Sudan", "instability_index": 80}
        ]
    },
    # conflict: top-5 avg of (90 + 70) / 2 = 80
    "hotspots": {
        "hotspots": [{"name": "gaza", "score": 90}, {"name": "kyiv", "score": 70}]
    },
    # infrastructure: 1 at-risk corridor 15 + 3 outages * 5 = 30
    "cables": {
        "corridors": {
            "red_sea": {"status_score": 2},
            "transatlantic_north": {"status_score": 0},
        }
    },
    "outages": {"outage_count": 3},
    # economic: stress passthrough 40
    "shipping": {"stress_score": 40, "assessment": "elevated"},
    # cyber: 10 threats * 2 = 20
    "cyber": {"threat_count": 10, "by_source": {"cisa": 6, "otx": 4}},
    # health: 1 high-concern * 25 + 5 reports * 3 = 40
    "health": {"count": 5, "high_concern_count": 1},
    # climate: 1 extreme (>3C) * 15 + 2 anomalies * 3 = 21
    "climate": {
        "anomalies": [
            {"zone": "arctic", "temp_deviation_c": 4.2},
            {"zone": "sahel", "temp_deviation_c": 1.0},
        ]
    },
    # space: Kp 5.0 * 11 = 55
    "space": {"current_kp": 5.0, "kp_level": "Minor storm"},
}


async def test_posture_composite_weighted_from_all_domains(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all_sources(monkeypatch, _ACTIVE_WORLD)
    result = await fetch_strategic_posture(fetcher)

    scores = {d: info["score"] for d, info in result["domain_scores"].items()}
    assert scores == {
        "military": 32.0,
        "political": 80.0,
        "conflict": 80.0,
        "infrastructure": 30.0,
        "economic": 40.0,
        "cyber": 20.0,
        "health": 40.0,
        "climate": 21.0,
        "space": 55.0,
    }
    assert result["composite_score"] == 48.3
    assert result["risk_level"] == "ELEVATED"
    assert result["domains_assessed"] == 9
    assert result["domain_scores"]["political"]["level"] == "CRITICAL"

    # Top threats come from the highest-scoring domains first.
    assert result["top_threats"][0]["domain_score"] == 80.0
    assert len(result["top_threats"]) <= 10
    # Signals carry human-readable detail.
    assert any("Sudan" in t["signal"] for t in result["top_threats"])


async def test_posture_quiet_world_scores_zero(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every source empty (the shape _safe() returns on failure): the
    composite must be 0/LOW, not an exception or a phantom score."""
    quiet = {key: {} for key in _ACTIVE_WORLD}
    _patch_all_sources(monkeypatch, quiet)
    result = await fetch_strategic_posture(fetcher)

    assert result["composite_score"] == 0.0
    assert result["risk_level"] == "LOW"
    assert all(info["score"] == 0.0 for info in result["domain_scores"].values())
    assert result["top_threats"] == []


async def test_posture_survives_source_exception(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads = dict(_ACTIVE_WORLD)
    _patch_all_sources(monkeypatch, payloads)

    async def _broken(fetcher, *args, **kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(intelligence, "fetch_instability_index", _broken)
    result = await fetch_strategic_posture(fetcher)

    # The broken domain degrades to zero; the others still score.
    assert result["domain_scores"]["political"]["score"] == 0.0
    assert result["domain_scores"]["conflict"]["score"] == 80.0
    # 48.29 - 0.16*80 = 35.49 -> 35.5, still ELEVATED.
    assert result["composite_score"] == 35.5
