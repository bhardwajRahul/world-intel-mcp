"""Tests for cli.py — every user-facing command via click.testing.CliRunner.

Fetch functions are faked at their module boundaries (the test_aoi.py /
test_world_brief.py pattern), so no network happens; assertions check that
rendered Rich output contains values derived from the fakes and that CLI
options reach the fetch functions with the right names.

Three cli.py bugs are pinned (not fixed) by characterization tests below,
marked BUG in comments:

1. Error swallowing: many commands only branch on ``ctx.obj["json"]`` and
   never check ``"error" in data``, so an upstream {"error": ...} renders
   as a healthy-looking empty table ("0 earthquakes", "No market data
   available") with the actual error message discarded. Commands that DO
   surface errors (energy, fred, fires, conflicts, dossier, btc, fleet,
   traffic, ...) print the JSON error. See the *_error_dict tests.

2. Rich markup swallowing: several commands interpolate data into
   ``[...]`` brackets (news category, sanctions entity_type, ai-watch
   source), and the report command's own remediation hint contains a
   literal ``[pdf]``. Lowercase bracketed values parse as Rich markup
   tags and are silently dropped from output — the label the line exists
   to show never renders, and the install hint prints as
   ``pip install -e '.'``. (Uppercase values like "[IV]" or "[Rust]" fail
   Rich's tag regex and survive as literal text.) This is also a
   markup-injection surface: bracketed sequences inside remote data
   (news titles, etc.) are interpreted as markup. See the
   *_markup_swallowed tests and test_report_error_with_fallback_hint.
"""

import pytest
from click.testing import CliRunner

from world_intel_mcp import cli


