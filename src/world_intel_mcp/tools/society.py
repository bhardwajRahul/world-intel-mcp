"""News and public-signal tools: RSS news, trending keywords,
GDELT, prediction markets, displacement, cyber threats, AI watch,
disease outbreaks, sanctions, elections, social signals, tech and
science feeds, government spending.

Phase 26 split: Tool definitions moved byte-identical and dispatch
case bodies verbatim from server.py; handlers reach shared
infrastructure via ``runtime``. See tools/system.py for the pattern.
"""

from typing import Any

from mcp.types import Tool

from .. import runtime
from ..sources import (
    news,
    prediction,
    displacement,
    cyber,
    ai_watch,
    health,
    sanctions,
    elections,
    social,
    hacker_news,
    github_trending,
    arxiv_papers,
    usa_spending,
)

TOOLS: list[Tool] = [
    # --- Prediction (1 tool) ---
    Tool(
        name="intel_prediction_markets",
        description="Get active prediction markets from Polymarket (questions, YES probabilities, volumes, sentiment).",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of markets (default 20)",
                    "default": 20,
                },
            },
        },
    ),
    # --- Displacement (1 tool) ---
    Tool(
        name="intel_displacement_summary",
        description="Get UNHCR refugee/displacement statistics by country of origin. No API key needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "year": {
                    "type": "integer",
                    "description": "Reporting year (default: last year)",
                },
            },
        },
    ),
    # --- Cyber (1 tool) ---
    Tool(
        name="intel_cyber_threats",
        description="Get aggregated cyber threat intelligence from 4 feeds (Feodo, CISA KEV, SANS, URLhaus). No API key needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max threats (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    # --- News (3 tools) ---
    Tool(
        name="intel_news_feed",
        description="Get aggregated intelligence news from 119 RSS feeds across 24 categories. Covers geopolitics, security, tech, finance, military, science, think tanks, regional, energy, space, nuclear, climate, maritime, arctic, and more.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category filter (24 categories available)",
                    "enum": [
                        "geopolitics",
                        "security",
                        "technology",
                        "finance",
                        "military",
                        "science",
                        "think_tanks",
                        "middle_east",
                        "asia_pacific",
                        "africa",
                        "latin_america",
                        "multilingual",
                        "energy",
                        "government",
                        "crisis",
                        "europe",
                        "south_asia",
                        "health",
                        "central_asia",
                        "arctic",
                        "maritime",
                        "space",
                        "nuclear",
                        "climate",
                    ],
                },
                "limit": {
                    "type": "integer",
                    "description": "Max items (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    Tool(
        name="intel_trending_keywords",
        description="Detect trending keywords from recent news headlines. Keyword spike detection across 20+ feeds.",
        inputSchema={
            "type": "object",
            "properties": {
                "min_count": {
                    "type": "integer",
                    "description": "Minimum occurrences (default 3)",
                    "default": 3,
                },
            },
        },
    ),
    Tool(
        name="intel_gdelt_search",
        description="Search GDELT 2.0 for global news articles or volume timelines. No API key needed.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (default: 'conflict')",
                    "default": "conflict",
                },
                "mode": {
                    "type": "string",
                    "description": "artlist (articles) or timelinevol (volume timeline)",
                    "enum": ["artlist", "timelinevol"],
                    "default": "artlist",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max records (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    # --- AI Watch (1 tool) ---
    Tool(
        name="intel_ai_releases",
        description="Track AI/AGI developments from arXiv, HuggingFace, and AI news feeds. Lab mention trending.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max items (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    # --- Health (1 tool) ---
    Tool(
        name="intel_disease_outbreaks",
        description="Aggregate disease outbreak alerts from WHO DON, ProMED, and CIDRAP. Flags high-concern pathogens (Ebola, H5N1, mpox, etc.).",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max items (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    # --- Sanctions (1 tool) ---
    Tool(
        name="intel_sanctions_search",
        description="Search the US Treasury OFAC Specially Designated Nationals (SDN) sanctions list. Substring match on name, country, program.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name substring to search"},
                "country": {"type": "string", "description": "Country filter"},
                "program": {
                    "type": "string",
                    "description": "Sanctions program filter",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    # --- Elections (1 tool) ---
    Tool(
        name="intel_election_calendar",
        description="Get upcoming global election calendar with proximity-based instability risk scoring. Covers 2025-2029.",
        inputSchema={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "ISO-3 code or country name filter",
                },
            },
        },
    ),
    # --- Social (1 tool) ---
    Tool(
        name="intel_social_signals",
        description="Monitor geopolitical discussion velocity on Reddit (r/worldnews, r/geopolitics). Engagement metrics and trending posts.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max posts per subreddit (default 25)",
                    "default": 25,
                },
            },
        },
    ),
    # --- Tech & Science (3 tools) ---
    Tool(
        name="intel_hacker_news",
        description="Get top stories from Hacker News (Firebase API). Returns title, score, URL, author, comment count. Optional: limit (default 30).",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of stories (default 30, max 100)",
                    "default": 30,
                },
            },
        },
    ),
    Tool(
        name="intel_trending_repos",
        description="Get trending GitHub repositories (recently created, most starred). Optional: language filter, time window, limit.",
        inputSchema={
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "Programming language filter (python, rust, typescript, etc.)",
                },
                "since_days": {
                    "type": "integer",
                    "description": "Look back N days for new repos (default 7)",
                    "default": 7,
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of repos (default 25)",
                    "default": 25,
                },
            },
        },
    ),
    Tool(
        name="intel_arxiv_papers",
        description="Search recent arXiv papers in AI/ML (cs.AI, cs.LG, cs.CL). Optional custom query. Returns title, authors, abstract, categories, PDF link.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "arXiv search query (default: cs.AI OR cs.LG OR cs.CL)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of papers (default 25)",
                    "default": 25,
                },
            },
        },
    ),
    # --- Government (1 tool) ---
    Tool(
        name="intel_usa_spending",
        description="Federal agency spending data from USAspending.gov. Shows top agencies by budget for current fiscal year. Optional: agency filter.",
        inputSchema={
            "type": "object",
            "properties": {
                "agency": {
                    "type": "string",
                    "description": "Filter by agency name substring",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of agencies (default 25)",
                    "default": 25,
                },
            },
        },
    ),
]


