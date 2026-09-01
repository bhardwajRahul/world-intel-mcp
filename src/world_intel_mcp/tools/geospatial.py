"""Static geospatial dataset tools: military bases, strategic
ports, pipelines, nuclear facilities, undersea cables, AI datacenters,
spaceports, critical minerals, stock exchanges, trade routes, cloud
regions, financial centers.

Phase 26 split: Tool definitions moved byte-identical and dispatch
case bodies verbatim from server.py; handlers reach shared
infrastructure via ``runtime``. See tools/system.py for the pattern.
"""

from typing import Any

from mcp.types import Tool

from ..sources import geospatial

TOOLS: list[Tool] = [
    # --- Geospatial Datasets (4 tools) ---
    Tool(
        name="intel_military_bases",
        description="Query 120+ military bases worldwide from 9 operators (USA, Russia, China, UK, France, NATO, India, Turkey, Israel, Iran, UAE). Filterable by operator, host country, base type, branch.",
        inputSchema={
            "type": "object",
            "properties": {
                "operator": {
                    "type": "string",
                    "description": "Filter by operating country (USA, RUS, CHN, GBR, FRA, NATO, IND, TUR, ISR, IRN, ARE)",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by host country name or ISO-3 code",
                },
                "base_type": {
                    "type": "string",
                    "description": "Filter by type: air_base, naval_base, army_base, marine_base, training, space_base, missile_defense, expeditionary",
                },
                "branch": {
                    "type": "string",
                    "description": "Filter by branch (USAF, US Navy, PLA Navy, RAF, etc.)",
                },
            },
        },
    ),
    Tool(
        name="intel_strategic_ports",
        description="Query 40+ strategic ports worldwide: container mega-ports, oil/LNG terminals, naval bases, bulk ports. Filterable by type and country.",
        inputSchema={
            "type": "object",
            "properties": {
                "port_type": {
                    "type": "string",
                    "description": "Filter by type: container, oil, lng, naval, bulk, mixed",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by country name or ISO-3 code",
                },
            },
        },
    ),
    Tool(
        name="intel_pipelines",
        description="Query 25+ strategic oil, gas, and hydrogen pipelines with routes, capacity, and status. Includes Nord Stream, Druzhba, Power of Siberia, BTC, TAPS, etc.",
        inputSchema={
            "type": "object",
            "properties": {
                "pipeline_type": {
                    "type": "string",
                    "description": "Filter by type: oil, gas, hydrogen",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: active, destroyed, proposed, stalled, reduced, cancelled, construction, intermittent, terminated",
                },
            },
        },
    ),
    Tool(
        name="intel_nuclear_facilities",
        description="Query 25+ nuclear power plants, enrichment sites, research reactors, and reprocessing facilities worldwide. Includes Zaporizhzhia, Natanz, Fordow, Yongbyon, etc.",
        inputSchema={
            "type": "object",
            "properties": {
                "facility_type": {
                    "type": "string",
                    "description": "Filter by type: power, enrichment, research, reprocessing, decommissioned",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by country name or ISO-3 code",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: operational, construction, shutdown, occupied, commissioning, decommissioning, exclusion_zone",
                },
            },
        },
    ),
    # --- Extended Geospatial (5 tools) ---
    Tool(
        name="intel_undersea_cables",
        description="Query 30+ undersea fiber-optic cable routes with landing points, owners, capacity (Tbps), and length (km). Filterable by status, country, owner, min capacity.",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: active, planned, construction, decommissioned",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by country in landing points",
                },
                "owner": {
                    "type": "string",
                    "description": "Filter by cable owner (Google, Meta, Microsoft, etc.)",
                },
                "min_capacity_tbps": {
                    "type": "number",
                    "description": "Minimum cable capacity in Tbps",
                },
            },
        },
    ),
    Tool(
        name="intel_ai_datacenters",
        description="Query 48+ AI datacenter clusters worldwide with power capacity (MW), operators, and locations. Covers hyperscalers and sovereign AI.",
        inputSchema={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Filter by country name or ISO-3 code",
                },
                "operator": {
                    "type": "string",
                    "description": "Filter by operator (AWS, Google, Microsoft, Meta, etc.)",
                },
                "min_power_mw": {
                    "type": "integer",
                    "description": "Minimum power capacity in MW",
                },
                "region": {
                    "type": "string",
                    "description": "Filter by region (North America, Europe, Asia-Pacific, etc.)",
                },
            },
        },
    ),
    Tool(
        name="intel_spaceports",
        description="Query 27+ launch facilities and spaceports worldwide. Filterable by country, status, type (orbital/suborbital), and operator.",
        inputSchema={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Filter by country name or ISO-3 code",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status: active, limited, planned, decommissioned",
                },
                "spaceport_type": {
                    "type": "string",
                    "description": "Filter by type: orbital, suborbital",
                },
                "operator": {
                    "type": "string",
                    "description": "Filter by operator (SpaceX, NASA, CNSA, Roscosmos, etc.)",
                },
            },
        },
    ),
    Tool(
        name="intel_critical_minerals",
        description="Query 28+ critical mineral deposits worldwide: lithium, cobalt, rare earths, nickel, copper, graphite, manganese, PGM, tungsten, uranium, tin, gallium, germanium.",
        inputSchema={
            "type": "object",
            "properties": {
                "mineral": {
                    "type": "string",
                    "description": "Filter by mineral (lithium, cobalt, rare_earths, nickel, copper, graphite, manganese, platinum_group, tungsten, uranium, tin, gallium, germanium)",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by country name or ISO-3 code",
                },
                "mineral_type": {
                    "type": "string",
                    "description": "Filter by type: battery, electronic, structural, energy, industrial, strategic",
                },
                "operator": {"type": "string", "description": "Filter by operator"},
            },
        },
    ),
    Tool(
        name="intel_stock_exchanges",
        description="Query 80+ stock exchanges across 4 tiers (mega >$3T, major, emerging, frontier) with market cap, index tickers, currencies, timezones.",
        inputSchema={
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "description": "Filter by tier: mega, major, emerging, frontier",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by country name or ISO-3 code",
                },
                "currency": {
                    "type": "string",
                    "description": "Filter by currency (USD, EUR, GBP, JPY, CNY, etc.)",
                },
            },
        },
    ),
    # --- Trade Routes (1 tool) ---
    Tool(
        name="intel_trade_routes",
        description="19 critical maritime chokepoints and trade routes with oil flow (mbd), daily vessel transits, trade value share. Optional: route_type (chokepoint/canal/route), country (ISO-3).",
        inputSchema={
            "type": "object",
            "properties": {
                "route_type": {
                    "type": "string",
                    "description": "Filter: chokepoint, canal, route",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by ISO-3 country code",
                },
            },
        },
    ),
    # --- Cloud Regions (1 tool) ---
    Tool(
        name="intel_cloud_regions",
        description="28 major cloud provider regions (AWS, Azure, GCP) with coordinates, zone counts, and launch dates. Optional: provider, country.",
        inputSchema={
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Filter: AWS, Azure, GCP",
                },
                "country": {
                    "type": "string",
                    "description": "Filter by region name substring",
                },
            },
        },
    ),
    # --- Financial Centers (1 tool) ---
    Tool(
        name="intel_financial_centers",
        description="GFCI top 20 global financial centers with rankings, ratings, specializations, and exchange info. Optional: country (ISO-3), min_rank.",
        inputSchema={
            "type": "object",
            "properties": {
                "country": {
                    "type": "string",
                    "description": "Filter by ISO-3 country code",
                },
                "min_rank": {
                    "type": "integer",
                    "description": "Only include centers ranked this or better",
                },
            },
        },
    ),
]


