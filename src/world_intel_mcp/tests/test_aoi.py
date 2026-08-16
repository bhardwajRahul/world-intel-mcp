"""Tests for analysis/aoi.py and the intel_aoi_* tool family (issue #16).

Persistence tests exercise ``AOIStore`` directly against a ``tmp_path``
SQLite file (same pattern as ``test_cache.py``'s ``cache`` fixture).
Composition tests (``fetch_aoi_brief`` / ``fetch_aoi_escalation``) mock at
the source-function boundary via monkeypatch, matching the pattern
``test_daily_digest.py`` established for this exact class of function:
aoi.py composes existing ``sources/*.py`` fetch functions rather than
making HTTP calls itself, so there is no network edge for respx to sit at.
"""

from pathlib import Path

import pytest

from world_intel_mcp.analysis import aoi
from world_intel_mcp.analysis.aoi import AOIAlreadyExists, AOIStore
from world_intel_mcp.sources import (
    aviation,
    conflict,
    military,
    news,
    seismology,
    wildfire,
)

_SERVER_PY = Path(__file__).resolve().parents[1] / "server.py"

# Pittsburgh, matching the README worked example (issue #16).
_PGH_LAT = 40.4406
_PGH_LON = -79.9959
_PGH_RADIUS_KM = 50.0

# ~7 km from Pittsburgh, inside a 50 km radius.
_NEAR_LAT, _NEAR_LON = 40.50, -80.00
# ~330 km from Pittsburgh (Detroit area), outside a 50 km radius.
_FAR_LAT, _FAR_LON = 42.33, -83.05


@pytest.fixture
def store(tmp_path: Path) -> AOIStore:
    s = AOIStore(tmp_path / "test_aoi_cache.db")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------


def test_haversine_km_zero_distance() -> None:
    assert aoi.haversine_km(40.44, -79.99, 40.44, -79.99) == pytest.approx(
        0.0, abs=1e-6
    )


def test_haversine_km_known_pair() -> None:
    # NYC (40.7128, -74.0060) to LA (34.0522, -118.2437) is ~3936 km.
    dist = aoi.haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
    assert dist == pytest.approx(3936, rel=0.01)


def test_bbox_from_radius_km_widens_at_low_latitude_and_narrows_near_pole() -> None:
    equator_box = aoi.bbox_from_radius_km(0.0, 0.0, 100.0)
    polar_box = aoi.bbox_from_radius_km(85.0, 0.0, 100.0)
    eq_lomin, eq_lomax = (
        float(equator_box.split(",")[1]),
        float(equator_box.split(",")[3]),
    )
    pl_lomin, pl_lomax = float(polar_box.split(",")[1]), float(polar_box.split(",")[3])
    # Same radius spans far more longitude near the pole than at the equator.
    assert (pl_lomax - pl_lomin) > (eq_lomax - eq_lomin)


def test_bbox_from_radius_km_clamps_to_valid_ranges() -> None:
    box = aoi.bbox_from_radius_km(89.5, 179.5, 2000.0)
    lamin, lomin, lamax, lomax = (float(x) for x in box.split(","))
    assert -90.0 <= lamin <= lamax <= 90.0
    assert -180.0 <= lomin <= lomax <= 180.0


