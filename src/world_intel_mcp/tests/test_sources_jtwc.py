"""Tests for sources/jtwc.py — respx-mocked JTWC RSS.

Gaps / not covered: the real Southern Hemisphere season shape with
active storms (SH was quiet when the live feed was observed, so SH
storm headers like "Tropical Cyclone 01S" are exercised via the
unknown-guid mock, not a captured SH payload); "Super Typhoon" and
"Reissued at" variants are mocked from documented JTWC conventions,
not observed live.
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources import jtwc as jtwc_mod
from world_intel_mcp.sources.jtwc import fetch_jtwc_cyclones

# Structure mirrors the live feed observed 2026-09-01: basin items with
# CDATA HTML descriptions, unbalanced <p><b> nesting, double space
# between classification and storm id, quiet SH item, advisories item.
_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>JTWC TROPICAL CYCLONE INFORMATION FEED</title>
    <pubDate>Tue, 01 Sep 2026 22:00:07 +0000</pubDate>
    <item>
      <title>Current Northwest Pacific/North Indian Ocean* Tropical Systems</title>
      <description><![CDATA[<p><b>Tropical Depression  17W (Saudel) Warning #42 </b><br>
<b>Issued at 01/2100Z<b>
<ul>
<li><a href='https://www.metoc.navy.mil/jtwc/products/wp1726web.txt' target='newwin'>TC Warning Text </a></li>
<li><a href='https://www.metoc.navy.mil/jtwc/products/wp1726.gif' target='newwin'>TC Warning Graphic</a></li>
</ul>
<p><b>Super Typhoon  22W (Krovanh) Warning #03 </b><br>
<b>Reissued at 01/2115Z<b>
<ul>
<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2226web.txt' target='newwin'>TC Warning Text </a></li>
</ul>
]]></description>
      <category>Northwest Pacific/North Indian Ocean* Tropical Systems</category>
      <guid>NWPAC-NIO-WARNINGS</guid>
      <pubDate>Tue, 01 Sep 26 22:00:07 +0000</pubDate>
    </item>
    <item>
      <title>Current Central/Eastern Pacific Tropical Systems</title>
      <description><![CDATA[<p><b><p><b>Hurricane  11E (Karina) Warning #22 </b><br>
<b>Issued at 01/2200Z<b>
<ul>
<li><a href='https://www.metoc.navy.mil/jtwc/products/ep1126web.txt' target='newwin'>TC Warning Text </a></li>
<li><a href='https://www.metoc.navy.mil/jtwc/products/ep1126.gif' target='newwin'>TC Warning Graphic</a></li>
</ul>
]]></description>
      <category>Central/Eastern Pacific Tropical Systems</category>
      <guid>EPAC-CPAC-WARNINGS</guid>
      <pubDate>Tue, 01 Sep 26 22:00:07 +0000</pubDate>
    </item>
    <item>
      <title>Current Southern Hemisphere Tropical Systems</title>
      <description><![CDATA[<ul><li><font color='red'>No Current Tropical Cyclone Warnings.</font></li></ul>
]]></description>
      <category>Southern Hemisphere Tropical Systems</category>
      <guid>SH-WARNINGS</guid>
      <pubDate>Tue, 01 Sep 26 22:00:07 +0000</pubDate>
    </item>
    <item>
      <title>Current Significant Tropical Weather Advisories</title>
      <description><![CDATA[<ul>
<li><b><a href="https://www.metoc.navy.mil/jtwc/products/abpwweb.txt" target='newwin'>ABPW10 (Western/South Pacific Ocean)</a><br>
<font color=red>Reissued at 01/2100Z</font></li>
<li><b><a href="https://www.metoc.navy.mil/jtwc/products/abioweb.txt" target='newwin'>ABIO10 (Indian Ocean)</a><br>
Issued at 01/1800Z</b></li>
</ul>]]></description>
      <category>Significant Tropical Weather Advisories</category>
      <guid>TROPICAL-ADVISORIES</guid>
      <pubDate>Tue, 01 Sep 26 22:00:07 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


def _quiet_rss() -> str:
    """Every basin quiet — the valid off-season shape."""
    quiet = (
        "<![CDATA[<ul><li><font color='red'>"
        "No Current Tropical Cyclone Warnings.</font></li></ul>]]>"
    )
    out = _RSS
    for guid in ("NWPAC-NIO-WARNINGS", "EPAC-CPAC-WARNINGS"):
        head, _, tail = out.partition(f"<guid>{guid}</guid>")
        # Replace the description preceding this guid
        start = head.rindex("<description>") + len("<description>")
        end = head.rindex("</description>")
        out = head[:start] + quiet + head[end:] + f"<guid>{guid}</guid>" + tail
    return out


@respx.mock
@pytest.mark.asyncio
async def test_fetch_jtwc_extracts_storms(fetcher: Fetcher) -> None:
    respx.get(url__regex=r".*metoc\.navy\.mil.*").mock(
        return_value=httpx.Response(200, text=_RSS)
    )

    result = await fetch_jtwc_cyclones(fetcher)

    assert result["source"] == "jtwc"
    assert result["count"] == 3
    assert "degraded" not in result
    assert result["by_basin"] == {
        "northwest_pacific_north_indian": 2,
        "central_eastern_pacific": 1,
        "southern_hemisphere": 0,  # quiet basin present with zero
    }

    saudel = result["storms"][0]
    assert saudel["id"] == "17W"
    assert saudel["name"] == "Saudel"
    assert saudel["classification"] == "Tropical Depression"
    assert saudel["warning_number"] == 42
    assert saudel["issued_at"] == "01/2100Z"
    assert saudel["basin"] == "northwest_pacific_north_indian"
    assert saudel["warning_text_url"] == (
        "https://www.metoc.navy.mil/jtwc/products/wp1726web.txt"
    )
    assert saudel["warning_graphic_url"] == (
        "https://www.metoc.navy.mil/jtwc/products/wp1726.gif"
    )

    krovanh = result["storms"][1]
    assert krovanh["classification"] == "Super Typhoon"
    assert krovanh["warning_number"] == 3  # "#03" coerced
    assert krovanh["issued_at"] == "01/2115Z"  # "Reissued at" variant
    # Krovanh's segment has no .gif link; Saudel's must not bleed over
    assert krovanh["warning_graphic_url"] is None
    assert krovanh["warning_text_url"] == (
        "https://www.metoc.navy.mil/jtwc/products/wp2226web.txt"
    )

    karina = result["storms"][2]
    assert karina["id"] == "11E"
    assert karina["classification"] == "Hurricane"
    assert karina["basin"] == "central_eastern_pacific"

    assert result["advisories"] == [
        {
            "title": "ABPW10 (Western/South Pacific Ocean)",
            "url": "https://www.metoc.navy.mil/jtwc/products/abpwweb.txt",
        },
        {
            "title": "ABIO10 (Indian Ocean)",
            "url": "https://www.metoc.navy.mil/jtwc/products/abioweb.txt",
        },
    ]
    assert result["feed_published"] == "Tue, 01 Sep 2026 22:00:07 +0000"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_jtwc_all_quiet_is_valid_not_degraded(fetcher: Fetcher) -> None:
    """Every basin quiet is a real state of the world, not an outage."""
    respx.get(url__regex=r".*metoc\.navy\.mil.*").mock(
        return_value=httpx.Response(200, text=_quiet_rss())
    )

    result = await fetch_jtwc_cyclones(fetcher)

    assert result["count"] == 0
    assert result["storms"] == []
    assert result["by_basin"] == {
        "northwest_pacific_north_indian": 0,
        "central_eastern_pacific": 0,
        "southern_hemisphere": 0,
    }
    assert "degraded" not in result
    assert "error" not in result
    # Advisories still parse even when all basins are quiet
    assert len(result["advisories"]) == 2


@respx.mock
@pytest.mark.asyncio
async def test_fetch_jtwc_unknown_guid_falls_back_to_category(
    fetcher: Fetcher,
) -> None:
    """A new/renamed basin item must not silently drop its storms."""
    rss = _RSS.replace("NWPAC-NIO-WARNINGS", "WESTPAC-WARNINGS")

    respx.get(url__regex=r".*metoc\.navy\.mil.*").mock(
        return_value=httpx.Response(200, text=rss)
    )

    result = await fetch_jtwc_cyclones(fetcher)

    assert result["count"] == 3  # nothing dropped
    derived = [b for b in result["by_basin"] if b.startswith("northwest_pacific")]
    assert derived  # basin label derived from the category text
    assert result["by_basin"][derived[0]] == 2


@respx.mock
@pytest.mark.asyncio
async def test_fetch_jtwc_drifted_format_logs_but_returns(
    fetcher: Fetcher, caplog: pytest.LogCaptureFixture
) -> None:
    """No storm headers AND no quiet marker means the format drifted."""
    rss = _RSS.replace(
        "No Current Tropical Cyclone Warnings.", "Something unrecognized."
    )

    respx.get(url__regex=r".*metoc\.navy\.mil.*").mock(
        return_value=httpx.Response(200, text=rss)
    )

    with caplog.at_level("INFO", logger="world-intel-mcp.sources.jtwc"):
        result = await fetch_jtwc_cyclones(fetcher)

    assert result["by_basin"]["southern_hemisphere"] == 0
    assert "degraded" not in result
    assert any("drifted" in r.message for r in caplog.records)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_jtwc_feed_down_is_marked_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch failure must never be shape-identical to quiet basins."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*metoc\.navy\.mil.*").mock(return_value=httpx.Response(500))

    result = await fetch_jtwc_cyclones(fetcher)

    assert result["degraded"] is True
    assert result["reason"] == "jtwc_fetch_failed"
    assert "unavailable" in result["error"].lower()
    assert result["storms"] == []
    assert result["by_basin"] == {}


@pytest.mark.asyncio
async def test_fetch_jtwc_without_feedparser(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jtwc_mod, "feedparser", None)

    result = await fetch_jtwc_cyclones(fetcher)

    assert result["degraded"] is True
    assert result["reason"] == "feedparser_missing"
