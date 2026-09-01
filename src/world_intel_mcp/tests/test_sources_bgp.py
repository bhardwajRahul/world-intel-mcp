"""Tests for sources/bgp.py — respx-mocked RIPEstat data calls.

Gaps / not covered: RIPEstat's "maintenance" envelope (status !=
"ok" with a data key still present) — the module treats a missing/empty
data key as failure and passes through whatever data holds otherwise;
IPv6 prefix responses (assumed shape-identical to v4, mocked only).
"""

import asyncio as asyncio_mod

import httpx
import pytest
import respx

from world_intel_mcp.fetcher import Fetcher
from world_intel_mcp.sources.bgp import _summarize_rpki, fetch_bgp_status

# Envelope + data shapes mirror live RIPEstat responses observed
# 2026-09-01 for AS3333 and 193.0.0.0/21.
_ASN_STATUS = {
    "status": "ok",
    "data": {
        "first_seen": {
            "prefix": "193.0.0.0/22",
            "origin": "3333",
            "time": "2000-08-18T08:00:00",
        },
        "last_seen": {
            "prefix": "193.0.22.0/23",
            "origin": "3333",
            "time": "2026-09-01T16:00:00",
        },
        "visibility": {
            "v4": {"ris_peers_seeing": 111, "total_ris_peers": 111},
            "v6": {"ris_peers_seeing": 108, "total_ris_peers": 108},
        },
        "announced_space": {
            "v4": {"prefixes": 6, "ips": 4608},
            "v6": {"prefixes": 1, "48s": 1},
        },
        "observed_neighbours": 904,
        "resource": "3333",
    },
}

_PREFIX_STATUS = {
    "status": "ok",
    "data": {
        "first_seen": {
            "prefix": "193.0.0.0/21",
            "origin": "3333",
            "time": "2000-10-31T00:00:00",
        },
        "last_seen": {
            "prefix": "193.0.0.0/21",
            "origin": "3333",
            "time": "2026-09-01T16:00:00",
        },
        "visibility": {
            "v4": {"ris_peers_seeing": 111, "total_ris_peers": 111},
            "v6": {"ris_peers_seeing": 0, "total_ris_peers": 0},
        },
        "origins": [{"origin": 3333, "route_objects": ["RIPE"]}],
        "less_specifics": [],
        "more_specifics": [{"origin": 3333, "prefix": "193.0.0.0/22"}],
        "resource": "193.0.0.0/21",
    },
}

_RPKI_VALID = {
    "status": "ok",
    "data": {
        "resource": "3333",
        "prefix": "193.0.0.0/21",
        "validating_roas": [
            {
                "origin": "3333",
                "prefix": "193.0.0.0/21",
                "validity": "valid",
                "max_length": 21,
            }
        ],
        "status": "valid",
        "validator": "routinator",
    },
}


def _moas_status(origins: list[int]) -> dict:
    """Prefix routing-status with multiple observed origins (MOAS)."""
    data = {k: v for k, v in _PREFIX_STATUS["data"].items()}
    data["origins"] = [{"origin": o, "route_objects": []} for o in origins]
    return {"status": "ok", "data": data}


