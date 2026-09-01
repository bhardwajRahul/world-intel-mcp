"""Tests for sources/news.py — RSS aggregation, trending keywords, GDELT.

Complements test_sources.py, which already covers the GDELT artlist
degraded-vs-zero distinction (issue #17). This file covers the RSS feed
aggregation contract, keyword trending, the GDELT artlist/timeline success
paths, and the timeline degraded shape.

Gaps / not covered: live feed availability across the 119 configured
feeds; the asyncio.wait_for per-feed hard timeout (needs a slow fake
transport); the 25-way semaphore cap (behavioral, not observable from the
result shape).
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources import news
from world_intel_mcp.sources.news import (
    _RSS_FEEDS,
    _parse_published,
    _truncate,
    fetch_gdelt_search,
    fetch_news_feed,
    fetch_trending_keywords,
)

_LONG_SUMMARY = "S" * 250

_RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Feed</title>
<item>
  <title>Newer headline</title>
  <link>https://news.example/1</link>
  <pubDate>Mon, 31 Aug 2026 14:00:00 GMT</pubDate>
  <description>{_LONG_SUMMARY}</description>
</item>
<item>
  <title>Older headline</title>
  <link>https://news.example/2</link>
  <pubDate>Sun, 30 Aug 2026 10:00:00 GMT</pubDate>
  <description>Short summary.</description>
</item>
</channel></rss>"""


@respx.mock
@pytest.mark.asyncio
async def test_fetch_news_feed_single_category(fetcher: Fetcher) -> None:
    respx.route().mock(return_value=httpx.Response(200, text=_RSS))

    result = await fetch_news_feed(fetcher, category="security")

    assert result["source"] == "rss-aggregator"
    assert result["categories_fetched"] == ["security"]
    # Every security feed returns the same 2-item RSS document.
    assert result["count"] == 2 * len(_RSS_FEEDS["security"])

    item = result["items"][0]
    assert item["category"] == "security"
    assert item["feed_name"] in {name for name, _ in _RSS_FEEDS["security"]}
    assert "source_tier" in item
    # Sorted by published descending: every "Newer headline" copy precedes
    # every "Older headline" copy.
    titles = [i["title"] for i in result["items"]]
    assert titles.index("Older headline") == len(_RSS_FEEDS["security"])
    # 250-char summary truncated to 200 + ellipsis.
    newer = next(i for i in result["items"] if i["title"] == "Newer headline")
    assert newer["summary"] == "S" * 200 + "..."
    assert newer["link"] == "https://news.example/1"
    older = next(i for i in result["items"] if i["title"] == "Older headline")
    assert older["summary"] == "Short summary."


@respx.mock
@pytest.mark.asyncio
async def test_fetch_news_feed_limit(fetcher: Fetcher) -> None:
    respx.route().mock(return_value=httpx.Response(200, text=_RSS))

    result = await fetch_news_feed(fetcher, category="security", limit=3)
    assert result["count"] == 3
    assert len(result["items"]) == 3


@pytest.mark.asyncio
async def test_fetch_news_feed_unknown_category(fetcher: Fetcher) -> None:
    result = await fetch_news_feed(fetcher, category="astrology")
    assert "Unknown category" in result["error"]
    assert result["items"] == []
    assert result["count"] == 0
    assert result["categories_fetched"] == []


