"""BGP routing status source for world-intel-mcp, via RIPEstat.

Per-resource routing health from the RIPE NCC's RIPEstat Data API
(stat.ripe.net). No API key required. Scope honesty: RIPEstat data
calls are resource-parameterized — you ask about ONE prefix or ASN.
This module is therefore a per-resource status check (visibility in
the RIS peer mesh, announced state, observed origins, RPKI validity),
NOT global hijack/anomaly detection; RIPEstat offers no target-free
"current incidents" feed usable here.

Shape facts, verified live 2026-09-01 against AS3333 and 193.0.0.0/21:
routing-status accepts both ASNs and prefixes but returns different
data keys per type (ASN: announced_space + observed_neighbours;
prefix: origins + less/more_specifics); origins arrive as ints;
visibility is per address family with ris_peers_seeing/total_ris_peers
counts; rpki-validation requires BOTH an origin ASN and a prefix and
returns status valid/invalid/unknown with the matching ROAs. For a
prefix query the RPKI check here validates each origin actually
observed in BGP; for an ASN query RPKI is skipped (validating every
announced prefix would be an unbounded fan-out) and marked so.
"""

import logging
import re
from datetime import datetime, timezone

from ..fetcher import Fetcher

logger = logging.getLogger("world-intel-mcp.sources.bgp")

_ROUTING_STATUS_URL = "https://stat.ripe.net/data/routing-status/data.json"
_RPKI_VALIDATION_URL = "https://stat.ripe.net/data/rpki-validation/data.json"

# Routing state moves in minutes; RIPEstat itself caches upstream.
_CACHE_TTL = 300
# ROAs change on hours-to-days timescales.
_RPKI_CACHE_TTL = 900

# At most this many observed origins get an RPKI check (MOAS prefixes
# rarely have more; keeps the fan-out bounded).
_MAX_RPKI_ORIGINS = 3

_ASN_RE = re.compile(r"^(?:AS)?(\d+)$", re.IGNORECASE)


async def fetch_bgp_status(fetcher: Fetcher, resource: str) -> dict:
    """Fetch BGP routing status for one prefix or ASN from RIPEstat.

    Args:
        fetcher: Shared HTTP fetcher with caching and circuit breaking.
        resource: An ASN ("AS3333" or "3333") or a CIDR prefix
            ("193.0.0.0/21", IPv6 accepted). Bare IP addresses are not
            accepted — pass the covering prefix.

    Returns:
        For an ASN: visibility per address family, announced space,
        observed neighbour count, first/last seen. For a prefix:
        visibility, observed origin ASNs with route objects,
        less/more specific counts, and per-origin RPKI validation
        (valid/invalid/unknown). Both carry resource, resource_type,
        source, and timestamp.
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    resource = resource.strip()

    asn_match = _ASN_RE.match(resource)
    is_prefix = "/" in resource
    if not asn_match and not is_prefix:
        return {
            "error": (
                f"Invalid resource: {resource!r}. Pass an ASN "
                "('AS3333' or '3333') or a CIDR prefix ('193.0.0.0/21')."
            ),
            "reason": "invalid_resource",
            "resource": resource,
            "source": "ripestat",
            "timestamp": timestamp,
        }

    query_resource = asn_match.group(1) if asn_match else resource
    resource_type = "asn" if asn_match else "prefix"

    data = await fetcher.get_json(
        url=_ROUTING_STATUS_URL,
        source="ripestat",
        cache_key=f"bgp:routing-status:{query_resource}",
        cache_ttl=_CACHE_TTL,
        params={"resource": query_resource},
    )

    payload = data.get("data") if isinstance(data, dict) else None
    if not payload:
        logger.warning("RIPEstat routing-status returned no data for %s", resource)
        return {
            "error": (
                f"RIPEstat routing-status unavailable for {resource} "
                "(no live or cached data)"
            ),
            "degraded": True,
            "reason": "ripestat_fetch_failed",
            "resource": resource,
            "resource_type": resource_type,
            "source": "ripestat",
            "timestamp": timestamp,
        }

    visibility = _extract_visibility(payload.get("visibility") or {})
    result: dict = {
        "resource": resource,
        "resource_type": resource_type,
        "visibility": visibility,
        "visible": any(
            (fam.get("ris_peers_seeing") or 0) > 0 for fam in visibility.values()
        ),
        "first_seen": payload.get("first_seen"),
        "last_seen": payload.get("last_seen"),
        "source": "ripestat",
        "timestamp": timestamp,
    }

    if resource_type == "asn":
        result["announced_space"] = payload.get("announced_space")
        result["observed_neighbours"] = payload.get("observed_neighbours")
        result["rpki"] = []
        result["rpki_note"] = (
            "RPKI validation needs a specific prefix; query a prefix "
            "resource to validate it against its observed origins."
        )
        return result

    origins = [
        {
            "origin": str(o.get("origin")),
            "route_objects": o.get("route_objects") or [],
        }
        for o in payload.get("origins") or []
        if o.get("origin") is not None
    ]
    result["origins"] = origins
    result["less_specifics_count"] = len(payload.get("less_specifics") or [])
    result["more_specifics_count"] = len(payload.get("more_specifics") or [])
    result["rpki"] = [
        await _validate_origin(fetcher, origin["origin"], resource)
        for origin in origins[:_MAX_RPKI_ORIGINS]
    ]
    result["rpki_status"] = _summarize_rpki(result["rpki"])
    return result


async def _validate_origin(fetcher: Fetcher, origin: str, prefix: str) -> dict:
    """RPKI-validate one origin/prefix pair via RIPEstat.

    A validation fetch failure is reported inline (status
    "fetch_failed") rather than degrading the whole result — the
    routing-status half is still good data.
    """
    data = await fetcher.get_json(
        url=_RPKI_VALIDATION_URL,
        source="ripestat",
        cache_key=f"bgp:rpki:{origin}:{prefix}",
        cache_ttl=_RPKI_CACHE_TTL,
        params={"resource": origin, "prefix": prefix},
    )
    payload = data.get("data") if isinstance(data, dict) else None
    if not payload:
        logger.warning(
            "RIPEstat rpki-validation unavailable for %s / %s", origin, prefix
        )
        return {"origin": origin, "status": "fetch_failed", "roa_count": 0}
    return {
        "origin": origin,
        "status": payload.get("status"),
        "roa_count": len(payload.get("validating_roas") or []),
    }


def _extract_visibility(visibility: dict) -> dict:
    """Reduce RIPEstat's visibility block to seeing/total per family."""
    out: dict[str, dict] = {}
    for family in ("v4", "v6"):
        fam = visibility.get(family)
        if isinstance(fam, dict):
            out[family] = {
                "ris_peers_seeing": fam.get("ris_peers_seeing"),
                "total_ris_peers": fam.get("total_ris_peers"),
            }
    return out


def _summarize_rpki(checks: list[dict]) -> str:
    """Collapse per-origin RPKI checks into one summary status.

    Any invalid origin makes the whole prefix "invalid" (that is the
    hijack-shaped signal); all-valid is "valid"; anything else —
    no ROAs, fetch failures, no observed origins — is "unknown".
    """
    statuses = {c.get("status") for c in checks}
    if "invalid" in statuses:
        return "invalid"
    if statuses and statuses <= {"valid"}:
        return "valid"
    return "unknown"