def _rpki_response(status: str, roas: int = 0) -> dict:
    return {
        "status": "ok",
        "data": {"validating_roas": [{}] * roas, "status": status},
    }


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bgp_status_asn(fetcher: Fetcher) -> None:
    route = respx.get(url__regex=r".*stat\.ripe\.net/data/routing-status.*").mock(
        return_value=httpx.Response(200, json=_ASN_STATUS)
    )

    result = await fetch_bgp_status(fetcher, "AS3333")

    assert result["source"] == "ripestat"
    assert result["resource"] == "AS3333"
    assert result["resource_type"] == "asn"
    assert "degraded" not in result
    assert result["visible"] is True
    assert result["visibility"]["v4"] == {
        "ris_peers_seeing": 111,
        "total_ris_peers": 111,
    }
    assert result["announced_space"]["v4"]["prefixes"] == 6
    assert result["observed_neighbours"] == 904
    assert result["first_seen"]["time"] == "2000-08-18T08:00:00"
    assert result["rpki"] == []  # ASN queries skip RPKI, explicitly
    assert "prefix" in result["rpki_note"]
    # The AS prefix is stripped before hitting RIPEstat
    assert route.calls.last.request.url.params["resource"] == "3333"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bgp_status_prefix_with_rpki(fetcher: Fetcher) -> None:
    respx.get(url__regex=r".*stat\.ripe\.net/data/routing-status.*").mock(
        return_value=httpx.Response(200, json=_PREFIX_STATUS)
    )
    rpki_route = respx.get(url__regex=r".*stat\.ripe\.net/data/rpki-validation.*").mock(
        return_value=httpx.Response(200, json=_RPKI_VALID)
    )

    result = await fetch_bgp_status(fetcher, "193.0.0.0/21")

    assert result["resource_type"] == "prefix"
    assert "degraded" not in result
    assert result["origins"] == [{"origin": "3333", "route_objects": ["RIPE"]}]
    assert result["less_specifics_count"] == 0
    assert result["more_specifics_count"] == 1
    assert result["rpki"] == [{"origin": "3333", "status": "valid", "roa_count": 1}]
    assert result["rpki_status"] == "valid"
    # RPKI was validated against the origin observed in BGP
    params = rpki_route.calls.last.request.url.params
    assert params["resource"] == "3333"
    assert params["prefix"] == "193.0.0.0/21"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bgp_status_moas_invalid_origin(fetcher: Fetcher) -> None:
    """One RPKI-invalid origin marks the whole prefix invalid."""
    respx.get(url__regex=r".*stat\.ripe\.net/data/routing-status.*").mock(
        return_value=httpx.Response(200, json=_moas_status([3333, 65551]))
    )

    def _rpki_by_origin(request: httpx.Request) -> httpx.Response:
        origin = request.url.params["resource"]
        status = "valid" if origin == "3333" else "invalid"
        return httpx.Response(200, json=_rpki_response(status, roas=1))

    respx.get(url__regex=r".*stat\.ripe\.net/data/rpki-validation.*").mock(
        side_effect=_rpki_by_origin
    )

    result = await fetch_bgp_status(fetcher, "193.0.0.0/21")

    assert [c["status"] for c in result["rpki"]] == ["valid", "invalid"]
    assert result["rpki_status"] == "invalid"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bgp_status_unannounced_prefix(fetcher: Fetcher) -> None:
    """A withdrawn/unseen prefix: zero visibility, no origins, rpki unknown."""
    data = {
        "status": "ok",
        "data": {
            "visibility": {
                "v4": {"ris_peers_seeing": 0, "total_ris_peers": 111},
            },
            "origins": [],
            "less_specifics": [],
            "more_specifics": [],
        },
    }
    respx.get(url__regex=r".*stat\.ripe\.net/data/routing-status.*").mock(
        return_value=httpx.Response(200, json=data)
    )

    result = await fetch_bgp_status(fetcher, "203.0.113.0/24")

    assert result["visible"] is False
    assert result["origins"] == []
    assert result["rpki"] == []
    assert result["rpki_status"] == "unknown"
    assert "degraded" not in result


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bgp_status_rpki_failure_is_inline_not_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Routing status still comes back when only the RPKI call fails."""

    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*stat\.ripe\.net/data/routing-status.*").mock(
        return_value=httpx.Response(200, json=_PREFIX_STATUS)
    )
    respx.get(url__regex=r".*stat\.ripe\.net/data/rpki-validation.*").mock(
        return_value=httpx.Response(500)
    )

    result = await fetch_bgp_status(fetcher, "193.0.0.0/21")

    assert "degraded" not in result
    assert result["rpki"] == [
        {"origin": "3333", "status": "fetch_failed", "roa_count": 0}
    ]
    assert result["rpki_status"] == "unknown"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bgp_status_feed_down_is_marked_degraded(
    fetcher: Fetcher, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _no_sleep(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(asyncio_mod, "sleep", _no_sleep)

    respx.get(url__regex=r".*stat\.ripe\.net.*").mock(return_value=httpx.Response(500))

    result = await fetch_bgp_status(fetcher, "3333")

    assert result["degraded"] is True
    assert result["reason"] == "ripestat_fetch_failed"
    assert "unavailable" in result["error"].lower()
    assert result["resource_type"] == "asn"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_bgp_status_invalid_resource(fetcher: Fetcher) -> None:
    """Bare IPs and junk are rejected locally — no HTTP call."""
    for bad in ("8.8.8.8", "example.com", ""):
        result = await fetch_bgp_status(fetcher, bad)
        assert result["reason"] == "invalid_resource"
        assert "degraded" not in result
    assert not respx.calls


def test_summarize_rpki() -> None:
    assert _summarize_rpki([]) == "unknown"
    assert _summarize_rpki([{"status": "valid"}]) == "valid"
    assert _summarize_rpki([{"status": "valid"}, {"status": "invalid"}]) == "invalid"
    assert _summarize_rpki([{"status": "valid"}, {"status": "unknown"}]) == "unknown"
    assert _summarize_rpki([{"status": "fetch_failed"}]) == "unknown"
