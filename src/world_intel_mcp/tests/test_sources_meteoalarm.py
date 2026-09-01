"""Tests for sources/meteoalarm.py — respx-mocked legacy ATOM feeds.

Gaps / not covered: only the France feed's live shape informed the
mock (other countries assumed identical); the real feed's PubSubHubbub
hub links and cap:geocode blocks are omitted from the mock as the
module ignores them.
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources import meteoalarm as meteoalarm_mod
from world_intel_mcp.sources.meteoalarm import (
    _normalize_country,
    fetch_meteoalarm_alerts,
)

# Entry shape mirrors the live France feed observed 2026-09-01:
# cap:* extension elements, awareness color only in the title.
_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <id>tag:meteoalarm.org,2021-02-19:FR</id>
  <title>MeteoAlarm - Alerting Europe for Extreme Weather</title>
  <updated>2026-09-01T21:36:24Z</updated>
  <entry>
    <cap:areaDesc>Hautes-Pyrénées</cap:areaDesc>
    <cap:event>Moderate thunderstorm warning</cap:event>
    <cap:onset>2026-09-01T14:00:10+00:00</cap:onset>
    <cap:expires>2026-09-01T22:00:00+00:00</cap:expires>
    <cap:certainty>Likely</cap:certainty>
    <cap:severity>Moderate</cap:severity>
    <cap:urgency>Future</cap:urgency>
    <cap:status>Actual</cap:status>
    <cap:message_type>Alert</cap:message_type>
    <cap:identifier>2.49.0.0.250.0.FR.645023</cap:identifier>
    <link href="https://meteoalarm.org?geocode=EMMA_ID:FR003"/>
    <published>2026-09-01T14:00:19Z</published>
    <id>https://feeds.meteoalarm.org/api/v1/warnings/feeds-france/aa-1</id>
    <title>Yellow Thunderstorm Warning issued for France - Hautes-Pyrénées</title>
    <updated>2026-09-01T14:00:19Z</updated>
  </entry>
  <entry>
    <cap:areaDesc>Finistère</cap:areaDesc>
    <cap:event>Severe wind warning</cap:event>
    <cap:severity>Severe</cap:severity>
    <cap:status>Actual</cap:status>
    <id>https://feeds.meteoalarm.org/api/v1/warnings/feeds-france/aa-2</id>
    <title>Orange Wind Warning issued for France - Finistère</title>
  </entry>
  <entry>
    <cap:areaDesc>Var</cap:areaDesc>
    <cap:event>Extreme rain warning</cap:event>
    <cap:severity>Extreme</cap:severity>
    <cap:status>Actual</cap:status>
    <id>https://feeds.meteoalarm.org/api/v1/warnings/feeds-france/aa-3</id>
    <title>Red Rain Warning issued for France - Var</title>
  </entry>
</feed>
"""

_EMPTY_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <id>tag:meteoalarm.org,2021-02-19:UK</id>
  <title>MeteoAlarm - Alerting Europe for Extreme Weather</title>
  <updated>2026-09-01T21:36:24Z</updated>
