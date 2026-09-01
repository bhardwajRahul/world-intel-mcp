"""Launch Library 2 upcoming-launch schedule source for world-intel-mcp.

Provides upcoming orbital/suborbital launch schedules from The Space
Devs' Launch Library 2 API. No API key required, but the free tier is
rate-limited to roughly 15 requests/hour — hence the long cache TTL.
The upstream "upcoming" endpoint also includes very recently launched
missions (verified live 2026-09-01: first result had already flown,
status "Launch Successful"); the status field passes that through
rather than filtering it out.
"""

import logging
from datetime import datetime, timezone

from ..fetcher import Fetcher

logger = logging.getLogger("world-intel-mcp.sources.launches")

_LL2_UPCOMING_URL = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/"

# Free tier is ~15 req/hr; a fresh fetch at most once per hour.
_CACHE_TTL = 3600


async def fetch_launch_schedule(
    fetcher: Fetcher,
    limit: int = 20,
) -> dict:
    """Fetch upcoming launches from Launch Library 2.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        limit: Maximum launches to return (passed to the API).

    Returns:
        Dict with launches list (name, provider, vehicle, pad with
        lat/lon, net launch time, status, mission), count, source,
        and timestamp.
    """
    now = datetime.now(timezone.utc)

    data = await fetcher.get_json(
        url=_LL2_UPCOMING_URL,
        source="launch-library",
        cache_key=f"launches:ll2:upcoming:{limit}",
        cache_ttl=_CACHE_TTL,
        params={"limit": limit},
    )

    if data is None:
        logger.warning("Launch Library 2 API returned no data")
        return {
            "error": "Launch Library 2 API unavailable (no live or cached data)",
            "degraded": True,
            "reason": "launch_library_fetch_failed",
            "launches": [],
            "count": 0,
            "source": "launch-library",
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    launches = []
    for result in data.get("results", [])[:limit]:
        status = result.get("status") or {}
        provider = result.get("launch_service_provider") or {}
        config = (result.get("rocket") or {}).get("configuration") or {}
        pad = result.get("pad") or {}
        pad_location = pad.get("location") or {}
        mission = result.get("mission") or {}
        orbit = mission.get("orbit") or {}

        description = mission.get("description")
        if description and len(description) > 500:
            description = description[:500]

        launches.append(
            {
                "id": result.get("id"),
                "name": result.get("name"),
                "provider": provider.get("name"),
                "provider_type": provider.get("type"),
                "vehicle": config.get("full_name") or config.get("name"),
                "pad": pad.get("name"),
                "pad_location": pad_location.get("name"),
                "country_code": pad_location.get("country_code"),
                # LL2 serializes pad coordinates as strings
                "latitude": _safe_float(pad.get("latitude")),
                "longitude": _safe_float(pad.get("longitude")),
                "net": result.get("net"),
                "window_start": result.get("window_start"),
                "window_end": result.get("window_end"),
                "status": status.get("name"),
                "status_abbrev": status.get("abbrev"),
                "mission": mission.get("name"),
                "mission_type": mission.get("type"),
                "orbit": orbit.get("abbrev"),
                "mission_description": description,
            }
        )

    return {
        "launches": launches,
        "count": len(launches),
        "source": "launch-library",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _safe_float(value: str | float | None) -> float | None:
    """Convert a value to float, returning None when absent or unparseable."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None
