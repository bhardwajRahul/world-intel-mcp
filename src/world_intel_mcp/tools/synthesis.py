"""NLP and strategic-synthesis tools: entity extraction, event
classification, news clustering, keyword spikes, strategic posture,
world brief, fleet report, population exposure.

Phase 26 split: Tool definitions moved byte-identical and dispatch
case bodies verbatim from server.py; handlers reach shared
infrastructure via ``runtime``. See tools/system.py for the pattern.
"""

from typing import Any

from mcp.types import Tool

from .. import runtime

TOOLS: list[Tool] = [
    # --- NLP Intelligence (4 tools) ---
    Tool(
        name="intel_extract_entities",
        description="Extract named entities (countries, leaders, organizations, companies, CVEs, APT groups) from text or recent news headlines.",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to analyze. If omitted, analyzes recent news headlines.",
                },
            },
        },
    ),
    Tool(
        name="intel_classify_event",
        description="Classify text into threat categories (military, terrorism, cyber, political, economic, health, climate, nuclear, etc.) with severity scoring (1-10).",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Event text or headline to classify.",
                },
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="intel_news_clusters",
        description="Cluster recent news articles by topic similarity using Jaccard coefficient. Groups related stories and extracts top keywords per cluster.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "RSS feed category filter (geopolitics, security, military, etc.)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max news items to cluster (default: 100)",
                },
                "threshold": {
                    "type": "number",
                    "description": "Similarity threshold 0.0-1.0 (default: 0.25)",
                },
            },
        },
    ),
    Tool(
        name="intel_keyword_spikes",
        description="Detect trending keyword spikes against historical baselines using Welford's algorithm. Extracts CVE identifiers and APT group mentions.",
        inputSchema={
            "type": "object",
            "properties": {
                "min_count": {
                    "type": "integer",
                    "description": "Minimum keyword frequency to consider (default: 3)",
                },
                "z_threshold": {
                    "type": "number",
                    "description": "Z-score threshold for spike detection (default: 2.0)",
                },
            },
        },
    ),
    # --- Strategic Synthesis (4 tools) ---
    Tool(
        name="intel_strategic_posture",
        description="Composite global risk assessment from 9 intelligence domains: military, political, conflict, infrastructure, economic, cyber, health, climate, space. Weighted composite score 0-100 with per-domain breakdown and top threats.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="intel_world_brief",
        description="Structured daily intelligence summary: risk overview, focal areas, top story clusters, temporal anomalies, and trending threats. Comprehensive situational awareness in one call.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="intel_fleet_report",
        description="Naval fleet activity report aggregating theater posture (5 theaters), vessel snapshot (9 waterways), military surge detections, and naval base count. Readiness scoring.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="intel_population_exposure",
        description="Estimate population at risk near active events (earthquakes, wildfires, conflict). Finds major cities within radius and sums exposed population.",
        inputSchema={
            "type": "object",
            "properties": {
                "radius_km": {
                    "type": "number",
                    "description": "Search radius in km (default: 200)",
                    "default": 200,
                },
                "event_types": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["earthquake", "wildfire", "conflict"],
                    },
                    "description": "Event types to include (default: all three)",
                },
            },
        },
    ),
]


async def _extract_entities(arguments: dict[str, Any]) -> Any:
    from ..analysis.entities import fetch_entity_extraction

    return await fetch_entity_extraction(runtime.fetcher, text=arguments.get("text"))


async def _classify_event(arguments: dict[str, Any]) -> Any:
    from ..analysis.classifier import fetch_classify_event

    return await fetch_classify_event(runtime.fetcher, text=arguments["text"])


async def _news_clusters(arguments: dict[str, Any]) -> Any:
    from ..analysis.clustering import fetch_news_clusters

    return await fetch_news_clusters(
        runtime.fetcher,
        category=arguments.get("category"),
        limit=arguments.get("limit", 100),
        threshold=arguments.get("threshold", 0.25),
    )


async def _keyword_spikes(arguments: dict[str, Any]) -> Any:
    from ..analysis.spikes import fetch_keyword_spikes

    return await fetch_keyword_spikes(
        runtime.fetcher,
        min_count=arguments.get("min_count", 3),
        z_threshold=arguments.get("z_threshold", 2.0),
    )


async def _strategic_posture(arguments: dict[str, Any]) -> Any:
    from ..analysis.posture import fetch_strategic_posture

    return await fetch_strategic_posture(runtime.fetcher)


async def _world_brief(arguments: dict[str, Any]) -> Any:
    from ..analysis.world_brief import fetch_world_brief

    return await fetch_world_brief(runtime.fetcher)


async def _fleet_report(arguments: dict[str, Any]) -> Any:
    from ..sources.fleet import fetch_fleet_report

    return await fetch_fleet_report(runtime.fetcher)


async def _population_exposure(arguments: dict[str, Any]) -> Any:
    from ..analysis.exposure import fetch_population_exposure

    return await fetch_population_exposure(
        runtime.fetcher,
        radius_km=arguments.get("radius_km", 200),
        event_types=arguments.get("event_types"),
    )


HANDLERS = {
    "intel_extract_entities": _extract_entities,
    "intel_classify_event": _classify_event,
    "intel_news_clusters": _news_clusters,
    "intel_keyword_spikes": _keyword_spikes,
    "intel_strategic_posture": _strategic_posture,
    "intel_world_brief": _world_brief,
    "intel_fleet_report": _fleet_report,
    "intel_population_exposure": _population_exposure,
}
