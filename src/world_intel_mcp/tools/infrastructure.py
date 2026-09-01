"""Infrastructure and transport tools: internet outages,
undersea cable health, navigational warnings, airport delays, global
air traffic, road traffic, webcams, shipping stress, cloud service
status.

Phase 26 split: Tool definitions moved byte-identical and dispatch
case bodies verbatim from server.py; handlers reach shared
infrastructure via ``runtime``. See tools/system.py for the pattern.
"""

from typing import Any

from mcp.types import Tool

from .. import runtime
from ..sources import (
    infrastructure,
    maritime,
    aviation,
    shipping,
    service_status,
)

TOOLS: list[Tool] = [
    # --- Infrastructure (2 tools) ---
    Tool(
        name="intel_internet_outages",
        description="Get internet outages from Cloudflare Radar (last 7 days). Optional: CLOUDFLARE_API_TOKEN for higher limits.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="intel_cable_health",
        description="Assess undersea cable corridor health from NGA navigational warnings. 6 corridors scored 0-3.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # --- Maritime (1 tool) ---
    Tool(
        name="intel_nav_warnings",
        description="Get active navigational warnings from NGA Maritime Safety. Optional: navarea (I-XVI).",
        inputSchema={
            "type": "object",
            "properties": {
                "navarea": {
                    "type": "string",
                    "description": "NAVAREA number (e.g., IV, XII)",
                },
            },
        },
    ),
    # --- Aviation (1 tool) ---
    Tool(
        name="intel_airport_delays",
        description="Get current US airport delays from FAA (20 major airports). No API key needed.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # --- Aviation domestic (1 tool) ---
    Tool(
        name="intel_aviation_domestic",
        description="Global air traffic snapshot from OpenSky Network: total airborne aircraft, regional breakdown, busiest origin countries, and sampled positions for mapping.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # --- Traffic (2 tools) ---
    Tool(
        name="intel_traffic_flow",
        description="Real-time traffic congestion for 20 major world cities via TomTom API. Congestion percentage, speeds, global average. Requires TOMTOM_API_KEY.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="intel_traffic_incidents",
        description="Major traffic incidents across 5 strategic regions (US East/West, Europe, Middle East, East Asia) via TomTom API. Requires TOMTOM_API_KEY.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # --- Webcams (1 tool) ---
    Tool(
        name="intel_webcams",
        description="Public webcam locations and live previews worldwide from Windy Webcams API. Filter by category (traffic, weather, landscape). Requires WINDY_API_KEY.",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Webcam category (traffic, weather, landscape, etc.)",
                    "default": "traffic",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max cameras to return (default 50)",
                    "default": 50,
                },
            },
        },
    ),
    # --- Shipping (1 tool) ---
    Tool(
        name="intel_shipping_index",
        description="Compute shipping stress index from dry bulk ETFs (BDRY, SBLK, EGLE, ZIM). Stress score 0-100.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # --- Service Status (1 tool) ---
    Tool(
        name="intel_service_status",
        description="Monitor cloud service provider status (AWS, Azure, GCP, Cloudflare, GitHub). Shows active incidents and recent outages. Optional: provider (aws/azure/gcp/cloudflare/github).",
        inputSchema={
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Filter by provider (aws, azure, gcp, cloudflare, github)",
                },
            },
        },
    ),
]


async def _internet_outages(arguments: dict[str, Any]) -> Any:
    return await infrastructure.fetch_internet_outages(runtime.fetcher)


async def _cable_health(arguments: dict[str, Any]) -> Any:
    return await infrastructure.fetch_cable_health(runtime.fetcher)


async def _nav_warnings(arguments: dict[str, Any]) -> Any:
    return await maritime.fetch_nav_warnings(
        runtime.fetcher, navarea=arguments.get("navarea")
    )


async def _airport_delays(arguments: dict[str, Any]) -> Any:
    return await aviation.fetch_airport_delays(runtime.fetcher)


async def _aviation_domestic(arguments: dict[str, Any]) -> Any:
    return await aviation.fetch_domestic_flights(runtime.fetcher)


async def _traffic_flow(arguments: dict[str, Any]) -> Any:
    from ..sources.traffic import fetch_traffic_flow

    return await fetch_traffic_flow(runtime.fetcher)


async def _traffic_incidents(arguments: dict[str, Any]) -> Any:
    from ..sources.traffic import fetch_traffic_incidents

    return await fetch_traffic_incidents(runtime.fetcher)


async def _webcams(arguments: dict[str, Any]) -> Any:
    from ..sources.webcams import fetch_webcams

    return await fetch_webcams(
        runtime.fetcher,
        category=arguments.get("category", "traffic"),
        limit=arguments.get("limit", 50),
    )


async def _shipping_index(arguments: dict[str, Any]) -> Any:
    return await shipping.fetch_shipping_index(runtime.fetcher)


async def _service_status(arguments: dict[str, Any]) -> Any:
    return await service_status.fetch_service_status(
        runtime.fetcher,
        provider=arguments.get("provider"),
    )


HANDLERS = {
    "intel_internet_outages": _internet_outages,
    "intel_cable_health": _cable_health,
    "intel_nav_warnings": _nav_warnings,
    "intel_airport_delays": _airport_delays,
    "intel_aviation_domestic": _aviation_domestic,
    "intel_traffic_flow": _traffic_flow,
    "intel_traffic_incidents": _traffic_incidents,
    "intel_webcams": _webcams,
    "intel_shipping_index": _shipping_index,
    "intel_service_status": _service_status,
}
