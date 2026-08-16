"""Tests for analysis/daily_digest.py and the intel_daily_digest tool (issue #15).

Mocks at the source-function boundary (monkeypatch), matching the pattern
used in test_intelligence.py, since daily_digest composes existing
`sources/*.py` fetch functions rather than making HTTP calls itself.
"""

import re
from pathlib import Path

import pytest

from world_intel_mcp.analysis.daily_digest import fetch_daily_digest
from world_intel_mcp.sources import (
    aviation,
    conflict,
    cyber,
    health,
    military,
    news,
    seismology,
    space_weather,
    traffic,
    wildfire,
)

_SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"


class _FakeVectorStore:
    def __init__(self, trend_result: dict, timeline_result: dict) -> None:
        self._trend_result = trend_result
        self._timeline_result = timeline_result

    async def trend_detection(
        self, category=None, recent_hours=6.0, baseline_hours=48.0
    ) -> dict:
        return self._trend_result

    async def timeline(self, domain=None, category=None, hours=24.0, limit=50) -> dict:
        return self._timeline_result


async def _fake_earthquakes(fetcher):
    return {
        "earthquakes": [
            {
                "id": "us1",
                "magnitude": 6.1,
                "place": "5km E of Nowhere",
                "time": "2026-08-16T01:00:00Z",
                "url": "https://earthquake.usgs.gov/us1",
            },
        ],
        "count": 1,
        "source": "usgs",
    }


async def _fake_military(fetcher):
    return {
        "aircraft": [],
        "count": 4,
        "source": "adsb.lol",
        "timestamp": "2026-08-16T00:00:00Z",
    }


async def _fake_acled(fetcher, **kwargs):
    return {
        "events": [
            {
                "event_type": "Battle",
                "location": "Somewhere",
                "event_date": "2026-08-15",
            }
        ],
        "count": 1,
        "source": "acled",
    }


async def _fake_ucdp(fetcher, **kwargs):
    return {"events": [], "count": 0, "source": "ucdp"}


async def _fake_wildfires(fetcher):
    return {
        "fires_by_region": {"california": {"count": 3, "top_clusters": [{}, {}, {}]}},
        "total_fires": 3,
    }


async def _fake_cyber(fetcher):
    return {
        "threats": [
            {
                "type": "c2_ip",
                "indicator": "1.2.3.4",
                "threat": "Emotet",
                "severity": "critical",
                "first_seen": "2026-08-15",
            },
        ],
        "count": 1,
    }


async def _fake_health(fetcher):
    return {
        "items": [
            {
                "title": "Outbreak of Z",
                "link": "https://who.int/z",
                "published": "2026-08-15",
                "is_high_concern": True,
            },
        ],
        "high_concern_count": 1,
    }


async def _fake_news(fetcher):
    return {
        "items": [
            {
                "title": "Big headline",
                "link": "https://news.example/a",
                "published": "2026-08-16T00:00:00Z",
            },
        ],
    }


async def _fake_space_weather(fetcher):
    return {"current_kp": 5.3, "timestamp": "2026-08-16T00:00:00Z"}


async def _fake_domestic_flights(fetcher):
    return {"total_aircraft": 5000, "timestamp": "2026-08-16T00:00:00Z"}


async def _fake_traffic_flow(fetcher):
    return {"global_avg_congestion": 33, "timestamp": "2026-08-16T00:00:00Z"}


def _patch_all_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seismology, "fetch_earthquakes", _fake_earthquakes)
    monkeypatch.setattr(military, "fetch_military_flights", _fake_military)
    monkeypatch.setattr(conflict, "fetch_acled_events", _fake_acled)
    monkeypatch.setattr(conflict, "fetch_ucdp_events", _fake_ucdp)
    monkeypatch.setattr(wildfire, "fetch_wildfires", _fake_wildfires)
    monkeypatch.setattr(cyber, "fetch_cyber_threats", _fake_cyber)
    monkeypatch.setattr(health, "fetch_disease_outbreaks", _fake_health)
    monkeypatch.setattr(news, "fetch_news_feed", _fake_news)
    monkeypatch.setattr(space_weather, "fetch_space_weather", _fake_space_weather)
    monkeypatch.setattr(aviation, "fetch_domestic_flights", _fake_domestic_flights)
    monkeypatch.setattr(traffic, "fetch_traffic_flow", _fake_traffic_flow)


