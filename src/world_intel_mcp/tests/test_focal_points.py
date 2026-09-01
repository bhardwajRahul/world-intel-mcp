"""Tests for analysis/focal_points.py — entity signal convergence.

Events without timestamps are treated as age zero (recency weight 1.0),
which makes focal scores exactly computable:
score = signal_count * (1 + type_diversity * 0.5) * mean_recency_weight.
"""

from datetime import datetime, timedelta, timezone

from world_intel_mcp.analysis.focal_points import detect_focal_points


def _iso_hours_ago(hours: float) -> str:
    ts = datetime.now(timezone.utc) - timedelta(hours=hours)
    return ts.isoformat().replace("+00:00", "Z")


def test_min_signals_includes_pair_excludes_singleton() -> None:
    """The load-bearing pair: two signals qualify, one does not."""
    events = [
        {"entity": "Iran", "type": "cyber"},
        {"entity": "Iran", "type": "military"},
        {"entity": "Norway", "type": "cyber"},
    ]
    result = detect_focal_points(events, min_signals=2)
    assert [fp["entity"] for fp in result] == ["Iran"]
    assert result[0]["signal_count"] == 2


def test_min_signals_one_admits_singletons() -> None:
    result = detect_focal_points([{"entity": "Norway", "type": "cyber"}], min_signals=1)
    assert [fp["entity"] for fp in result] == ["Norway"]


def test_entity_grouping_is_case_insensitive_display_keeps_first_casing() -> None:
    events = [
        {"entity": "Iran", "type": "cyber"},
        {"entity": "iran", "type": "military"},
        {"entity": "IRAN", "type": "maritime"},
    ]
    result = detect_focal_points(events)
    assert len(result) == 1
    assert result[0]["signal_count"] == 3
    assert result[0]["entity"] == "Iran"  # first event's casing


def test_exact_focal_score_without_timestamps() -> None:
    events = [
        {"entity": "Strait of Hormuz", "type": "maritime", "country": "Iran"},
        {"entity": "Strait of Hormuz", "type": "military", "country": "Oman"},
    ]
    result = detect_focal_points(events)
    fp = result[0]
    # 2 signals * (1 + 2 types * 0.5) * recency 1.0 = 4.0
    assert fp["focal_score"] == 4.0
    assert fp["signal_types"] == ["maritime", "military"]
    assert fp["countries"] == ["Iran", "Oman"]
    assert fp["urgency"] == "watch"


def test_stale_events_are_discarded_and_can_disqualify_entity() -> None:
    events = [
        {"entity": "Iran", "type": "cyber", "timestamp": _iso_hours_ago(1)},
        {"entity": "Iran", "type": "military", "timestamp": _iso_hours_ago(100)},
    ]
    # The stale event drops out, leaving 1 signal < min_signals=2.
    assert detect_focal_points(events, min_signals=2, max_age_hours=48.0) == []
    # With a wider window both events survive.
    wide = detect_focal_points(events, min_signals=2, max_age_hours=200.0)
    assert wide[0]["signal_count"] == 2


def test_urgency_tiers() -> None:
    events = (
        [{"entity": "watchville", "type": "a"}] * 2
        + [{"entity": "elevatia", "type": "a"}] * 5
        + [{"entity": "criticalia", "type": "a"}] * 10
    )
    result = {fp["entity"]: fp["urgency"] for fp in detect_focal_points(events)}
    assert result == {
        "watchville": "watch",
        "elevatia": "elevated",
        "criticalia": "critical",
    }


def test_recent_events_capped_at_ten_and_internal_fields_stripped() -> None:
    events = [{"entity": "Sudan", "type": "conflict", "id": i} for i in range(12)]
    result = detect_focal_points(events)
    fp = result[0]
    assert fp["signal_count"] == 12
    assert len(fp["recent_events"]) == 10
    for ev in fp["recent_events"]:
        assert not any(key.startswith("_") for key in ev)


def test_events_without_entity_are_skipped() -> None:
    assert detect_focal_points([{"type": "cyber"}, {"type": "military"}]) == []


def test_sorted_by_focal_score_descending() -> None:
    events = [{"entity": "busy", "type": t} for t in ["a", "b", "c", "a", "b", "c"]] + [
        {"entity": "quiet", "type": "a"},
        {"entity": "quiet", "type": "a"},
    ]
    result = detect_focal_points(events)
    assert [fp["entity"] for fp in result] == ["busy", "quiet"]
    # busy: 6 * (1 + 3*0.5) = 15.0; quiet: 2 * 1.5 = 3.0
    assert result[0]["focal_score"] == 15.0
    assert result[1]["focal_score"] == 3.0


def test_timestamp_type_tolerance() -> None:
    """datetime objects (aware and naive), unparseable strings, and junk
    types must all be tolerated rather than crash or silently drop."""
    now = datetime.now(timezone.utc)
    events = [
        {
            "entity": "Red Sea",
            "type": "maritime",
            "timestamp": now - timedelta(hours=1),
        },
        {
            "entity": "Red Sea",
            "type": "military",
            # Naive datetime is interpreted as UTC.
            "timestamp": (now - timedelta(hours=2)).replace(tzinfo=None),
        },
        {"entity": "Red Sea", "type": "cyber", "timestamp": "not-a-date"},
        {"entity": "Red Sea", "type": "conflict", "timestamp": 12345},
    ]
    result = detect_focal_points(events)
    assert result[0]["signal_count"] == 4
