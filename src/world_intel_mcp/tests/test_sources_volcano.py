"""Tests for sources/volcano.py — respx-mocked Smithsonian GVP weekly RSS.

Gaps / not covered: the live feed's ISO-8859-1 / UTF-8 charset
mismatch (mocks are clean UTF-8, so the replacement-character behavior
described in the module docstring is untested); very long summaries
beyond the 500-char truncation.
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

import world_intel_mcp.sources.volcano as volcano_mod
from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.volcano import _parse_title, fetch_volcano_activity

# Repeated sentence pushes the Telica summary past the 500-char cap.
_LONG_SUMMARY = "Daily gas-and-ash emissions continued. " * 20

_GVP_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:georss="http://www.georss.org/georss">
  <channel>
    <title>Smithsonian / USGS Weekly Volcanic Activity Report</title>
    <link>https://volcano.si.edu/reports_weekly.cfm</link>
    <pubDate>Thu, 27 Aug 2026 03:30:31 -0500</pubDate>
    <item>
      <title>Ambae (Vanuatu) - Report for 20 August-26 August 2026 - New Eruptive Activity</title>
      <description>&lt;p&gt;Explosive activity produced tall ash plumes on 25 August.&lt;/p&gt;</description>
      <link>https://volcano.si.edu/reports_weekly.cfm</link>
      <guid isPermaLink="true">https://volcano.si.edu/reports_weekly.cfm#vn_257030</guid>
      <pubDate>Thu, 27 Aug 2026 03:30:31 -0400</pubDate>
      <georss:point>-15.389 167.835</georss:point>
    </item>
    <item>
      <title>Telica (Nicaragua) - Report for 20 August-26 August 2026 - Continuing Eruptive Activity</title>
      <description>&lt;p&gt;LONG_SUMMARY_HERE&lt;/p&gt;</description>
      <link>https://volcano.si.edu/reports_weekly.cfm</link>
      <guid isPermaLink="true">https://volcano.si.edu/reports_weekly.cfm#vn_344090</guid>
      <pubDate>Thu, 27 Aug 2026 03:30:31 -0400</pubDate>
      <georss:point>12.602 -86.845</georss:point>
    </item>
    <item>
      <title>Some unstructured bulletin title</title>
      <description>No structured title, no coordinates.</description>
      <link>https://volcano.si.edu/reports_weekly.cfm</link>
    </item>
  </channel>
</rss>
""".replace("LONG_SUMMARY_HERE", _LONG_SUMMARY)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_volcano_activity_parses_feed(fetcher: Fetcher) -> None:
    respx.get(url__regex=r".*volcano\.si\.edu.*").mock(
        return_value=httpx.Response(200, text=_GVP_RSS)
    )

    result = await fetch_volcano_activity(fetcher)

    assert result["source"] == "gvp"
    assert result["count"] == 3
    assert "degraded" not in result
    assert result["new_activity_count"] == 1
    assert result["continuing_activity_count"] == 1
    assert result["report_published"] == "Thu, 27 Aug 2026 03:30:31 -0500"

    ambae = result["volcanoes"][0]
    assert ambae["name"] == "Ambae"
    assert ambae["country"] == "Vanuatu"
    assert ambae["report_week"] == "20 August-26 August 2026"
    assert ambae["activity_status"] == "New Eruptive Activity"
    # georss:point is "lat lon"; feedparser hands back (lon, lat) —
    # the module must un-swap it.
    assert ambae["latitude"] == pytest.approx(-15.389)
    assert ambae["longitude"] == pytest.approx(167.835)
    # HTML stripped from the summary.
    assert (
        ambae["summary"] == "Explosive activity produced tall ash plumes on 25 August."
    )
    assert ambae["link"] == "https://volcano.si.edu/reports_weekly.cfm#vn_257030"
    assert ambae["published"] == "Thu, 27 Aug 2026 03:30:31 -0400"

    telica = result["volcanoes"][1]
    assert telica["country"] == "Nicaragua"
    assert telica["activity_status"] == "Continuing Eruptive Activity"
    assert telica["latitude"] == pytest.approx(12.602)
    assert telica["longitude"] == pytest.approx(-86.845)
    # Long summaries are truncated to 500 chars.
    assert len(telica["summary"]) == 500
    assert telica["summary"].startswith("Daily gas-and-ash emissions continued.")

    odd = result["volcanoes"][2]
    assert odd["name"] == "Some unstructured bulletin title"
    assert odd["country"] is None
    assert odd["latitude"] is None
    assert odd["longitude"] is None
    assert odd["activity_status"] is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_volcano_activity_feed_down_is_marked_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*volcano\.si\.edu.*").mock(return_value=httpx.Response(500))

    result = await fetch_volcano_activity(fetcher)

    assert result["degraded"] is True
    assert result["reason"] == "gvp_fetch_failed"
    assert "unavailable" in result["error"].lower()
    assert result["volcanoes"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_fetch_volcano_activity_without_feedparser(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(volcano_mod, "feedparser", None)

    result = await fetch_volcano_activity(fetcher)

    assert result["degraded"] is True
    assert result["reason"] == "feedparser_missing"
    assert "feedparser" in result["error"]
    assert result["volcanoes"] == []


def test_parse_title_variants() -> None:
    assert _parse_title(
        "Kilauea (United States) - Report for 1 January-7 January 2026 - Continuing Eruptive Activity"
    ) == (
        "Kilauea",
        "United States",
        "1 January-7 January 2026",
        "Continuing Eruptive Activity",
    )
    # No trailing status segment.
    assert _parse_title("Etna (Italy) - Report for 1 January-7 January 2026") == (
        "Etna",
        "Italy",
        "1 January-7 January 2026",
        None,
    )
    # No "(Country)" in the head segment.
    assert _parse_title(
        "Oddball - Report for 1 January-7 January 2026 - New Eruptive Activity"
    ) == (
        "Oddball",
        None,
        "1 January-7 January 2026",
        "New Eruptive Activity",
    )
    # Fully unstructured title falls back whole.
    assert _parse_title("Just a title") == ("Just a title", None, None, None)
