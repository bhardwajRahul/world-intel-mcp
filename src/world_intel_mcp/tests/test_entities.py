"""Tests for analysis/entities.py — regex NER over config reference data.

Fixtures use names that actually exist in config/countries.py and
config/entities.py, so the tests exercise the real lookup tables rather
than a parallel synthetic dataset. The news-path wrapper is tested by
monkeypatching at the source-function boundary (pattern from test_aoi.py).
"""

import pytest

from world_intel_mcp.analysis.entities import extract_entities, fetch_entity_extraction
from world_intel_mcp.sources import news


def _iso3s(result: dict) -> set[str]:
    return {c["iso3"] for c in result["entities"]["countries"]}


def test_countries_extracted_by_keyword_capital_and_excluded_when_absent() -> None:
    result = extract_entities(
        "Russia struck targets across Ukraine while Beijing watched"
    )
    assert _iso3s(result) == {"RUS", "UKR", "CHN"}  # "beijing" maps to CHN
    # The load-bearing exclusion: countries never mentioned must not appear.
    assert "USA" not in _iso3s(result)
    rus = next(c for c in result["entities"]["countries"] if c["iso3"] == "RUS")
    assert rus["name"] == "Russia"
    assert rus["baseline_risk"] == 55  # from config/countries.py


def test_country_mentioned_multiple_ways_deduplicated() -> None:
    result = extract_entities("Russian forces near Moscow, Russia")
    assert _iso3s(result) == {"RUS"}
    assert result["by_type"]["countries"] == 1


def test_leaders_extracted_with_variant_dedup() -> None:
    result = extract_entities("President Vladimir Putin met Xi Jinping in Beijing")
    names = {ldr["name"] for ldr in result["entities"]["leaders"]}
    # "vladimir putin" must not also emit a second entry via the "putin"
    # variant, nor "xi jinping" via "xi".
    assert names == {"Vladimir Putin", "Xi Jinping"}
    putin = next(
        l for l in result["entities"]["leaders"] if l["name"] == "Vladimir Putin"
    )
    assert putin["country"] == "RUS"
    assert putin["title"] == "President"


def test_short_org_abbreviations_require_word_boundary() -> None:
    # "un" appears inside "tribunal" and "announced" but never as a word.
    result = extract_entities("The tribunal announced sanctions on shipping firms")
    assert result["entities"]["organizations"] == []

    result = extract_entities("The UN and NATO convened")
    names = {o["name"] for o in result["entities"]["organizations"]}
    assert names == {"UN", "NATO"}
    nato = next(o for o in result["entities"]["organizations"] if o["name"] == "NATO")
    assert nato["type"] == "military_alliance"


def test_org_long_form_and_abbreviation_deduplicated() -> None:
    result = extract_entities("The UN said the United Nations would act")
    assert result["by_type"]["organizations"] == 1
    assert result["entities"]["organizations"][0]["name"] == "UN"


def test_companies_extracted_with_ticker_and_sector() -> None:
    result = extract_entities("Lockheed Martin and NVIDIA won new contracts")
    companies = {c["name"]: c for c in result["entities"]["companies"]}
    assert set(companies) == {"Lockheed Martin", "Nvidia"}
    assert companies["Lockheed Martin"]["ticker"] == "LMT"
    assert companies["Lockheed Martin"]["sector"] == "defense"
    assert companies["Nvidia"]["ticker"] == "NVDA"


def test_cves_deduplicated_and_case_insensitive() -> None:
    result = extract_entities(
        "Patch CVE-2024-3400 now; CVE-2024-3400 is exploited alongside CVE-2023-23397"
    )
    assert set(result["entities"]["cves"]) == {"CVE-2024-3400", "CVE-2023-23397"}
    assert result["by_type"]["cves"] == 2

    lowercase = extract_entities("cve-2025-1234 disclosed today")
    assert lowercase["entities"]["cves"] == ["cve-2025-1234"]


def test_apt_groups_extracted_lowercased() -> None:
    result = extract_entities("APT29 and Cozy Bear ran a campaign; Lazarus was quiet")
    assert set(result["entities"]["apt_groups"]) == {"apt29", "cozy bear", "lazarus"}
    # Sandworm exists in the dataset but is not in the text.
    assert "sandworm" not in result["entities"]["apt_groups"]


