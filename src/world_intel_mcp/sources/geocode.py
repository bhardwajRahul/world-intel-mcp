"""Reverse geocoding via OpenStreetMap Nominatim.

Turns an AOI's coordinates into the names of the place it sits in, so
area news can be searched by where the area *is* rather than by what
the user happened to call it. An AOI named "Home" or "PGH Square"
previously matched those strings in GDELT and returned unrelated
articles from anywhere in the world.

No API key. Nominatim's usage policy caps this at one request per
second and requires an identifying User-Agent with a contact address,
both of which are honored here; place names do not move, so results
are cached for 30 days.
"""

from datetime import datetime, timezone
from typing import Any

from ..fetcher import Fetcher

_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
_SOURCE = "nominatim"

# A place name does not change; the only reason to refetch is a new AOI.
_CACHE_TTL = 60 * 60 * 24 * 30

# Nominatim requires an identifying UA with a way to make contact.
_USER_AGENT = "world-intel-mcp/0.9 (+https://github.com/marc-shade/world-intel-mcp)"

# Settlement keys in Nominatim's address object, most specific first.
_SETTLEMENT_KEYS = ("city", "town", "village", "hamlet", "municipality", "suburb")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def fetch_place_context(fetcher: Fetcher, lat: Any, lon: Any) -> dict:
    """Resolve coordinates to the names of the place containing them.

    Returns a dict with ``place`` (the settlement, or None where
    nothing is named — mid-ocean, empty desert), ``county``, ``state``,
    ``country``/``country_code``, ``display_name``, and ``terms``: the
    place names most specific first, suitable for a news query.

    A point with no named place is a successful lookup reporting
    ``place: None``, deliberately distinct from ``{"error": ...}`` for
    an upstream failure — a caller must be able to tell "nowhere is
    named here" from "the geocoder is down", because only the second
    is worth retrying or reporting as an outage.
    """
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return {
            "error": f"Invalid coordinates: lat={lat!r}, lon={lon!r}",
            "place": None,
        }
    if not (-90.0 <= lat_f <= 90.0) or not (-180.0 <= lon_f <= 180.0):
        return {
            "error": (
                f"Coordinates out of range: lat={lat_f} (-90..90), "
                f"lon={lon_f} (-180..180)"
            ),
            "place": None,
        }

    data = await fetcher.get_json(
        _REVERSE_URL,
        params={
            "lat": f"{lat_f:.5f}",
            "lon": f"{lon_f:.5f}",
            "format": "jsonv2",
            # City/county granularity: a street address would make a
            # useless news query.
            "zoom": 10,
            "addressdetails": 1,
        },
        source=_SOURCE,
        cache_key=f"geocode:reverse:{lat_f:.4f}:{lon_f:.4f}",
        cache_ttl=_CACHE_TTL,
        headers={"User-Agent": _USER_AGENT},
    )

    if data is None:
        # get_json exhausted its retries and found no stale entry. The
        # specific cause (rate limit, 5xx, timeout, DNS) is in the
        # fetcher's log; naming a parse problem here would send a
        # reader to the wrong place, which a live 429 did on
        # 2026-09-02.
        return {
            "error": (
                "Reverse geocoding unavailable: the Nominatim request failed "
                "(rate limit, upstream error, or network). See fetcher logs "
                "for the specific failure."
            ),
            "place": None,
        }
    if not isinstance(data, dict):
        return {
            "error": (
                f"Nominatim returned an unexpected response shape "
                f"({type(data).__name__}, expected object)."
            ),
            "place": None,
        }
    if data.get("error"):
        # Nominatim's own "unable to geocode" — a real answer about the
        # point, not a transport failure.
        return {
            "place": None,
            "county": None,
            "state": None,
            "country": None,
            "country_code": None,
            "display_name": None,
            "terms": [],
            "note": f"No named place at {lat_f}, {lon_f} (open water or unnamed area).",
            "source": "nominatim-reverse",
            "timestamp": _utc_now_iso(),
        }

    address = data.get("address") or {}
    place = next(
        (address[k] for k in _SETTLEMENT_KEYS if address.get(k)),
        None,
    )
    county = address.get("county")
    state = address.get("state")

    # Most specific first: a news query leads with the settlement and
    # widens only as far as the county, since a state-wide term buys
    # noise rather than locality.
    terms = [t for t in (place, county) if t]

    return {
        "place": place,
        "county": county,
        "state": state,
        "country": address.get("country"),
        "country_code": address.get("country_code"),
        "display_name": data.get("display_name"),
        "terms": terms,
        "source": "nominatim-reverse",
        "timestamp": _utc_now_iso(),
    }
