"""Tests for analysis/surge.py — military surge detection over baselines.

Baselines come from the module's SENSITIVE_REGIONS table (e.g. persian_gulf
United States: 15, red_sea United States: 3, baltic_sea Russia: 3), and the
middle_east theater maps to persian_gulf + red_sea, european to
baltic_sea + black_sea.
"""

import pytest

from world_intel_mcp.analysis.surge import detect_surges


def test_empty_theater_data_yields_no_surges() -> None:
    assert detect_surges({}) == []


def test_surge_detected_in_mapped_regions_sorted_by_ratio() -> None:
    theater = {"middle_east": {"count": 60, "countries": ["United States"]}}
    surges = detect_surges(theater)
    assert [s["region"] for s in surges] == ["red_sea", "persian_gulf"]
    red_sea = surges[0]
    assert red_sea["country"] == "United States"
    assert red_sea["current"] == 60
    assert red_sea["baseline"] == 3
    assert red_sea["surge_ratio"] == 20.0
    assert red_sea["severity"] == "critical"
    assert surges[1]["surge_ratio"] == 4.0  # 60 / persian_gulf baseline 15


def test_at_baseline_is_quiet_above_threshold_reported() -> None:
    """Load-bearing pair in one dataset: 15 aircraft is exactly the
    persian_gulf US baseline (ratio 1.0, silent) while the same count is a
    5x surge against the red_sea baseline of 3."""
    theater = {"middle_east": {"count": 15, "countries": ["United States"]}}
    surges = detect_surges(theater)
    assert [s["region"] for s in surges] == ["red_sea"]
    assert surges[0]["surge_ratio"] == 5.0


@pytest.mark.parametrize(
    "count,expected_severity",
    [
        (5, "watch"),  # 5/3 = 1.67
        (6, "elevated"),  # 6/3 = 2.0
        (9, "critical"),  # 9/3 = 3.0
    ],
)
def test_severity_ladder_for_baltic_russia(count: int, expected_severity: str) -> None:
    theater = {"european": {"count": count, "countries": ["Russia"]}}
    surges = detect_surges(theater)
    baltic = next(s for s in surges if s["region"] == "baltic_sea")
    assert baltic["country"] == "Russia"
    assert baltic["severity"] == expected_severity


def test_count_distributed_across_theater_countries() -> None:
    # 40 aircraft over 2 countries -> 20 each. US 20/15 = 1.33 stays
    # quiet; Iran 20/5 = 4.0 is critical.
    theater = {"middle_east": {"count": 40, "countries": ["United States", "Iran"]}}
    surges = detect_surges(theater)
    gulf = [s for s in surges if s["region"] == "persian_gulf"]
    assert [s["country"] for s in gulf] == ["Iran"]
    assert gulf[0]["current"] == 20
    assert gulf[0]["severity"] == "critical"


def test_country_without_baseline_is_ignored() -> None:
    # France has no baseline in any european-mapped region.
    theater = {"european": {"count": 30, "countries": ["France"]}}
    assert detect_surges(theater) == []


def test_theater_with_no_countries_is_skipped() -> None:
    theater = {"middle_east": {"count": 100, "countries": []}}
    assert detect_surges(theater) == []


def test_temporal_anomaly_boosts_watch_to_elevated() -> None:
    theater = {"european": {"count": 5, "countries": ["Russia"]}}  # 1.67 = watch
    surges = detect_surges(
        theater,
        temporal_baselines={"baltic_sea": {"z_score": 2.5, "multiplier": 1.8}},
    )
    baltic = next(s for s in surges if s["region"] == "baltic_sea")
    assert baltic["severity"] == "elevated"
    assert baltic["temporal_anomaly"] == {"z_score": 2.5, "multiplier": 1.8}


def test_temporal_anomaly_boosts_elevated_to_critical() -> None:
    theater = {"european": {"count": 6, "countries": ["Russia"]}}  # 2.0 = elevated
    surges = detect_surges(theater, temporal_baselines={"baltic_sea": {"z_score": 3.1}})
    baltic = next(s for s in surges if s["region"] == "baltic_sea")
    assert baltic["severity"] == "critical"


def test_weak_temporal_signal_does_not_boost() -> None:
    theater = {"european": {"count": 5, "countries": ["Russia"]}}
    surges = detect_surges(
        theater,
        # z_score must be strictly greater than 2.0 to boost.
        temporal_baselines={"baltic_sea": {"z_score": 2.0, "multiplier": 1.1}},
    )
    baltic = next(s for s in surges if s["region"] == "baltic_sea")
    assert baltic["severity"] == "watch"
    assert "temporal_anomaly" not in baltic
