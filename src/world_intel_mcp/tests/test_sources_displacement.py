"""Tests for sources/displacement.py — respx-mocked UNHCR aggregation.

Gaps / not covered: real UNHCR pagination (the module requests limit=100 and
never pages); the top-30 truncation is not exercised with >30 countries.
"""

import asyncio as asyncio_mod
from datetime import datetime, timezone

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.displacement import _safe_int, fetch_displacement_summary

_UNHCR = {
    "items": [
        {
            "coo_name": "Syria",
            "refugees": 100,
            "asylum_seekers": 10,
            "idps": 50,
            "stateless": 0,
            "ooc": 5,
        },
        # Second Syria row must aggregate into the first.
        {"coo_name": "Syria", "refugees": 200},
        {
            "coo_name": "Ukraine",
            "refugees": 1000,
            "asylum_seekers": "not-a-number",  # unparseable -> 0
            "idps": 500,
        },
        # Missing coo_name buckets under "Unknown".
        {"refugees": 7},
    ]
}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_displacement_summary_aggregates_by_origin(
    fetcher: Fetcher,
) -> None:
    route = respx.get(url__regex=r".*api\.unhcr\.org.*").mock(
        return_value=httpx.Response(200, json=_UNHCR)
    )

    result = await fetch_displacement_summary(fetcher)

    assert result["source"] == "unhcr"
    assert result["count"] == 3
    # Sorted by total_displaced descending: Ukraine 1500, Syria 365, Unknown 7.
    assert [e["country"] for e in result["by_origin"]] == [
        "Ukraine",
        "Syria",
        "Unknown",
    ]
    ukraine = result["by_origin"][0]
    assert ukraine["refugees"] == 1000
    assert ukraine["asylum_seekers"] == 0  # unparseable string coerced to 0
    assert ukraine["internally_displaced"] == 500
    assert ukraine["total_displaced"] == 1500

    syria = result["by_origin"][1]
    assert syria["refugees"] == 300  # 100 + 200 across two rows
    assert syria["total_displaced"] == 365

    totals = result["global_totals"]
    assert totals["total_refugees"] == 1307
    assert totals["total_asylum_seekers"] == 10
    assert totals["total_idps"] == 550
    assert totals["total_stateless"] == 0
    assert totals["total_ooc"] == 5
    assert totals["grand_total"] == 1872

    # Default year is the previous calendar year (UNHCR lags).
    expected_year = datetime.now(timezone.utc).year - 1
    assert result["year"] == expected_year
    assert route.calls.last.request.url.params["yearFrom"] == str(expected_year)


@respx.mock
@pytest.mark.asyncio
async def test_fetch_displacement_summary_year_coerced_from_string(
    fetcher: Fetcher,
) -> None:
    route = respx.get(url__regex=r".*api\.unhcr\.org.*").mock(
        return_value=httpx.Response(200, json={"items": []})
    )

    result = await fetch_displacement_summary(fetcher, year="2020")
    assert result["year"] == 2020
    assert result["by_origin"] == []
    assert result["count"] == 0
    assert route.calls.last.request.url.params["yearFrom"] == "2020"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_displacement_summary_api_down_returns_zeroed_shape(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suspected bug (documented, not fixed): a UNHCR outage returns
    global_totals of all zeros with NO error/degraded key — byte-shape
    identical to a world with zero displaced persons. This is the
    fail-reads-as-success class this repo treats as its worst bug family;
    flagged in the review report rather than fixed here."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*api\.unhcr\.org.*").mock(return_value=httpx.Response(500))

    result = await fetch_displacement_summary(fetcher)
    assert result["by_origin"] == []
    assert result["count"] == 0
    assert result["global_totals"]["grand_total"] == 0
    assert "error" not in result  # current (dishonest-quiet) behavior


def test_safe_int() -> None:
    assert _safe_int(None) == 0
    assert _safe_int(5) == 5
    assert _safe_int(5.9) == 5
    assert _safe_int("42") == 42
    assert _safe_int("nope") == 0
