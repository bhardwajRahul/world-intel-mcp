"""Tests for analysis/cascade.py — infrastructure cascade simulation.

Expected losses come straight from the module's CABLE_DEPENDENCIES table
(e.g. red_sea: Djibouti 0.8, Egypt 0.5, Saudi Arabia 0.3).
"""

from world_intel_mcp.analysis.cascade import simulate_cascade


def _impact_for(result: dict, country: str) -> dict:
    return next(c for c in result["country_impacts"] if c["country"] == country)


def test_single_corridor_full_disruption() -> None:
    result = simulate_cascade(["red_sea"])
    assert result["disrupted"] == ["red_sea"]

    djibouti = _impact_for(result, "Djibouti")
    assert djibouti["total_capacity_loss"] == 0.8
    assert djibouti["impact_score"] == 80
    assert djibouti["risk_level"] == "critical"
    assert djibouti["affected_corridors"] == ["red_sea"]

    # Sorted by impact descending: Djibouti (0.8) leads.
    assert result["country_impacts"][0]["country"] == "Djibouti"
    assert _impact_for(result, "Egypt")["risk_level"] == "high"  # 50
    assert _impact_for(result, "Sudan")["risk_level"] == "moderate"  # 30
    # A single-corridor disruption produces no cascading risks.
    assert result["cascading_risks"] == []


def test_low_risk_tier() -> None:
    result = simulate_cascade(["transpacific"])
    us = _impact_for(result, "United States")
    assert us["impact_score"] == 10
    assert us["risk_level"] == "low"


def test_unknown_corridor_is_ignored() -> None:
    result = simulate_cascade(["atlantis_cable"])
    assert result["disrupted"] == []
    assert result["country_impacts"] == []
    assert result["cascading_risks"] == []


def test_empty_input() -> None:
    result = simulate_cascade([])
    assert result == {"disrupted": [], "country_impacts": [], "cascading_risks": []}


def test_health_status_scales_severity() -> None:
    # status_score 1 (advisory) scales the simulated disruption by 0.8.
    advisory = simulate_cascade(
        ["red_sea"], current_health={"red_sea": {"status_score": 1}}
    )
    assert _impact_for(advisory, "Djibouti")["total_capacity_loss"] == 0.64

    at_risk = simulate_cascade(
        ["red_sea"], current_health={"red_sea": {"status_score": 2}}
    )
    assert _impact_for(at_risk, "Djibouti")["total_capacity_loss"] == 0.72

    # Already-disrupted (3) and clear (0) corridors both simulate at 1.0.
    for status in (0, 3):
        full = simulate_cascade(
            ["red_sea"], current_health={"red_sea": {"status_score": status}}
        )
        assert _impact_for(full, "Djibouti")["total_capacity_loss"] == 0.8


def test_multi_corridor_losses_accumulate_and_cascades_flagged() -> None:
    result = simulate_cascade(["red_sea", "asia_europe"])

    # Saudi Arabia depends on both: 0.3 + 0.35 = 0.65.
    saudi = _impact_for(result, "Saudi Arabia")
    assert saudi["total_capacity_loss"] == 0.65
    assert set(saudi["affected_corridors"]) == {"red_sea", "asia_europe"}
    assert saudi["risk_level"] == "critical"

    descriptions = [r["description"] for r in result["cascading_risks"]]
    # Multi-corridor country risk plus two waterway chokes (Suez Canal and
    # Bab-el-Mandeb both carry red_sea + asia_europe).
    assert any("Multi-corridor disruption" in d for d in descriptions)
    assert any("Suez Canal" in d for d in descriptions)
    assert any("Bab-el-Mandeb" in d for d in descriptions)
    multi = next(
        r for r in result["cascading_risks"] if "Multi-corridor" in r["description"]
    )
    assert "Saudi Arabia" in multi["countries_affected"]
    # Egypt sits on only one of the disrupted corridors.
    assert "Egypt" not in multi["countries_affected"]