@respx.mock
@pytest.mark.asyncio
async def test_fetch_news_feed_all_feeds_down(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observation (flagged in review, not fixed): dead feeds contribute
    nothing silently — a category-wide outage returns count=0 with no
    error/degraded marker, shape-identical to a slow news day."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.route().mock(return_value=httpx.Response(500))

    result = await fetch_news_feed(fetcher, category="security")
    assert result["items"] == []
    assert result["count"] == 0
    assert result["categories_fetched"] == ["security"]
    assert "error" not in result  # current (dishonest-quiet) behavior


@pytest.mark.asyncio
async def test_fetch_trending_keywords(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [
        {"title": "Ukraine's grid attacked"},
        {"title": "Drone raid hits Ukraine depot"},
        {"title": "Ukraine counteroffensive stalls; drone losses mount"},
        {"title": ""},  # empty title tolerated
    ]

    async def _fake_feed(f, category=None, limit=50):
        return {"items": items}

    monkeypatch.setattr(news, "fetch_news_feed", _fake_feed)

    result = await fetch_trending_keywords(fetcher, min_count=3)

    assert result["source"] == "keyword-analysis"
    assert result["total_items_analyzed"] == 4
    # "ukraine" appears 3x (possessive punctuation stripped); "drone" only
    # 2x so it must fall below min_count=3.
    assert result["keywords"] == [{"word": "ukraine", "count": 3}]


@pytest.mark.asyncio
async def test_fetch_trending_keywords_min_count_filter(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_feed(f, category=None, limit=50):
        return {"items": [{"title": "Taiwan strait tension"}] * 2}

    monkeypatch.setattr(news, "fetch_news_feed", _fake_feed)

    result = await fetch_trending_keywords(fetcher, min_count=2)
    words = {k["word"]: k["count"] for k in result["keywords"]}
    # Stopwords and <3-char tokens never appear.
    assert words == {"taiwan": 2, "strait": 2, "tension": 2}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_gdelt_search_artlist_success(fetcher: Fetcher) -> None:
    respx.get(url__regex=r".*api\.gdeltproject\.org.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "articles": [
                    {
                        "title": "Border clash reported",
                        "url": "https://example.com/a1",
                        "seendate": "20260831T120000Z",
                        "socialimage": "",
                        "domain": "example.com",
                        "language": "English",
                        "sourcecountry": "France",
                    }
                ]
            },
        )
    )

    result = await fetch_gdelt_search(fetcher, query="border clash", limit=10)

    assert result["source"] == "gdelt"
    assert result["mode"] == "artlist"
    assert result["query"] == "border clash"
    assert result["count"] == 1
    article = result["articles"][0]
    assert article["title"] == "Border clash reported"
    assert article["url"] == "https://example.com/a1"
    assert article["domain"] == "example.com"
    assert article["sourcecountry"] == "France"
    assert result.get("error") is None
    assert result.get("degraded") is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_gdelt_search_timeline_mode(fetcher: Fetcher) -> None:
    timeline = [
        {"series": "Volume Intensity", "data": [{"date": "20260830", "value": 1.2}]}
    ]
    respx.get(url__regex=r".*api\.gdeltproject\.org.*").mock(
        return_value=httpx.Response(200, json={"timeline": timeline})
    )

    result = await fetch_gdelt_search(fetcher, query="coup", mode="timelinevol")
    assert result["mode"] == "timelinevol"
    assert result["timeline"] == timeline
    assert result["count"] == 1


@respx.mock
@pytest.mark.asyncio
async def test_fetch_gdelt_search_timeline_degraded_shape(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue-#17 contract in timeline mode: a failed fetch keeps timeline
    as its normal empty-list shape while flagging degradation."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*api\.gdeltproject\.org.*").mock(
        return_value=httpx.Response(429, text="rate limited")
    )

    result = await fetch_gdelt_search(fetcher, query="coup", mode="timelinevol")
    assert result["degraded"] is True
    assert result["reason"] == "gdelt_fetch_failed"
    assert result["timeline"] == []
    assert result["articles"] is None
    assert result["count"] == 0


def test_truncate() -> None:
    assert _truncate(None) == ""
    assert _truncate("") == ""
    assert _truncate("short") == "short"
    assert _truncate("x" * 200) == "x" * 200  # exactly at the limit
    assert _truncate("x" * 201) == "x" * 200 + "..."


def test_parse_published_fallbacks() -> None:
    import time as time_mod

    parsed = _parse_published({"published_parsed": time_mod.gmtime(1700000000)})
    assert parsed is not None and parsed.endswith("Z")

    updated = _parse_published({"updated_parsed": time_mod.gmtime(1700000000)})
    assert updated is not None and updated.endswith("Z")

    assert _parse_published({"published": "raw"}) == "raw"
    assert _parse_published({"updated": "raw2"}) == "raw2"
    assert _parse_published({}) is None
