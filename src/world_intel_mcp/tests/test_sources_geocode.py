"""Tests for sources/geocode.py — respx-mocked Nominatim reverse lookups.

Reverse geocoding exists here for one reason: AOI news was scoped by
mention of the AOI's *name*, so an area a user called "Home" or "PGH
Square" pulled whatever GDELT matched that string. Measured live
2026-09-02: query "Home" returned a Chinese A-share IPO article and
"PGH Square" an Indian op-ed on Gaza, both for a Pittsburgh geofence.
Turning coordinates into real place names is what makes AOI news
geographic.

Gaps / not covered: Nominatim's rate-limit (429) and usage-policy
blocking responses are mocked, not provoked live; the zoom level (10,
city/county granularity) is asserted as sent but its result quality
across countries is verified only for the US case measured above.
"""

import httpx
import pytest
import respx

from world_intel_mcp.sources import geocode

_URL = r".*nominatim\.openstreetmap\.org/reverse.*"

_PITTSBURGH = {
    "name": "Pittsburgh",
    "display_name": "Pittsburgh, Allegheny County, Pennsylvania, United States",
    "address": {
        "city": "Pittsburgh",
        "county": "Allegheny County",
        "state": "Pennsylvania",
        "country": "United States",
        "country_code": "us",
    },
}


@pytest.mark.asyncio
@respx.mock
async def test_reverse_returns_place_terms(fetcher) -> None:
    route = respx.get(url__regex=_URL).mock(
        return_value=httpx.Response(200, json=_PITTSBURGH)
    )
    result = await geocode.fetch_place_context(fetcher, 40.44, -79.99)

    assert "error" not in result
    assert result["place"] == "Pittsburgh"
    assert result["county"] == "Allegheny County"
    assert result["state"] == "Pennsylvania"
    assert result["country_code"] == "us"
    # Most specific first: a news query should lead with the city.
    assert result["terms"][0] == "Pittsburgh"
    assert "Allegheny County" in result["terms"]
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_reverse_sends_contact_user_agent(fetcher) -> None:
    """Nominatim's usage policy requires identifying the application
    with a contact URL; the default fetcher UA does not carry one."""
    route = respx.get(url__regex=_URL).mock(
        return_value=httpx.Response(200, json=_PITTSBURGH)
    )
    await geocode.fetch_place_context(fetcher, 40.44, -79.99)

    ua = route.calls.last.request.headers.get("User-Agent", "")
    assert "world-intel-mcp" in ua
    assert "github.com" in ua


@pytest.mark.asyncio
@respx.mock
async def test_reverse_rejects_out_of_range_coordinates(fetcher) -> None:
    route = respx.get(url__regex=_URL).mock(
        return_value=httpx.Response(200, json=_PITTSBURGH)
    )
    result = await geocode.fetch_place_context(fetcher, 91.0, 0.0)
    assert "error" in result
    assert not route.called  # never spend a request on invalid input


@pytest.mark.asyncio
@respx.mock
async def test_reverse_open_ocean_has_no_place(fetcher) -> None:
    """Nominatim returns an error object for points with no address.
    That is a real answer ("nowhere named here"), not a failure to
    hide: the caller must be able to tell it apart from an outage."""
    respx.get(url__regex=_URL).mock(
        return_value=httpx.Response(200, json={"error": "Unable to geocode"})
    )
    result = await geocode.fetch_place_context(fetcher, 0.0, -140.0)
    assert result["place"] is None
    assert result["terms"] == []
    assert "error" not in result  # the lookup succeeded; the place does not exist


@pytest.mark.asyncio
@respx.mock
async def test_reverse_upstream_failure_is_an_error(fetcher) -> None:
    respx.get(url__regex=_URL).mock(return_value=httpx.Response(503))
    result = await geocode.fetch_place_context(fetcher, 40.44, -79.99)
    assert "error" in result
    assert result.get("place") is None


@pytest.mark.asyncio
@respx.mock
async def test_town_and_village_count_as_place(fetcher) -> None:
    """Smaller settlements come back under town/village/hamlet rather
    than city; an AOI over a village must still get its own name."""
    respx.get(url__regex=_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "display_name": "Grafton, Taylor County, West Virginia",
                "address": {
                    "town": "Grafton",
                    "county": "Taylor County",
                    "state": "West Virginia",
                    "country_code": "us",
                },
            },
        )
    )
    result = await geocode.fetch_place_context(fetcher, 39.34, -80.01)
    assert result["place"] == "Grafton"
    assert result["terms"][0] == "Grafton"


@pytest.mark.asyncio
@respx.mock
async def test_failed_request_is_not_reported_as_a_shape_problem(fetcher) -> None:
    """Caught live 2026-09-02: a real Nominatim 429 surfaced to the AOI
    brief as "returned an unexpected response shape", which points a
    reader at parsing when the cause was rate limiting. A failed fetch
    (get_json returns None) and a genuinely odd payload are different
    failures and must not share a message."""
    respx.get(url__regex=_URL).mock(return_value=httpx.Response(429))
    result = await geocode.fetch_place_context(fetcher, 40.44, -79.99)

    assert "error" in result
    err = result["error"].lower()
    assert "shape" not in err
    assert "request" in err or "unavailable" in err


@pytest.mark.asyncio
@respx.mock
async def test_genuinely_odd_payload_still_reports_shape(fetcher) -> None:
    """The shape message keeps its own real case: a 200 that parses to
    something that is not an object."""
    respx.get(url__regex=_URL).mock(return_value=httpx.Response(200, json=[1, 2, 3]))
    result = await geocode.fetch_place_context(fetcher, 40.44, -79.99)

    assert "error" in result
    assert "shape" in result["error"].lower()
