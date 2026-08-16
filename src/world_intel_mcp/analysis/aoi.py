"""User-defined areas of interest (AOIs): geofences (issue #16).

The intel community calls this an AOI; consumer software calls it a
geofence. This module composes the same domain fetch functions used
elsewhere in the codebase (seismology, military, conflict, wildfire,
aviation, news) around a user-named point-plus-radius, the way
``analysis/daily_digest.py`` composes them around "right now" instead of
"this place". It lives in ``analysis/`` rather than ``sources/`` because,
like ``daily_digest.py`` and ``situation.py``, its job is cross-domain
composition and citation, not talking to a single upstream API.

Follows the same citation discipline as ``situation.py``/``daily_digest.py``:
every listed item carries a ``[n]`` reference into a numbered ``sources``
list, and ``cited`` is only true when the brief text actually contains one.
``data_gaps`` names every domain that could not be geographically scoped
rather than silently omitting it.

AOI persistence (``AOIStore``) uses a dedicated ``aois`` table in the same
SQLite database file the process-wide ``Cache`` already opened, using the
same ``db_path`` and the same WAL / busy_timeout pragmas, via its own connection.
SQLite's WAL mode is explicitly designed for multiple connections against
one file, which is already how this repo's ``Cache`` coexists with
external readers. A dedicated table (not cache-entry abuse) because an AOI
is a named row a user expects to list and delete, not a TTL'd blob; a
separate connection (not new methods bolted onto ``Cache``) because
``Cache`` is a generic TTL key-value store and mixing a structured CRUD
table into it would blur that class's one job, at the cost of a well-
tested 188-line module untouched by this change.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .escalation import score_hotspot
from .situation import _add_source, _cite, _has_valid_citation

logger = logging.getLogger("world-intel-mcp.analysis.aoi")

MIN_RADIUS_KM = 1.0
MAX_RADIUS_KM = 2000.0

_EARTH_RADIUS_KM = 6371.0
_KM_PER_DEGREE_LAT = 111.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometers."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return _EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(min(1.0, a)))


def bbox_from_radius_km(lat: float, lon: float, radius_km: float) -> str:
    """Derive a ``lamin,lomin,lamax,lomax`` bounding box (the format
    ``sources/military.py``'s ``fetch_military_flights(bbox=...)`` takes)
    that fully contains a circle of ``radius_km`` around (lat, lon).

    Longitude degrees shrink toward the poles; the cosine factor is
    clamped so a near-polar AOI gets a wide-but-finite box instead of a
    division blowup. This is a bounding rectangle, not the circle itself;
    callers that need the exact radius still haversine-filter the
    candidates it returns (see ``filter_by_radius``), the same way
    ``analysis/convergence.py``'s grid cells are a coarse pre-filter, not
    the final answer.
    """
    dlat = radius_km / _KM_PER_DEGREE_LAT
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    dlon = radius_km / (_KM_PER_DEGREE_LAT * cos_lat)
    lamin = max(-90.0, lat - dlat)
    lamax = min(90.0, lat + dlat)
    lomin = max(-180.0, lon - dlon)
    lomax = min(180.0, lon + dlon)
    return f"{lamin:.4f},{lomin:.4f},{lamax:.4f},{lomax:.4f}"


def _distance_or_none(
    lat: float, lon: float, item_lat: Any, item_lon: Any
) -> float | None:
    if item_lat is None or item_lon is None:
        return None
    try:
        return haversine_km(lat, lon, float(item_lat), float(item_lon))
    except (TypeError, ValueError):
        return None


def filter_by_radius(
    items: list[dict],
    lat: float,
    lon: float,
    radius_km: float,
    lat_key: str = "latitude",
    lon_key: str = "longitude",
) -> list[dict]:
    """Keep only items whose coordinates fall within ``radius_km`` of
    (lat, lon), each annotated with ``distance_km`` and sorted nearest
    first. Items with missing or unparseable coordinates are dropped, not
    silently kept: an AOI brief that includes events it can't place on
    the map isn't a geofence, it's a global feed with extra steps."""
    out = []
    for item in items:
        dist = _distance_or_none(lat, lon, item.get(lat_key), item.get(lon_key))
        if dist is not None and dist <= radius_km:
            out.append({**item, "distance_km": round(dist, 1)})
    out.sort(key=lambda i: i["distance_km"])
    return out


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_aoi_params(name: Any, lat: Any, lon: Any, radius_km: Any) -> str | None:
    """Return a human-readable error message, or ``None`` if the AOI
    parameters are valid. Never raises: every branch it can take from
    missing/wrong-typed MCP arguments ends in a string, not an exception,
    so callers can return ``{"error": ...}`` uniformly."""
    if not isinstance(name, str) or not name.strip():
        return "name must be a non-empty string."
    for label, value in (("lat", lat), ("lon", lon), ("radius_km", radius_km)):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return f"{label} must be a number (got {value!r})."
    if not (-90.0 <= lat <= 90.0):
        return f"lat must be between -90 and 90 (got {lat})."
    if not (-180.0 <= lon <= 180.0):
        return f"lon must be between -180 and 180 (got {lon})."
    if not (MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM):
        return (
            f"radius_km must be between {MIN_RADIUS_KM} and "
            f"{MAX_RADIUS_KM} (got {radius_km})."
        )
    return None


# ---------------------------------------------------------------------------
# Persistence: dedicated table in the shared cache database
# ---------------------------------------------------------------------------


class AOIAlreadyExists(Exception):
    """Raised by ``AOIStore.define()`` when the (case-insensitive) name is
    already taken. Carries the existing row so the caller can echo it back
    politely instead of just saying no."""

    def __init__(self, existing: dict[str, Any]):
        self.existing = existing
        super().__init__(f"AOI '{existing['name']}' already exists")


class AOIStore:
    """Named point-radius geofences, persisted in a dedicated ``aois``
    table inside the same SQLite file the process's ``Cache`` uses (pass
    its resolved ``db_path`` in, not a fresh default-path computation,
    so this always lands in the literal file the running cache settled
    on, fallback path included).
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=10)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS aois (
                name_key TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                radius_km REAL NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    @staticmethod
    def _key(name: str) -> str:
        return name.strip().lower()

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        _name_key, name, lat, lon, radius_km, created_at = row
        return {
            "name": name,
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "created_at": created_at,
        }

    def define(
        self, name: str, lat: float, lon: float, radius_km: float
    ) -> dict[str, Any]:
        """Insert a new AOI. Raises ``AOIAlreadyExists`` (carrying the
        existing row) if the name is already taken."""
        existing = self.get(name)
        if existing is not None:
            raise AOIAlreadyExists(existing)
        clean_name = name.strip()
        now = time.time()
        self._conn.execute(
            "INSERT INTO aois (name_key, name, lat, lon, radius_km, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (self._key(name), clean_name, lat, lon, radius_km, now),
        )
        self._conn.commit()
        return {
            "name": clean_name,
            "lat": lat,
            "lon": lon,
            "radius_km": radius_km,
            "created_at": now,
        }

    def get(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT name_key, name, lat, lon, radius_km, created_at "
            "FROM aois WHERE name_key = ?",
            (self._key(name),),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT name_key, name, lat, lon, radius_km, created_at "
            "FROM aois ORDER BY name"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, name: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM aois WHERE name_key = ?", (self._key(name),)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Tool-facing: define / list / delete
# ---------------------------------------------------------------------------


def define_aoi(store: AOIStore, name: Any, lat: Any, lon: Any, radius_km: Any) -> dict:
    error = validate_aoi_params(name, lat, lon, radius_km)
    if error:
        return {"error": error}
    try:
        aoi = store.define(name, float(lat), float(lon), float(radius_km))
    except AOIAlreadyExists as exc:
        return {
            "error": f"AOI '{name.strip()}' already exists.",
            "existing": exc.existing,
        }
    return {"aoi": aoi, "source": "aoi-define", "timestamp": _utc_now_iso()}


def list_aois(store: AOIStore) -> dict:
    aois = store.list_all()
    return {
        "aois": aois,
        "count": len(aois),
        "source": "aoi-list",
        "timestamp": _utc_now_iso(),
    }


def delete_aoi(store: AOIStore, name: Any) -> dict:
    if not isinstance(name, str) or not name.strip():
        return {"error": "name must be a non-empty string."}
    deleted = store.delete(name)
    if not deleted:
        return {"error": f"AOI '{name}' not found."}
    return {
        "deleted": name.strip(),
        "source": "aoi-delete",
        "timestamp": _utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# Nearby static infrastructure: pure, no I/O, config datasets only
# ---------------------------------------------------------------------------


def _nearby_points(
    items: list[dict],
    lat: float,
    lon: float,
    radius_km: float,
    extra_keys: tuple[str, ...] = (),
) -> list[dict]:
    out = []
    for item in items:
        dist = _distance_or_none(lat, lon, item.get("lat"), item.get("lon"))
        if dist is None or dist > radius_km:
            continue
        entry = {"name": item.get("name"), "distance_km": round(dist, 1)}
        for key in extra_keys:
            entry[key] = item.get(key)
        out.append(entry)
    out.sort(key=lambda e: e["distance_km"])
    return out


def nearby_bases(lat: float, lon: float, radius_km: float) -> list[dict]:
    from ..config.geospatial import MILITARY_BASES

    return _nearby_points(
        MILITARY_BASES, lat, lon, radius_km, extra_keys=("country", "operator", "type")
    )


def nearby_ports(lat: float, lon: float, radius_km: float) -> list[dict]:
    from ..config.geospatial import STRATEGIC_PORTS

    return _nearby_points(
        STRATEGIC_PORTS, lat, lon, radius_km, extra_keys=("country", "type")
    )


def nearby_nuclear(lat: float, lon: float, radius_km: float) -> list[dict]:
    from ..config.geospatial import NUCLEAR_FACILITIES

    return _nearby_points(
        NUCLEAR_FACILITIES,
        lat,
        lon,
        radius_km,
        extra_keys=("country", "type", "status"),
    )


def nearby_datacenters(lat: float, lon: float, radius_km: float) -> list[dict]:
    from ..config.datacenters import AI_DATACENTERS

    return _nearby_points(AI_DATACENTERS, lat, lon, radius_km, extra_keys=("country",))


def nearby_spaceports(lat: float, lon: float, radius_km: float) -> list[dict]:
    from ..config.spaceports import SPACEPORTS

    return _nearby_points(
        SPACEPORTS, lat, lon, radius_km, extra_keys=("country", "status")
    )


def nearby_pipelines(lat: float, lon: float, radius_km: float) -> list[dict]:
    """Pipelines are line features; proximity is approximated from each
    pipeline's two published endpoints (``lat_start``/``lon_start``,
    ``lat_end``/``lon_end``); the config dataset carries no intermediate
    waypoints. A pipeline that passes through the AOI without either
    endpoint nearby is missed by this approximation; documented here
    rather than silently wrong."""
    from ..config.geospatial import PIPELINES

    out = []
    for p in PIPELINES:
        d_start = _distance_or_none(lat, lon, p.get("lat_start"), p.get("lon_start"))
        d_end = _distance_or_none(lat, lon, p.get("lat_end"), p.get("lon_end"))
        candidates = [d for d in (d_start, d_end) if d is not None]
        if not candidates:
            continue
        dist = min(candidates)
        if dist <= radius_km:
            out.append(
                {
                    "name": p.get("name"),
                    "distance_km": round(dist, 1),
                    "route": p.get("route"),
                    "type": p.get("type"),
                    "status": p.get("status"),
                }
            )
    out.sort(key=lambda e: e["distance_km"])
    return out


def nearby_cables(lat: float, lon: float, radius_km: float) -> list[dict]:
    """Cables are multi-point routes; proximity is the closest published
    landing point, not the undersea path between landing points."""
    from ..config.cables import UNDERSEA_CABLES

    out = []
    for cable in UNDERSEA_CABLES:
        best_dist: float | None = None
        best_landing: str | None = None
        for lp in cable.get("landing_points", []):
            dist = _distance_or_none(lat, lon, lp.get("lat"), lp.get("lon"))
            if dist is not None and (best_dist is None or dist < best_dist):
                best_dist = dist
                best_landing = lp.get("name")
        if best_dist is not None and best_dist <= radius_km:
            out.append(
                {
                    "name": cable.get("name"),
                    "distance_km": round(best_dist, 1),
                    "nearest_landing_point": best_landing,
                    "status": cable.get("status"),
                }
            )
    out.sort(key=lambda e: e["distance_km"])
    return out


def nearby_infrastructure(
    lat: float, lon: float, radius_km: float
) -> dict[str, list[dict]]:
    """All seven static infrastructure categories near an AOI, each item
    carrying ``distance_km``. Pure: no I/O, static config datasets only."""
    return {
        "military_bases": nearby_bases(lat, lon, radius_km),
        "ports": nearby_ports(lat, lon, radius_km),
        "pipelines": nearby_pipelines(lat, lon, radius_km),
        "nuclear_facilities": nearby_nuclear(lat, lon, radius_km),
        "undersea_cables": nearby_cables(lat, lon, radius_km),
        "datacenters": nearby_datacenters(lat, lon, radius_km),
        "spaceports": nearby_spaceports(lat, lon, radius_km),
    }


_INFRA_LABELS = {
    "military_bases": "Military Bases",
    "ports": "Ports",
    "pipelines": "Pipelines",
    "nuclear_facilities": "Nuclear Facilities",
    "undersea_cables": "Undersea Cables",
    "datacenters": "Datacenters",
    "spaceports": "Spaceports",
}


# ---------------------------------------------------------------------------
# Wildfires: region-mapping (FIRMS has no point+radius query)
# ---------------------------------------------------------------------------


def _overlapping_wildfire_regions(
    lat: float, lon: float, radius_km: float
) -> list[str]:
    """Which of ``sources/wildfire.py``'s ``REGIONS`` continental bboxes
    the AOI's bounding box overlaps. FIRMS has no point+radius query, and
    ``fetch_wildfires`` exposes only these 9 continental regions, so an
    AOI is "region-mappable" whenever its box intersects at least one of
    them: true for all populated land; an AOI in open ocean far from any
    region is the honest gap."""
    from ..sources.wildfire import REGIONS

    dlat = radius_km / _KM_PER_DEGREE_LAT
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    dlon = radius_km / (_KM_PER_DEGREE_LAT * cos_lat)
    a_west, a_south, a_east, a_north = lon - dlon, lat - dlat, lon + dlon, lat + dlat

    overlapping = []
    for region_name, bbox in REGIONS.items():
        west, south, east, north = (float(x) for x in bbox.split(","))
        if a_west <= east and a_east >= west and a_south <= north and a_north >= south:
            overlapping.append(region_name)
    return overlapping


async def _safe_fetch(coro, label: str) -> dict:
    try:
        result = await coro
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        logger.warning("AOI brief: %s failed: %s", label, exc)
        return {"error": str(exc)}


async def _fetch_wildfires_for_aoi(fetcher, wildfire_regions: list[str]) -> dict:
    from ..sources import wildfire

    if not wildfire_regions:
        return {"error": "AOI does not overlap any FIRMS coverage region"}

    results = await asyncio.gather(
        *[wildfire.fetch_wildfires(fetcher, region=r) for r in wildfire_regions]
    )
    clusters: list[dict] = []
    errors: list[str] = []
    for res in results:
        if not isinstance(res, dict):
            continue
        if res.get("error"):
            errors.append(res["error"])
            continue
        for region_data in res.get("fires_by_region", {}).values():
            clusters.extend(region_data.get("top_clusters", []))
    if not clusters and errors:
        return {"error": "; ".join(sorted(set(errors)))}
    return {"clusters": clusters}


# ---------------------------------------------------------------------------
# intel_aoi_brief
# ---------------------------------------------------------------------------


async def fetch_aoi_brief(fetcher, store: AOIStore, name: Any) -> dict:
    """Compose a cited brief for a user-defined AOI: earthquakes, military
    flights (bbox-derived), wildfires (region-mapped), ACLED conflict
    events, sampled aviation traffic, nearby static infrastructure, and
    news headline mentions of the AOI name. Every listed item carries a
    ``[n]`` citation; ``data_gaps`` names every domain that could not be
    scoped to the AOI rather than silently omitting it.
    """
    if not isinstance(name, str) or not name.strip():
        return {"error": "name must be a non-empty string."}

    aoi = store.get(name)
    if aoi is None:
        return {
            "error": f"AOI '{name}' not found. Use intel_aoi_list to see defined areas."
        }

    from ..sources import aviation, conflict, military, news, seismology

    lat, lon, radius_km = aoi["lat"], aoi["lon"], aoi["radius_km"]
    aoi_name = aoi["name"]
    bbox = bbox_from_radius_km(lat, lon, radius_km)
    wildfire_regions = _overlapping_wildfire_regions(lat, lon, radius_km)

    (
        eq_result,
        mil_result,
        conflict_result,
        wildfire_result,
        aviation_result,
        news_result,
    ) = await asyncio.gather(
        _safe_fetch(seismology.fetch_earthquakes(fetcher, hours=72), "earthquakes"),
        _safe_fetch(
            military.fetch_military_flights(fetcher, bbox=bbox), "military_flights"
        ),
        _safe_fetch(conflict.fetch_acled_events(fetcher, days=7), "acled_events"),
        _safe_fetch(_fetch_wildfires_for_aoi(fetcher, wildfire_regions), "wildfires"),
        _safe_fetch(aviation.fetch_domestic_flights(fetcher), "domestic_flights"),
        _safe_fetch(
            news.fetch_gdelt_search(fetcher, query=aoi_name, mode="artlist", limit=10),
            "news",
        ),
    )

    sources: list[dict] = []
    citations: dict[str, list[int]] = {}
    data_gaps: list[str] = []
    counts: dict[str, int] = {}
    sections: dict[str, list[str]] = {}

    def _line(domain: str, text: str) -> None:
        sections.setdefault(domain, []).append(text)

    # Earthquakes ------------------------------------------------------
    if isinstance(eq_result, dict) and eq_result.get("error"):
        data_gaps.append(f"Earthquakes: {eq_result['error']}")
        counts["earthquakes"] = 0
    else:
        eq_events = (
            eq_result.get("earthquakes", []) if isinstance(eq_result, dict) else []
        )
        eq_in_range = filter_by_radius(
            eq_events, lat, lon, radius_km, "latitude", "longitude"
        )
        counts["earthquakes"] = len(eq_in_range)
        for eq in eq_in_range:
            n = _add_source(
                sources,
                "earthquakes",
                f"M{eq.get('magnitude')} earthquake, {eq.get('place') or 'unknown location'} "
                f"({eq['distance_km']} km from {aoi_name})",
                url=eq.get("url"),
                timestamp=eq.get("time"),
            )
            _cite(citations, "earthquakes", n)
            _line(
                "earthquakes",
                f"- [{n}] M{eq.get('magnitude')} {eq.get('place')} ({eq['distance_km']} km)",
            )

    # Military flights ---------------------------------------------------
    if isinstance(mil_result, dict) and mil_result.get("error"):
        data_gaps.append(f"Military flights: {mil_result['error']}")
        counts["military_flights"] = 0
    else:
        mil_aircraft = (
            mil_result.get("aircraft", []) if isinstance(mil_result, dict) else []
        )
        mil_in_range = filter_by_radius(
            mil_aircraft, lat, lon, radius_km, "latitude", "longitude"
        )
        counts["military_flights"] = len(mil_in_range)
        if mil_in_range:
            n = _add_source(
                sources,
                "military_flights",
                f"{len(mil_in_range)} military aircraft within {radius_km} km of {aoi_name}",
            )
            _cite(citations, "military_flights", n)
            for ac in mil_in_range[:10]:
                _line(
                    "military_flights",
                    f"- [{n}] {ac.get('callsign') or ac.get('icao24')} "
                    f"({ac.get('origin_country') or 'unknown origin'}, {ac['distance_km']} km)",
                )

    # Conflict (ACLED) ----------------------------------------------------
    if isinstance(conflict_result, dict) and conflict_result.get("error"):
        data_gaps.append(f"Conflict events: {conflict_result['error']}")
        counts["conflict_events"] = 0
    else:
        conflict_events = (
            conflict_result.get("events", [])
            if isinstance(conflict_result, dict)
            else []
        )
        conflict_in_range = filter_by_radius(
            conflict_events, lat, lon, radius_km, "latitude", "longitude"
        )
        counts["conflict_events"] = len(conflict_in_range)
        for ev in conflict_in_range[:10]:
            loc = (
                ev.get("location")
                or ev.get("admin1")
                or ev.get("country")
                or "unspecified location"
            )
            n = _add_source(
                sources,
                "conflict_events",
                f"{ev.get('event_type') or 'conflict event'}, {loc} "
                f"({ev['distance_km']} km from {aoi_name})",
                timestamp=ev.get("event_date"),
            )
            _cite(citations, "conflict_events", n)
            _line(
                "conflict_events",
                f"- [{n}] {ev.get('event_type')}, {loc} ({ev['distance_km']} km)",
            )

    # Wildfires ------------------------------------------------------------
    if isinstance(wildfire_result, dict) and wildfire_result.get("error"):
        data_gaps.append(f"Wildfires: {wildfire_result['error']}")
        counts["wildfires"] = 0
    else:
        clusters = (
            wildfire_result.get("clusters", [])
            if isinstance(wildfire_result, dict)
            else []
        )
        fire_in_range = filter_by_radius(clusters, lat, lon, radius_km, "lat", "lon")
        counts["wildfires"] = len(fire_in_range)
        for fc in fire_in_range:
            n = _add_source(
                sources,
                "wildfires",
                f"{fc.get('fire_count')} fire detections ({fc['distance_km']} km from {aoi_name})",
            )
            _cite(citations, "wildfires", n)
            _line(
                "wildfires",
                f"- [{n}] {fc.get('fire_count')} detections, max FRP {fc.get('max_frp')} ({fc['distance_km']} km)",
            )

    # Aviation (sampled) ---------------------------------------------------
    if isinstance(aviation_result, dict) and aviation_result.get("error"):
        data_gaps.append(f"Aviation: {aviation_result['error']}")
        counts["aviation"] = 0
    else:
        sampled = (
            aviation_result.get("sampled", [])
            if isinstance(aviation_result, dict)
            else []
        )
        aviation_in_range = filter_by_radius(sampled, lat, lon, radius_km, "lat", "lon")
        counts["aviation"] = len(aviation_in_range)
        if aviation_in_range:
            n = _add_source(
                sources,
                "aviation",
                f"{len(aviation_in_range)} sampled aircraft within {radius_km} km of {aoi_name} "
                "(1-in-10 global sample, not exhaustive)",
            )
            _cite(citations, "aviation", n)
            _line(
                "aviation",
                f"- [{n}] {len(aviation_in_range)} sampled aircraft observed",
            )

    # News headline mentions -----------------------------------------------
    if isinstance(news_result, dict) and news_result.get("error"):
        data_gaps.append(f"News: {news_result['error']}")
        counts["news"] = 0
        articles: list = []
    else:
        articles = (
            news_result.get("articles", []) if isinstance(news_result, dict) else []
        )
        counts["news"] = len(articles)
    for art in articles[:10]:
        title = art.get("title")
        if not title:
            continue
        n = _add_source(
            sources, "news", title, url=art.get("url"), timestamp=art.get("seendate")
        )
        _cite(citations, "news", n)
        _line("news", f"- [{n}] {title} ({art.get('domain') or 'unknown source'})")

    # Nearby static infrastructure -------------------------------------
    infra = nearby_infrastructure(lat, lon, radius_km)
    for category, items in infra.items():
        counts[category] = len(items)
        for item in items:
            n = _add_source(
                sources,
                category,
                f"{item['name']} ({item['distance_km']} km from {aoi_name})",
            )
            _cite(citations, category, n)
            _line(category, f"- [{n}] {item['name']} ({item['distance_km']} km)")

    # --- Markdown ---------------------------------------------------------
    md_parts = [
        f"# AOI Brief: {aoi_name}",
        f"Center: {lat}, {lon} (radius {radius_km} km)",
        "",
    ]
    section_order = [
        ("earthquakes", "Earthquakes"),
        ("military_flights", "Military Flights"),
        ("conflict_events", "Conflict Events (ACLED)"),
        ("wildfires", "Wildfires"),
        ("aviation", "Aviation (sampled)"),
        ("news", "News Headline Mentions"),
        *[(k, v) for k, v in _INFRA_LABELS.items()],
    ]
    for domain, label in section_order:
        lines = sections.get(domain)
        md_parts.append(f"## {label}")
        md_parts.append("\n".join(lines) if lines else "_None observed in range._")
        md_parts.append("")

    if data_gaps:
        md_parts.append("## Data Gaps")
        md_parts.extend(f"- {gap}" for gap in data_gaps)

    markdown = "\n".join(md_parts)
    cited = _has_valid_citation(markdown, len(sources))

    return {
        "aoi": {"name": aoi_name, "lat": lat, "lon": lon, "radius_km": radius_km},
        "markdown": markdown,
        "counts": counts,
        "sources": sources,
        "cited": cited,
        "data_gaps": data_gaps,
        "source": "aoi-brief",
        "timestamp": _utc_now_iso(),
    }


# ---------------------------------------------------------------------------
# intel_aoi_escalation (optional, reuses analysis/escalation.py unmodified)
# ---------------------------------------------------------------------------


async def fetch_aoi_escalation(fetcher, store: AOIStore, name: Any) -> dict:
    """Run the existing hotspot escalation scoring (``score_hotspot`` in
    ``analysis/escalation.py``, unmodified) on a user-defined AOI instead
    of only the 22 built-in intel hotspots. Gathers military and conflict
    signals scoped to the AOI's own radius (via haversine), rather than
    the fixed 2-degree window ``fetch_hotspot_escalation`` uses for the
    built-ins."""
    if not isinstance(name, str) or not name.strip():
        return {"error": "name must be a non-empty string."}

    aoi = store.get(name)
    if aoi is None:
        return {
            "error": f"AOI '{name}' not found. Use intel_aoi_list to see defined areas."
        }

    from ..sources import conflict as conflict_mod
    from ..sources import military as mil_mod

    lat, lon, radius_km = aoi["lat"], aoi["lon"], aoi["radius_km"]
    aoi_name = aoi["name"]
    bbox = bbox_from_radius_km(lat, lon, radius_km)

    acled_result, mil_result = await asyncio.gather(
        _safe_fetch(conflict_mod.fetch_acled_events(fetcher, days=7), "acled_events"),
        _safe_fetch(
            mil_mod.fetch_military_flights(fetcher, bbox=bbox), "military_flights"
        ),
    )

    data_gaps: list[str] = []
    conflict_count = fatalities = protests = 0
    if isinstance(acled_result, dict) and acled_result.get("error"):
        data_gaps.append(f"Conflict events: {acled_result['error']}")
    else:
        events = filter_by_radius(
            acled_result.get("events", []) if isinstance(acled_result, dict) else [],
            lat,
            lon,
            radius_km,
            "latitude",
            "longitude",
        )
        for ev in events:
            if "protest" in (ev.get("event_type") or "").lower():
                protests += 1
            else:
                conflict_count += 1
            fatalities += ev.get("fatalities") or 0

    military_count = 0
    if isinstance(mil_result, dict) and mil_result.get("error"):
        data_gaps.append(f"Military flights: {mil_result['error']}")
    else:
        aircraft = filter_by_radius(
            mil_result.get("aircraft", []) if isinstance(mil_result, dict) else [],
            lat,
            lon,
            radius_km,
            "latitude",
            "longitude",
        )
        military_count = len(aircraft)

    hotspot_config = {
        "lat": lat,
        "lon": lon,
        "baseline_escalation": 0,
        "associated_countries": [],
    }
    scored = score_hotspot(
        hotspot_config,
        news_mentions=None,
        military_count=military_count,
        conflict_events=conflict_count,
        convergence_score=None,
        fatalities=fatalities,
        protests=protests,
    )

    return {
        "aoi": {"name": aoi_name, "lat": lat, "lon": lon, "radius_km": radius_km},
        "unavailable_components": ["news", "convergence"],
        "data_gaps": data_gaps,
        "source": "aoi-escalation",
        "timestamp": _utc_now_iso(),
        **scored,
    }