def test_empty_text_yields_no_entities() -> None:
    result = extract_entities("")
    assert result["total_entities"] == 0
    assert all(count == 0 for count in result["by_type"].values())
    assert result["source"] == "regex-ner"


def test_total_entities_matches_by_type_sum() -> None:
    result = extract_entities(
        "Putin discussed CVE-2024-3400 with NATO officials in Russia"
    )
    assert result["total_entities"] == sum(result["by_type"].values())
    assert result["total_entities"] == 4  # RUS + Putin + NATO + one CVE


async def test_fetch_entity_extraction_with_text(fetcher) -> None:
    result = await fetch_entity_extraction(fetcher, text="Putin visited Russia")
    assert _iso3s(result) == {"RUS"}
    assert "input_source" not in result  # direct text path, not news


async def test_fetch_entity_extraction_from_news_feed(
    fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_feed(fetcher, limit=100, category=None):
        return {
            "items": [
                {"title": "Putin visits Beijing", "summary": "talks with Xi Jinping"},
                {"title": "New CVE-2026-0001 exploited", "summary": ""},
            ]
        }

    monkeypatch.setattr(news, "fetch_news_feed", _fake_feed)
    result = await fetch_entity_extraction(fetcher, text=None, use_news=True)
    assert result["input_source"] == "news_feed"
    assert result["items_analyzed"] == 2
    assert "CHN" in _iso3s(result)
    names = {l["name"] for l in result["entities"]["leaders"]}
    assert names == {"Vladimir Putin", "Xi Jinping"}
    assert result["entities"]["cves"] == ["CVE-2026-0001"]


async def test_fetch_entity_extraction_no_text_no_news(fetcher) -> None:
    result = await fetch_entity_extraction(fetcher, text=None, use_news=False)
    assert result["total_entities"] == 0


# ---------------------------------------------------------------------------
# Word-boundary regressions (Phase 24.5): substring matching tagged entities
# from the inside of unrelated words — "usa" in "thousand", "bp" in "subplot".
# Each false-positive test is paired with a real-mention test so the fix
# cannot pass by simply matching less.
# ---------------------------------------------------------------------------


def test_country_keyword_inside_word_not_tagged() -> None:
    # "thousand" and "usable" both contain "usa"; neither mentions the USA.
    result = extract_entities("A thousand protesters filled the square")
    assert _iso3s(result) == set()

    result = extract_entities("The bridge is no longer usable after the storm")
    assert _iso3s(result) == set()


def test_country_word_and_plural_demonym_still_tagged() -> None:
    result = extract_entities("Americans voted as the USA prepared for midterms")
    assert _iso3s(result) == {"USA"}


def test_company_names_inside_words_not_tagged() -> None:
    # "metadata" contains "meta", "bombshell" contains "shell",
    # "subplot" contains "bp".
    result = extract_entities("The metadata revealed a bombshell subplot")
    assert result["entities"]["companies"] == []


def test_company_short_names_still_match_as_words() -> None:
    result = extract_entities("BP and Shell posted profits while Meta hired")
    names = {c["name"] for c in result["entities"]["companies"]}
    assert names == {"Bp", "Shell", "Meta"}


def test_leader_names_inside_words_not_tagged() -> None:
    # Same bug class: "taxi" contains "xi", "commodity" contains "modi",
    # "trumpet" contains "trump".
    result = extract_entities("The taxi passed commodity traders at the trumpet parade")
    assert result["entities"]["leaders"] == []


def test_leader_short_names_still_match_as_words() -> None:
    result = extract_entities("Xi and Modi met at the summit")
    names = {ldr["name"] for ldr in result["entities"]["leaders"]}
    assert names == {"Xi Jinping", "Narendra Modi"}


def test_long_org_name_inside_word_not_tagged() -> None:
    # The pre-fix boundary guard only covered keywords of <=4 chars, so
    # "hamas" matched inside "bahamas".
    result = extract_entities("Storm damage reported across the Bahamas")
    assert result["entities"]["organizations"] == []
