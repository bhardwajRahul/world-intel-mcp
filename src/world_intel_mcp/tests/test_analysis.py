"""Tests for circuit breaker and infrastructure."""

import time


from world_intel_mcp.analysis.escalation import score_hotspot
from world_intel_mcp.circuit_breaker import CircuitBreaker


def test_circuit_starts_closed() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1.0)
    assert cb.is_available("test-source")


def test_circuit_trips_after_threshold() -> None:
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=10.0)
    cb.record_failure("src")
    assert cb.is_available("src")  # 1 failure, threshold is 2
    cb.record_failure("src")
    assert not cb.is_available("src")  # tripped


def test_circuit_recovers_after_cooldown() -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.5)
    cb.record_failure("src")
    assert not cb.is_available("src")
    time.sleep(0.6)
    assert cb.is_available("src")  # half-open, allows probe


def test_success_resets_failures() -> None:
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=10.0)
    cb.record_failure("src")
    cb.record_failure("src")
    cb.record_success("src")
    assert cb.is_available("src")
    # Even after 2 more failures, need 3 consecutive
    cb.record_failure("src")
    cb.record_failure("src")
    assert cb.is_available("src")  # only 2 since reset


def test_status_output() -> None:
    cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
    cb.record_success("healthy")
    cb.record_failure("unhealthy")
    cb.record_failure("unhealthy")

    status = cb.status()
    assert status["healthy"]["status"] == "closed"
    assert status["unhealthy"]["status"] == "open"
    assert status["unhealthy"]["total_trips"] == 1


def test_independent_sources() -> None:
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60.0)
    cb.record_failure("source_a")
    assert not cb.is_available("source_a")
    assert cb.is_available("source_b")  # independent


def test_circuit_reopens_on_failed_probe_after_cooldown() -> None:
    """Issue #7: is_available() lets a single probe through once cooldown
    elapses, but record_failure() previously only re-tripped the breaker
    when it was closed — so a failed probe left tripped_at stuck at the
    original trip time. Every subsequent is_available() call then saw the
    (stale) cooldown as already elapsed and let calls straight through:
    "half-open forever," backoff never re-enforced against a source that
    is still failing."""
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.2)

    cb.record_failure("src")  # trips
    assert not cb.is_available("src")

    time.sleep(0.25)  # cooldown elapses — single probe allowed
    assert cb.is_available("src")

    cb.record_failure("src")  # the probe itself failed (source still down)

    # A real backoff must block again immediately, not fall straight
    # through — that's the "half-open forever" bug.
    assert not cb.is_available("src")
    assert cb.status()["src"]["status"] == "open"
    assert cb.status()["src"]["cooldown_remaining_s"] > 0

    time.sleep(0.25)  # second cooldown elapses
    assert cb.is_available("src")  # probe allowed again, as expected


def test_score_hotspot_unavailable_signals_are_null_and_renormalized() -> None:
    """Issue #6: news_mentions and convergence_score were hardcoded to 0
    for every hotspot on every call (real per-hotspot signals were never
    wired), which permanently zeroed up to 20 of 100 points and was
    indistinguishable from a genuinely quiet news cycle. An active hotspot
    with every OTHER signal maxed out could never structurally exceed
    80/100 — Kyiv, an active war zone, scored 20.0 ("watch", the lowest
    tier)."""
    hotspot_config = {"baseline_escalation": 5, "lat": 0.0, "lon": 0.0}

    result = score_hotspot(
        hotspot_config,
        news_mentions=None,  # unavailable — NOT measured, not "zero mentions"
        military_count=100,  # maxes the military component (20)
        conflict_events=100,  # maxes the conflict component (20)
        convergence_score=None,  # unavailable
        fatalities=1000,
        protests=100,  # maxes the social_unrest component (12)
    )

    assert result["components"]["news"] is None
    assert result["components"]["convergence"] is None
    assert result["unavailable_components"] == ["news", "convergence"]
    # Renormalized over the 72 points actually measured (baseline 20 +
    # military 20 + conflict 20 + social_unrest 12), all of which are
    # maxed out here — so the score reaches 100, not a value structurally
    # capped by two components that were never real signals to begin with.
    assert result["score"] == 100.0
    assert result["level"] == "critical"


def test_score_hotspot_measured_zero_is_not_unavailable() -> None:
    """A genuinely measured zero (the signal was queried and found quiet)
    must still be reported as 0.0, not conflated with "not measured"."""
    hotspot_config = {"baseline_escalation": 0, "lat": 0.0, "lon": 0.0}

    result = score_hotspot(hotspot_config, news_mentions=0, convergence_score=0.0)

    assert result["components"]["news"] == 0.0
    assert result["components"]["convergence"] == 0.0
    assert result["unavailable_components"] == []
