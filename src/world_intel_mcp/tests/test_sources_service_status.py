"""Tests for sources/service_status.py — respx-mocked provider RSS feeds.

Gaps / not covered: real feed schema drift per provider; feedparser's
timezone handling of published_parsed (asserted for shape, not exact
instant, because time.mktime interprets the tuple in local time).
"""

import asyncio as asyncio_mod
import time as time_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.service_status import (
    _STATUS_FEEDS,
    _classify_severity,
    _parse_published,
    fetch_service_status,
)

# Three items: critical (major outage), info (maintenance), medium
# (investigating). Active per provider = 2 (critical + medium).
_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Status</title>
<item>
  <title>Major outage: API errors in us-east-1</title>
  <link>https://status.example/1</link>
  <pubDate>Mon, 31 Aug 2026 14:00:00 GMT</pubDate>
  <description>Widespread API failures.</description>
</item>
<item>
  <title>Scheduled maintenance window</title>
  <link>https://status.example/2</link>
  <pubDate>Sun, 30 Aug 2026 10:00:00 GMT</pubDate>
  <description>Planned maintenance.</description>
</item>
<item>
  <title>Investigating connectivity issues</title>
  <link>https://status.example/3</link>
  <pubDate>Sat, 29 Aug 2026 08:00:00 GMT</pubDate>
  <description>We are looking into reports.</description>
</item>
</channel></rss>"""

_FEED_PATTERNS = {
    "AWS": r".*status\.aws\.amazon\.com.*",
    "Azure": r".*azurestatuscdn\.azureedge\.net.*",
    "GCP": r".*status\.cloud\.google\.com.*",
    "Cloudflare": r".*cloudflarestatus\.com.*",
    "GitHub": r".*githubstatus\.com.*",
}


def _mock_all_feeds() -> None:
    for pattern in _FEED_PATTERNS.values():
        respx.get(url__regex=pattern).mock(return_value=httpx.Response(200, text=_RSS))


@respx.mock
@pytest.mark.asyncio
async def test_fetch_service_status_all_providers(fetcher: Fetcher) -> None:
    _mock_all_feeds()

    result = await fetch_service_status(fetcher)

    assert result["source"] == "service-status"
    assert result["count"] == 15  # 3 items x 5 providers
    assert result["by_provider"] == {
        "AWS": 3,
        "Azure": 3,
        "GCP": 3,
        "Cloudflare": 3,
        "GitHub": 3,
    }
    assert sorted(result["providers_checked"]) == sorted(
        f["provider"] for f in _STATUS_FEEDS
    )
    # critical + medium are active; info is not: 2 per provider.
    assert result["active_incidents"] == 10

    # Field contract on one incident, values derived from the RSS.
    incident = next(
        i
        for i in result["incidents"]
        if i["provider"] == "GitHub" and "Major outage" in i["title"]
    )
    assert incident["severity"] == "critical"
    assert incident["link"] == "https://status.example/1"
    assert incident["summary"] == "Widespread API failures."
    assert incident["published"] is not None

    # Sorted by published descending: newest (Aug 31) first.
    assert "Major outage" in result["incidents"][0]["title"]


@respx.mock
@pytest.mark.asyncio
async def test_fetch_service_status_provider_filter(fetcher: Fetcher) -> None:
    # Only the GitHub feed is mocked; any other request would error under
    # respx, so a green run proves the filter fetches exactly one feed.
    respx.get(url__regex=_FEED_PATTERNS["GitHub"]).mock(
        return_value=httpx.Response(200, text=_RSS)
    )

    result = await fetch_service_status(fetcher, provider="github")
    assert result["providers_checked"] == ["GitHub"]
    assert result["count"] == 3
    assert set(result["by_provider"]) == {"GitHub"}


@pytest.mark.asyncio
async def test_fetch_service_status_unknown_provider(fetcher: Fetcher) -> None:
    result = await fetch_service_status(fetcher, provider="nonexistent-cloud")
    assert "Unknown provider" in result["error"]
    assert result["incidents"] == []
    assert result["count"] == 0


@respx.mock
@pytest.mark.asyncio
async def test_fetch_service_status_one_feed_down(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing feed contributes zero incidents while others still report.
    Observation (flagged in review, not fixed): the response does not say
    WHICH provider's feed failed — a dead AWS feed is shape-identical to a
    healthy AWS with no incidents."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    for provider, pattern in _FEED_PATTERNS.items():
        if provider == "AWS":
            respx.get(url__regex=pattern).mock(return_value=httpx.Response(500))
        else:
            respx.get(url__regex=pattern).mock(
                return_value=httpx.Response(200, text=_RSS)
            )

    result = await fetch_service_status(fetcher)
    assert result["count"] == 12  # 3 x 4 surviving providers
    assert "AWS" not in result["by_provider"]
    assert "AWS" in result["providers_checked"]  # still claimed as checked


@respx.mock
@pytest.mark.asyncio
async def test_resolved_incident_with_severity_words_counts_active(
    fetcher: Fetcher,
) -> None:
    """Suspected bug (documented, not fixed): _SEVERITY_KEYWORDS is scanned
    in insertion order and "major"/"outage" precede "resolved", so a
    'Resolved: Major outage' post-mortem classifies as critical and inflates
    active_incidents."""
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>S</title>
    <item><title>Resolved: Major outage restored</title>
    <link>https://status.example/9</link>
    <description>All clear.</description></item>
    </channel></rss>"""

    respx.get(url__regex=_FEED_PATTERNS["GitHub"]).mock(
        return_value=httpx.Response(200, text=rss)
    )

    result = await fetch_service_status(fetcher, provider="github")
    assert result["incidents"][0]["severity"] == "critical"  # current behavior
    assert result["active_incidents"] == 1  # inflated


def test_classify_severity() -> None:
    assert _classify_severity("Major outage", "") == "critical"
    assert _classify_severity("Service disruption", "") == "high"
    assert _classify_severity("Degraded performance", "") == "high"
    assert _classify_severity("Partial impairment", "") == "medium"
    assert _classify_severity("Investigating reports", "") == "medium"
    assert _classify_severity("Resolved", "") == "resolved"
    assert _classify_severity("Monitoring recovery", "") == "low"
    assert _classify_severity("Scheduled maintenance", "") == "info"
    assert _classify_severity("Something else entirely", "") == "unknown"
    # Keyword can live in the summary, not just the title.
    assert _classify_severity("Update", "elevated error rates observed") == "high"


def test_parse_published() -> None:
    entry = {"published_parsed": time_mod.gmtime(1700000000)}
    parsed = _parse_published(entry)
    assert parsed is not None
    assert parsed.endswith("Z")  # ISO-8601 UTC shape

    # Fallback to the raw string fields when no parsed tuple exists.
    assert _parse_published({"published": "raw-date"}) == "raw-date"
    assert _parse_published({"updated": "other-date"}) == "other-date"
    assert _parse_published({}) is None
