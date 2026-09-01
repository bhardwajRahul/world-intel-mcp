"""Tests for analysis/convergence.py — geographic multi-domain convergence.

Pure grid math: expected scores are computed by hand from the documented
formula ``type_count * (1 + sqrt(events)) * (total_weight / events)``.
"""

from world_intel_mcp.analysis.convergence import detect_convergence


def _cell_events() -> list[dict]:
    """Three events, two domains, all inside the 1-degree cell (10, 20)."""
    return [
        {"lat": 10.2, "lon": 20.3, "type": "conflict"},
        {"lat": 10.4, "lon": 20.6, "type": "military"},
        {"lat": 10.8, "lon": 20.9, "type": "conflict"},
    ]


def test_detects_multi_domain_cell_and_ignores_others() -> None:
    """The load-bearing triple: a qualifying cell is reported; a monotype
    cell and an under-populated cell are not."""
    events = _cell_events() + [
        # Three events of a single type: fails min_types=2.
        {"lat": 40.1, "lon": 50.1, "type": "fire"},
        {"lat": 40.2, "lon": 50.2, "type": "fire"},
        {"lat": 40.3, "lon": 50.3, "type": "fire"},
        # Two events of two types: fails min_total=3.
        {"lat": 60.2, "lon": 70.2, "type": "conflict"},
        {"lat": 60.3, "lon": 70.3, "type": "military"},
    ]
    hotspots = detect_convergence(events)
    assert len(hotspots) == 1
    hs = hotspots[0]
    assert hs["lat"] == 10.5  # cell center
    assert hs["lon"] == 20.5
    assert hs["event_count"] == 3
    assert hs["signal_types"] == ["conflict", "military"]
    assert hs["type_count"] == 2
    assert hs["total_weight"] == 3.0  # default weight 1.0 each
    # 2 * (1 + sqrt(3)) * (3/3) = 5.4641...
    assert hs["convergence_score"] == 5.46


def test_invalid_coordinates_are_skipped_numeric_strings_accepted() -> None:
    events = _cell_events() + [
        {"lat": None, "lon": 20.5, "type": "conflict"},
        {"lon": 20.5, "type": "conflict"},  # missing lat
        {"lat": "not-a-number", "lon": 20.5, "type": "conflict"},
        # Numeric strings must count: float("10.4") is valid.
        {"lat": "10.4", "lon": "20.5", "type": "outage"},
    ]
    hotspots = detect_convergence(events)
    assert len(hotspots) == 1
    assert hotspots[0]["event_count"] == 4  # 3 base + the string-coord event
    assert "outage" in hotspots[0]["signal_types"]


def test_weights_scale_the_score() -> None:
    events = [
        {"lat": 10.1, "lon": 20.1, "type": "conflict", "weight": 2.0},
        {"lat": 10.2, "lon": 20.2, "type": "military", "weight": 1.0},
        {"lat": 10.3, "lon": 20.3, "type": "conflict", "weight": 3.0},
    ]
    hotspots = detect_convergence(events)
    assert hotspots[0]["total_weight"] == 6.0
    # 2 * (1 + sqrt(3)) * (6/3) = 10.928...
    assert hotspots[0]["convergence_score"] == 10.93


def test_resolution_controls_grouping() -> None:
    # Spread over ~4 degrees: separate 1-degree cells, one 5-degree cell.
    events = [
        {"lat": 10.5, "lon": 20.5, "type": "conflict"},
        {"lat": 12.5, "lon": 22.5, "type": "military"},
        {"lat": 14.4, "lon": 24.4, "type": "conflict"},
    ]
    assert detect_convergence(events, resolution=1.0) == []
    coarse = detect_convergence(events, resolution=5.0)
    assert len(coarse) == 1
    # Cell (2, 4) at resolution 5 -> center ((2+0.5)*5, (4+0.5)*5).
    assert coarse[0]["lat"] == 12.5
    assert coarse[0]["lon"] == 22.5


def test_negative_coordinates_use_floor_not_truncation() -> None:
    """floor(-0.2) is -1; int() truncation toward zero would put these
    events in the wrong cell and report center 0.5 instead of -0.5."""
    events = [
        {"lat": -0.2, "lon": -0.3, "type": "conflict"},
        {"lat": -0.4, "lon": -0.6, "type": "military"},
        {"lat": -0.9, "lon": -0.9, "type": "conflict"},
    ]
    hotspots = detect_convergence(events)
    assert len(hotspots) == 1
    assert hotspots[0]["lat"] == -0.5
    assert hotspots[0]["lon"] == -0.5


def test_hotspots_sorted_by_score_descending() -> None:
    strong = [
        {"lat": 30.1 + i * 0.1, "lon": 40.1, "type": t}
        for i, t in enumerate(["conflict", "military", "fire", "conflict"])
    ]
    weak = _cell_events()
    hotspots = detect_convergence(strong + weak)
    assert len(hotspots) == 2
    # strong: 3 * (1 + sqrt(4)) * 1 = 9.0 beats weak's 5.46
    assert hotspots[0]["convergence_score"] == 9.0
    assert hotspots[0]["lat"] == 30.5
    assert hotspots[0]["convergence_score"] > hotspots[1]["convergence_score"]


def test_empty_input_returns_empty_list() -> None:
    assert detect_convergence([]) == []
