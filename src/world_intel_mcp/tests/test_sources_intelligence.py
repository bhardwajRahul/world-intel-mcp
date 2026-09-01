"""Tests for sources/intelligence.py success paths and degradation shapes.

Complements tests/test_intelligence.py (which covers the issue-#3 ACLED
failure-honesty paths for fetch_risk_scores and the hotspot-escalation
unavailable-components disclosure). This file covers the remaining ten
public functions.

Patching strategy: intelligence.py binds ``acled_query``/
``acled_failure_reason`` into its own namespace at import, so those are
patched on the intelligence module; sibling sources (news, military,
infrastructure, seismology, displacement, maritime, conflict) are imported
inside each function body and looked up as module attributes at call time,
so those are patched on their own modules.

Gaps / not covered: the real ACLED OAuth flow (covered by
test_intelligence.py via _acled_get_token); Ollama streaming; the
TemporalBaseline anomaly-firing path (needs 10+ historical observations —
only the recording path is exercised here); exact CII arithmetic
(instability tests assert raw_data pass-through and the UCDP floor, not
the weighted-sum internals, which belong to analysis/instability.py).
"""

from datetime import datetime, timezone

import httpx
import pytest
import respx

from world_intel_mcp.analysis.temporal import TemporalBaseline
from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources import (
    conflict,
    displacement,
    infrastructure,
    intelligence,
    maritime,
    military,
    news,
    seismology,
)
from world_intel_mcp.sources.intelligence import _haversine_km, _risk_level


def _async_return(value):
    async def _fake(*args, **kwargs):
        return value

    return _fake


def _fake_reason(reason: str):
    async def _fake(data):
        return reason

    return _fake


# ---------------------------------------------------------------------------
# _risk_level / _haversine_km helpers
# ---------------------------------------------------------------------------


def test_risk_level_boundaries() -> None:
    assert _risk_level(151) == "critical"
    assert _risk_level(150) == "elevated"
    assert _risk_level(101) == "elevated"
    assert _risk_level(100) == "moderate"
    assert _risk_level(51) == "moderate"
    assert _risk_level(50) == "low"
    assert _risk_level(0) == "low"


def test_haversine_km() -> None:
    assert _haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0
    # One degree of latitude is ~111 km.
    d = _haversine_km(0.0, 0.0, 1.0, 0.0)
    assert 110.0 < d < 112.5


# ---------------------------------------------------------------------------
# Function 1: fetch_country_brief
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_fetch_country_brief_with_ollama(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLLAMA_API_URL", "http://ollama.test")

    respx.get("https://api.worldbank.org/v2/country/UA/indicator/NY.GDP.MKTP.CD").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"page": 1},
                [
                    {"date": "2023", "value": 25000000000000},
                    {"date": "2022", "value": None},  # dropped
                ],
            ],
        )
    )
    respx.get("https://api.worldbank.org/v2/country/UA/indicator/FP.CPI.TOTL.ZG").mock(
        return_value=httpx.Response(
            200, json=[{"page": 1}, [{"date": "2023", "value": 3.2}]]
        )
    )
    respx.post("http://ollama.test/api/generate").mock(
        return_value=httpx.Response(200, json={"response": " Analytical brief. "})
    )

    # ACLED count query succeeds with a string count (exercises coercion).
    monkeypatch.setattr(intelligence, "acled_query", _async_return({"count": "7"}))

    result = await intelligence.fetch_country_brief(fetcher, country_code="UA")

    assert result["source"] == "country-intelligence"
    assert result["country_code"] == "UA"
    assert result["llm_available"] is True
    assert result["brief"] == "Analytical brief."  # stripped
    assert result["data"]["gdp"] == [{"year": "2023", "value": 25000000000000.0}]
    assert result["data"]["inflation"] == [{"year": "2023", "value": 3.2}]
    assert result["data"]["recent_events"] == 7
    assert result["data_gaps"] == []


