"""Hotspot escalation scoring — composite dynamic scores for intel hotspots.

Pure analysis module — no I/O.
"""

from __future__ import annotations


def score_hotspot(
    hotspot_config: dict,
    news_mentions: int | None = 0,
    military_count: int = 0,
    conflict_events: int = 0,
    convergence_score: float | None = 0,
    fatalities: int = 0,
    protests: int = 0,
) -> dict:
    """Score a single hotspot 0-100 with component breakdown.

    Components, each with a fixed point cap that always sums to 100:
    1. baseline (0-20): static from config, scaled from baseline_escalation 0-5
    2. news (0-20): min(20, news_mentions * 0.2)
    3. military (0-20): min(20, military_count * 1.0)
    4. conflict (0-20): min(20, (conflict_events * 0.5) + (fatalities * 0.1))
    5. social_unrest (0-12): min(12, protests * 0.4)
    6. convergence (0-8): min(8, convergence_score * 2.0)

    ``news_mentions`` and ``convergence_score`` accept ``None`` to mean the
    signal was not measured (as opposed to a real zero count). When either
    is ``None``, its component is reported as ``null`` in ``components``
    (never a fabricated 0.0), that component's point cap is dropped from
    the denominator, and ``score`` is renormalized over only the components
    that were actually measured — so a hotspot with two of four signal
    families structurally unavailable can still reach "critical" instead
    of being capped near "watch" by construction. ``unavailable_components``
    lists which components were skipped this call.

    Args:
        hotspot_config: From INTEL_HOTSPOTS: {lat, lon, baseline_escalation, associated_countries}.
        news_mentions: GDELT/news article count near hotspot, or None if not measured.
        military_count: Aircraft near hotspot.
        conflict_events: ACLED events near hotspot.
        convergence_score: From geo-convergence, or None if not measured.
        fatalities: Total fatalities from conflict events.
        protests: Protest event count near hotspot.

    Returns:
        Dict with score, components, unavailable_components, level, and trend_signal.
    """
    baseline_escalation = hotspot_config.get("baseline_escalation", 0)
    baseline = min(20.0, baseline_escalation * 4.0)

    mil = min(20.0, military_count * 1.0)

    conflict = min(20.0, (conflict_events * 0.5) + (fatalities * 0.1))

    unrest = min(12.0, protests * 0.4)

    raw_total = baseline + mil + conflict + unrest
    max_total = 20.0 + 20.0 + 20.0 + 12.0  # always-available components

    unavailable: list[str] = []

    if news_mentions is None:
        news: float | None = None
        unavailable.append("news")
    else:
        news = min(20.0, news_mentions * 0.2)
        raw_total += news
        max_total += 20.0

    if convergence_score is None:
        convergence: float | None = None
        unavailable.append("convergence")
    else:
        convergence = min(8.0, convergence_score * 2.0)
        raw_total += convergence
        max_total += 8.0

    # Renormalize onto the 0-100 scale using only the components that were
    # actually measured, so missing signals don't structurally cap the score.
    total = (raw_total / max_total) * 100.0 if max_total > 0 else 0.0
    total = min(100.0, max(0.0, total))

    if total >= 70:
        level = "critical"
    elif total >= 40:
        level = "elevated"
    else:
        level = "watch"

    # Trend signal: compare current dynamic signals to baseline
    dynamic_score = total - baseline
    if dynamic_score > 40:
        trend_signal = "surging"
    elif dynamic_score > 20:
        trend_signal = "rising"
    elif dynamic_score > 5:
        trend_signal = "active"
    else:
        trend_signal = "stable"

    return {
        "score": round(total, 1),
        "components": {
            "baseline": round(baseline, 1),
            "news": round(news, 1) if news is not None else None,
            "military": round(mil, 1),
            "conflict": round(conflict, 1),
            "social_unrest": round(unrest, 1),
            "convergence": round(convergence, 1) if convergence is not None else None,
        },
        "unavailable_components": unavailable,
        "level": level,
        "trend_signal": trend_signal,
    }


def score_all_hotspots(
    hotspots: dict[str, dict],
    hotspot_signals: dict[str, dict],
) -> list[dict]:
    """Score all hotspots at once, sorted by score descending.

    Args:
        hotspots: INTEL_HOTSPOTS mapping.
        hotspot_signals: {hotspot_name: {news_mentions, military_count,
            conflict_events, convergence_score, fatalities, protests}}.
            news_mentions/convergence_score default to None (unavailable)
            when absent — NOT 0 — so a signal nobody measured is never
            silently scored as a signal that was measured and found quiet.

    Returns:
        List of scored hotspot dicts sorted by score descending.
    """
    results: list[dict] = []

    for name, config in hotspots.items():
        signals = hotspot_signals.get(name, {})
        scored = score_hotspot(
            hotspot_config=config,
            news_mentions=signals.get("news_mentions"),
            military_count=signals.get("military_count", 0),
            conflict_events=signals.get("conflict_events", 0),
            convergence_score=signals.get("convergence_score"),
            fatalities=signals.get("fatalities", 0),
            protests=signals.get("protests", 0),
        )
        results.append(
            {
                "name": name,
                "lat": config["lat"],
                "lon": config["lon"],
                "associated_countries": config.get("associated_countries", []),
                **scored,
            }
        )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