</feed>
"""


@respx.mock
@pytest.mark.asyncio
async def test_fetch_meteoalarm_extracts_alerts(fetcher: Fetcher) -> None:
    respx.get(url__regex=r".*feeds\.meteoalarm\.org/feeds/.*-france$").mock(
        return_value=httpx.Response(200, text=_ATOM)
    )

    result = await fetch_meteoalarm_alerts(fetcher, country="France")

    assert result["source"] == "meteoalarm"
    assert result["country"] == "france"
    assert result["count"] == 3
    assert result["total_entries"] == 3
    assert "degraded" not in result
    assert result["by_severity"] == {"Moderate": 1, "Severe": 1, "Extreme": 1}
    assert result["by_color"] == {"yellow": 1, "orange": 1, "red": 1}
    assert result["feed_updated"] == "2026-09-01T21:36:24Z"

    first = result["alerts"][0]
    assert first["event"] == "Moderate thunderstorm warning"
    assert first["severity"] == "Moderate"
    assert first["awareness_color"] == "yellow"  # from title, not CAP
    assert first["area"] == "Hautes-Pyrénées"
    assert first["onset"] == "2026-09-01T14:00:10+00:00"
    assert first["expires"] == "2026-09-01T22:00:00+00:00"
    assert first["certainty"] == "Likely"
    assert first["urgency"] == "Future"
    assert first["status"] == "Actual"
    assert first["message_type"] == "Alert"
    assert first["identifier"] == "2.49.0.0.250.0.FR.645023"
    assert first["published"] == "2026-09-01T14:00:19Z"

    assert result["alerts"][1]["awareness_color"] == "orange"
    assert result["alerts"][2]["awareness_color"] == "red"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_meteoalarm_limit_keeps_full_counts(fetcher: Fetcher) -> None:
    """Limit truncates the alerts list but not the summary counters."""
    respx.get(url__regex=r".*feeds\.meteoalarm\.org.*").mock(
        return_value=httpx.Response(200, text=_ATOM)
    )

    result = await fetch_meteoalarm_alerts(fetcher, country="france", limit=1)

    assert result["count"] == 1
    assert result["total_entries"] == 3
    assert result["by_severity"] == {"Moderate": 1, "Severe": 1, "Extreme": 1}
    assert result["by_color"] == {"yellow": 1, "orange": 1, "red": 1}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_meteoalarm_no_country_returns_roster(fetcher: Fetcher) -> None:
    """No Europe-wide feed exists — country=None returns the roster, no HTTP."""
    result = await fetch_meteoalarm_alerts(fetcher)

    assert result["count"] == 0
    assert result["alerts"] == []
    assert result["country"] is None
    assert "error" not in result
    assert "degraded" not in result
    assert len(result["available_countries"]) == 39
    assert "france" in result["available_countries"]
    assert "united-kingdom" in result["available_countries"]
    assert not respx.calls  # roster answered locally


@respx.mock
@pytest.mark.asyncio
async def test_fetch_meteoalarm_unknown_country_is_not_degraded(
    fetcher: Fetcher,
) -> None:
    """Bad input is a usage error, not an upstream outage."""
    result = await fetch_meteoalarm_alerts(fetcher, country="Atlantis")

    assert result["reason"] == "unknown_country"
    assert "Atlantis" in result["error"]
    assert "degraded" not in result
    assert result["alerts"] == []
    assert "available_countries" in result
    assert not respx.calls


@respx.mock
@pytest.mark.asyncio
async def test_fetch_meteoalarm_alias_and_quiet_feed(fetcher: Fetcher) -> None:
    """ "UK" resolves to united-kingdom; an empty feed is calm weather."""
    route = respx.get(
        url__regex=r".*feeds\.meteoalarm\.org/feeds/.*-united-kingdom$"
    ).mock(return_value=httpx.Response(200, text=_EMPTY_ATOM))

    result = await fetch_meteoalarm_alerts(fetcher, country="UK")

    assert route.called
    assert result["country"] == "united-kingdom"
    assert result["count"] == 0
    assert result["total_entries"] == 0
    assert result["alerts"] == []
    assert result["by_severity"] == {}
    assert "degraded" not in result
    assert "error" not in result


@respx.mock
@pytest.mark.asyncio
async def test_fetch_meteoalarm_feed_down_is_marked_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*feeds\.meteoalarm\.org.*").mock(
        return_value=httpx.Response(500)
    )

    result = await fetch_meteoalarm_alerts(fetcher, country="germany")

    assert result["degraded"] is True
    assert result["reason"] == "meteoalarm_fetch_failed"
    assert "unavailable" in result["error"].lower()
    assert result["alerts"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_fetch_meteoalarm_without_feedparser(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(meteoalarm_mod, "feedparser", None)

    result = await fetch_meteoalarm_alerts(fetcher, country="france")

    assert result["degraded"] is True
    assert result["reason"] == "feedparser_missing"


def test_normalize_country() -> None:
    assert _normalize_country("France") == "france"
    assert _normalize_country("  United Kingdom ") == "united-kingdom"
    assert _normalize_country("UK") == "united-kingdom"
    assert _normalize_country("czech_republic") == "czechia"
    assert _normalize_country("North Macedonia") == "republic-of-north-macedonia"
    assert _normalize_country("Bosnia and Herzegovina") == "bosnia-herzegovina"
