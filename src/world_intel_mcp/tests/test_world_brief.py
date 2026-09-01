"""Tests for analysis/world_brief.py — structured daily intelligence summary.

fetch_world_brief composes two analysis functions and three source/analysis
fetchers; tests mock all five at their module boundaries (pattern from
test_aoi.py / test_daily_digest.py).
"""

from datetime import datetime, timezone

import pytest

from world_intel_mcp.analysis import clustering, posture, spikes
from world_intel_mcp.analysis.world_brief import fetch_world_brief
from world_intel_mcp.sources import intelligence


def _make_fake(payload: dict):
    async def _fake(fetcher, *args, **kwargs):
        return payload

    return _fake


_POSTURE = {
    "composite_score": 48.3,
    "risk_level": "ELEVATED",
    "domain_scores": {
        "military": {"score": 32.0, "level": "GUARDED", "signals": []},
        "political": {"score": 80.0, "level": "CRITICAL", "signals": []},
    },
    "top_threats": [
        {"domain": "political", "signal": f"threat {i}", "domain_score": 80.0}
        for i in range(7)
    ],
}

_FOCAL = {
    "focal_points": [
        {
            "entity": f"entity-{i}",
            "entity_type": "country",
            "signal_count": 3,
            "domains": ["conflict"],
        }
        for i in range(10)
    ]
}

_CLUSTERS = {
    "clusters": [
        {
            "keywords": ["kyiv", "strikes", "missile", "grid", "energy", "russia"],
            "article_count": 4,
            "sources": ["BBC", "Reuters", "AP", "AFP"],
            "items": [{"title": "Headline one"}],
        }
    ]
}

_ANOMALIES = {
    "anomalies": [
        {
            "key": "conflict:UKR",
            "z_score": 3.1,
            "current_value": 50,
            "baseline_mean": 20,
            "description": "conflict events well above baseline",
        }
    ]
}

_SPIKES = {
    "spikes": [{"keyword": f"kw{i}", "z_score": 3.0} for i in range(12)],
    "spike_count": 12,
    "cve_mentions": ["CVE-2026-1111"],
    "apt_mentions": ["lazarus"],
}


def _patch_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(posture, "fetch_strategic_posture", _make_fake(_POSTURE))
    monkeypatch.setattr(intelligence, "fetch_focal_points", _make_fake(_FOCAL))
    monkeypatch.setattr(clustering, "fetch_news_clusters", _make_fake(_CLUSTERS))
    monkeypatch.setattr(
        intelligence, "fetch_temporal_anomalies", _make_fake(_ANOMALIES)
    )
    monkeypatch.setattr(spikes, "fetch_keyword_spikes", _make_fake(_SPIKES))


async def test_world_brief_assembles_all_sections(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all(monkeypatch)
    result = await fetch_world_brief(fetcher)

    assert result["date"] == datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert result["source"] == "world-intelligence-brief"

    overview = result["risk_overview"]
    assert overview["composite_score"] == 48.3
    assert overview["risk_level"] == "ELEVATED"
    assert overview["domain_summary"]["political"] == {
        "score": 80.0,
        "level": "CRITICAL",
    }

    # Caps: 8 focal areas of 10, 5 threats of 7, 8 spikes of 12.
    assert result["focal_area_count"] == 8
    assert result["focal_areas"][0]["entity"] == "entity-0"
    assert len(result["top_threats"]) == 5
    assert len(result["trending"]["spikes"]) == 8
    assert result["trending"]["spike_count"] == 12
    assert result["trending"]["cve_mentions"] == ["CVE-2026-1111"]
    assert result["trending"]["apt_mentions"] == ["lazarus"]

    assert result["top_story_count"] == 1
    story = result["top_stories"][0]
    assert story["topic_keywords"] == ["kyiv", "strikes", "missile", "grid", "energy"]
    assert story["sources"] == ["BBC", "Reuters", "AP"]
    assert story["headline"] == "Headline one"

    assert result["anomaly_count"] == 1
    assert result["anomalies"][0]["metric"] == "conflict:UKR"
    assert result["anomalies"][0]["z_score"] == 3.1


async def test_world_brief_survives_posture_failure(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One broken section must degrade to defaults, not sink the brief."""
    _patch_all(monkeypatch)

    async def _broken(fetcher, *args, **kwargs):
        raise RuntimeError("posture upstream down")

    monkeypatch.setattr(posture, "fetch_strategic_posture", _broken)
    result = await fetch_world_brief(fetcher)

    assert result["risk_overview"]["composite_score"] == 0
    assert result["risk_overview"]["risk_level"] == "UNKNOWN"
    assert result["risk_overview"]["domain_summary"] == {}
    assert result["top_threats"] == []
    # The other sections still populate.
    assert result["focal_area_count"] == 8
    assert result["top_story_count"] == 1


async def test_world_brief_all_sources_empty(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    for mod, name in [
        (posture, "fetch_strategic_posture"),
        (intelligence, "fetch_focal_points"),
        (clustering, "fetch_news_clusters"),
        (intelligence, "fetch_temporal_anomalies"),
        (spikes, "fetch_keyword_spikes"),
    ]:
        monkeypatch.setattr(mod, name, _make_fake({}))

    result = await fetch_world_brief(fetcher)
    assert result["focal_area_count"] == 0
    assert result["top_story_count"] == 0
    assert result["anomaly_count"] == 0
    assert result["trending"]["spikes"] == []


@pytest.mark.asyncio
async def test_top_stories_count_from_real_clustering_shape(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: fetch_news_clusters emits the member count as "size",
    and world_brief read only "article_count", so every real brief
    reported 0 articles per story (the silent-zero class). The brief
    must propagate the count from the shape clustering actually emits."""
    _patch_all(monkeypatch)
    real_shape = {
        "clusters": [
            {
                "headline": "Ceasefire talks resume",
                "size": 7,
                "keywords": ["ceasefire", "talks"],
                "sources": ["Reuters"],
                "items": [{"title": "Ceasefire talks resume", "source": "Reuters"}],
            }
        ],
        "cluster_count": 1,
    }
    monkeypatch.setattr(clustering, "fetch_news_clusters", _make_fake(real_shape))
    result = await fetch_world_brief(fetcher)
    assert result["top_stories"][0]["article_count"] == 7
