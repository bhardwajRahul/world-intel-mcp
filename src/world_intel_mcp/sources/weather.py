"""NWS severe weather alerts source for world-intel-mcp.

Provides active CAP alerts from the US National Weather Service API
(api.weather.gov). No API key required, but NWS policy requires a
descriptive User-Agent, which this module sends explicitly.

Coverage is US-only (states, territories, and marine zones) — there is
no global feed behind this endpoint, and the output says so via a
``coverage: "US"`` key.

Geometry honesty: many active alerts are zone-based and carry a null
GeoJSON geometry (measured 2026-09-01: 17 of 28 nationwide Severe
alerts had polygons). When a polygon is present, latitude/longitude are
the mean of its outer-ring vertices — a representative point, not an
official centroid. When geometry is null they are None; no coordinates
are invented from zone URLs.
"""

import logging
from datetime import datetime, timezone

from ..fetcher import Fetcher

logger = logging.getLogger("world-intel-mcp.sources.weather")

_NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

# NWS policy: identify your application. The Fetcher default UA is
# generic, so this module always sends its own descriptive one.
_NWS_HEADERS = {
    "User-Agent": "world-intel-mcp (https://github.com/marc-shade/world-intel-mcp)",
    "Accept": "application/geo+json",
}


async def fetch_weather_alerts(
    fetcher: Fetcher,
    area: str | None = None,
    severity: str | None = None,
    limit: int = 50,
) -> dict:
    """Fetch active NWS severe weather alerts (US only).

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        area: Optional two-letter state/territory code (e.g. "TX").
        severity: Optional severity filter — one of Extreme, Severe,
            Moderate, Minor, Unknown (case-insensitive input).
        limit: Maximum alerts to return. Applied client-side: the
            /alerts/active endpoint rejects a limit query parameter
            with HTTP 400 (verified live 2026-09-01).

    Returns:
        Dict with alerts list, count, by_severity counts, coverage,
        query, source, and timestamp.
    """
    now = datetime.now(timezone.utc)

    params: dict[str, str] = {}
    if area:
        params["area"] = area.strip().upper()
    if severity:
        params["severity"] = severity.strip().capitalize()

    query = {"area": params.get("area"), "severity": params.get("severity")}

    data = await fetcher.get_json(
        url=_NWS_ALERTS_URL,
        source="nws",
        cache_key=f"weather:alerts:{params.get('area')}:{params.get('severity')}",
        cache_ttl=300,
        headers=_NWS_HEADERS,
        params=params or None,
    )

    if data is None:
        logger.warning("NWS alerts API returned no data")
        return {
            "error": "NWS alerts API unavailable (no live or cached data)",
            "degraded": True,
            "reason": "nws_fetch_failed",
            "alerts": [],
            "count": 0,
            "by_severity": {},
            "coverage": "US",
            "query": query,
            "source": "nws",
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    alerts = []
    by_severity: dict[str, int] = {}
    for feature in data.get("features", [])[:limit]:
        props = feature.get("properties", {})
        lat, lon = _representative_point(feature.get("geometry"))

        alert_severity = props.get("severity") or "Unknown"
        by_severity[alert_severity] = by_severity.get(alert_severity, 0) + 1

        alerts.append(
            {
                "id": feature.get("id"),
                "event": props.get("event"),
                "severity": alert_severity,
                "urgency": props.get("urgency"),
                "certainty": props.get("certainty"),
                "headline": props.get("headline"),
                "area": props.get("areaDesc"),
                "effective": props.get("effective"),
                "expires": props.get("expires"),
                "onset": props.get("onset"),
                "ends": props.get("ends"),
                "sender": props.get("senderName"),
                "latitude": lat,
                "longitude": lon,
            }
        )

    return {
        "alerts": alerts,
        "count": len(alerts),
        "by_severity": by_severity,
        "coverage": "US",
        "query": query,
        "source": "nws",
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _representative_point(
    geometry: dict | None,
) -> tuple[float | None, float | None]:
    """Derive a representative (lat, lon) from an alert's GeoJSON geometry.

    Polygon: mean of the outer-ring vertices (closing duplicate vertex
    dropped). MultiPolygon: same, on the first polygon's outer ring.
    Null or unrecognized geometry: (None, None) — zone-based alerts
    carry no coordinates and none are fabricated.
    """
    if not geometry:
        return (None, None)

    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon" and coords:
        ring = coords[0]
    elif gtype == "MultiPolygon" and coords and coords[0]:
        ring = coords[0][0]
    else:
        return (None, None)

    if not ring:
        return (None, None)
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]

    try:
        lon = sum(pt[0] for pt in ring) / len(ring)
        lat = sum(pt[1] for pt in ring) / len(ring)
    except (TypeError, IndexError, ZeroDivisionError):
        return (None, None)
    return (round(lat, 4), round(lon, 4))
