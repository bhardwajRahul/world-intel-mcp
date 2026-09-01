"""Named entity extraction from text.

Regex-based NER for countries, leaders, organizations, companies, CVEs,
and APT groups. No ML dependencies — uses reference data from config/.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from ..config.countries import TIER1_COUNTRIES
from ..config.entities import LEADERS, ORGANIZATIONS, COMPANIES, APT_GROUPS


def _compile_keywords(
    keywords, *, plural_min_len: int | None = None
) -> re.Pattern[str]:
    """Compile keywords into one word-boundary-anchored alternation.

    Longest-first ordering makes multi-word variants win over their prefixes
    ("united nations" before "un"). With plural_min_len set, alphabetic
    keywords at least that long also match a trailing "s" ("americans",
    "houthis"); shorter abbreviations stay exact so "usa" never matches
    inside "thousand" or "usable".
    """
    parts = []
    for kw in sorted(keywords, key=len, reverse=True):
        esc = re.escape(kw)
        if plural_min_len is not None and len(kw) >= plural_min_len and kw.isalpha():
            esc += "s?"
        parts.append(esc)
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b")


# Pre-compile patterns
_CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
_APT_RE = re.compile(
    r"\b(?:"
    + "|".join(re.escape(a) for a in sorted(APT_GROUPS, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)

# Build country keyword → iso3 lookup (lowercase)
_COUNTRY_KW: dict[str, str] = {}
for _iso3, _info in TIER1_COUNTRIES.items():
    for _kw in _info["keywords"]:
        _COUNTRY_KW[_kw.lower()] = _iso3
    _COUNTRY_KW[_info["name"].lower()] = _iso3
    _COUNTRY_KW[_iso3.lower()] = _iso3

# Build leader name lookup (lowercase)
_LEADER_KW: dict[str, dict] = {k.lower(): v for k, v in LEADERS.items()}

# Build org lookup (lowercase)
_ORG_KW: dict[str, dict] = {k.lower(): v for k, v in ORGANIZATIONS.items()}

# Build company lookup (lowercase)
_COMPANY_KW: dict[str, dict] = {k.lower(): v for k, v in COMPANIES.items()}

# Demonyms pluralize in headlines ("Americans", "Houthis"); leader, org, and
# company names must stay exact — "apples" is not Apple Inc.
_COUNTRY_RE = _compile_keywords(_COUNTRY_KW, plural_min_len=5)
_LEADER_RE = _compile_keywords(_LEADER_KW)
_ORG_RE = _compile_keywords(_ORG_KW)
_COMPANY_RE = _compile_keywords(_COMPANY_KW)


def extract_entities(text: str) -> dict:
    """Extract named entities from text.

    Returns dict with entities grouped by type, plus counts and metadata.
    """
    text_lower = text.lower()

    countries: list[dict] = []
    leaders: list[dict] = []
    organizations: list[dict] = []
    companies: list[dict] = []
    cves: list[str] = []
    apts: list[str] = []

    seen_countries: set[str] = set()
    seen_leaders: set[str] = set()
    seen_orgs: set[str] = set()
    seen_companies: set[str] = set()

    # Countries (word-boundary match; the regex may add a plural "s" that
    # is not itself a lookup key, so fall back to the singular)
    for match in _COUNTRY_RE.finditer(text_lower):
        kw = match.group(0)
        iso3 = _COUNTRY_KW.get(kw) or _COUNTRY_KW.get(kw[:-1])
        if iso3 is None or iso3 in seen_countries:
            continue
        seen_countries.add(iso3)
        info = TIER1_COUNTRIES[iso3]
        countries.append(
            {
                "iso3": iso3,
                "name": info["name"],
                "baseline_risk": info["baseline_risk"],
            }
        )

    # Leaders (longest alternative wins, so "vladimir putin" never also
    # emits a second entry via "putin")
    for match in _LEADER_RE.finditer(text_lower):
        info = _LEADER_KW[match.group(0)]
        if info["name"] in seen_leaders:
            continue
        seen_leaders.add(info["name"])
        leaders.append(
            {
                "name": info["name"],
                "title": info["title"],
                "country": info["country"],
            }
        )

    # Organizations
    for match in _ORG_RE.finditer(text_lower):
        info = _ORG_KW[match.group(0)]
        if info["abbrev"] in seen_orgs:
            continue
        seen_orgs.add(info["abbrev"])
        organizations.append(
            {
                "name": info["abbrev"],
                "type": info["type"],
            }
        )

    # Companies
    for match in _COMPANY_RE.finditer(text_lower):
        kw = match.group(0)
        if kw in seen_companies:
            continue
        info = _COMPANY_KW[kw]
        seen_companies.add(kw)
        companies.append(
            {
                "name": kw.title(),
                "ticker": info["ticker"],
                "sector": info["sector"],
            }
        )

    # CVEs
    cves = list(set(_CVE_RE.findall(text)))

    # APTs
    apt_matches = _APT_RE.findall(text)
    apts = list(set(m.lower() for m in apt_matches))

    total = len(countries) + len(leaders) + len(organizations) + len(companies) + len(cves) + len(apts)

    return {
        "entities": {
            "countries": countries,
            "leaders": leaders,
            "organizations": organizations,
            "companies": companies,
            "cves": cves,
            "apt_groups": apts,
        },
        "by_type": {
            "countries": len(countries),
            "leaders": len(leaders),
            "organizations": len(organizations),
            "companies": len(companies),
            "cves": len(cves),
            "apt_groups": len(apts),
        },
        "total_entities": total,
        "source": "regex-ner",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def fetch_entity_extraction(fetcher, text: str | None = None, use_news: bool = True) -> dict:
    """Extract entities from provided text or recent news headlines.

    If text is provided, extract from that. Otherwise fetch recent news
    headlines and extract entities from the combined text.
    """
    if text:
        return extract_entities(text)

    if use_news:
        from ..sources import news
        feed_data = await news.fetch_news_feed(fetcher, limit=100)
        items = feed_data.get("items", [])
        combined = " ".join(
            (item.get("title", "") + " " + item.get("summary", ""))
            for item in items
        )
        result = extract_entities(combined)
        result["input_source"] = "news_feed"
        result["items_analyzed"] = len(items)
        return result

    return extract_entities("")
