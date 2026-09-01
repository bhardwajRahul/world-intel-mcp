"""Tests for analysis/classifier.py — keyword threat classification.

Pure-function tests with realistic headlines. Each positive case is paired
with a negative (a text that must NOT trigger the same outcome) so a broken
classifier cannot pass by over- or under-matching.
"""

from world_intel_mcp.analysis.classifier import (
    CATEGORIES,
    classify_event,
    fetch_classify_event,
)

# Three military keywords ("troops", "artillery", "frontline"), no severity
# modifiers, and no keywords from any other category.
_MILITARY_TEXT = "Russian troops shelled the frontline with artillery near the border"

# No category keyword or severity modifier appears anywhere in this text.
_BENIGN_TEXT = "The bakery unveiled a fresh sourdough recipe on Sunday"


def test_military_headline_classified() -> None:
    result = classify_event(_MILITARY_TEXT)
    assert result["primary_category"] == "military"
    assert (
        result["severity"] == CATEGORIES["military"]["severity_base"]
    )  # 8, no modifiers
    # 3 keyword hits -> confidence min(1.0, 3*0.2 + 0.3) = 0.9
    assert result["confidence"] == 0.9
    assert result["category_count"] == 1
    assert result["severity_modifiers"] == []
    matched = result["all_categories"][0]["keywords"]
    assert "troops" in matched
    assert "frontline" in matched
    assert result["source"] == "keyword-classifier"


def test_benign_text_is_unclassified() -> None:
    """The load-bearing negative: a classifier that fires on everything
    proves nothing when it fires on a real threat."""
    result = classify_event(_BENIGN_TEXT)
    assert result["primary_category"] == "unclassified"
    assert result["severity"] == 0
    assert result["confidence"] == 0.0
    assert result["all_categories"] == []
    assert result["category_count"] == 0
    assert result["severity_modifiers"] == []


def test_high_severity_modifier_and_cap_at_ten() -> None:
    # 4 nuclear keywords; "nuclear" is also a high-severity modifier (+2),
    # so 9 + 2 must cap at 10.
    result = classify_event("IAEA warns of uranium enrichment at nuclear facility")
    assert result["primary_category"] == "nuclear"
    assert result["severity"] == 10
    assert result["confidence"] == 1.0  # 4 hits saturates the scale
    assert "nuclear" in result["severity_modifiers"]


def test_moderate_severity_modifier_adds_one() -> None:
    # Maritime base 5, "attack" is a moderate modifier -> 6.
    result = classify_event("Piracy attack on a cargo ship near the strait")
    assert result["primary_category"] == "maritime"
    assert result["severity"] == 6
    assert result["severity_modifiers"] == ["attack"]


def test_high_modifier_wins_over_moderate_no_stacking() -> None:
    # Both "killed" (high, +2) and "attack" (moderate, +1) appear; the
    # bumps must not stack: maritime base 5 + 2 = 7, not 8.
    result = classify_event("Piracy attack near the strait killed three seafarers")
    assert result["primary_category"] == "maritime"
    assert result["severity"] == 7
    assert "killed" in result["severity_modifiers"]
    assert "attack" in result["severity_modifiers"]


def test_primary_category_is_most_keyword_hits() -> None:
    # cyber matches 2 keywords ("ransomware", "hack"), maritime 1 ("port").
    result = classify_event("Ransomware hack hits port operators")
    assert result["primary_category"] == "cyber"
    assert result["severity"] == CATEGORIES["cyber"]["severity_base"]
    cats = [c["category"] for c in result["all_categories"]]
    assert cats[0] == "cyber"
    assert "maritime" in cats
    assert result["category_count"] == 2


def test_single_keyword_confidence_floor() -> None:
    # 1 hit -> min(1.0, 0.2 + 0.3) = 0.5
    result = classify_event("The satellite mission was a success")
    assert result["primary_category"] == "space"
    assert result["confidence"] == 0.5
    assert result["severity"] == CATEGORIES["space"]["severity_base"]


def test_classification_is_case_insensitive() -> None:
    upper = classify_event(_MILITARY_TEXT.upper())
    assert upper["primary_category"] == "military"
    assert upper["confidence"] == 0.9


async def test_fetch_classify_event_wraps_sync_classifier() -> None:
    result = await fetch_classify_event(None, _MILITARY_TEXT)
    direct = classify_event(_MILITARY_TEXT)
    assert result["primary_category"] == direct["primary_category"]
    assert result["severity"] == direct["severity"]
    assert result["confidence"] == direct["confidence"]