@respx.mock
@pytest.mark.asyncio
async def test_fetch_country_brief_ollama_down_and_acled_gap(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLLAMA_API_URL", "http://ollama.test")

    respx.get(url__regex=r".*api\.worldbank\.org.*").mock(
        return_value=httpx.Response(200, json=[{"page": 1}, []])
    )
    respx.post("http://ollama.test/api/generate").mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    monkeypatch.setattr(intelligence, "acled_query", _async_return(None))
    monkeypatch.setattr(
        intelligence, "acled_failure_reason", _fake_reason("acled_unconfigured")
    )

    result = await intelligence.fetch_country_brief(fetcher, country_code="UA")

    assert result["llm_available"] is False
    assert result["brief"].startswith("LLM brief unavailable")
    assert result["data"]["gdp"] == []
    assert result["data"]["recent_events"] == 0
    # The failed ACLED count is disclosed, not silently reported as 0 events.
    assert result["data_gaps"] == ["acled_unconfigured"]


# ---------------------------------------------------------------------------
# Function 2: fetch_risk_scores (success path; failure paths live in
# test_intelligence.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_risk_scores_success(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [{"country": "Syria"}] * 100 + [{"country": "Atlantis"}] * 60
    monkeypatch.setattr(intelligence, "acled_query", _async_return({"data": events}))

    result = await intelligence.fetch_risk_scores(fetcher)

    assert result["source"] == "risk-analysis"
    assert result["count"] == 2
    # Atlantis has no curated baseline (defaults to 500/yr = 41.7/month):
    # 60 events -> 144.0 -> elevated. Syria baseline 5000/yr = 416.7/month:
    # 100 events -> 24.0 -> low. Sorted by risk descending.
    atlantis, syria = result["countries"]
    assert atlantis["country"] == "Atlantis"
    assert atlantis["monthly_baseline"] == 41.7
    assert atlantis["risk_score"] == 144.0
    assert atlantis["risk_level"] == "elevated"
    assert syria["country"] == "Syria"
    assert syria["events_30d"] == 100
    assert syria["monthly_baseline"] == 416.7
    assert syria["risk_score"] == 24.0
    assert syria["risk_level"] == "low"


@pytest.mark.asyncio
async def test_fetch_risk_scores_limit(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [{"country": "Syria"}] * 10 + [{"country": "Atlantis"}] * 60
    monkeypatch.setattr(intelligence, "acled_query", _async_return({"data": events}))

    result = await intelligence.fetch_risk_scores(fetcher, limit=1)
    assert result["count"] == 1
    assert result["countries"][0]["country"] == "Atlantis"


# ---------------------------------------------------------------------------
# Function 3: fetch_instability_index
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_instability_index_single_country(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    acled_events = (
        [{"event_type": "Protests", "fatalities": "0"}] * 2
        + [{"event_type": "Riots", "fatalities": 0}]
        + [{"event_type": "Battles", "fatalities": 10}] * 3
    )
    monkeypatch.setattr(
        intelligence, "acled_query", _async_return({"data": acled_events})
    )
    monkeypatch.setattr(
        infrastructure,
        "fetch_internet_outages",
        _async_return({"outages": [{"countries": ["SYR"]}, {"countries": ["UKR"]}]}),
    )

    seen_bbox: list = []

    async def _fake_flights(f, bbox=None):
        seen_bbox.append(bbox)
        return {"count": 10}

    monkeypatch.setattr(military, "fetch_military_flights", _fake_flights)
    monkeypatch.setattr(news, "fetch_gdelt_search", _async_return({"count": 40}))

    result = await intelligence.fetch_instability_index(fetcher, country_code="SYR")

    assert result["source"] == "instability-index-v2"
    assert result["country_code"] == "SYR"
    assert result["country_name"] == "Syria"
    # Raw counts derived from the injected payloads.
    assert result["raw_data"] == {
        "acled_events": 6,
        "protests": 2,
        "riots": 1,
        "conflict_events": 3,
        "fatalities": 30,
        "military_aircraft": 10,
        "internet_outages": 1,  # only the SYR-matching outage
        "news_articles": 40,
    }
    # Syria bbox from the curated table is plumbed into the military query.
    assert seen_bbox == ["32,35,37,42"]
    # Syria (baseline_risk 80) gets the UCDP active-war floor and the
    # displacement boost; the index can never sit below the floor.
    assert result["ucdp_floor"] == 70.0
    assert result["displacement_boost"] == 3.0
    assert result["event_multiplier"] == 1.2
    assert result["instability_index"] >= 70.0
    assert result["risk_level"] in ("high", "critical")
    assert result["data_gaps"] == []


@pytest.mark.asyncio
async def test_fetch_instability_index_multi_country(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = [{"country": "Ukraine", "event_type": "Battles", "fatalities": 3}] * 5
    monkeypatch.setattr(intelligence, "acled_query", _async_return({"data": events}))

    result = await intelligence.fetch_instability_index(fetcher)

    assert result["source"] == "instability-index-v2"
    assert result["count"] == 10
    codes = {c["country_code"] for c in result["countries"]}
    assert codes == set(intelligence._FOCUS_COUNTRIES)

    ukraine = next(c for c in result["countries"] if c["country_code"] == "UKR")
    assert ukraine["events_30d"] == 5
    # UKR baseline_risk 85 -> 70.0 floor.
    assert ukraine["instability_index"] >= 70.0

    # Sorted by instability_index descending.
    indices = [c["instability_index"] for c in result["countries"]]
    assert indices == sorted(indices, reverse=True)


@pytest.mark.asyncio
async def test_fetch_instability_index_multi_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intelligence, "acled_query", _async_return(None))
    monkeypatch.setattr(
        intelligence, "acled_failure_reason", _fake_reason("acled_fetch_failed")
    )

    result = await intelligence.fetch_instability_index(fetcher)
    assert result["degraded"] is True
    assert "fetch failed" in result["error"]


@pytest.mark.asyncio
async def test_fetch_instability_index_multi_unconfigured(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intelligence, "acled_query", _async_return(None))
    monkeypatch.setattr(
        intelligence, "acled_failure_reason", _fake_reason("acled_unconfigured")
    )

    result = await intelligence.fetch_instability_index(fetcher)
    assert "not configured" in result["error"]
    assert result.get("degraded") is None


# ---------------------------------------------------------------------------
# Function 4: fetch_signal_convergence
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_fetch_signal_convergence_custom_point(fetcher: Fetcher) -> None:
    route = respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, json={"features": [{} for _ in range(20)]})
    )

    result = await intelligence.fetch_signal_convergence(fetcher, lat=10.0, lon=20.0)

    assert result["source"] == "signal-convergence"
    assert len(result["hotspots"]) == 1
    hotspot = result["hotspots"][0]
    assert hotspot["name"] == "custom"
    assert hotspot["signals"]["earthquakes"] == 20
    # 20 quakes saturate the 0-5 earthquake band; a custom point gets no
    # known-hotspot bonus, so the score is exactly 5.0.
    assert hotspot["convergence_score"] == 5.0

    # Bounding box derived from lat/lon +/- radius (default 5 degrees).
    params = route.calls.last.request.url.params
    assert float(params["minlatitude"]) == 5.0
    assert float(params["maxlatitude"]) == 15.0
    assert float(params["minlongitude"]) == 15.0
    assert float(params["maxlongitude"]) == 25.0


@respx.mock
@pytest.mark.asyncio
async def test_fetch_signal_convergence_default_hotspots(fetcher: Fetcher) -> None:
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, json={"features": []})
    )

    result = await intelligence.fetch_signal_convergence(fetcher)

    assert len(result["hotspots"]) == 5
    names = {h["name"] for h in result["hotspots"]}
    assert names == set(intelligence._HOTSPOTS)
    # No quakes: each known hotspot keeps only its 2.0 presence bonus.
    assert all(h["convergence_score"] == 2.0 for h in result["hotspots"])


