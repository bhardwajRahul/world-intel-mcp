"""Tests for analysis/signals.py — per-country multi-domain aggregation.

Convergence scores in comments follow the documented formula:
20 * unique_domains + min(30, 5 * total_signals) + 10 * high_severity.
"""

from world_intel_mcp.analysis.signals import aggregate_country_signals


def test_no_inputs_yields_empty_dict() -> None:
    assert aggregate_country_signals() == {}


def test_conflict_events_aggregate_with_fatality_severity() -> None:
    result = aggregate_country_signals(
        conflict_events=[
            {"country": "Ukraine", "fatalities": 12},
            {"country": "Ukraine", "fatalities": 0},
            {"country": "Sudan", "fatalities": 5},
        ]
    )
    ukr = result["Ukraine"]
    assert ukr["conflict_events"] == 2
    assert ukr["fatalities"] == 12
    assert ukr["active_domains"] == ["conflict"]
    assert ukr["signal_count"] == 1
    assert ukr["total_signals"] == 2
    # 20*1 + min(30, 5*2) + 10*1 (one event with >10 fatalities) = 40
    assert ukr["convergence_score"] == 40
    # 20*1 + 5*1 + 0 = 25
    assert result["Sudan"]["convergence_score"] == 25
    # Sorted by convergence score descending.
    assert list(result) == ["Ukraine", "Sudan"]


def test_events_without_country_are_dropped() -> None:
    assert aggregate_country_signals(conflict_events=[{"fatalities": 99}]) == {}


def test_displacement_counts_severity_but_not_signal_volume() -> None:
    result = aggregate_country_signals(
        displacement_data=[
            {"country": "Sudan", "total_displaced": 150_000},
            {"country": "Chad", "total_displaced": "many"},  # non-numeric ignored
        ]
    )
    sdn = result["Sudan"]
    assert sdn["displaced_persons"] == 150_000
    assert sdn["active_domains"] == ["displacement"]
    # Displacement contributes a domain and severity but no signal volume:
    # 20*1 + min(30, 5*0) + 10*1 = 30.
    assert sdn["total_signals"] == 0
    assert sdn["convergence_score"] == 30
    assert result["Chad"]["displaced_persons"] == 0
    assert result["Chad"]["convergence_score"] == 20


def test_earthquake_country_parsed_from_usgs_place_string() -> None:
    result = aggregate_country_signals(
        earthquake_data=[
            {"place": "80km SSE of Lima, Peru", "magnitude": 6.4},
            {"place": "10km N of Tokyo, Japan", "magnitude": 4.0},
            {"place": "central mid-Atlantic ridge", "magnitude": 5.0},
        ]
    )
    assert result["Peru"]["earthquakes"] == 1
    assert result["Peru"]["max_earthquake_mag"] == 6.4
    # 20*1 + 5*1 + 10*1 (magnitude >= 6.0) = 35
    assert result["Peru"]["convergence_score"] == 35
    assert result["Japan"]["max_earthquake_mag"] == 4.0
    assert result["Japan"]["convergence_score"] == 25  # no severity bonus
    # A place string without ", Country" falls back to Unknown.
    assert result["Unknown"]["earthquakes"] == 1


def test_fires_use_country_or_region_mapping() -> None:
    result = aggregate_country_signals(
        fire_data=[
            {"country": "Greece"},
            {"region": "europe"},  # maps to first europe country: Greece
            {"region": "atlantis"},  # unmapped region contributes nothing
            "not-a-dict",  # malformed entry skipped
        ]
    )
    assert list(result) == ["Greece"]
    assert result["Greece"]["fires"] == 2
    assert result["Greece"]["active_domains"] == ["wildfire"]


def test_outage_countries_accept_list_or_string() -> None:
    result = aggregate_country_signals(
        outage_data=[
            {"countries": ["US", "CA"]},
            {"countries": "GB"},
            {"unrelated": True},
        ]
    )
    assert result["US"]["outages"] == 1
    assert result["CA"]["outages"] == 1
    assert result["GB"]["outages"] == 1
    assert result["GB"]["active_domains"] == ["infrastructure"]


def test_military_flights_counted_by_origin_country() -> None:
    result = aggregate_country_signals(
        military_data=[
            {"origin_country": "Russia"},
            {"origin_country": None},
            "not-a-dict",
        ]
    )
    assert list(result) == ["Russia"]
    assert result["Russia"]["military_aircraft"] == 1
    assert result["Russia"]["active_domains"] == ["military"]


def test_riots_split_from_protests_by_event_type() -> None:
    result = aggregate_country_signals(
        protest_data=[
            {"country": "France", "event_type": "Riots"},
            {"country": "France", "event_type": "Protests"},
            {"country": "France"},  # missing event_type counts as protest
        ]
    )
    fra = result["France"]
    assert fra["riots"] == 1
    assert fra["protests"] == 2
    assert fra["active_domains"] == ["unrest"]
    assert fra["total_signals"] == 3


def test_domain_breadth_outranks_raw_volume() -> None:
    """Three domains with one event each must outscore six events in a
    single domain — that is the point of convergence scoring."""
    result = aggregate_country_signals(
        conflict_events=(
            [{"country": "Kenya", "fatalities": 0}]
            + [{"country": "Brazil", "fatalities": 0}] * 6
        ),
        earthquake_data=[{"place": "10km N of Nairobi, Kenya", "magnitude": 4.5}],
        fire_data=[{"country": "Kenya"}],
    )
    # Kenya: 20*3 + 5*3 = 75. Brazil: 20*1 + min(30, 5*6) = 50.
    assert result["Kenya"]["convergence_score"] == 75
    assert result["Brazil"]["convergence_score"] == 50
    assert list(result) == ["Kenya", "Brazil"]
