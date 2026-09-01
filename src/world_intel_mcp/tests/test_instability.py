"""Tests for analysis/instability.py — Country Instability Index scorers.

Expected values are hand-computed from the documented scoring curves
(e.g. CII v2: weighted 0-25 components * 4, then multiplier, boosts,
UCDP floor, and a 0-100 clamp).
"""

import pytest

from world_intel_mcp.analysis.instability import (
    compute_cii,
    score_conflict_intensity,
    score_conflict_v2,
    score_economic_stress,
    score_humanitarian_crisis,
    score_information,
    score_infrastructure_disruption,
    score_military_activity,
    score_security,
    score_unrest,
)

# ---------------------------------------------------------------------------
# v1 component scorers
# ---------------------------------------------------------------------------


def test_score_conflict_intensity_scales_and_caps() -> None:
    assert score_conflict_intensity(0) == 0.0
    assert score_conflict_intensity(150, days=30) == 10.0  # 5/day * 2
    assert score_conflict_intensity(600, days=30) == 20.0  # capped


def test_score_economic_stress_tiers() -> None:
    assert score_economic_stress(None, None) == 0.0
    assert score_economic_stress(25.0, -6.0) == 20.0  # 10 + 10
    assert score_economic_stress(12.0, 0.5) == 8.0  # 5 + 3
    assert score_economic_stress(6.0, 2.0) == 2.0  # 2 + 0
    assert score_economic_stress(None, -3.0) == 7.0


def test_score_humanitarian_crisis() -> None:
    assert score_humanitarian_crisis(0) == 0.0
    assert score_humanitarian_crisis(10) == 5.0
    assert score_humanitarian_crisis(4, displacement_total=200_000) == 7.0
    assert score_humanitarian_crisis(30, displacement_total=2_000_000) == 20.0


def test_score_infrastructure_disruption() -> None:
    assert score_infrastructure_disruption(0) == 0.0
    assert score_infrastructure_disruption(3, cable_warnings=2) == 11.0
    assert score_infrastructure_disruption(10, cable_warnings=10) == 20.0


@pytest.mark.parametrize(
    "aircraft,expected",
    [(0, 0.0), (3, 2.0), (8, 5.0), (15, 10.0), (30, 15.0), (60, 20.0)],
)
def test_score_military_activity_ladder(aircraft: int, expected: float) -> None:
    assert score_military_activity(aircraft) == expected


# ---------------------------------------------------------------------------
# v2 component scorers (0-25)
# ---------------------------------------------------------------------------


def test_score_unrest() -> None:
    assert score_unrest() == 0.0
    assert score_unrest(protest_count=10, riot_count=4) == 5.0  # 3 + 2
    assert score_unrest(protest_count=50, riot_count=20) == 25.0  # saturated


def test_score_conflict_v2() -> None:
    assert score_conflict_v2() == 0.0
    assert score_conflict_v2(event_count=30, fatalities=200, days=30) == 3.0  # 1 + 2
    assert score_conflict_v2(event_count=450, fatalities=1_000, days=30) == 25.0


def test_score_security() -> None:
    assert score_security() == 0.0
    assert score_security(military_count=10, outage_count=1) == 4.0  # 2.4 + 1.6
    assert score_security(military_count=50, outage_count=5, cable_warnings=3) == 25.0


def test_score_information() -> None:
    assert score_information() == 0.0
    assert score_information(news_velocity=20, trending_count=4) == 5.0  # 3 + 2
    assert score_information(news_velocity=100, trending_count=20) == 25.0


# ---------------------------------------------------------------------------
# compute_cii — v2 weighted path
# ---------------------------------------------------------------------------


def test_compute_cii_v2_weighted_index() -> None:
    # 10*0.25 + 20*0.30 + 5*0.20 + 15*0.25 = 13.25; * 4 = 53.0
    result = compute_cii(unrest=10, conflict=20, security=5, information=15)
    assert result["instability_index"] == 53.0
    assert result["risk_level"] == "high"
    assert result["components"] == {
        "unrest": 10,
        "conflict": 20,
        "security": 5,
        "information": 15,
    }
    assert result["weights"]["conflict"] == 0.30


def test_compute_cii_zero_is_low() -> None:
    result = compute_cii()
    assert result["instability_index"] == 0.0
    assert result["risk_level"] == "low"


def test_compute_cii_event_multiplier_and_cap() -> None:
    boosted = compute_cii(
        unrest=10, conflict=20, security=5, information=15, event_multiplier=1.5
    )
    assert boosted["instability_index"] == 79.5
    assert boosted["risk_level"] == "critical"

    capped = compute_cii(
        unrest=25, conflict=25, security=25, information=25, event_multiplier=3.0
    )
    assert capped["instability_index"] == 100.0


def test_compute_cii_boosts_are_additive() -> None:
    result = compute_cii(
        unrest=10,
        conflict=20,
        security=5,
        information=15,
        focal_boost=5.0,
        displacement_boost=2.0,
    )
    assert result["instability_index"] == 60.0  # 53 + 5 + 2
    assert result["focal_boost"] == 5.0
    assert result["displacement_boost"] == 2.0


def test_compute_cii_ucdp_floor_lifts_low_scores() -> None:
    """An active war (UCDP floor) must not score near zero just because
    live signal feeds are quiet."""
    result = compute_cii(ucdp_floor=40.0)
    assert result["instability_index"] == 40.0
    assert result["risk_level"] == "medium"
    assert result["ucdp_floor"] == 40.0
    # The floor only lifts; it never drags a higher score down.
    high = compute_cii(
        unrest=25, conflict=25, security=25, information=25, ucdp_floor=40.0
    )
    assert high["instability_index"] == 100.0


# ---------------------------------------------------------------------------
# compute_cii — v1 backward-compat path
# ---------------------------------------------------------------------------


def test_compute_cii_v1_fallback_simple_sum() -> None:
    result = compute_cii(
        conflict=20.0,
        economic=15.0,
        humanitarian=10.0,
        infrastructure=5.0,
        military=20.0,
    )
    assert result["instability_index"] == 70.0
    assert result["risk_level"] == "high"
    # v1 responses carry the legacy component names and no weights.
    assert result["components"]["conflict_intensity"] == 20.0
    assert result["components"]["economic_stress"] == 15.0
    assert "weights" not in result


@pytest.mark.parametrize(
    "total,expected_level",
    [(80.0, "critical"), (60.0, "high"), (30.0, "medium"), (10.0, "low")],
)
def test_compute_cii_v1_risk_tiers(total: float, expected_level: str) -> None:
    result = compute_cii(conflict=total, economic=0.0)
    assert result["instability_index"] == total
    assert result["risk_level"] == expected_level