@pytest.mark.asyncio
async def test_digest_markdown_contains_citations_with_vector_store(
    fetcher, monkeypatch
) -> None:
    _patch_all_domains(monkeypatch)
    vs = _FakeVectorStore(
        trend_result={
            "trends": [
                {
                    "category": "Conflict & Security",
                    "recent_count": 10,
                    "baseline_count": 2,
                    "recent_rate_per_hr": 1.7,
                    "baseline_rate_per_hr": 0.2,
                    "change_pct": 750.0,
                    "trend": "SURGE",
                },
                {
                    "category": "Financial Markets",
                    "recent_count": 4,
                    "baseline_count": 4,
                    "recent_rate_per_hr": 0.5,
                    "baseline_rate_per_hr": 0.5,
                    "change_pct": 0.0,
                    "trend": "NORMAL",
                },
            ],
            "categories_analyzed": 2,
            "surges": 1,
            "drops": 0,
        },
        timeline_result={
            "entries": [
                {
                    "domain": "acled",
                    "category": "Conflict & Security",
                    "text": "Battle reported near Somewhere",
                    "datetime": "2026-08-16T00:10:00Z",
                    "timestamp": 0,
                },
            ],
            "count": 1,
            "hours": 24,
        },
    )

    result = await fetch_daily_digest(fetcher, vector_store=vs)

    assert result["vector_store_available"] is True
    assert result["cited"] is True
    assert not any("vector store unavailable" in gap for gap in result["data_gaps"])

    md = result["markdown"]
    assert "## Trends" in md
    assert "SURGE" in md
    assert "NORMAL" not in md  # only notable shifts are surfaced
    assert "## Timeline" in md
    assert "Battle reported near Somewhere" in md

    # Every [n] appearing in the markdown must be a real, existing source.
    found_ns = {int(n) for n in re.findall(r"\[(\d+)\]", md)}
    real_ns = {s["n"] for s in result["sources"]}
    assert found_ns, "expected at least one citation in the digest"
    assert found_ns <= real_ns, "digest cited a number with no matching source"


@pytest.mark.asyncio
async def test_digest_vector_degraded_path_returns_data_gaps(
    fetcher, monkeypatch
) -> None:
    """Primary tested path per the 0.2.0 conventions: no qdrant/fastembed
    installed means vector_store is None. The digest must say so honestly
    rather than rendering an empty Trends/Timeline section as a quiet day."""
    _patch_all_domains(monkeypatch)

    result = await fetch_daily_digest(fetcher, vector_store=None)

    assert result["vector_store_available"] is False
    assert (
        "vector store unavailable: trends and timeline omitted" in result["data_gaps"]
    )

    md = result["markdown"]
    assert (
        md.count("Omitted: vector store unavailable.") == 2
    )  # Trends + Timeline sections

    # Domain events still came through and are still cited; degradation
    # is scoped to the vector-store sections only.
    assert result["cited"] is True
    assert not any(s["domain"] in ("trends", "timeline") for s in result["sources"])


@pytest.mark.asyncio
async def test_digest_domain_failure_reports_gap_not_fabricated_event(
    fetcher, monkeypatch
) -> None:
    _patch_all_domains(monkeypatch)

    async def _broken_cyber(fetcher):
        return {"error": "CISA KEV unreachable"}

    monkeypatch.setattr(cyber, "fetch_cyber_threats", _broken_cyber)

    result = await fetch_daily_digest(fetcher, vector_store=None)

    assert any(
        "Cyber threats: CISA KEV unreachable" in gap for gap in result["data_gaps"]
    )
    assert not any(s["domain"] == "cyber" for s in result["sources"])


def test_intel_daily_digest_registered_and_dispatched() -> None:
    """Structural parity check: the TOOLS/`_dispatch` 1:1 invariant this
    repo maintains (see ROADMAP.md 'MCP tool parity') must hold for the
    new tool. Reads server.py as text rather than importing the module,
    since importing `world_intel_mcp.server` has real side effects
    (opens a live Cache() at the default on-disk path) that no other
    test in this suite triggers."""
    text = _SERVER_PY.read_text()

    assert 'name="intel_daily_digest"' in text

    dispatch_idx = text.index('case "intel_daily_digest":')
    assert dispatch_idx > 0
    dispatch_body = text[dispatch_idx : dispatch_idx + 300]
    assert "fetch_daily_digest" in dispatch_body
