"""Tests for analysis/situation.py: cited situation briefs (issue #15).

Uses respx to mock the Ollama endpoint, matching the network-edge-mocking
style used elsewhere in this suite (see test_sources.py, test_intelligence.py).
"""

import re

import httpx
import pytest
import respx

from world_intel_mcp.analysis.situation import _extract_metrics, fetch_situation_brief

_OLLAMA_GENERATE = "http://localhost:11434/api/generate"


def _synthetic_overview() -> dict:
    """A synthetic overview shaped like the real per-domain fetch outputs
    (see the corresponding sources/*.py functions), covering every metric
    `_extract_metrics` reports on."""
    return {
        "earthquakes": {
            "earthquakes": [
                {
                    "id": "us1",
                    "magnitude": 4.1,
                    "place": "10km SW of Testville",
                    "time": "2026-08-16T01:00:00Z",
                    "url": "https://earthquake.usgs.gov/us1",
                },
                {
                    "id": "us2",
                    "magnitude": 5.7,
                    "place": "20km N of Sampleton",
                    "time": "2026-08-16T02:00:00Z",
                    "url": "https://earthquake.usgs.gov/us2",
                },
            ],
            "count": 2,
            "source": "usgs",
        },
        "military_flights": {
            "aircraft": [],
            "count": 3,
            "source": "adsb.lol",
            "timestamp": "2026-08-16T03:00:00Z",
        },
        "acled_events": {
            "events": [
                {
                    "event_type": "Battle",
                    "location": "Testcity",
                    "country": "Testland",
                    "event_date": "2026-08-15",
                },
            ],
            "count": 1,
            "source": "acled",
        },
        "wildfires": {
            "fires_by_region": {
                "california": {
                    "count": 5,
                    "top_clusters": [{"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}],
                },
            },
            "total_fires": 5,
        },
        "cyber_threats": {
            "threats": [
                {
                    "type": "c2_ip",
                    "indicator": "1.2.3.4",
                    "threat": "TrickBot",
                    "severity": "critical",
                    "first_seen": "2026-08-15",
                },
            ],
            "count": 1,
        },
        "strategic_posture": {
            "composite_score": 42,
            "risk_level": "moderate",
            "timestamp": "2026-08-16T03:00:00Z",
        },
        "alert_digest": {
            "alerts": [
                {
                    "domain": "space",
                    "priority": "high",
                    "message": "Geomagnetic storm: Kp=6",
                },
            ],
            "alert_count": 1,
            "timestamp": "2026-08-16T03:00:00Z",
        },
        "space_weather": {"current_kp": 6.0, "timestamp": "2026-08-16T03:00:00Z"},
        "disease_outbreaks": {
            "items": [
                {
                    "title": "Outbreak of X in Y",
                    "link": "https://who.int/x",
                    "published": "2026-08-15",
                    "is_high_concern": True,
                },
            ],
            "high_concern_count": 1,
        },
        "news_feed": {
            "items": [
                {
                    "title": "Headline One",
                    "link": "https://news.example/1",
                    "published": "2026-08-16T00:00:00Z",
                },
                {
                    "title": "Headline Two",
                    "link": "https://news.example/2",
                    "published": "2026-08-16T00:30:00Z",
                },
            ],
        },
        "domestic_flights": {
            "total_aircraft": 1234,
            "timestamp": "2026-08-16T03:00:00Z",
        },
        "traffic_flow": {
            "global_avg_congestion": 27,
            "timestamp": "2026-08-16T03:00:00Z",
        },
    }


# ---------------------------------------------------------------------------
# _extract_metrics: unit level, precise citation-map assertions
# ---------------------------------------------------------------------------


def test_sources_populated_from_synthetic_overview() -> None:
    metrics, sources, citations = _extract_metrics(_synthetic_overview())

    assert len(sources) == 13  # 11 single-item domains + 2 news headlines
    # Numbered sequentially with no gaps or duplicates.
    assert [s["n"] for s in sources] == list(range(1, len(sources) + 1))

    domains = {s["domain"] for s in sources}
    assert domains == {
        "earthquakes",
        "military",
        "conflict",
        "wildfires",
        "cyber",
        "posture",
        "alerts",
        "space_weather",
        "health",
        "news",
        "aviation",
        "traffic",
    }

    eq_source = next(s for s in sources if s["domain"] == "earthquakes")
    assert (
        eq_source["url"] == "https://earthquake.usgs.gov/us2"
    )  # higher-magnitude quake
    assert "5.7" in eq_source["description"]
    assert eq_source["timestamp"] == "2026-08-16T02:00:00Z"

    news_sources = [s for s in sources if s["domain"] == "news"]
    assert len(news_sources) == 2
    assert news_sources[0]["url"] == "https://news.example/1"
    assert news_sources[0]["description"] == "Headline One"

    assert metrics["earthquakes"] == 2
    assert metrics["max_magnitude"] == 5.7
    assert citations["earthquakes"] == [eq_source["n"]]
    assert citations["headlines"] == [s["n"] for s in news_sources]


def test_earthquake_count_without_events_produces_no_citation() -> None:
    """Issue #15: never fabricate a citation. A count with no underlying
    event list is not a traceable item, so it must not be cited even
    though the count itself is still reported."""
    overview = _synthetic_overview()
    overview["earthquakes"] = {"earthquakes": [], "count": 3, "source": "usgs"}

    metrics, sources, citations = _extract_metrics(overview)

    assert metrics["earthquakes"] == 3
    assert "earthquakes" not in citations
    assert not any(s["domain"] == "earthquakes" for s in sources)


def test_errored_domain_produces_no_citation() -> None:
    """A domain that failed upstream (carries an `error` key) must not be
    cited even if some default count survives in the metrics dict."""
    overview = _synthetic_overview()
    overview["cyber_threats"] = {
        "error": "CISA KEV unreachable",
        "threats": [],
        "count": 0,
    }

    metrics, sources, citations = _extract_metrics(overview)

    assert "cyber_threats" not in citations
    assert not any(s["domain"] == "cyber" for s in sources)


def test_empty_overview_produces_no_sources() -> None:
    metrics, sources, citations = _extract_metrics({})

    assert sources == []
    assert citations == {}
    assert metrics["earthquakes"] == 0
    assert metrics["risk_level"] == "unknown"


# ---------------------------------------------------------------------------
# fetch_situation_brief: end to end, network edge mocked with respx
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_fallback_brief_is_mechanically_cited() -> None:
    respx.post(_OLLAMA_GENERATE).mock(
        side_effect=httpx.ConnectError("no ollama in test env")
    )

    result = await fetch_situation_brief(_synthetic_overview())

    assert result["ai_generated"] is False
    assert result["model"] == "fallback"
    assert result["cited"] is True
    assert len(result["sources"]) == 13

    real_ns = {s["n"] for s in result["sources"]}
    found_ns = {int(n) for n in re.findall(r"\[(\d+)\]", result["brief"])}
    assert found_ns, "fallback brief carried no citations at all"
    assert found_ns <= real_ns, "fallback brief cited a number with no matching source"

    # Every line of the structured fallback is cited: it is assembled
    # per-metric and every metric here has a traceable source.
    for line in result["brief"].splitlines():
        assert re.search(r"\[\d+\]", line), f"fallback line not cited: {line!r}"


@respx.mock
@pytest.mark.asyncio
async def test_cited_false_when_llm_ignores_citation_instructions() -> None:
    """The load-bearing honesty property: an LLM response that never
    references the source list must be reported as uncited, not silently
    trusted because the model *could* have cited something real."""
    respx.post(_OLLAMA_GENERATE).mock(
        return_value=httpx.Response(
            200,
            json={"response": "Everything looks calm today, nothing much to report."},
        )
    )

    result = await fetch_situation_brief(_synthetic_overview())

    assert result["ai_generated"] is True
    assert result["sources"]  # a real source list was offered to the model
    assert result["cited"] is False  # but the model never used it


@respx.mock
@pytest.mark.asyncio
async def test_cited_true_when_llm_uses_a_real_source_number() -> None:
    respx.post(_OLLAMA_GENERATE).mock(
        return_value=httpx.Response(
            200,
            json={
                "response": "Seismic activity ticked up [1] while cyber indicators [5] held steady."
            },
        )
    )

    result = await fetch_situation_brief(_synthetic_overview())

    assert result["ai_generated"] is True
    assert result["cited"] is True


@respx.mock
@pytest.mark.asyncio
async def test_out_of_range_citation_does_not_count_as_cited() -> None:
    """Citation numbers never exceed the sources list: a bracketed number
    that looks like a citation but doesn't match a real source must not
    be treated as the model honoring the citation instruction."""
    respx.post(_OLLAMA_GENERATE).mock(
        return_value=httpx.Response(
            200,
            json={"response": "Everything is quiet [99], nothing to see [42]."},
        )
    )

    result = await fetch_situation_brief(_synthetic_overview())

    assert len(result["sources"]) == 13
    assert result["cited"] is False


@respx.mock
@pytest.mark.asyncio
async def test_empty_overview_falls_back_uncited() -> None:
    respx.post(_OLLAMA_GENERATE).mock(
        side_effect=httpx.ConnectError("no ollama in test env")
    )

    result = await fetch_situation_brief({})

    assert result["sources"] == []
    assert result["cited"] is False