def test_filter_by_radius_includes_near_excludes_far() -> None:
    """The load-bearing pair: a fence that does not exclude is not a fence."""
    items = [
        {"latitude": _NEAR_LAT, "longitude": _NEAR_LON, "id": "near"},
        {"latitude": _FAR_LAT, "longitude": _FAR_LON, "id": "far"},
    ]
    result = aoi.filter_by_radius(items, _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    ids = [r["id"] for r in result]
    assert "near" in ids
    assert "far" not in ids
    assert result[0]["distance_km"] < _PGH_RADIUS_KM


def test_filter_by_radius_drops_items_missing_coordinates() -> None:
    items = [{"latitude": None, "longitude": None, "id": "no-coords"}]
    result = aoi.filter_by_radius(items, _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    assert result == []


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_aoi_params_accepts_valid_input() -> None:
    assert (
        aoi.validate_aoi_params("Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
        is None
    )


@pytest.mark.parametrize(
    "name,lat,lon,radius_km",
    [
        ("", 40.0, -80.0, 50.0),
        ("   ", 40.0, -80.0, 50.0),
        ("X", 91.0, -80.0, 50.0),
        ("X", -91.0, -80.0, 50.0),
        ("X", 40.0, 181.0, 50.0),
        ("X", 40.0, -181.0, 50.0),
        ("X", 40.0, -80.0, 0.5),
        ("X", 40.0, -80.0, 2001.0),
        ("X", "not-a-number", -80.0, 50.0),
        ("X", 40.0, None, 50.0),
        (123, 40.0, -80.0, 50.0),
    ],
)
def test_validate_aoi_params_rejects_invalid_input(name, lat, lon, radius_km) -> None:
    assert aoi.validate_aoi_params(name, lat, lon, radius_km) is not None


# ---------------------------------------------------------------------------
# AOIStore persistence
# ---------------------------------------------------------------------------


def test_define_and_get_round_trip(store: AOIStore) -> None:
    defined = store.define("Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    assert defined["name"] == "Pittsburgh"
    fetched = store.get("Pittsburgh")
    assert fetched["lat"] == _PGH_LAT
    assert fetched["lon"] == _PGH_LON
    assert fetched["radius_km"] == _PGH_RADIUS_KM


def test_get_is_case_insensitive(store: AOIStore) -> None:
    store.define("Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    assert store.get("pittsburgh") is not None
    assert store.get("PITTSBURGH") is not None


def test_get_missing_returns_none(store: AOIStore) -> None:
    assert store.get("Nowhere") is None


def test_list_all_sorted_by_name(store: AOIStore) -> None:
    store.define("Zurich", 47.37, 8.54, 25.0)
    store.define("Austin", 30.27, -97.74, 40.0)
    names = [a["name"] for a in store.list_all()]
    assert names == ["Austin", "Zurich"]


def test_delete_round_trip(store: AOIStore) -> None:
    store.define("Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    assert store.delete("Pittsburgh") is True
    assert store.get("Pittsburgh") is None


def test_delete_nonexistent_returns_false(store: AOIStore) -> None:
    assert store.delete("Nowhere") is False


def test_define_duplicate_raises_with_existing_echoed(store: AOIStore) -> None:
    store.define("Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    with pytest.raises(AOIAlreadyExists) as exc_info:
        store.define("pittsburgh", 0.0, 0.0, 10.0)
    assert exc_info.value.existing["name"] == "Pittsburgh"
    assert exc_info.value.existing["lat"] == _PGH_LAT


# ---------------------------------------------------------------------------
# Tool-facing define / list / delete
# ---------------------------------------------------------------------------


def test_define_aoi_success(store: AOIStore) -> None:
    result = aoi.define_aoi(store, "Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    assert "error" not in result
    assert result["aoi"]["name"] == "Pittsburgh"


def test_define_aoi_validation_rejection_does_not_touch_store(store: AOIStore) -> None:
    result = aoi.define_aoi(store, "Bad", 999.0, -80.0, 50.0)
    assert "error" in result
    assert store.get("Bad") is None


def test_define_aoi_duplicate_echoes_existing_politely(store: AOIStore) -> None:
    aoi.define_aoi(store, "Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    result = aoi.define_aoi(store, "Pittsburgh", 0.0, 0.0, 10.0)
    assert "error" in result
    assert result["existing"]["lat"] == _PGH_LAT
    assert result["existing"]["radius_km"] == _PGH_RADIUS_KM


def test_list_aois_reports_count(store: AOIStore) -> None:
    aoi.define_aoi(store, "Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    aoi.define_aoi(store, "Austin", 30.27, -97.74, 40.0)
    result = aoi.list_aois(store)
    assert result["count"] == 2
    assert {a["name"] for a in result["aois"]} == {"Pittsburgh", "Austin"}


def test_delete_aoi_not_found(store: AOIStore) -> None:
    result = aoi.delete_aoi(store, "Nowhere")
    assert "error" in result


def test_delete_aoi_success(store: AOIStore) -> None:
    aoi.define_aoi(store, "Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    result = aoi.delete_aoi(store, "Pittsburgh")
    assert result["deleted"] == "Pittsburgh"


# ---------------------------------------------------------------------------
# Nearby static infrastructure (pure, real config datasets)
# ---------------------------------------------------------------------------


def test_nearby_bases_finds_norfolk_at_its_own_coordinates() -> None:
    # Norfolk Naval Station: lat 36.95, lon -76.33 (config/geospatial.py).
    result = aoi.nearby_bases(36.95, -76.33, 5.0)
    names = [b["name"] for b in result]
    assert "Norfolk Naval Station" in names


def test_nearby_bases_excludes_far_away_base() -> None:
    result = aoi.nearby_bases(_PGH_LAT, _PGH_LON, 5.0)
    assert result == []


def test_nearby_pipelines_matches_on_either_endpoint() -> None:
    # TAPS pipeline ends at Valdez (61.13, -146.35); a tight radius there
    # should match via the endpoint-proximity approximation.
    result = aoi.nearby_pipelines(61.13, -146.35, 5.0)
    names = [p["name"] for p in result]
    assert "Trans-Alaska (TAPS)" in names


def test_nearby_cables_matches_closest_landing_point() -> None:
    # MAREA lands at Bilbao, Spain and Virginia Beach, USA.
    result = aoi.nearby_cables(36.95, -76.0, 60.0)
    assert any(c["name"] == "MAREA" for c in result)


def test_nearby_infrastructure_has_all_seven_categories() -> None:
    result = aoi.nearby_infrastructure(_PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    assert set(result.keys()) == {
        "military_bases",
        "ports",
        "pipelines",
        "nuclear_facilities",
        "undersea_cables",
        "datacenters",
        "spaceports",
    }


# ---------------------------------------------------------------------------
# Wildfire region mapping
# ---------------------------------------------------------------------------


def test_overlapping_wildfire_regions_finds_north_america_for_pittsburgh() -> None:
    regions = aoi._overlapping_wildfire_regions(_PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    assert "north_america" in regions


# ---------------------------------------------------------------------------
# fetch_aoi_brief: composition, citations, data_gaps
# ---------------------------------------------------------------------------


async def _fake_earthquakes(fetcher, **kwargs):
    return {
        "earthquakes": [
            {
                "id": "near1",
                "magnitude": 3.2,
                "place": "near Pittsburgh",
                "time": "2026-08-16T01:00:00Z",
                "latitude": _NEAR_LAT,
                "longitude": _NEAR_LON,
                "url": "https://earthquake.usgs.gov/near1",
            },
            {
                "id": "far1",
                "magnitude": 5.0,
                "place": "near Detroit",
                "time": "2026-08-16T01:00:00Z",
                "latitude": _FAR_LAT,
                "longitude": _FAR_LON,
                "url": "https://earthquake.usgs.gov/far1",
            },
        ],
        "count": 2,
        "source": "usgs",
    }


async def _fake_military(fetcher, bbox=None):
    return {
        "aircraft": [
            {
                "icao24": "aaa111",
                "callsign": "RCH123",
                "origin_country": "United States",
                "latitude": _NEAR_LAT,
                "longitude": _NEAR_LON,
            },
            {
                "icao24": "bbb222",
                "callsign": "RCH999",
                "origin_country": "United States",
                "latitude": _FAR_LAT,
                "longitude": _FAR_LON,
            },
        ],
        "count": 2,
        "source": "adsb.lol",
    }


async def _fake_acled(fetcher, **kwargs):
    return {
        "events": [
            {
                "event_type": "Protests",
                "location": "Near Pittsburgh",
                "admin1": "Pennsylvania",
                "country": "United States",
                "event_date": "2026-08-15",
                "latitude": _NEAR_LAT,
                "longitude": _NEAR_LON,
                "fatalities": 0,
            },
            {
                "event_type": "Battles",
                "location": "Near Detroit",
                "admin1": "Michigan",
                "country": "United States",
                "event_date": "2026-08-15",
                "latitude": _FAR_LAT,
                "longitude": _FAR_LON,
                "fatalities": 2,
            },
        ],
        "count": 2,
        "source": "acled",
    }


async def _fake_wildfires(fetcher, region=None):
    return {
        "fires_by_region": {
            region or "north_america": {
                "count": 2,
                "top_clusters": [
                    {
                        "lat": _NEAR_LAT,
                        "lon": _NEAR_LON,
                        "fire_count": 4,
                        "max_frp": 12.5,
                    },
                    {
                        "lat": _FAR_LAT,
                        "lon": _FAR_LON,
                        "fire_count": 9,
                        "max_frp": 40.0,
                    },
                ],
            }
        },
        "total_fires": 2,
        "source": "nasa-firms",
    }


async def _fake_domestic_flights(fetcher):
    return {
        "total_aircraft": 2,
        "sampled": [
            {"lat": _NEAR_LAT, "lon": _NEAR_LON, "callsign": "UAL1", "origin": "USA"},
            {"lat": _FAR_LAT, "lon": _FAR_LON, "callsign": "UAL2", "origin": "USA"},
        ],
        "source": "opensky-domestic",
    }


async def _fake_gdelt(fetcher, **kwargs):
    return {
        "articles": [
            {
                "title": "Pittsburgh flooding warning issued",
                "url": "https://news.example/pgh",
                "seendate": "20260816T010000Z",
                "domain": "news.example",
            }
        ],
        "count": 1,
        "source": "gdelt",
    }


@pytest.fixture
def aoi_store_with_pittsburgh(tmp_path: Path) -> AOIStore:
    s = AOIStore(tmp_path / "test_aoi_brief_cache.db")
    s.define("Pittsburgh", _PGH_LAT, _PGH_LON, _PGH_RADIUS_KM)
    yield s
    s.close()


def _patch_all_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seismology, "fetch_earthquakes", _fake_earthquakes)
    monkeypatch.setattr(military, "fetch_military_flights", _fake_military)
    monkeypatch.setattr(conflict, "fetch_acled_events", _fake_acled)
    monkeypatch.setattr(wildfire, "fetch_wildfires", _fake_wildfires)
    monkeypatch.setattr(aviation, "fetch_domestic_flights", _fake_domestic_flights)
    monkeypatch.setattr(news, "fetch_gdelt_search", _fake_gdelt)


@pytest.mark.asyncio
async def test_fetch_aoi_brief_not_found(fetcher, store: AOIStore) -> None:
    result = await aoi.fetch_aoi_brief(fetcher, store, "Nowhere")
    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_aoi_brief_includes_in_radius_excludes_out_of_radius(
    fetcher, aoi_store_with_pittsburgh: AOIStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing pair, at the tool level: every synthetic domain
    carries one event inside the 50 km radius and one ~330 km outside it.
    Only the in-radius ones may appear."""
    _patch_all_domains(monkeypatch)

    result = await aoi.fetch_aoi_brief(fetcher, aoi_store_with_pittsburgh, "Pittsburgh")

    assert result["counts"]["earthquakes"] == 1
    assert result["counts"]["military_flights"] == 1
    assert result["counts"]["conflict_events"] == 1
    assert result["counts"]["wildfires"] == 1
    assert result["counts"]["aviation"] == 1

    assert "near Pittsburgh" in result["markdown"]
    assert "near Detroit" not in result["markdown"]
    assert "Near Pittsburgh" in result["markdown"]
    assert "Near Detroit" not in result["markdown"]


@pytest.mark.asyncio
async def test_fetch_aoi_brief_is_cited(
    fetcher, aoi_store_with_pittsburgh: AOIStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all_domains(monkeypatch)
    result = await aoi.fetch_aoi_brief(fetcher, aoi_store_with_pittsburgh, "Pittsburgh")
    assert result["cited"] is True
    assert len(result["sources"]) > 0
    # Every source has a real, resolvable citation number.
    max_n = len(result["sources"])
    assert all(1 <= s["n"] <= max_n for s in result["sources"])


@pytest.mark.asyncio
async def test_fetch_aoi_brief_reports_data_gap_for_unscopable_domain(
    fetcher, aoi_store_with_pittsburgh: AOIStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all_domains(monkeypatch)

    async def _broken_acled(fetcher, **kwargs):
        return {
            "error": "ACLED credentials not configured (ACLED_EMAIL + ACLED_PASSWORD)"
        }

    monkeypatch.setattr(conflict, "fetch_acled_events", _broken_acled)

    result = await aoi.fetch_aoi_brief(fetcher, aoi_store_with_pittsburgh, "Pittsburgh")

    assert any("Conflict events" in gap for gap in result["data_gaps"])
    assert not any(s["domain"] == "conflict_events" for s in result["sources"])


@pytest.mark.asyncio
async def test_fetch_aoi_brief_reports_data_gap_when_gdelt_fails(
    fetcher, aoi_store_with_pittsburgh: AOIStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #17: a GDELT fetch failure (rate limit, API error) must
    surface as a data_gap here, the same as every other domain in this
    brief, not read as "no news mentions" the way it silently did
    before fetch_gdelt_search() carried an honest error/degraded shape."""
    _patch_all_domains(monkeypatch)

    async def _broken_gdelt(fetcher, **kwargs):
        return {
            "error": "GDELT fetch failed (rate limited, API error, or malformed response)",
            "degraded": True,
            "reason": "gdelt_fetch_failed",
            "articles": [],
            "count": 0,
        }

    monkeypatch.setattr(news, "fetch_gdelt_search", _broken_gdelt)

    result = await aoi.fetch_aoi_brief(fetcher, aoi_store_with_pittsburgh, "Pittsburgh")

    assert any("News" in gap for gap in result["data_gaps"])
    assert not any(s["domain"] == "news" for s in result["sources"])


@pytest.mark.asyncio
async def test_fetch_aoi_brief_reports_data_gap_when_no_wildfire_region_overlaps(
    fetcher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all_domains(monkeypatch)
    s = AOIStore(tmp_path / "test_open_ocean.db")
    # Deep South Pacific, far from all 9 REGIONS bboxes in wildfire.py.
    s.define("Open Ocean", -55.0, -140.0, 50.0)

    result = await aoi.fetch_aoi_brief(fetcher, s, "Open Ocean")

    assert any("Wildfires" in gap for gap in result["data_gaps"])
    s.close()


@pytest.mark.asyncio
async def test_fetch_aoi_brief_includes_nearby_infrastructure(
    fetcher, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_all_domains(monkeypatch)
    s = AOIStore(tmp_path / "test_norfolk.db")
    s.define("Norfolk", 36.95, -76.33, 5.0)

    result = await aoi.fetch_aoi_brief(fetcher, s, "Norfolk")

    assert result["counts"]["military_bases"] >= 1
    assert "Norfolk Naval Station" in result["markdown"]
    s.close()


# ---------------------------------------------------------------------------
# fetch_aoi_escalation: reuses analysis/escalation.py unmodified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_aoi_escalation_not_found(fetcher, store: AOIStore) -> None:
    result = await aoi.fetch_aoi_escalation(fetcher, store, "Nowhere")
    assert "error" in result


@pytest.mark.asyncio
async def test_fetch_aoi_escalation_scores_only_in_radius_signals(
    fetcher, aoi_store_with_pittsburgh: AOIStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(conflict, "fetch_acled_events", _fake_acled)
    monkeypatch.setattr(military, "fetch_military_flights", _fake_military)

    result = await aoi.fetch_aoi_escalation(
        fetcher, aoi_store_with_pittsburgh, "Pittsburgh"
    )

    assert "error" not in result
    # 1 in-radius military aircraft -> military component = min(20, 1*1.0) = 1.0
    assert result["components"]["military"] == pytest.approx(1.0)
    # 1 in-radius protest event, 0 conflict events, 0 fatalities in radius
    # -> conflict component = min(20, 0*0.5 + 0*0.1) = 0.0
    assert result["components"]["conflict"] == pytest.approx(0.0)
    assert result["components"]["news"] is None
    assert result["components"]["convergence"] is None
    assert set(result["unavailable_components"]) == {"news", "convergence"}


@pytest.mark.asyncio
async def test_fetch_aoi_escalation_reports_data_gap_on_fetch_failure(
    fetcher, aoi_store_with_pittsburgh: AOIStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _broken_military(fetcher, bbox=None):
        return {"error": "adsb.lol and OpenSky both unavailable"}

    monkeypatch.setattr(conflict, "fetch_acled_events", _fake_acled)
    monkeypatch.setattr(military, "fetch_military_flights", _broken_military)

    result = await aoi.fetch_aoi_escalation(
        fetcher, aoi_store_with_pittsburgh, "Pittsburgh"
    )

    assert any("Military flights" in gap for gap in result["data_gaps"])


# ---------------------------------------------------------------------------
# Server registration / dispatch parity (matches test_daily_digest.py's
# pattern: read server.py as text rather than importing it, since import
# opens a live Cache()/AOIStore() at the default on-disk path).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_name,fn_name",
    [
        ("intel_aoi_define", "aoi.define_aoi"),
        ("intel_aoi_list", "aoi.list_aois"),
        ("intel_aoi_delete", "aoi.delete_aoi"),
        ("intel_aoi_brief", "aoi.fetch_aoi_brief"),
        ("intel_aoi_escalation", "aoi.fetch_aoi_escalation"),
    ],
)
def test_aoi_tools_registered_and_dispatched(tool_name: str, fn_name: str) -> None:
    """Structural parity check: the TOOLS/`_dispatch` 1:1 invariant this
    repo maintains (see ROADMAP.md 'MCP tool parity') must hold for every
    new AOI tool."""
    text = _SERVER_PY.read_text()

    assert f'name="{tool_name}"' in text

    dispatch_idx = text.index(f'case "{tool_name}":')
    assert dispatch_idx > 0
    dispatch_body = text[dispatch_idx : dispatch_idx + 300]
    assert fn_name in dispatch_body


def test_aoi_store_instantiated_from_cache_db_path() -> None:
    """The AOIStore must share the Cache's resolved db_path, not compute
    its own default independently (which could diverge under
    WORLD_INTEL_CACHE_DB or the tempdir fallback)."""
    text = _SERVER_PY.read_text()
    assert "_aoi_store = aoi.AOIStore(cache.db_path)" in text
