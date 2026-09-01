"""Tests for analysis/clustering.py — Jaccard news clustering.

Similarity values in comments are hand-computed from the token sets after
stopword removal (e.g. "new" is a stopword and must not count).
"""

import pytest

from world_intel_mcp.analysis.clustering import (
    cluster_articles,
    fetch_news_clusters,
    jaccard_similarity,
)
from world_intel_mcp.sources import news


def test_jaccard_identical_sets() -> None:
    assert jaccard_similarity({"a", "b", "c"}, {"a", "b", "c"}) == 1.0


def test_jaccard_disjoint_sets() -> None:
    assert jaccard_similarity({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_partial_overlap() -> None:
    # {a,b} vs {b,c}: intersection 1, union 3.
    assert jaccard_similarity({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


def test_jaccard_empty_set_is_zero() -> None:
    assert jaccard_similarity(set(), {"a"}) == 0.0
    assert jaccard_similarity({"a"}, set()) == 0.0


def test_similar_titles_cluster_dissimilar_stay_apart() -> None:
    """The load-bearing pair: near-duplicates merge, the unrelated story
    does not get pulled in."""
    articles = [
        {"title": "Russia launches missile strikes on Kyiv energy grid"},
        # Token overlap 6/7 with the first title ("new" is a stopword).
        {"title": "Russia launches new missile strikes on Kyiv grid"},
        {"title": "Chocolate festival delights visitors in Belgium"},
    ]
    clusters = cluster_articles(articles, similarity_threshold=0.3)
    assert len(clusters) == 2
    # Sorted by member count: the pair first.
    assert clusters[0]["member_count"] == 2
    assert clusters[0]["member_indices"] == [0, 1]
    assert clusters[0]["representative"] is articles[0]
    assert clusters[1]["member_count"] == 1
    assert clusters[1]["representative"] is articles[2]


def test_threshold_boundary_is_inclusive() -> None:
    # {border,camps,flood} vs {border,camps,burn}: J = 2/4 = 0.5 exactly.
    articles = [
        {"title": "border camps flood"},
        {"title": "border camps burn"},
    ]
    merged = cluster_articles(articles, similarity_threshold=0.5)
    assert merged[0]["member_count"] == 2  # sim >= threshold merges
    split = cluster_articles(articles, similarity_threshold=0.51)
    assert all(c["member_count"] == 1 for c in split)


def test_empty_input_returns_empty_list() -> None:
    assert cluster_articles([]) == []


def test_missing_or_none_titles_become_singletons() -> None:
    articles = [{"title": None}, {}, {"title": "Real headline about earthquakes"}]
    clusters = cluster_articles(articles)
    assert len(clusters) == 3
    assert all(c["member_count"] == 1 for c in clusters)


def test_custom_title_field() -> None:
    articles = [
        {"headline": "Drought grips southern Europe farms"},
        {"headline": "Drought grips southern Europe vineyards"},
    ]
    clusters = cluster_articles(articles, title_field="headline")
    assert clusters[0]["member_count"] == 2


async def test_fetch_news_clusters_reports_clusters_and_singletons(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = [
        {
            "title": "Russia launches missile strikes on Kyiv energy grid",
            "source_name": "BBC",
            "link": "https://example.com/1",
        },
        {
            "title": "Russia missile strikes hit Kyiv grid overnight",
            "source": "Reuters",
            "link": "https://example.com/2",
        },
        {
            "title": "Missile strikes on Kyiv grid continue as Russia presses",
            "source_name": "BBC",
            "link": "https://example.com/3",
        },
        {"title": "Chocolate festival delights visitors in Brussels"},
        {"title": "Quantum computing startup raises funding round"},
    ]

    async def _fake_feed(fetcher, category=None, limit=100):
        return {"items": items}

    monkeypatch.setattr(news, "fetch_news_feed", _fake_feed)
    result = await fetch_news_clusters(fetcher)

    # Only multi-member clusters are surfaced; the two unrelated stories
    # are counted as singletons, not clusters.
    assert result["cluster_count"] == 1
    assert result["singleton_count"] == 2
    assert result["total_items"] == 5
    assert result["threshold"] == 0.25
    assert result["source"] == "jaccard-clustering"

    cluster = result["clusters"][0]
    assert cluster["size"] == 3
    assert cluster["headline"] == items[0]["title"]
    assert "kyiv" in cluster["keywords"]
    assert "missile" in cluster["keywords"]
    assert sorted(cluster["sources"]) == ["BBC", "Reuters"]
    assert len(cluster["items"]) == 3
    assert cluster["items"][0] == {
        "title": items[0]["title"],
        "source": "BBC",
        "link": "https://example.com/1",
    }