@pytest.fixture(autouse=True)
def _cli_isolation(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the lazily-built Fetcher's Cache at a tmp SQLite file, widen
    Rich's non-tty console so table cells don't truncate, and reset the
    module-global fetcher so each test builds a fresh one."""
    monkeypatch.setenv("WORLD_INTEL_CACHE_DB", str(tmp_path / "cli-cache.db"))
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(cli, "_fetcher", None)


def _invoke(*args: str):
    return CliRunner().invoke(cli.main, list(args), catch_exceptions=False)


def _fake(payload, calls: list | None = None):
    """Async fake fetch fn; records call kwargs when given a list."""

    async def _f(*args, **kwargs):
        if calls is not None:
            calls.append(kwargs)
        return payload

    return _f


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_command_registry() -> None:
    names = set(cli.main.commands)
    assert {
        "markets",
        "crypto",
        "macro",
        "energy",
        "gas-prices",
        "natgas",
        "electricity",
        "fred",
        "earthquakes",
        "fires",
        "conflicts",
        "flights",
        "posture",
        "outages",
        "cables",
        "warnings",
        "climate",
        "news",
        "trending",
        "gdelt",
        "predictions",
        "displacement",
        "delays",
        "threats",
        "brief",
        "dossier",
        "risk",
        "instability",
        "btc",
        "central-banks",
        "shipping",
        "social",
        "disease",
        "elections",
        "nuclear",
        "space",
        "sanctions",
        "ai-watch",
        "fleet",
        "hn",
        "gh-trending",
        "arxiv",
        "spending",
        "bases",
        "exchanges",
        "traffic",
        "incidents",
        "air-traffic",
        "status",
        "sync",
        "dashboard",
        "report",
    } <= names
    # webcams_cmd has no explicit name=, but click >= 8.1 strips the
    # `_cmd` suffix when deriving default command names, so the
    # user-facing name still comes out right.
    assert "webcams" in names
    assert len(names) == 53


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

_QUOTES = {
    "quotes": [
        {"symbol": "TSTX", "price": 1234.5, "change_pct": 2.34, "currency": "USD"},
        {"symbol": "DOWN", "price": 99.5, "change_pct": -1.2, "currency": "EUR"},
    ]
}


def test_markets_renders_quotes_and_passes_symbols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    monkeypatch.setattr(cli.markets, "fetch_market_quotes", _fake(_QUOTES, calls))
    result = _invoke("markets", "-s", "AAA", "-s", "BBB")
    assert result.exit_code == 0
    assert calls == [{"symbols": ["AAA", "BBB"]}]
    assert "TSTX" in result.output
    assert "1,234.50" in result.output
    assert "+2.34%" in result.output
    assert "-1.20%" in result.output
    assert "USD" in result.output


def test_markets_no_symbols_defaults_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    monkeypatch.setattr(cli.markets, "fetch_market_quotes", _fake(_QUOTES, calls))
    assert _invoke("markets").exit_code == 0
    assert calls == [{"symbols": None}]


def test_markets_empty_prints_no_data_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.markets, "fetch_market_quotes", _fake({"quotes": []}))
    result = _invoke("markets")
    assert result.exit_code == 0
    assert "No market data available" in result.output


def test_markets_json_flag_prints_raw_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.markets, "fetch_market_quotes", _fake(_QUOTES))
    result = _invoke("--json-output", "markets")
    assert result.exit_code == 0
    assert '"TSTX"' in result.output
    assert '"change_pct"' in result.output


def test_markets_error_dict_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # BUG: markets never checks "error" in data. An upstream failure
    # renders as the healthy-looking empty state and the error text is
    # discarded. Pinned, not fixed (fix belongs in cli.py).
    monkeypatch.setattr(
        cli.markets, "fetch_market_quotes", _fake({"error": "yahoo down"})
    )
    result = _invoke("markets")
    assert result.exit_code == 0
    assert "No market data available" in result.output
    assert "yahoo down" not in result.output


def test_crypto_renders_and_passes_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    payload = {
        "coins": [
            {
                "symbol": "btc",
                "current_price": 65_000.0,
                "price_change_percentage_24h": 3.5,
                "market_cap": 1_280_000_000,
            }
        ]
    }
    monkeypatch.setattr(cli.markets, "fetch_crypto_quotes", _fake(payload, calls))
    result = _invoke("crypto", "--limit", "5")
    assert result.exit_code == 0
    assert calls == [{"limit": 5}]
    assert "Top 5 Cryptocurrencies" in result.output
    assert "BTC" in result.output
    assert "$65,000.00" in result.output
    assert "+3.50%" in result.output
    assert "$1,280,000,000" in result.output


def test_macro_renders_dict_none_and_scalar_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "signals": {
            "vix": {"value": 18.2, "classification": "calm"},
            "dxy": None,
            "spread": 4.2,
        }
    }
    monkeypatch.setattr(cli.markets, "fetch_macro_signals", _fake(payload))
    result = _invoke("macro")
    assert result.exit_code == 0
    assert "18.2" in result.output
    assert "calm" in result.output
    assert "unavailable" in result.output  # None signal
    assert "4.2" in result.output  # bare scalar signal


def test_btc_technicals_values_and_na_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "price": 64_250.5,
        "sma_50": 61_000.0,
        "sma_200": None,
        "mayer_multiple": None,
        "cross_signal": "golden_cross",
        "ath_distance_pct": -12.5,
        "change_7d_pct": 4.2,
        "change_30d_pct": None,
    }
    monkeypatch.setattr(cli.markets, "fetch_btc_technicals", _fake(payload))
    result = _invoke("btc")
    assert result.exit_code == 0
    assert "$64,250.50" in result.output
    assert "$61,000.00" in result.output
    assert "golden_cross" in result.output
    assert "-12.5%" in result.output
    assert "+4.20%" in result.output
    assert "N/A" in result.output  # sma_200 / mayer / 30d all None


def test_btc_error_dict_is_surfaced_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli.markets, "fetch_btc_technicals", _fake({"error": "coingecko down"})
    )
    result = _invoke("btc")
    assert result.exit_code == 0
    assert "coingecko down" in result.output


# ---------------------------------------------------------------------------
# Economic
# ---------------------------------------------------------------------------


def test_energy_renders_oil_and_gas(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "oil": {
            "brent": {"price": 82.5, "date": "2026-08-29"},
            "wti": {"price": 78.1, "date": "2026-08-29"},
        },
        "natural_gas": {"price": 2.9, "date": "2026-08-29"},
    }
    monkeypatch.setattr(cli.economic, "fetch_energy_prices", _fake(payload))
    result = _invoke("energy")
    assert result.exit_code == 0
    assert "Brent Crude" in result.output
    assert "$82.5" in result.output
    assert "$2.9" in result.output


def test_energy_error_dict_is_surfaced_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli.economic, "fetch_energy_prices", _fake({"error": "EIA_API_KEY missing"})
    )
    result = _invoke("energy")
    assert result.exit_code == 0
    assert "EIA_API_KEY missing" in result.output


def test_gas_prices_renders_changes_and_em_dash_for_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "prices": {
            "regular": {
                "price_per_gallon": 3.199,
                "change_pct": 0.5,
                "week_ago_pct": -1.2,
            },
            "diesel": {
                "price_per_gallon": 3.899,
                "change_pct": None,
                "week_ago_pct": None,
            },
        }
    }
    monkeypatch.setattr(cli.economic, "fetch_gas_prices", _fake(payload))
    result = _invoke("gas-prices")
    assert result.exit_code == 0
    assert "$3.199" in result.output
    assert "+0.50%" in result.output
    assert "-1.20%" in result.output
    assert "$3.899" in result.output
    assert "—" in result.output  # None change renders as em dash


def test_natgas_renders_period_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"prices": [{"period": "2026-06", "price": 14.23}]}
    monkeypatch.setattr(cli.economic, "fetch_residential_natgas_prices", _fake(payload))
    result = _invoke("natgas")
    assert result.exit_code == 0
    assert "2026-06" in result.output
    assert "$14.23" in result.output


def test_electricity_passes_state_and_renders_rates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "state": "CA",
        "rates": {"residential": {"price_cents_kwh": 16.44, "period": "2026-05"}},
    }
    monkeypatch.setattr(cli.economic, "fetch_electricity_rates", _fake(payload, calls))
    result = _invoke("electricity", "--state", "CA")
    assert result.exit_code == 0
    assert calls == [{"state": "CA"}]
    assert "Electricity Rates — CA" in result.output
    assert "Residential" in result.output
    assert "16.44" in result.output


def test_fred_passes_series_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    # Single-word title: the Rich table sizes to its (narrow) content and
    # wraps longer titles across lines, which would defeat substring asserts.
    payload = {
        "title": "Jobless",
        "observations": [{"date": "2026-07-01", "value": "4.2"}],
    }
    monkeypatch.setattr(cli.economic, "fetch_fred_series", _fake(payload, calls))
    result = _invoke("fred", "UNRATE", "--limit", "5")
    assert result.exit_code == 0
    assert calls == [{"series_id": "UNRATE", "limit": 5}]
    assert "FRED: Jobless" in result.output
    assert "2026-07-01" in result.output
    assert "4.2" in result.output


def test_fred_error_dict_is_surfaced_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli.economic, "fetch_fred_series", _fake({"error": "series not found"})
    )
    result = _invoke("fred", "NOPE")
    assert result.exit_code == 0
    assert "series not found" in result.output


def test_central_banks_renders_rates_and_fred_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "count": 2,
        "fred_available": True,
        "rates": [
            {
                "bank": "Federal Reserve",
                "country": "US",
                "rate": 4.25,
                "as_of": "2026-08-01",
            },
            {"bank": "TCMB", "country": "TR", "rate": 42.0, "as_of": "2026-08-01"},
        ],
    }
    monkeypatch.setattr(cli, "fetch_central_bank_rates", _fake(payload))
    result = _invoke("central-banks")
    assert result.exit_code == 0
    assert "2 Central Banks" in result.output
    assert "FRED" in result.output
    assert "Federal Reserve" in result.output
    assert "4.25" in result.output
    assert "42.00" in result.output


# ---------------------------------------------------------------------------
# Natural
# ---------------------------------------------------------------------------


def test_earthquakes_passes_options_and_renders_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "count": 2,
        "earthquakes": [
            {
                "magnitude": 6.1,
                "place": "Off Honshu",
                "depth_km": 10.0,
                "time": "2026-08-31T12:00:00.000Z",
                "alert_level": "red",
            },
            {
                "magnitude": 4.6,
                "place": "Nevada",
                "depth_km": 5.2,
                "time": "2026-08-31T13:00:00.000Z",
                "alert_level": None,
            },
        ],
    }
    monkeypatch.setattr(cli.seismology, "fetch_earthquakes", _fake(payload, calls))
    result = _invoke("earthquakes", "--min-mag", "5.0", "--hours", "48")
    assert result.exit_code == 0
    assert calls == [{"min_magnitude": 5.0, "hours": 48}]
    assert "2 earthquakes" in result.output
    assert "M5.0+ in last 48h" in result.output
    assert "6.1" in result.output
    assert "Off Honshu" in result.output
    assert "2026-08-31T12:00:00" in result.output  # time truncated to 19 chars
    assert "red" in result.output
    assert "Nevada" in result.output


def test_earthquakes_error_dict_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # BUG: earthquakes never checks "error" in data. A USGS failure renders
    # as "0 earthquakes" over an empty table — indistinguishable from a
    # genuinely quiet day. Pinned, not fixed.
    monkeypatch.setattr(
        cli.seismology, "fetch_earthquakes", _fake({"error": "USGS unreachable"})
    )
    result = _invoke("earthquakes")
    assert result.exit_code == 0
    assert "0 earthquakes" in result.output
    assert "USGS unreachable" not in result.output


def test_fires_renders_regions_and_skips_zero_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "total_fires": 12,
        "fires_by_region": {
            "north_america": {
                "count": 12,
                "top_clusters": [
                    {"lat": 39.1, "lon": -120.3, "fire_count": 8, "max_frp": 250.0}
                ],
            },
            "europe": {"count": 0},
        },
    }
    monkeypatch.setattr(cli.wildfire, "fetch_wildfires", _fake(payload, calls))
    result = _invoke("fires", "-r", "north_america")
    assert result.exit_code == 0
    assert calls == [{"region": "north_america"}]
    assert "12 high-confidence fires detected" in result.output
    assert "(39.1, -120.3)" in result.output
    assert "8 fires" in result.output
    assert "FRP max 250" in result.output
    assert "europe" not in result.output  # zero-count regions skipped


def test_fires_error_dict_is_surfaced_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli.wildfire, "fetch_wildfires", _fake({"error": "FIRMS key missing"})
    )
    result = _invoke("fires")
    assert result.exit_code == 0
    assert "FIRMS key missing" in result.output


def test_climate_renders_anomalies_and_sig_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "zones": {
            "arctic": {
                "name": "Arctic",
                "temp_anomaly_c": 4.2,
                "precip_anomaly_pct": -10.0,
            },
            "sahel": {
                "name": "Sahel",
                "temp_anomaly_c": 0.5,
                "precip_anomaly_pct": 25.0,
            },
        },
        "significant_anomalies": ["arctic"],
    }
    monkeypatch.setattr(cli.climate, "fetch_climate_anomalies", _fake(payload))
    result = _invoke("climate")
    assert result.exit_code == 0
    assert "Arctic" in result.output
    assert "+4.2C" in result.output
    assert "-10%" in result.output
    assert "SIG" in result.output
    assert "Sahel" in result.output
    assert "+0.5C" in result.output


# ---------------------------------------------------------------------------
# Conflict / Military
# ---------------------------------------------------------------------------


def test_conflicts_passes_options_and_renders_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "count": 1,
        "events": [
            {
                "event_date": "2026-08-30",
                "event_type": "Battles",
                "country": "Ukraine",
                "location": "Kharkiv",
                "fatalities": 12,
            }
        ],
    }
    monkeypatch.setattr(cli.conflict, "fetch_acled_events", _fake(payload, calls))
    result = _invoke("conflicts", "-c", "Ukraine", "-d", "30")
    assert result.exit_code == 0
    assert calls == [{"country": "Ukraine", "days": 30}]
    assert "1 conflict events" in result.output
    assert "(last 30d)" in result.output
    assert "Battles" in result.output
    assert "Kharkiv" in result.output
    assert "12" in result.output


def test_conflicts_error_dict_is_surfaced_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli.conflict, "fetch_acled_events", _fake({"error": "ACLED token missing"})
    )
    result = _invoke("conflicts")
    assert result.exit_code == 0
    assert "ACLED token missing" in result.output


def test_flights_passes_bbox_and_renders_aircraft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "count": 1,
        "aircraft": [
            {
                "callsign": "RCH123",
                "icao24": "ae1234",
                "origin_country": "United States",
                "altitude_m": 10_000,
                "velocity_ms": 250.0,
            }
        ],
    }
    monkeypatch.setattr(cli.military, "fetch_military_flights", _fake(payload, calls))
    result = _invoke("flights", "-b", "1,2,3,4")
    assert result.exit_code == 0
    assert calls == [{"bbox": "1,2,3,4"}]
    assert "1 military aircraft detected" in result.output
    assert "RCH123" in result.output
    assert "ae1234" in result.output
    assert "10,000" in result.output


def test_posture_renders_theaters(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "total_military_aircraft": 25,
        "theaters": {
            "eastern_europe": {
                "count": 22,
                "countries": ["United States", "Poland"],
                "sample_callsigns": ["RCH1", "LAGR2"],
            }
        },
    }
    monkeypatch.setattr(cli.military, "fetch_theater_posture", _fake(payload))
    result = _invoke("posture")
    assert result.exit_code == 0
    assert "25 total military aircraft" in result.output
    assert "Eastern Europe" in result.output
    assert "22" in result.output
    assert "United States, Poland" in result.output
    assert "RCH1, LAGR2" in result.output


def test_nuclear_passes_hours_and_renders_sites(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "total_flagged_events": 1,
        "critical_flags": 0,
        "sites": [
            {"name": "Punggye-ri", "events": [{"m": 4.1}]},
            {"name": "Lop Nur", "events": []},
        ],
    }
    monkeypatch.setattr(cli.nuclear, "fetch_nuclear_monitor", _fake(payload, calls))
    result = _invoke("nuclear", "--hours", "48")
    assert result.exit_code == 0
    assert calls == [{"hours": 48}]
    assert "1 flagged events" in result.output
    assert "in last 48h" in result.output
    assert "Punggye-ri: 1 events" in result.output
    assert "Lop Nur: 0 events" in result.output


# ---------------------------------------------------------------------------
# Infrastructure / Maritime
# ---------------------------------------------------------------------------


def test_outages_renders_ongoing(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "ongoing_count": 2,
        "total_7d": 5,
        "outages": [
            {
                "start": "2026-08-31T05:00",
                "is_ongoing": True,
                "countries": ["Sudan"],
                "description": "Nationwide internet blackout",
            }
        ],
    }
    monkeypatch.setattr(cli.infrastructure, "fetch_internet_outages", _fake(payload))
    result = _invoke("outages")
    assert result.exit_code == 0
    assert "2 ongoing outages" in result.output
    assert "5 in last 7 days" in result.output
    assert "Sudan" in result.output
    assert "Nationwide internet blackout" in result.output
    assert "ONGOING" in result.output


def test_cables_maps_status_scores_to_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "corridors": {
            "red_sea": {
                "status_score": 2,
                "cables": ["AAE-1", "SEACOM"],
                "relevant_warnings": [1, 2],
            }
        }
    }
    monkeypatch.setattr(cli.infrastructure, "fetch_cable_health", _fake(payload))
    result = _invoke("cables")
    assert result.exit_code == 0
    assert "Red Sea" in result.output
    assert "At Risk" in result.output  # score 2 label
    assert "AAE-1, SEACOM" in result.output


def test_warnings_passes_navarea_and_renders_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "count": 3,
        "by_navarea": {"IV": 2, "XII": 1},
        "warnings": [
            {"navarea": "IV", "id": "NAV 0417", "text": "GUNNERY EXERCISES IN AREA"}
        ],
    }
    monkeypatch.setattr(cli.maritime, "fetch_nav_warnings", _fake(payload, calls))
    result = _invoke("warnings", "-n", "IV")
    assert result.exit_code == 0
    assert calls == [{"navarea": "IV"}]
    assert "3 active warnings" in result.output
    assert "IV:2" in result.output
    assert "XII:1" in result.output
    assert "NAV 0417" in result.output
    assert "GUNNERY EXERCISES" in result.output


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


def test_news_passes_options_and_category_label_markup_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "count": 1,
        "categories_fetched": ["security"],
        "items": [
            {
                "category": "geopolitics",
                "title": "Summit convened on maritime security",
                "feed_name": "BBC World",
                "published": "2026-08-31T10:00:00Z",
            }
        ],
    }
    monkeypatch.setattr(cli.news, "fetch_news_feed", _fake(payload, calls))
    result = _invoke("news", "-c", "security", "--limit", "5")
    assert result.exit_code == 0
    assert calls == [{"category": "security", "limit": 5}]
    assert "1 items" in result.output
    assert "Summit convened on maritime security" in result.output
    assert "BBC World" in result.output
    assert "2026-08-31T10:00" in result.output
    # BUG: the per-item category label is printed as "[geopolitics]", which
    # Rich parses as an (unknown, lowercase) markup tag and silently drops —
    # the item's category never reaches the user. Pinned, not fixed.
    assert "geopolitics" not in result.output


def test_news_rejects_invalid_category() -> None:
    result = _invoke("news", "-c", "bogus")
    assert result.exit_code == 2
    assert "Invalid value" in result.stderr
    assert "bogus" in result.stderr


def test_news_empty_prints_no_items_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.news, "fetch_news_feed", _fake({"count": 0, "items": []}))
    result = _invoke("news")
    assert result.exit_code == 0
    assert "No news items available" in result.output


def test_trending_passes_min_count_and_renders_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "total_items_analyzed": 200,
        "keywords": [{"word": "ceasefire", "count": 14}],
    }
    monkeypatch.setattr(cli.news, "fetch_trending_keywords", _fake(payload, calls))
    result = _invoke("trending", "-m", "5")
    assert result.exit_code == 0
    assert calls == [{"min_count": 5}]
    assert "200 items" in result.output
    assert "ceasefire" in result.output
    assert "14" in result.output


def test_gdelt_artlist_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    payload = {"articles": [{"title": "Protests spread", "domain": "example.com"}]}
    monkeypatch.setattr(cli.news, "fetch_gdelt_search", _fake(payload, calls))
    result = _invoke("gdelt", "protest")
    assert result.exit_code == 0
    assert calls == [{"query": "protest", "mode": "artlist", "limit": 20}]
    assert "1 articles" in result.output
    assert "'protest'" in result.output
    assert "Protests spread" in result.output
    assert "(example.com)" in result.output


def test_gdelt_timelinevol_mode_prints_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"timeline": [{"date": "2026-08-31", "value": 42}]}
    monkeypatch.setattr(cli.news, "fetch_gdelt_search", _fake(payload))
    result = _invoke("gdelt", "protest", "-m", "timelinevol")
    assert result.exit_code == 0
    assert "Timeline volume for 'protest'" in result.output
    assert "2026-08-31" in result.output


# ---------------------------------------------------------------------------
# Prediction / Displacement / Aviation / Cyber
# ---------------------------------------------------------------------------


def test_predictions_renders_probability_and_sentiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "markets": [
            {
                "question": "Will X happen by year end",
                "yes_probability": 0.62,
                "sentiment": "likely_yes",
                "volume_24h": 1_500_000,
            }
        ]
    }
    monkeypatch.setattr(
        cli.prediction, "fetch_prediction_markets", _fake(payload, calls)
    )
    result = _invoke("predictions", "--limit", "10")
    assert result.exit_code == 0
    assert calls == [{"limit": 10}]
    assert "Will X happen by year end" in result.output
    assert "62%" in result.output
    assert "likely_yes" in result.output
    assert "$1,500,000" in result.output


def test_displacement_passes_year_and_renders_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "year": 2025,
        "global_totals": {"grand_total": 120_000_000},
        "by_origin": [
            {
                "country": "Syria",
                "total_displaced": 13_000_000,
                "refugees": 6_500_000,
                "internally_displaced": 6_500_000,
            }
        ],
    }
    monkeypatch.setattr(
        cli.displacement, "fetch_displacement_summary", _fake(payload, calls)
    )
    result = _invoke("displacement", "-y", "2025")
    assert result.exit_code == 0
    assert calls == [{"year": 2025}]
    assert "Global Displacement (2025)" in result.output
    assert "120,000,000" in result.output
    assert "Syria" in result.output
    assert "13,000,000" in result.output


def test_delays_all_clear_message(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"delayed_count": 0, "total_checked": 30, "delayed": []}
    monkeypatch.setattr(cli.aviation, "fetch_airport_delays", _fake(payload))
    result = _invoke("delays")
    assert result.exit_code == 0
    assert "No major airport delays!" in result.output


def test_delays_renders_delayed_airports(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "delayed_count": 1,
        "total_checked": 30,
        "delayed": [
            {
                "code": "EWR",
                "name": "Newark Liberty",
                "status": [
                    {"type": "Ground Delay", "reason": "weather", "avg_delay": "45 min"}
                ],
            }
        ],
    }
    monkeypatch.setattr(cli.aviation, "fetch_airport_delays", _fake(payload))
    result = _invoke("delays")
    assert result.exit_code == 0
    assert "1 airports with delays" in result.output
    assert "EWR" in result.output
    assert "Newark Liberty" in result.output
    assert "Ground Delay - weather (45 min)" in result.output


def test_threats_renders_severity_summary_and_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "count": 5,
        "feeds_successful": 3,
        "feeds_attempted": 4,
        "by_severity": {"critical": 1, "high": 2, "medium": 1, "low": 1},
        "threats": [
            {
                "severity": "critical",
                "type": "ip",
                "indicator": "203.0.113.7",
                "threat": "botnet C2",
                "source_feed": "feodo",
            }
        ],
    }
    monkeypatch.setattr(cli.cyber, "fetch_cyber_threats", _fake(payload))
    result = _invoke("threats")
    assert result.exit_code == 0
    assert "5 threats" in result.output
    assert "3/4 feeds" in result.output
    assert "Critical: 1" in result.output
    assert "203.0.113.7" in result.output
    assert "botnet C2" in result.output
    assert "feodo" in result.output


# ---------------------------------------------------------------------------
# Intelligence
# ---------------------------------------------------------------------------


def test_brief_data_only_tag_and_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    payload = {
        "llm_available": False,
        "brief": "Country brief text here.",
        "data": {"gdp": [1, 2], "recent_events": 3},
    }
    monkeypatch.setattr(cli.intelligence, "fetch_country_brief", _fake(payload, calls))
    result = _invoke("brief", "DE")
    assert result.exit_code == 0
    assert calls == [{"country_code": "DE"}]
    assert "Intelligence Brief: DE" in result.output
    assert "data-only" in result.output
    assert "Country brief text here." in result.output
    assert "GDP data points: 2" in result.output
    assert "Recent conflict events: 3" in result.output


def test_risk_renders_country_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "countries": [
            {
                "country": "Sudan",
                "events_30d": 300,
                "risk_score": 88.0,
                "risk_level": "critical",
            }
        ]
    }
    monkeypatch.setattr(cli.intelligence, "fetch_risk_scores", _fake(payload))
    result = _invoke("risk")
    assert result.exit_code == 0
    assert "Sudan" in result.output
    assert "300" in result.output
    assert "88" in result.output
    assert "critical" in result.output


def test_instability_single_country_renders_component_bars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "instability_index": 72,
        "risk_level": "high",
        "components": {"conflict_intensity": 18.5},
    }
    monkeypatch.setattr(cli.intelligence, "fetch_instability_index", _fake(payload))
    result = _invoke("instability", "UKR")
    assert result.exit_code == 0
    assert "UKR Instability Index: 72/100 (high)" in result.output
    assert "conflict_intensity" in result.output
    assert "18.5/20" in result.output
    assert "█" in result.output


def test_instability_all_countries_renders_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "countries": [
            {
                "country_name": "Sudan",
                "country_code": "SDN",
                "instability_index": 81,
                "events_30d": 240,
                "risk_level": "critical",
            }
        ]
    }
    monkeypatch.setattr(cli.intelligence, "fetch_instability_index", _fake(payload))
    result = _invoke("instability")
    assert result.exit_code == 0
    assert "Sudan (SDN)" in result.output
    assert "81" in result.output
    assert "240" in result.output
    assert "critical" in result.output


def test_dossier_renders_all_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    import world_intel_mcp.analysis.dossier as dossier_mod

    calls: list = []
    payload = {
        "overview": {
            "country": "Ukraine",
            "iso2": "UA",
            "iso3": "UKR",
            "baseline_risk": 78,
        },
        "economy": {
            "gdp": [{"year": 2025, "value": 178e9}],
            "conflict_events_30d": 450,
        },
        "markets": {"ticker": "^UX", "quote": {"price": 1200, "change_pct": 1.5}},
        "elections": {
            "upcoming": [
                {
                    "election_type": "parliamentary",
                    "date": "2026-10-01",
                    "risk_score": 4.0,
                }
            ]
        },
        "sanctions": {"match_count": 2},
        "news": {
            "mention_count": 5,
            "mentions": [{"title": "Article about grid strikes"}],
        },
        "security": {"hotspot_count": 2, "conflict_count": 1},
    }
    monkeypatch.setattr(dossier_mod, "fetch_country_dossier", _fake(payload, calls))
    result = _invoke("dossier", "-c", "UA")
    assert result.exit_code == 0
    assert calls == [{"country": "UA"}]
    assert "Country Dossier: Ukraine" in result.output
    assert "(UA/UKR)" in result.output
    assert "GDP 2025: $178.0B" in result.output
    assert "Conflict events (30d): 450" in result.output
    assert "^UX = 1200 (1.5%)" in result.output
    assert "parliamentary on 2026-10-01" in result.output
    assert "risk: 4" in result.output
    assert "2 OFAC matches" in result.output
    assert "5 recent mentions" in result.output
    assert "Article about grid strikes" in result.output
    assert "Hotspots: 2" in result.output
    assert "Conflicts: 1" in result.output
    assert "Baseline risk: 78/100" in result.output


def test_dossier_error_dict_is_surfaced_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import world_intel_mcp.analysis.dossier as dossier_mod

    monkeypatch.setattr(
        dossier_mod, "fetch_country_dossier", _fake({"error": "unknown country XX"})
    )
    result = _invoke("dossier", "-c", "XX")
    assert result.exit_code == 0
    assert "unknown country XX" in result.output


# ---------------------------------------------------------------------------
# Shipping / Social / Health / Elections / Space / Sanctions / AI
# ---------------------------------------------------------------------------


def test_shipping_renders_stress_and_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "assessment": "elevated",
        "stress_score": 62.0,
        "quotes": [{"symbol": "BDRY", "price": 12.34, "change_pct": -3.1}],
    }
    monkeypatch.setattr(cli.shipping, "fetch_shipping_index", _fake(payload))
    result = _invoke("shipping")
    assert result.exit_code == 0
    assert "Shipping Stress: elevated" in result.output
    assert "score: 62/100" in result.output
    assert "BDRY" in result.output
    assert "$12.34" in result.output
    assert "-3.10%" in result.output


def test_social_renders_metrics_and_posts(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "velocity_metrics": {"total_posts": 50, "high_engagement_count": 7},
        "top_posts": [{"score": 4521, "title": "Major escalation reported"}],
    }
    monkeypatch.setattr(cli.social, "fetch_social_signals", _fake(payload))
    result = _invoke("social")
    assert result.exit_code == 0
    assert "50 posts" in result.output
    assert "7 high engagement" in result.output
    assert "4521" in result.output
    assert "Major escalation reported" in result.output


def test_disease_renders_outbreaks_with_high_concern_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "count": 3,
        "high_concern_count": 1,
        "items": [
            {
                "is_high_concern": True,
                "title": "H5N1 cluster investigated",
                "feed_name": "WHO",
            }
        ],
    }
    monkeypatch.setattr(cli.health, "fetch_disease_outbreaks", _fake(payload))
    result = _invoke("disease")
    assert result.exit_code == 0
    assert "3 outbreak reports" in result.output
    assert "1 high concern" in result.output
    assert "HC" in result.output
    assert "H5N1 cluster investigated" in result.output
    assert "(WHO)" in result.output


def test_elections_passes_country_and_renders_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "elections": [
            {
                "date": "2026-10-04",
                "country": "Brazil",
                "type": "presidential",
                "days_until": 33,
                "risk_score": 4.5,
            }
        ]
    }
    monkeypatch.setattr(cli.elections, "fetch_election_calendar", _fake(payload, calls))
    result = _invoke("elections", "-c", "BRA")
    assert result.exit_code == 0
    assert calls == [{"country": "BRA"}]
    assert "2026-10-04" in result.output
    assert "Brazil" in result.output
    assert "presidential" in result.output
    assert "33" in result.output
    assert "4.5" in result.output


def test_space_renders_metrics_and_skips_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "k_index": 3.2,
        "solar_wind_speed_km_s": 450.0,
        "solar_wind_density": None,
        "bz_gsm_nt": None,
        "flux_10_7": 155,
    }
    monkeypatch.setattr(cli.space_weather, "fetch_space_weather", _fake(payload))
    result = _invoke("space")
    assert result.exit_code == 0
    assert "K Index" in result.output
    assert "3.2" in result.output
    assert "450.0" in result.output
    assert "155" in result.output
    assert "Bz" not in result.output  # None metrics are omitted


def test_sanctions_passes_query_and_entity_type_markup_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "count": 1,
        "total_entities": 12_000,
        "matches": [
            {
                "entity_type": "org",
                "name": "WAGNER GROUP",
                "programs": ["RUSSIA-EO14024"],
            }
        ],
    }
    monkeypatch.setattr(cli.sanctions, "fetch_sanctions_search", _fake(payload, calls))
    result = _invoke("sanctions", "Wagner")
    assert result.exit_code == 0
    assert calls == [{"query": "Wagner", "country": None}]
    assert "1 matches" in result.output
    assert "'Wagner'" in result.output
    assert "12000 total" in result.output
    assert "WAGNER GROUP" in result.output
    assert "RUSSIA-EO14024" in result.output
    # BUG: "[org]" is parsed as Rich markup and silently dropped — the
    # entity type never renders. Pinned, not fixed.
    assert "org" not in result.output


def test_ai_watch_source_label_markup_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "total_items": 2,
        "items": [{"title": "New frontier model released", "source": "arxiv"}],
    }
    monkeypatch.setattr(cli.ai_watch, "fetch_ai_watch", _fake(payload))
    result = _invoke("ai-watch")
    assert result.exit_code == 0
    assert "2 items" in result.output
    assert "New frontier model released" in result.output
    # BUG: "[arxiv]" is parsed as Rich markup and silently dropped — the
    # per-item source label never renders. Pinned, not fixed.
    assert "arxiv" not in result.output


# ---------------------------------------------------------------------------
# Fleet / Tech & Science
# ---------------------------------------------------------------------------


def test_fleet_renders_totals_and_ships(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "report_title": "USNI Fleet Tracker update",
        "force_totals": {
            "battle_force": {"total": 296, "uss": 238, "usns": 58},
            "deployed": {"total": 110, "uss": 70, "usns": 40},
        },
        "ships": [
            {
                "name": "USS Gerald R. Ford",
                "hull_number": "CVN-78",
                "type": "carrier",
                "region": "Mediterranean",
            }
        ],
    }
    monkeypatch.setattr(cli, "fetch_usni_fleet", _fake(payload))
    result = _invoke("fleet")
    assert result.exit_code == 0
    assert "USNI Fleet Tracker update" in result.output
    assert "Battle Force: 296 ships (238 USS, 58 USNS)" in result.output
    assert "Deployed: 110 (70 USS, 40 USNS)" in result.output
    assert "1 ships identified" in result.output
    assert "USS Gerald R. Ford" in result.output
    assert "CVN-78" in result.output


def test_fleet_error_dict_is_surfaced_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "fetch_usni_fleet", _fake({"error": "USNI page structure changed"})
    )
    result = _invoke("fleet")
    assert result.exit_code == 0
    assert "USNI page structure changed" in result.output


def test_hn_renders_stories(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    payload = {"stories": [{"score": 512, "title": "Show HN: Something"}]}
    monkeypatch.setattr(cli, "fetch_hacker_news", _fake(payload, calls))
    result = _invoke("hn", "--limit", "5")
    assert result.exit_code == 0
    assert calls == [{"limit": 5}]
    assert "512" in result.output
    assert "Show HN: Something" in result.output


def test_gh_trending_renders_repos(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "repos": [
            {
                "stars": 3200,
                "name": "acme/widget",
                "language": "Rust",
                "description": "A widget framework",
            }
        ]
    }
    monkeypatch.setattr(cli, "fetch_trending_repos", _fake(payload))
    result = _invoke("gh-trending")
    assert result.exit_code == 0
    assert "3200" in result.output
    assert "acme/widget" in result.output
    # "[Rust]" survives only because it starts uppercase and so fails
    # Rich's markup-tag regex; a lowercase language would be swallowed
    # like the news category (see BUG note in module docstring).
    assert "[Rust]" in result.output
    assert "A widget framework" in result.output


def test_arxiv_passes_query_and_renders_papers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list = []
    payload = {
        "papers": [
            {
                "title": "Attention Is Still All You Need",
                "authors": ["A. One", "B. Two"],
            }
        ]
    }
    monkeypatch.setattr(cli, "fetch_arxiv_papers", _fake(payload, calls))
    result = _invoke("arxiv", "-q", "cs.CR", "--limit", "3")
    assert result.exit_code == 0
    assert calls == [{"query": "cs.CR", "limit": 3}]
    assert "Attention Is Still All You Need" in result.output
    assert "A. One, B. Two" in result.output


def test_spending_renders_agency_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "agencies": [
            {
                "name": "Department of Defense",
                "budget_authority": 850e9,
                "obligated": 600e9,
            }
        ]
    }
    monkeypatch.setattr(cli, "fetch_usa_spending", _fake(payload))
    result = _invoke("spending")
    assert result.exit_code == 0
    assert "Department of Defense" in result.output
    assert "$850.0B" in result.output
    assert "$600.0B" in result.output


# ---------------------------------------------------------------------------
# Geospatial (no fetcher argument)
# ---------------------------------------------------------------------------


def test_bases_passes_filters_and_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    payload = {
        "count": 1,
        "total_in_database": 70,
        "bases": [
            {
                "name": "Ramstein AB",
                "operator": "USA",
                "country": "Germany",
                "type": "air",
                "branch": "USAF",
            }
        ],
    }
    monkeypatch.setattr(cli.geospatial, "fetch_military_bases", _fake(payload, calls))
    result = _invoke("bases", "-o", "USA")
    assert result.exit_code == 0
    assert calls == [{"operator": "USA", "country": None}]
    assert "1 bases" in result.output
    assert "of 70" in result.output
    assert "Ramstein AB" in result.output
    assert "Germany" in result.output


def test_exchanges_passes_tier_and_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []
    payload = {
        "count": 1,
        "total_market_cap_usd_t": 30.5,
        "exchanges": [
            {
                "name": "NYSE",
                "country": "USA",
                "tier": "mega",
                "market_cap_usd_t": 28.33,
            }
        ],
    }
    monkeypatch.setattr(cli.geospatial, "fetch_stock_exchanges", _fake(payload, calls))
    result = _invoke("exchanges", "-t", "mega")
    assert result.exit_code == 0
    assert calls == [{"tier": "mega", "country": None}]
    assert "$30.5T" in result.output
    assert "NYSE" in result.output
    assert "28.33" in result.output


def test_exchanges_rejects_invalid_tier() -> None:
    result = _invoke("exchanges", "-t", "huge")
    assert result.exit_code == 2
    assert "Invalid value" in result.stderr


# ---------------------------------------------------------------------------
# Traffic / Aviation extras / Webcams
# ---------------------------------------------------------------------------


def test_traffic_renders_cities(monkeypatch: pytest.MonkeyPatch) -> None:
    import world_intel_mcp.sources.traffic as traffic_mod

    payload = {
        "count": 2,
        "global_avg_congestion": 45.0,
        "cities": [
            {
                "name": "Lagos",
                "country": "NGA",
                "congestion_pct": 72,
                "current_speed_kmh": 18,
            }
        ],
    }
    monkeypatch.setattr(traffic_mod, "fetch_traffic_flow", _fake(payload))
    result = _invoke("traffic")
    assert result.exit_code == 0
    assert "avg congestion 45%" in result.output
    assert "Lagos" in result.output
    assert "72%" in result.output
    assert "18" in result.output


def test_traffic_error_dict_is_surfaced_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import world_intel_mcp.sources.traffic as traffic_mod

    monkeypatch.setattr(
        traffic_mod, "fetch_traffic_flow", _fake({"error": "TOMTOM key missing"})
    )
    result = _invoke("traffic")
    assert result.exit_code == 0
    assert "TOMTOM key missing" in result.output


def test_incidents_renders_delays_and_dash_for_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import world_intel_mcp.sources.traffic as traffic_mod

    payload = {
        "total_count": 3,
        "regions_checked": 5,
        "incidents": [
            {
                "region": "LA",
                "description": "Overturned truck",
                "delay_seconds": 600,
                "from_road": "I-405",
            },
            {
                "region": "NYC",
                "description": "Lane closure",
                "delay_seconds": 0,
                "from_road": "FDR Drive",
            },
        ],
    }
    monkeypatch.setattr(traffic_mod, "fetch_traffic_incidents", _fake(payload))
    result = _invoke("incidents")
    assert result.exit_code == 0
    assert "3 across" in result.output
    assert "5 regions" in result.output
    assert "Overturned truck" in result.output
    assert "10" in result.output  # 600s -> 10 min
    assert "I-405" in result.output
    assert "Lane closure" in result.output


def test_air_traffic_renders_regions_and_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "total_aircraft": 9000,
        "by_region": {"europe": {"count": 4000, "commercial": 3500, "general": 500}},
        "busiest_origins": [{"country": "United States", "count": 2500}],
    }
    monkeypatch.setattr(cli.aviation, "fetch_domestic_flights", _fake(payload))
    result = _invoke("air-traffic")
    assert result.exit_code == 0
    assert "9000 airborne" in result.output
    assert "europe" in result.output
    assert "4000" in result.output
    assert "3500" in result.output
    assert "Busiest Origins:" in result.output
    assert "United States: 2500" in result.output


def test_webcams_passes_options_and_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    import world_intel_mcp.sources.webcams as webcams_mod

    calls: list = []
    payload = {
        "count": 1,
        "cameras": [
            {
                "title": "Harbor Cam",
                "city": "Rotterdam",
                "country": "Netherlands",
                "status": "active",
            }
        ],
    }
    monkeypatch.setattr(webcams_mod, "fetch_webcams", _fake(payload, calls))
    result = _invoke("webcams", "-c", "ports", "--limit", "5")
    assert result.exit_code == 0
    assert calls == [{"category": "ports", "limit": 5}]
    assert "1 cameras (ports)" in result.output
    assert "Harbor Cam" in result.output
    assert "Rotterdam" in result.output


# ---------------------------------------------------------------------------
# System: status / sync / report
# ---------------------------------------------------------------------------


def test_status_without_requests_shows_empty_breaker_note() -> None:
    result = _invoke("status")
    assert result.exit_code == 0
    assert "World Intelligence Status" in result.output
    assert "Cache:" in result.output
    assert "No circuit breaker data yet" in result.output


def test_status_renders_breaker_table_after_failure() -> None:
    # Seed the shared fetcher's breaker, then render status through the CLI.
    f = cli._get_fetcher()
    f.breaker.record_failure("test-src")
    result = _invoke("status")
    assert result.exit_code == 0
    assert "Circuit Breakers" in result.output
    assert "test-src" in result.output
    assert "closed" in result.output  # single failure does not trip


def test_status_json_output() -> None:
    result = _invoke("--json-output", "status")
    assert result.exit_code == 0
    assert '"circuit_breakers"' in result.output
    assert '"cache"' in result.output


def test_sync_without_source_evicts_expired() -> None:
    result = _invoke("sync")
    assert result.exit_code == 0
    assert "Evicted 0 expired cache entries" in result.output


def test_sync_with_source_reports_not_implemented() -> None:
    result = _invoke("sync", "yahoo")
    assert result.exit_code == 0
    assert "Force sync not yet implemented for specific source 'yahoo'" in result.output


def test_report_success_panel_and_option_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import world_intel_mcp.reports as reports_mod

    calls: list = []
    payload = {
        "path": "/tmp/r.html",
        "format": "html",
        "size_bytes": 123_456,
        "sections_included": ["markets", "cyber"],
        "sections_failed": ["fleet"],
        "generation_seconds": 4.2,
    }
    monkeypatch.setattr(reports_mod, "generate_report", _fake(payload, calls))
    result = _invoke(
        "report", "--format", "html", "--sections", "markets,cyber", "-t", "Daily"
    )
    assert result.exit_code == 0
    assert calls == [
        {
            "output_path": None,
            "title": "Daily",
            "sections": ["markets", "cyber"],
            "fmt": "html",
        }
    ]
    assert "Report generated" in result.output
    assert "/tmp/r.html" in result.output
    assert "123,456 bytes" in result.output
    assert "markets, cyber" in result.output
    assert "4.2s" in result.output
    assert "Failed: fleet" in result.output


def test_report_error_with_fallback_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    import world_intel_mcp.reports as reports_mod

    payload = {
        "error": "WeasyPrint not installed",
        "fallback": "pip install -e '.[pdf]'",
    }
    monkeypatch.setattr(reports_mod, "generate_report", _fake(payload))
    result = _invoke("report")
    assert result.exit_code == 0
    assert "Error:" in result.output
    assert "WeasyPrint not installed" in result.output
    # BUG: the fallback hint's literal "[pdf]" is parsed as a Rich markup
    # tag and silently dropped, so the user is told to run
    # `pip install -e '.'` — which would NOT install the pdf extra.
    # Pinned, not fixed.
    assert "pip install -e '.'" in result.output
    assert "[pdf]" not in result.output
