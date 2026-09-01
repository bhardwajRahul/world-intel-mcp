"""Business-finance tools: forex, bonds and yields, earnings,
SEC filings, company enrichment, macro composite.

Phase 26 split: Tool definitions moved byte-identical and dispatch
case bodies verbatim from server.py; handlers reach shared
infrastructure via ``runtime``. See tools/system.py for the pattern.
"""

from typing import Any

from mcp.types import Tool

from .. import runtime

TOOLS: list[Tool] = [
    # --- Forex (3 tools) ---
    Tool(
        name="intel_forex_rates",
        description="Get latest foreign exchange rates from ECB via Frankfurter API. Optional: base currency (default USD), target symbols list.",
        inputSchema={
            "type": "object",
            "properties": {
                "base": {
                    "type": "string",
                    "description": "Base currency code (default: USD)",
                    "default": "USD",
                },
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Target currency codes (e.g., ['EUR', 'GBP', 'JPY'])",
                },
            },
        },
    ),
    Tool(
        name="intel_forex_timeseries",
        description="Get historical FX rate timeseries with trend analysis. Optional: base, symbol, days.",
        inputSchema={
            "type": "object",
            "properties": {
                "base": {
                    "type": "string",
                    "description": "Base currency (default: USD)",
                    "default": "USD",
                },
                "symbol": {
                    "type": "string",
                    "description": "Target currency (default: EUR)",
                    "default": "EUR",
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days of history (default: 30)",
                    "default": 30,
                },
            },
        },
    ),
    Tool(
        name="intel_major_crosses",
        description="Get all 8 major FX currency pairs (EUR/USD, USD/JPY, GBP/USD, etc.) with cross rates and DXY proxy.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # --- Bonds & Yields (2 tools) ---
    Tool(
        name="intel_yield_curve",
        description="Get US Treasury yield curve (2Y-30Y maturities), 2s10s and 3m10y spreads, and inversion detection. Uses FRED or Yahoo Finance fallback.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="intel_bond_indices",
        description="Get major bond ETF prices and performance: AGG (total bond), TLT (20Y+ Treasury), HYG (high yield), LQD (investment grade), TIP (TIPS).",
        inputSchema={"type": "object", "properties": {}},
    ),
    # --- Earnings (2 tools) ---
    Tool(
        name="intel_earnings_calendar",
        description="Get upcoming earnings announcements for top 20 mega-cap stocks (AAPL, MSFT, GOOGL, etc.) with EPS estimates and days until report.",
        inputSchema={
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Days to look ahead for 'this_week' filter (default: 7)",
                    "default": 7,
                },
            },
        },
    ),
    Tool(
        name="intel_earnings_surprise",
        description="Get recent earnings surprises for a specific stock — past quarter actual vs estimate, surprise %, and forward estimates.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., 'AAPL')",
                },
            },
            "required": ["symbol"],
        },
    ),
    # --- SEC Filings (3 tools) ---
    Tool(
        name="intel_sec_filings",
        description="Search SEC EDGAR filings via full-text search. Filter by form type (10-K, 10-Q, 8-K) and date range.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (company name, keyword, etc.)",
                },
                "form_type": {
                    "type": "string",
                    "description": "Comma-separated form types (e.g., '10-K,10-Q,8-K')",
                },
                "date_range": {
                    "type": "string",
                    "description": "Date range as 'YYYY-MM-DD,YYYY-MM-DD' (default: last 30 days)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 25, max: 100)",
                    "default": 25,
                },
            },
        },
    ),
    Tool(
        name="intel_company_filings",
        description="Get recent SEC filings for a company by ticker symbol (10-K, 10-Q, 8-K). Resolves ticker to CIK automatically.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., 'AAPL')",
                },
                "form_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Form types to include (default: ['10-K', '10-Q', '8-K'])",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max filings (default: 10)",
                    "default": 10,
                },
            },
            "required": ["ticker"],
        },
    ),
    Tool(
        name="intel_recent_8k",
        description="Get most recent 8-K filings (material corporate events: M&A, executive changes, earnings releases) across all companies.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max filings (default: 25, max: 100)",
                    "default": 25,
                },
            },
        },
    ),
    # --- Company Enrichment (1 tool) ---
    Tool(
        name="intel_company_profile",
        description="Get comprehensive company profile: stock quote, financials, sector/industry, recent news, SEC filings, and GitHub repos (for tech companies). Accepts ticker or company name.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Ticker symbol (e.g., 'AAPL') or company name",
                },
            },
            "required": ["query"],
        },
    ),
    # --- Macro Composite (1 tool) ---
    Tool(
        name="intel_macro_composite",
        description="Get weighted macro market composite score (0-100) synthesizing Fear & Greed, VIX, sector breadth, DXY, BTC technicals, and 10Y yield into an actionable verdict (RISK_ON / CONSTRUCTIVE / NEUTRAL / CAUTIOUS / STRONG_CAUTION).",
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def _forex_rates(arguments: dict[str, Any]) -> Any:
    from ..sources.forex import fetch_forex_rates

    return await fetch_forex_rates(
        runtime.fetcher,
        base=arguments.get("base", "USD"),
        symbols=arguments.get("symbols"),
    )


async def _forex_timeseries(arguments: dict[str, Any]) -> Any:
    from ..sources.forex import fetch_forex_timeseries

    return await fetch_forex_timeseries(
        runtime.fetcher,
        base=arguments.get("base", "USD"),
        symbol=arguments.get("symbol", "EUR"),
        days=arguments.get("days", 30),
    )


async def _major_crosses(arguments: dict[str, Any]) -> Any:
    from ..sources.forex import fetch_major_crosses

    return await fetch_major_crosses(runtime.fetcher)


async def _yield_curve(arguments: dict[str, Any]) -> Any:
    from ..sources.bonds import fetch_yield_curve

    return await fetch_yield_curve(runtime.fetcher)


async def _bond_indices(arguments: dict[str, Any]) -> Any:
    from ..sources.bonds import fetch_bond_indices

    return await fetch_bond_indices(runtime.fetcher)


async def _earnings_calendar(arguments: dict[str, Any]) -> Any:
    from ..sources.earnings import fetch_earnings_calendar

    return await fetch_earnings_calendar(
        runtime.fetcher, days_ahead=arguments.get("days_ahead", 7)
    )


async def _earnings_surprise(arguments: dict[str, Any]) -> Any:
    from ..sources.earnings import fetch_earnings_surprise

    return await fetch_earnings_surprise(runtime.fetcher, symbol=arguments["symbol"])


async def _sec_filings(arguments: dict[str, Any]) -> Any:
    from ..sources.sec_edgar import fetch_sec_filings

    return await fetch_sec_filings(
        runtime.fetcher,
        query=arguments.get("query"),
        form_type=arguments.get("form_type"),
        date_range=arguments.get("date_range"),
        limit=arguments.get("limit", 25),
    )


async def _company_filings(arguments: dict[str, Any]) -> Any:
    from ..sources.sec_edgar import fetch_company_filings

    return await fetch_company_filings(
        runtime.fetcher,
        ticker=arguments["ticker"],
        form_types=arguments.get("form_types"),
        limit=arguments.get("limit", 10),
    )


async def _recent_8k(arguments: dict[str, Any]) -> Any:
    from ..sources.sec_edgar import fetch_recent_8k

    return await fetch_recent_8k(runtime.fetcher, limit=arguments.get("limit", 25))


async def _company_profile(arguments: dict[str, Any]) -> Any:
    from ..analysis.company import fetch_company_profile

    return await fetch_company_profile(runtime.fetcher, query=arguments["query"])


async def _macro_composite(arguments: dict[str, Any]) -> Any:
    from ..analysis.macro_composite import fetch_macro_composite

    return await fetch_macro_composite(runtime.fetcher)


HANDLERS = {
    "intel_forex_rates": _forex_rates,
    "intel_forex_timeseries": _forex_timeseries,
    "intel_major_crosses": _major_crosses,
    "intel_yield_curve": _yield_curve,
    "intel_bond_indices": _bond_indices,
    "intel_earnings_calendar": _earnings_calendar,
    "intel_earnings_surprise": _earnings_surprise,
    "intel_sec_filings": _sec_filings,
    "intel_company_filings": _company_filings,
    "intel_recent_8k": _recent_8k,
    "intel_company_profile": _company_profile,
    "intel_macro_composite": _macro_composite,
}