async def _prediction_markets(arguments: dict[str, Any]) -> Any:
    return await prediction.fetch_prediction_markets(
        runtime.fetcher, limit=arguments.get("limit", 20)
    )


async def _displacement_summary(arguments: dict[str, Any]) -> Any:
    return await displacement.fetch_displacement_summary(
        runtime.fetcher, year=arguments.get("year")
    )


async def _cyber_threats(arguments: dict[str, Any]) -> Any:
    return await cyber.fetch_cyber_threats(
        runtime.fetcher, limit=arguments.get("limit", 50)
    )


async def _news_feed(arguments: dict[str, Any]) -> Any:
    return await news.fetch_news_feed(
        runtime.fetcher,
        category=arguments.get("category"),
        limit=arguments.get("limit", 50),
    )


async def _trending_keywords(arguments: dict[str, Any]) -> Any:
    return await news.fetch_trending_keywords(
        runtime.fetcher, min_count=arguments.get("min_count", 3)
    )


async def _gdelt_search(arguments: dict[str, Any]) -> Any:
    return await news.fetch_gdelt_search(
        runtime.fetcher,
        query=arguments.get("query", "conflict"),
        mode=arguments.get("mode", "artlist"),
        limit=arguments.get("limit", 50),
    )


async def _ai_releases(arguments: dict[str, Any]) -> Any:
    return await ai_watch.fetch_ai_watch(
        runtime.fetcher, limit=arguments.get("limit", 50)
    )


async def _disease_outbreaks(arguments: dict[str, Any]) -> Any:
    return await health.fetch_disease_outbreaks(
        runtime.fetcher, limit=arguments.get("limit", 50)
    )


async def _sanctions_search(arguments: dict[str, Any]) -> Any:
    return await sanctions.fetch_sanctions_search(
        runtime.fetcher,
        query=arguments.get("query", ""),
        country=arguments.get("country"),
        program=arguments.get("program"),
        limit=arguments.get("limit", 50),
    )


async def _election_calendar(arguments: dict[str, Any]) -> Any:
    return await elections.fetch_election_calendar(
        runtime.fetcher,
        country=arguments.get("country"),
    )


async def _social_signals(arguments: dict[str, Any]) -> Any:
    return await social.fetch_social_signals(
        runtime.fetcher,
        limit=arguments.get("limit", 25),
    )


async def _hacker_news(arguments: dict[str, Any]) -> Any:
    return await hacker_news.fetch_hacker_news(
        runtime.fetcher,
        limit=arguments.get("limit", 30),
    )


async def _trending_repos(arguments: dict[str, Any]) -> Any:
    return await github_trending.fetch_trending_repos(
        runtime.fetcher,
        language=arguments.get("language"),
        since_days=arguments.get("since_days", 7),
        limit=arguments.get("limit", 25),
    )


async def _arxiv_papers(arguments: dict[str, Any]) -> Any:
    return await arxiv_papers.fetch_arxiv_papers(
        runtime.fetcher,
        query=arguments.get("query"),
        limit=arguments.get("limit", 25),
    )


async def _usa_spending(arguments: dict[str, Any]) -> Any:
    return await usa_spending.fetch_usa_spending(
        runtime.fetcher,
        agency=arguments.get("agency"),
        limit=arguments.get("limit", 25),
    )


HANDLERS = {
    "intel_prediction_markets": _prediction_markets,
    "intel_displacement_summary": _displacement_summary,
    "intel_cyber_threats": _cyber_threats,
    "intel_news_feed": _news_feed,
    "intel_trending_keywords": _trending_keywords,
    "intel_gdelt_search": _gdelt_search,
    "intel_ai_releases": _ai_releases,
    "intel_disease_outbreaks": _disease_outbreaks,
    "intel_sanctions_search": _sanctions_search,
    "intel_election_calendar": _election_calendar,
    "intel_social_signals": _social_signals,
    "intel_hacker_news": _hacker_news,
    "intel_trending_repos": _trending_repos,
    "intel_arxiv_papers": _arxiv_papers,
    "intel_usa_spending": _usa_spending,
}