@respx.mock
@pytest.mark.asyncio
async def test_fetch_signal_convergence_usgs_down(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio as asyncio_mod

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(500)
    )

    result = await intelligence.fetch_signal_convergence(fetcher, lat=10.0, lon=20.0)
    assert result["hotspots"][0]["signals"]["earthquakes"] == 0
    assert result["hotspots"][0]["convergence_score"] == 0.0


# ---------------------------------------------------------------------------
# Function 5: fetch_focal_points
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_focal_points_converging_entity(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    monkeypatch.setattr(
        news,
        "fetch_news_feed",
        _async_return(
            {"items": [{"title": "Ukraine strikes report", "published": now_iso}]}
        ),
    )
    monkeypatch.setattr(
        military,
        "fetch_theater_posture",
        _async_return(
            {"theaters": {"european": {"count": 12, "countries": ["Ukraine"]}}}
        ),
    )
    monkeypatch.setattr(
        infrastructure,
        "fetch_internet_outages",
        _async_return(
            {
                "outages": [
                    {"countries": ["Ukraine"], "start": now_iso, "is_ongoing": True}
                ]
            }
        ),
    )
    monkeypatch.setattr(
        intelligence,
        "acled_query",
        _async_return({"data": [{"country": "Ukraine", "event_date": today}]}),
    )

    result = await intelligence.fetch_focal_points(fetcher)

    assert result["source"] == "focal-point-analysis"
    assert result["total_events_analyzed"] == 4
    assert result["count"] == 1
    assert result["data_gaps"] == []

    fp = result["focal_points"][0]
    assert fp["entity"] == "Ukraine"
    assert fp["signal_count"] == 4
    assert fp["signal_types"] == ["infrastructure", "military", "news", "protest"]
    assert fp["urgency"] == "watch"  # < 5 signals
    assert fp["countries"] == ["Ukraine"]


# ---------------------------------------------------------------------------
# Function 6: fetch_signal_summary
# ---------------------------------------------------------------------------


def _patch_signal_summary_sources(
    monkeypatch: pytest.MonkeyPatch,
    conflict_result: dict,
    protest_query_result: dict | None,
) -> None:
    monkeypatch.setattr(conflict, "fetch_acled_events", _async_return(conflict_result))
    monkeypatch.setattr(
        seismology, "fetch_earthquakes", _async_return({"earthquakes": []})
    )
    monkeypatch.setattr(
        infrastructure, "fetch_internet_outages", _async_return({"outages": []})
    )
    monkeypatch.setattr(
        military, "fetch_theater_posture", _async_return({"theaters": {}})
    )
    monkeypatch.setattr(
        intelligence, "acled_query", _async_return(protest_query_result)
    )
    monkeypatch.setattr(
        displacement,
        "fetch_displacement_summary",
        _async_return(
            {"by_origin": [{"country": "Ukraine", "total_displaced": 250000}]}
        ),
    )


@pytest.mark.asyncio
async def test_fetch_signal_summary_aggregates_domains(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_signal_summary_sources(
        monkeypatch,
        conflict_result={
            "events": [{"country": "Ukraine", "fatalities": 5}],
            "count": 1,
        },
        protest_query_result={
            "data": [{"country": "Ukraine", "event_type": "Protests"}]
        },
    )

    result = await intelligence.fetch_signal_summary(fetcher)

    assert result["source"] == "signal-aggregation-v2"
    assert result["count"] == 1
    assert result["data_gaps"] == []

    ukraine = result["countries"][0]
    assert ukraine["country"] == "Ukraine"
    assert ukraine["conflict_events"] == 1
    assert ukraine["fatalities"] == 5
    assert ukraine["displaced_persons"] == 250000
    assert ukraine["protests"] == 1
    assert ukraine["active_domains"] == ["conflict", "displacement", "unrest"]
    # 3 domains x 20 + min(30, 5 x 2 signals) + 10 x 1 high-severity
    # (250k displaced) = 80.
    assert ukraine["convergence_score"] == 80


@pytest.mark.asyncio
async def test_fetch_signal_summary_country_filter(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_signal_summary_sources(
        monkeypatch,
        conflict_result={
            "events": [
                {"country": "Ukraine", "fatalities": 5},
                {"country": "Sudan", "fatalities": 2},
            ],
            "count": 2,
        },
        protest_query_result={"data": []},
    )

    result = await intelligence.fetch_signal_summary(fetcher, country="ukr")
    assert result["count"] == 1
    assert result["countries"][0]["country"] == "Ukraine"


@pytest.mark.asyncio
async def test_fetch_signal_summary_discloses_acled_gaps(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_signal_summary_sources(
        monkeypatch,
        conflict_result={
            "events": [],
            "count": 0,
            "reason": "acled_fetch_failed",
            "degraded": True,
        },
        protest_query_result=None,
    )
    monkeypatch.setattr(
        intelligence, "acled_failure_reason", _fake_reason("acled_fetch_failed")
    )

    result = await intelligence.fetch_signal_summary(fetcher)
    # Both gaps collapse into one deduplicated, sorted entry.
    assert result["data_gaps"] == ["acled_fetch_failed"]


# ---------------------------------------------------------------------------
# Function 7: fetch_temporal_anomalies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_temporal_anomalies_records_observations(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        intelligence, "_temporal", TemporalBaseline(db_path=str(tmp_path / "t.db"))
    )
    monkeypatch.setattr(
        military,
        "fetch_theater_posture",
        _async_return(
            {"theaters": {"european": {"count": 5}, "middle_east": {"count": 3}}}
        ),
    )
    monkeypatch.setattr(
        intelligence,
        "acled_query",
        _async_return(
            {
                "data": [
                    {"country": "Ukraine"},
                    {"country": "Ukraine"},
                    {"country": "Sudan"},
                ]
            }
        ),
    )

    result = await intelligence.fetch_temporal_anomalies(fetcher)

    assert result["source"] == "temporal-anomaly-detection"
    # 2 theaters + 2 distinct ACLED countries.
    assert result["observations_recorded"] == 4
    # A fresh baseline (n=1 < 10) can never flag anomalies.
    assert result["anomalies"] == []
    assert result["anomaly_count"] == 0
    assert result["data_gaps"] == []


@pytest.mark.asyncio
async def test_fetch_temporal_anomalies_acled_outage_disclosed(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        intelligence, "_temporal", TemporalBaseline(db_path=str(tmp_path / "t.db"))
    )
    monkeypatch.setattr(
        military,
        "fetch_theater_posture",
        _async_return({"theaters": {"european": {"count": 5}}}),
    )
    monkeypatch.setattr(intelligence, "acled_query", _async_return(None))
    monkeypatch.setattr(
        intelligence, "acled_failure_reason", _fake_reason("acled_fetch_failed")
    )

    result = await intelligence.fetch_temporal_anomalies(fetcher)
    assert result["observations_recorded"] == 1  # theaters only
    assert result["data_gaps"] == ["acled_fetch_failed"]


# ---------------------------------------------------------------------------
# Function 8: fetch_unrest_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_unrest_events_parses_and_dedupes(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = [
        {
            "event_date": "2026-08-30",
            "event_type": "Protests",
            "sub_event_type": "Peaceful protest",
            "country": "France",
            "admin1": "Ile-de-France",
            "location": "Paris",
            "latitude": "48.85",
            "longitude": "2.35",
            "fatalities": "0",
            "actor1": "Protesters",
            "notes": "march",
        },
        # Same day, ~7 km away: deduplicated into the first, which must
        # inherit the higher fatality count.
        {
            "event_date": "2026-08-30",
            "event_type": "Riots",
            "country": "France",
            "latitude": "48.90",
            "longitude": "2.40",
            "fatalities": 2,
        },
        # Same day but Marseille (~660 km away): kept.
        {
            "event_date": "2026-08-30",
            "event_type": "Protests",
            "country": "France",
            "latitude": 43.30,
            "longitude": 5.37,
            "fatalities": 0,
        },
        # Same place, different day: kept.
        {
            "event_date": "2026-08-29",
            "event_type": "Protests",
            "country": "France",
            "latitude": 48.85,
            "longitude": 2.35,
            "fatalities": 1,
        },
        # Unparseable coordinates: kept (cannot be deduplicated).
        {
            "event_date": "2026-08-30",
            "event_type": "Protests",
            "country": "France",
            "latitude": "garbage",
            "longitude": "2.0",
            "fatalities": "n/a",
        },
    ]
    monkeypatch.setattr(intelligence, "acled_query", _async_return({"data": raw}))

    result = await intelligence.fetch_unrest_events(fetcher, country="France", days=3)

    assert result["source"] == "acled-unrest"
    assert result["count"] == 4
    assert result["deduplicated"] == 1
    assert result["query"] == {"country": "France", "days": 3}

    first = result["events"][0]
    assert first["location"] == "Paris"
    assert first["latitude"] == 48.85  # string coerced to float
    assert first["fatalities"] == 2  # merged from the deduplicated riot
    assert first["sub_event_type"] == "Peaceful protest"

    unparseable = result["events"][-1]
    assert unparseable["latitude"] is None
    assert unparseable["fatalities"] == 0  # "n/a" coerced to 0


@pytest.mark.asyncio
async def test_fetch_unrest_events_degraded_and_unconfigured(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(intelligence, "acled_query", _async_return(None))

    monkeypatch.setattr(
        intelligence, "acled_failure_reason", _fake_reason("acled_fetch_failed")
    )
    result = await intelligence.fetch_unrest_events(fetcher)
    assert result["degraded"] is True
    assert "fetch failed" in result["error"]

    monkeypatch.setattr(
        intelligence, "acled_failure_reason", _fake_reason("acled_unconfigured")
    )
    result = await intelligence.fetch_unrest_events(fetcher)
    assert "not configured" in result["error"]
    assert result.get("degraded") is None


# ---------------------------------------------------------------------------
# Function 9: fetch_hotspot_escalation (event-attribution path; the empty
# path is covered by test_intelligence.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_hotspot_escalation_attributes_nearby_events(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    acled_events = [
        # Within 2 degrees of the gaza hotspot (31.42, 34.35).
        {
            "latitude": "31.50",
            "longitude": "34.30",
            "event_type": "Battles",
            "fatalities": 12,
        },
        {
            "latitude": "31.40",
            "longitude": "34.40",
            "event_type": "Protests",
            "fatalities": 0,
        },
    ]
    monkeypatch.setattr(
        intelligence, "acled_query", _async_return({"data": acled_events})
    )
    monkeypatch.setattr(
        military,
        "fetch_theater_posture",
        _async_return(
            {
                "theaters": {
                    "middle_east": {
                        "count": 10,
                        "countries": ["United States"],
                        "bbox": "10,25,45,65",
                    }
                }
            }
        ),
    )

    result = await intelligence.fetch_hotspot_escalation(fetcher)

    assert result["source"] == "hotspot-escalation"
    assert result["count"] == len(result["hotspots"]) == 22
    assert result["unavailable_components"] == ["news", "convergence"]
    assert result["data_gaps"] == []

    gaza = next(h for h in result["hotspots"] if h["name"] == "gaza")
    comp = gaza["components"]
    assert comp["baseline"] == 20.0  # baseline_escalation 5 x 4
    # 1 conflict event x 0.5 + 12 fatalities x 0.1 = 1.7.
    assert comp["conflict"] == 1.7
    assert comp["social_unrest"] == 0.4  # 1 protest x 0.4
    assert comp["news"] is None
    assert comp["convergence"] is None
    # Renormalized over measured components: 22.1 / 72 x 100 = 30.7.
    assert gaza["score"] == 30.7
    assert gaza["level"] == "watch"


# ---------------------------------------------------------------------------
# Function 10: fetch_military_surge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_military_surge_detects_surge(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        intelligence, "_temporal", TemporalBaseline(db_path=str(tmp_path / "t.db"))
    )
    # 40 US aircraft in the european theater map onto baltic_sea, whose US
    # baseline is 2 -> ratio 20 -> critical. black_sea has no US baseline,
    # so nothing fires there.
    monkeypatch.setattr(
        military,
        "fetch_theater_posture",
        _async_return(
            {"theaters": {"european": {"count": 40, "countries": ["United States"]}}}
        ),
    )

    result = await intelligence.fetch_military_surge(fetcher)

    assert result["source"] == "military-surge-detection"
    assert result["regions_checked"] == 8
    assert result["surge_count"] == 1
    surge = result["surges"][0]
    assert surge["region"] == "baltic_sea"
    assert surge["country"] == "United States"
    assert surge["current"] == 40
    assert surge["baseline"] == 2
    assert surge["surge_ratio"] == 20.0
    assert surge["severity"] == "critical"


@pytest.mark.asyncio
async def test_fetch_military_surge_quiet_posture(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        intelligence, "_temporal", TemporalBaseline(db_path=str(tmp_path / "t.db"))
    )
    monkeypatch.setattr(
        military, "fetch_theater_posture", _async_return({"theaters": {}})
    )

    result = await intelligence.fetch_military_surge(fetcher)
    assert result["surges"] == []
    assert result["surge_count"] == 0


# ---------------------------------------------------------------------------
# Function 11: fetch_vessel_snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_vessel_snapshot_naval_keywords(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suspected bug (documented, not fixed): the loop matches naval
    keywords against ALL warnings with no proximity/navarea filter, so
    every one of the 9 waterways receives the identical naval count and
    status — 3 naval warnings anywhere on Earth mark Panama and Hormuz
    'critical' alike."""
    warnings = [
        {"id": "2026-1", "text": "NAVAL EXERCISES IN AREA", "navarea": "IV"},
        {"id": "2026-2", "text": "SUBMARINE OPERATIONS", "navarea": "XI"},
        {"id": "2026-3", "text": "LIVE FIRING IN PROGRESS", "navarea": "IX"},
        {"id": "2026-4", "text": "BUOY UNLIT", "navarea": "IV"},
    ]
    monkeypatch.setattr(
        maritime, "fetch_nav_warnings", _async_return({"warnings": warnings})
    )

    result = await intelligence.fetch_vessel_snapshot(fetcher)

    assert result["source"] == "nga-msi-vessel-snapshot"
    assert result["count"] == 9
    assert result["total_nav_warnings"] == 4

    names = {w["name"] for w in result["waterways"]}
    assert "Strait of Hormuz" in names
    for ww in result["waterways"]:
        assert ww["naval_warnings"] == 3  # keyword matches; BUOY UNLIT excluded
        assert ww["status"] == "critical"  # >= 3 naval warnings
        assert len(ww["warning_details"]) == 3


@pytest.mark.asyncio
async def test_fetch_vessel_snapshot_clear(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(maritime, "fetch_nav_warnings", _async_return({"warnings": []}))

    result = await intelligence.fetch_vessel_snapshot(fetcher)
    assert all(ww["status"] == "clear" for ww in result["waterways"])
    assert all(ww["naval_warnings"] == 0 for ww in result["waterways"])


# ---------------------------------------------------------------------------
# Function 12: fetch_cascade_analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_cascade_analysis_specific_corridor(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        infrastructure,
        "fetch_cable_health",
        _async_return(
            {"corridors": {"red_sea": {"status_score": 3, "status_label": "disrupted"}}}
        ),
    )

    result = await intelligence.fetch_cascade_analysis(fetcher, corridor="red_sea")

    assert result["source"] == "cascade-analysis"
    assert result["scenario_count"] == 1
    scenario = result["scenarios"][0]
    assert scenario["scenario"] == "Disruption of red_sea"
    assert scenario["corridors"] == ["red_sea"]
    assert scenario["disrupted"] == ["red_sea"]
    # Djibouti carries the highest red_sea dependency (0.8): with full
    # disruption severity it must top the impact list at score 80.
    top_impact = scenario["country_impacts"][0]
    assert top_impact["country"] == "Djibouti"
    assert top_impact["impact_score"] == 80
    assert top_impact["risk_level"] == "critical"

    assert result["current_health"]["red_sea"]["status_score"] == 3
    assert result["current_health"]["red_sea"]["status_label"] == "disrupted"


@pytest.mark.asyncio
async def test_fetch_cascade_analysis_no_at_risk_corridors(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        infrastructure,
        "fetch_cable_health",
        _async_return(
            {
                "corridors": {
                    "red_sea": {"status_score": 0, "status_label": "clear"},
                    "asia_europe": {"status_score": 1, "status_label": "advisory"},
                }
            }
        ),
    )

    result = await intelligence.fetch_cascade_analysis(fetcher)
    assert result["scenario_count"] == 1
    assert (
        result["scenarios"][0]["scenario"]
        == "Hypothetical: Red Sea corridor disruption"
    )


@pytest.mark.asyncio
async def test_fetch_cascade_analysis_multiple_at_risk(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        infrastructure,
        "fetch_cable_health",
        _async_return(
            {
                "corridors": {
                    "red_sea": {"status_score": 2, "status_label": "at_risk"},
                    "asia_europe": {"status_score": 3, "status_label": "disrupted"},
                }
            }
        ),
    )

    result = await intelligence.fetch_cascade_analysis(fetcher)
    # Two individual scenarios plus the combined worst case.
    assert result["scenario_count"] == 3
    labels = [s["scenario"] for s in result["scenarios"]]
    assert "Disruption of red_sea" in labels
    assert "Disruption of asia_europe" in labels
    assert "Combined disruption (worst case)" in labels
    combined = next(
        s
        for s in result["scenarios"]
        if s["scenario"] == "Combined disruption (worst case)"
    )
    assert sorted(combined["corridors"]) == ["asia_europe", "red_sea"]
