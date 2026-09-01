"""Vector-store tools: semantic search, similar events,
timeline, collection stats, on-demand collection, cross-domain
correlation, domain summary, trend detection.

Phase 26 split: Tool definitions moved byte-identical and dispatch
case bodies verbatim from server.py; handlers reach shared
infrastructure via ``runtime``. See tools/system.py for the pattern.
"""

from typing import Any

from mcp.types import Tool

from .. import runtime

TOOLS: list[Tool] = [
    # --- Vector Search (3 tools) ---
    Tool(
        name="intel_semantic_search",
        description="Semantic search across all stored intelligence data using natural language. Searches historical data accumulated from all 101+ tools. Filters: domain (e.g., 'markets', 'conflict'), category (e.g., 'Financial Markets', 'Cyber Threats'), hours (last N hours). Returns ranked results by relevance.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query (e.g., 'military activity near Taiwan', 'oil price disruptions')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 20)",
                    "default": 20,
                },
                "domain": {
                    "type": "string",
                    "description": "Filter by source domain (e.g., 'markets', 'conflict', 'military')",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category (e.g., 'Financial Markets', 'Conflict & Security', 'Cyber Threats')",
                },
                "hours": {
                    "type": "number",
                    "description": "Only results from last N hours",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="intel_similar_events",
        description="Find historically similar intelligence events or data. Given a text description, finds the most similar stored entries across all domains. Useful for pattern matching and precedent analysis.",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Reference text to find similar events for",
                },
                "domain": {
                    "type": "string",
                    "description": "Source domain of the reference text",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                    "default": 10,
                },
                "hours": {
                    "type": "number",
                    "description": "Only results from last N hours",
                },
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="intel_timeline",
        description="Get chronological timeline of stored intelligence data. Returns recent entries sorted by time. Filter by domain or category to focus on specific intelligence areas.",
        inputSchema={
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Filter by source domain",
                },
                "category": {
                    "type": "string",
                    "description": "Filter by category",
                },
                "hours": {
                    "type": "number",
                    "description": "Time window in hours (default 24)",
                    "default": 24,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    Tool(
        name="intel_vector_stats",
        description="Get vector store statistics: total points, collection status, embedding model info. Shows how much intelligence data has been accumulated.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="intel_collect",
        description="Trigger an immediate collection cycle to populate the vector store. Fetches all intelligence sources and stores them. Optional: sources (comma-separated domain groups like 'markets,conflict,cyber').",
        inputSchema={
            "type": "object",
            "properties": {
                "sources": {
                    "type": "string",
                    "description": "Comma-separated domain groups (e.g., 'markets,conflict,cyber'). Default: all sources.",
                },
            },
        },
    ),
    Tool(
        name="intel_cross_correlate",
        description="Cross-domain intelligence correlation. Given a topic, finds related signals across ALL intelligence domains (military, financial, cyber, conflict, etc.) and groups them by category. Shows how events ripple across domains — e.g., how a military buildup correlates with market movements and news coverage.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Topic to correlate across domains (e.g., 'Taiwan strait tensions', 'oil supply disruption')",
                },
                "hours": {
                    "type": "number",
                    "description": "Time window in hours (default 24)",
                    "default": 24,
                },
                "limit_per_domain": {
                    "type": "integer",
                    "description": "Max signals per domain category (default 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="intel_domain_summary",
        description="Summary of all intelligence data stored in the vector database. Shows per-category data point counts, unique sources, latest/earliest timestamps, and total events tracked. Answers: what intelligence do we have and how recent is it?",
        inputSchema={
            "type": "object",
            "properties": {
                "hours": {
                    "type": "number",
                    "description": "Time window in hours (default 24)",
                    "default": 24,
                },
            },
        },
    ),
    Tool(
        name="intel_trend_detection",
        description="Detect activity trends by comparing recent intelligence activity against a baseline. Identifies SURGE (>50% increase), ELEVATED (>20%), DECLINING (<-20%), and DROP (<-50%) patterns. Useful for early warning when a domain suddenly spikes or goes quiet.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Focus on one category (e.g., 'Conflict & Security'). Default: all categories.",
                },
                "recent_hours": {
                    "type": "number",
                    "description": "Recent window to measure (default 6 hours)",
                    "default": 6,
                },
                "baseline_hours": {
                    "type": "number",
                    "description": "Baseline window for comparison (default 48 hours)",
                    "default": 48,
                },
            },
        },
    ),
]


async def _semantic_search(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    return await runtime.vector_store.semantic_search(
        query=arguments["query"],
        limit=arguments.get("limit", 20),
        domain=arguments.get("domain"),
        category=arguments.get("category"),
        hours=arguments.get("hours"),
    )


async def _similar_events(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    return await runtime.vector_store.find_similar(
        domain=arguments.get("domain", "unknown"),
        text=arguments["text"],
        limit=arguments.get("limit", 10),
        hours=arguments.get("hours"),
    )


async def _timeline(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    return await runtime.vector_store.timeline(
        domain=arguments.get("domain"),
        category=arguments.get("category"),
        hours=arguments.get("hours", 24.0),
        limit=arguments.get("limit", 50),
    )


async def _vector_stats(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    return await runtime.vector_store.collection_stats()


async def _collect(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    from ..collector import collect_once

    return await collect_once(
        runtime.fetcher,
        runtime.vector_store,
        source_filter=(
            None
            if not arguments.get("sources")
            else set(arguments["sources"].split(","))
        ),
    )


async def _cross_correlate(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    return await runtime.vector_store.cross_domain_correlate(
        query=arguments["query"],
        hours=arguments.get("hours", 24.0),
        limit_per_domain=arguments.get("limit_per_domain", 5),
    )


async def _domain_summary(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    return await runtime.vector_store.domain_summary(
        hours=arguments.get("hours", 24.0),
    )


async def _trend_detection(arguments: dict[str, Any]) -> Any:
    if runtime.vector_store is None:
        return {"error": "Vector store not available (Qdrant not running?)"}
    return await runtime.vector_store.trend_detection(
        category=arguments.get("category"),
        recent_hours=arguments.get("recent_hours", 6.0),
        baseline_hours=arguments.get("baseline_hours", 48.0),
    )


HANDLERS = {
    "intel_semantic_search": _semantic_search,
    "intel_similar_events": _similar_events,
    "intel_timeline": _timeline,
    "intel_vector_stats": _vector_stats,
    "intel_collect": _collect,
    "intel_cross_correlate": _cross_correlate,
    "intel_domain_summary": _domain_summary,
    "intel_trend_detection": _trend_detection,
}
