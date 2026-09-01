"""Tests for sources/maritime.py — respx-mocked NGA MSI broadcast warnings.

Gaps / not covered: live NGA payload variants beyond the three shapes the
module handles (list, dict-with-key, single dict); coordinate strings with
seconds notation (the regex only handles degrees-minutes).
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.maritime import (
    NAVAREAS,
    _extract_coords,
    _is_active,
    _parse_warning,
    fetch_nav_warnings,
)

_W_GULF = {
    "msgYear": 2026,
    "msgNumber": 100,
    "navArea": "IV",
    "subregion": "24",
    "status": "in force",
    "issueDate": "2026-08-30",
    "text": (
        "GULF OF MEXICO. HAZARDOUS OPERATIONS 22-16.65N 097-44.48W. "
        "WIDE BERTH REQUESTED."
    ),
    "authority": "NGA",
}
_W_CANCELLED = {
    "msgYear": 2026,
    "msgNumber": 90,
    "navArea": "IV",
    "issueDate": "2026-07-01",
    "cancelDate": "2026-08-01",
    "text": "CANCELLED WARNING.",
}
_W_PACIFIC = {
    "msgYear": 2026,
    "msgNumber": 200,
    "navArea": "XII",
    "issueDate": "2026-08-31",
    "text": "ROCKET LAUNCHING HAZARD AREA.",  # no coordinates
}
_W_LONG = {
    "msgYear": 2026,
    "msgNumber": 300,
    "navArea": "IV",
    "issueDate": "2026-08-29",
    "text": "A" * 600,
}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_nav_warnings_list_payload(fetcher: Fetcher) -> None:
    respx.get(url__regex=r".*msi\.nga\.mil.*").mock(
        return_value=httpx.Response(
            200, json=[_W_GULF, _W_CANCELLED, _W_PACIFIC, _W_LONG]
        )
    )

    result = await fetch_nav_warnings(fetcher)

    assert result["source"] == "nga-msi"
    # Cancelled warning excluded.
    assert result["count"] == 3
    ids = [w["id"] for w in result["warnings"]]
    assert "2026-90" not in ids
    # Sorted by issue_date descending: Aug 31, Aug 30, Aug 29.
    assert ids == ["2026-200", "2026-100", "2026-300"]

    gulf = next(w for w in result["warnings"] if w["id"] == "2026-100")
    assert gulf["navarea"] == "IV"
    assert gulf["subregion"] == "24"
    assert gulf["status"] == "active"
    assert gulf["cancel_date"] is None
    # 22 + 16.65/60 = 22.2775 N; 97 + 44.48/60 = 97.7413 W (negative).
    assert gulf["lat"] == 22.2775
    assert gulf["lon"] == -97.7413

    pacific = next(w for w in result["warnings"] if w["id"] == "2026-200")
    assert pacific["lat"] is None
    assert pacific["lon"] is None

    long_w = next(w for w in result["warnings"] if w["id"] == "2026-300")
    assert len(long_w["text"]) == 503  # 500 chars + "..."
    assert long_w["text"].endswith("...")

    assert result["by_navarea"] == {"XII": 1, "IV": 2}
    assert result["navareas"] == NAVAREAS


@respx.mock
@pytest.mark.asyncio
async def test_fetch_nav_warnings_navarea_filter_case_insensitive(
    fetcher: Fetcher,
) -> None:
    respx.get(url__regex=r".*msi\.nga\.mil.*").mock(
        return_value=httpx.Response(200, json=[_W_GULF, _W_PACIFIC])
    )

    result = await fetch_nav_warnings(fetcher, navarea="xii")
    assert result["count"] == 1
    assert result["warnings"][0]["id"] == "2026-200"
    assert result["by_navarea"] == {"XII": 1}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_nav_warnings_dict_payload_single_warning(
    fetcher: Fetcher,
) -> None:
    # The API sometimes wraps a single warning dict under "broadcast-warn".
    respx.get(url__regex=r".*msi\.nga\.mil.*").mock(
        return_value=httpx.Response(200, json={"broadcast-warn": _W_GULF})
    )

    result = await fetch_nav_warnings(fetcher)
    assert result["count"] == 1
    assert result["warnings"][0]["id"] == "2026-100"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_nav_warnings_api_down(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Observation (flagged in review, not fixed): an NGA outage returns
    warnings=[] with no error key — shape-identical to calm seas."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*msi\.nga\.mil.*").mock(return_value=httpx.Response(500))

    result = await fetch_nav_warnings(fetcher)
    assert result["warnings"] == []
    assert result["count"] == 0
    assert result["by_navarea"] == {}
    assert "error" not in result  # current (dishonest-quiet) behavior


def test_extract_coords() -> None:
    assert _extract_coords("22-16.65N 097-44.48W") == (22.2775, -97.7413)
    # Southern/eastern hemisphere signs.
    assert _extract_coords("05-30.0S 120-15.0E") == (-5.5, 120.25)
    assert _extract_coords("no coordinates here") == (None, None)
    assert _extract_coords("") == (None, None)


def test_is_active_and_parse_warning() -> None:
    assert _is_active({"cancelDate": None}) is True
    assert _is_active({"cancelDate": ""}) is True
    assert _is_active({"cancelDate": "2026-08-01"}) is False

    parsed = _parse_warning(_W_CANCELLED)
    assert parsed["status"] == "cancelled"
    assert parsed["cancel_date"] == "2026-08-01"

    # Missing msgYear/msgNumber leaves id as None.
    assert _parse_warning({"text": "x"})["id"] is None