async def _military_bases(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_military_bases(
        operator=arguments.get("operator"),
        country=arguments.get("country"),
        base_type=arguments.get("base_type"),
        branch=arguments.get("branch"),
    )


async def _strategic_ports(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_strategic_ports(
        port_type=arguments.get("port_type"),
        country=arguments.get("country"),
    )


async def _pipelines(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_pipelines(
        pipeline_type=arguments.get("pipeline_type"),
        status=arguments.get("status"),
    )


async def _nuclear_facilities(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_nuclear_facilities(
        facility_type=arguments.get("facility_type"),
        country=arguments.get("country"),
        status=arguments.get("status"),
    )


async def _undersea_cables(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_undersea_cables(
        status=arguments.get("status"),
        country=arguments.get("country"),
        owner=arguments.get("owner"),
        min_capacity_tbps=arguments.get("min_capacity_tbps"),
    )


async def _ai_datacenters(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_ai_datacenters(
        country=arguments.get("country"),
        operator=arguments.get("operator"),
        min_power_mw=arguments.get("min_power_mw"),
        region=arguments.get("region"),
    )


async def _spaceports(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_spaceports(
        country=arguments.get("country"),
        status=arguments.get("status"),
        spaceport_type=arguments.get("spaceport_type"),
        operator=arguments.get("operator"),
    )


async def _critical_minerals(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_critical_minerals(
        mineral=arguments.get("mineral"),
        country=arguments.get("country"),
        mineral_type=arguments.get("mineral_type"),
        operator=arguments.get("operator"),
    )


async def _stock_exchanges(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_stock_exchanges(
        tier=arguments.get("tier"),
        country=arguments.get("country"),
        currency=arguments.get("currency"),
    )


async def _trade_routes(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_trade_routes(
        route_type=arguments.get("route_type"),
        country=arguments.get("country"),
    )


async def _cloud_regions(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_cloud_regions(
        provider=arguments.get("provider"),
        country=arguments.get("country"),
    )


async def _financial_centers(arguments: dict[str, Any]) -> Any:
    return await geospatial.fetch_financial_centers(
        country=arguments.get("country"),
        min_rank=arguments.get("min_rank"),
    )


HANDLERS = {
    "intel_military_bases": _military_bases,
    "intel_strategic_ports": _strategic_ports,
    "intel_pipelines": _pipelines,
    "intel_nuclear_facilities": _nuclear_facilities,
    "intel_undersea_cables": _undersea_cables,
    "intel_ai_datacenters": _ai_datacenters,
    "intel_spaceports": _spaceports,
    "intel_critical_minerals": _critical_minerals,
    "intel_stock_exchanges": _stock_exchanges,
    "intel_trade_routes": _trade_routes,
    "intel_cloud_regions": _cloud_regions,
    "intel_financial_centers": _financial_centers,
}
